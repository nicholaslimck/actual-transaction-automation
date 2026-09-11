"""Tests for the generalised backfill CLI (_backfill.py).

Covers the routing logic that must stay identical to main.py's cron path, since
a divergence would send a transaction to the wrong Actual account.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _backfill import (  # noqa: E402
    accounts_for_bank,
    dedupe_batch,
    known_banks,
    select_txns,
)


def cfg(accounts):
    return {"accounts": accounts}


# --- account grouping ------------------------------------------------------

MULTI_ACCOUNT_CONFIG = cfg([
    {"name": "DBS PayLah", "bank": "dbs",
     "email_sender": "paylah.alert@dbs.com", "actual_account_id": "acct-1"},
    {"name": "DBS PayNow", "bank": "dbs",
     "email_sender": "ibanking.alert@dbs.com", "actual_account_id": "acct-1",
     "account_filter": "4831"},
    {"name": "DBS Yuu", "bank": "dbs",
     "email_sender": "ibanking.alert@dbs.com", "actual_account_id": "acct-2",
     "account_filter": "7654"},
    {"name": "Trust Credit", "bank": "trust",
     "email_sender": "from_us@trustbank.sg", "actual_account_id": "acct-3"},
])


def test_bank_filter_selects_only_that_bank():
    groups = accounts_for_bank(MULTI_ACCOUNT_CONFIG, "trust")
    assert list(groups) == ["from_us@trustbank.sg"]
    assert [a["name"] for a in groups["from_us@trustbank.sg"]] == ["Trust Credit"]


def test_bank_filter_is_case_insensitive():
    assert accounts_for_bank(MULTI_ACCOUNT_CONFIG, "TRUST")


def test_no_bank_returns_every_sender():
    groups = accounts_for_bank(MULTI_ACCOUNT_CONFIG, None)
    assert set(groups) == {"paylah.alert@dbs.com", "ibanking.alert@dbs.com",
                           "from_us@trustbank.sg"}


def test_two_accounts_sharing_one_sender_stay_grouped():
    """DBS PayNow + Yuu share a sender; both must be routed in one pass."""
    groups = accounts_for_bank(MULTI_ACCOUNT_CONFIG, "dbs")
    assert [a["name"] for a in groups["ibanking.alert@dbs.com"]] == [
        "DBS PayNow", "DBS Yuu"]


def test_unknown_bank_yields_nothing():
    assert accounts_for_bank(MULTI_ACCOUNT_CONFIG, "nope") == {}


def test_known_banks_lists_config_banks():
    assert known_banks(MULTI_ACCOUNT_CONFIG) == ["dbs", "trust"]


# --- transaction selection -------------------------------------------------

def email(subject="", txns=None):
    return ({"subject": subject, "raw_id": "1"}, txns or [])


TXN_4831 = {"imported_id": "a", "account_last4": "4831", "payee_name": "X"}
TXN_7654 = {"imported_id": "b", "account_last4": "7654", "payee_name": "Y"}
TXN_NO_LAST4 = {"imported_id": "c", "account_last4": None, "payee_name": "Z"}


def test_account_filter_keeps_only_matching_last4():
    pairs = select_txns([email("t", [TXN_4831, TXN_7654])],
                        {"account_filter": "4831"})
    assert [t["imported_id"] for _, ts in pairs for t in ts] == ["a"]


def test_account_filter_zero_pads_short_values():
    """config may hold '4831' or 4831; a 3-digit value must still match."""
    txn = dict(TXN_4831, account_last4="531")
    pairs = select_txns([email("t", [txn])], {"account_filter": "0531"})
    assert len(pairs) == 1


def test_account_filter_drops_txns_without_last4():
    pairs = select_txns([email("t", [TXN_NO_LAST4])], {"account_filter": "4831"})
    assert pairs == []


def test_no_account_filter_keeps_everything():
    pairs = select_txns([email("t", [TXN_4831, TXN_7654, TXN_NO_LAST4])], {})
    assert [t["imported_id"] for _, ts in pairs for t in ts] == ["a", "b", "c"]


def test_subject_filter_gates_at_email_level():
    emails = [email("Here's your cashback summary", [TXN_4831]),
              email("Miles earned", [TXN_7654])]
    pairs = select_txns(emails, {"subject_filter": "earned"})
    assert [t["imported_id"] for _, ts in pairs for t in ts] == ["b"]


def test_subject_and_account_filters_apply_together():
    """AND semantics, matching main.py.process_sender."""
    emails = [email("earned", [TXN_4831, TXN_7654]),
              email("summary", [TXN_7654])]
    pairs = select_txns(emails, {"subject_filter": "earned", "account_filter": "7654"})
    assert [t["imported_id"] for _, ts in pairs for t in ts] == ["b"]


def test_emails_with_no_transactions_are_skipped():
    assert select_txns([email("t", [])], {}) == []


# --- batch de-duplication --------------------------------------------------

def test_dedupe_batch_keeps_first_of_repeated_ids():
    """Trust sends the same purchase as both a push and an email alert."""
    txns = [{"imported_id": "a", "amount": -100},
            {"imported_id": "b", "amount": -200},
            {"imported_id": "a", "amount": -100}]
    assert [t["imported_id"] for t in dedupe_batch(txns)] == ["a", "b"]
