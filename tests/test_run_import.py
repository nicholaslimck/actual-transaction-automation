import pytest
from main import process_sender, group_accounts_by_sender


# ---- Stubs ----

def make_email(raw_id="1"):
    return {"subject": "Alert", "body_text": "", "body_html": "", "date": "", "message_id": f"<{raw_id}>", "email_date": None, "raw_id": raw_id}


class FakeFetcher:
    def __init__(self, emails):
        self.emails = emails
        self.seen = []
    def fetch_unread_from(self, sender, lookback_days):
        return self.emails
    def mark_as_seen(self, raw_id):
        self.seen.append(raw_id)


class FakeParser:
    def __init__(self, txns):
        self.txns = txns
    def parse(self, email_data):
        return self.txns


class FakeImporter:
    def __init__(self, result):
        self.result = result
        self.called_with = []
    def import_transactions(self, account_id, transactions):
        self.called_with.append((account_id, transactions))
        return self.result


class FakeDedup:
    def __init__(self):
        self.recorded = []
    def check(self, account_id, ids):
        return set()  # nothing known
    def record(self, account_id, ids):
        self.recorded.append((account_id, ids))


ACCOUNTS = [{"actual_account_id": "acct-1", "name": "TestAcct"}]
TXNS = [{"date": "2026-06-01", "amount": -100, "payee_name": "Shop", "imported_id": "id-1"}]


def test_success_records_and_marks_seen():
    fetcher = FakeFetcher([make_email("msg1")])
    dedup = FakeDedup()
    importer = FakeImporter({"added": 1, "updated": 0})
    n_add, n_upd = process_sender("sender@bank.com", ACCOUNTS, fetcher, FakeParser(TXNS), importer, dedup, dry_run=False, lookback_days=3)
    assert n_add == 1
    assert n_upd == 0
    assert len(dedup.recorded) == 1
    assert "msg1" in fetcher.seen


def test_import_failure_does_not_record_or_mark_seen():
    fetcher = FakeFetcher([make_email("msg1")])
    dedup = FakeDedup()
    importer = FakeImporter({"error": "bad"})
    process_sender("sender@bank.com", ACCOUNTS, fetcher, FakeParser(TXNS), importer, dedup, dry_run=False, lookback_days=3)
    assert len(dedup.recorded) == 0
    assert "msg1" not in fetcher.seen


def test_dry_run_no_import_no_record_no_seen():
    fetcher = FakeFetcher([make_email("msg1")])
    dedup = FakeDedup()
    importer = FakeImporter({"added": 1, "updated": 0})
    process_sender("sender@bank.com", ACCOUNTS, fetcher, FakeParser(TXNS), importer, dedup, dry_run=True, lookback_days=3)
    assert importer.called_with == []
    assert len(dedup.recorded) == 0
    assert fetcher.seen == []


def test_partial_failure_email_marked_seen_if_any_account_succeeded():
    """2 accounts: first fails, second succeeds -> email IS marked seen."""
    accounts = [
        {"actual_account_id": "acct-fail", "name": "Fail"},
        {"actual_account_id": "acct-ok", "name": "OK"},
    ]
    results = iter([{"error": "oops"}, {"added": 1, "updated": 0}])
    class SequentialImporter:
        called_with = []
        def import_transactions(self, aid, txns):
            self.called_with.append(aid)
            return next(results)
    fetcher = FakeFetcher([make_email("msg1")])
    dedup = FakeDedup()
    importer = SequentialImporter()
    process_sender("sender@bank.com", accounts, fetcher, FakeParser(TXNS), importer, dedup, dry_run=False, lookback_days=3)
    assert "msg1" in fetcher.seen


def test_no_emails_returns_zero():
    fetcher = FakeFetcher([])
    dedup = FakeDedup()
    importer = FakeImporter({"added": 0, "updated": 0})
    n_add, n_upd = process_sender("sender@bank.com", ACCOUNTS, fetcher, FakeParser(TXNS), importer, dedup, dry_run=False, lookback_days=3)
    assert n_add == 0 and n_upd == 0


def test_group_accounts_by_sender_filters_incomplete():
    config = {"accounts": [
        {"email_sender": "a@b.com", "actual_account_id": "id1", "name": "A"},
        {"email_sender": "", "actual_account_id": "id2", "name": "B"},  # no sender
        {"email_sender": "c@d.com", "actual_account_id": "", "name": "C"},  # no account id
        {"email_sender": "a@b.com", "actual_account_id": "id3", "name": "D"},  # same sender
    ]}
    result = group_accounts_by_sender(config)
    assert set(result.keys()) == {"a@b.com"}
    assert len(result["a@b.com"]) == 2
