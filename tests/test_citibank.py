"""Unit tests for the Citibank Singapore email parser."""
from datetime import datetime, timezone
from bank_parsers.citibank import CitibankParser

parser = CitibankParser()


def make_email(subject="", body_text="", body_html="", message_id="<test-msg-1>",
               email_date=None, raw_id="1"):
    return {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "date": "",
        "message_id": message_id,
        "email_date": email_date or datetime(2026, 5, 31, tzinfo=timezone.utc),
        "raw_id": raw_id,
    }


# ---------------------------------------------------------------------------
# Shared test fixture
# ---------------------------------------------------------------------------

CITI_BODY = """\
Dear Customer,
We would like to inform you that there is a charge made on
your Citi Cash Back+ Card:

Account Number           : XXXX-XXXX-XXXX-0000
Transaction date         : 28/05/26
Transaction time         : 17:01:19
Transaction amount       : SGD2100.00
Transaction  details     : SAMPLE MERCHANT
"""


# ---------------------------------------------------------------------------
# Test 1 — Structured alert parsing
# ---------------------------------------------------------------------------

def test_structured_alert_len():
    txns = parser.parse(make_email(body_text=CITI_BODY))
    assert len(txns) == 1


def test_structured_alert_amount():
    txns = parser.parse(make_email(body_text=CITI_BODY))
    assert txns[0]["amount"] == -210000


def test_structured_alert_payee_starts_with_merchant():
    txns = parser.parse(make_email(body_text=CITI_BODY))
    assert txns[0]["payee_name"].startswith("SAMPLE MERCHANT")


def test_structured_alert_notes_contain_last_four():
    txns = parser.parse(make_email(body_text=CITI_BODY))
    assert "*0000" in txns[0]["notes"]


def test_structured_alert_date():
    txns = parser.parse(make_email(body_text=CITI_BODY))
    assert txns[0]["date"] == "2026-05-28"


def test_structured_alert_imported_id_has_citi_prefix():
    txns = parser.parse(make_email(body_text=CITI_BODY))
    assert txns[0]["imported_id"].startswith("citi:")


# ---------------------------------------------------------------------------
# Test 2 — imported_id is deterministic (same email → same id)
# ---------------------------------------------------------------------------

def test_imported_id_is_deterministic():
    txns_a = parser.parse(make_email(body_text=CITI_BODY))
    txns_b = parser.parse(make_email(body_text=CITI_BODY))
    assert txns_a[0]["imported_id"] == txns_b[0]["imported_id"]


# ---------------------------------------------------------------------------
# Test 3 — Different transaction produces a different imported_id
# ---------------------------------------------------------------------------

CITI_BODY_GRAB = """\
Dear Customer,
We would like to inform you that there is a charge made on
your Citi Cash Back+ Card:

Account Number           : XXXX-XXXX-XXXX-0000
Transaction date         : 28/05/26
Transaction time         : 18:30:00
Transaction amount       : SGD50.00
Transaction  details     : GRAB
"""


def test_different_txn_produces_different_imported_id():
    txns_original = parser.parse(make_email(body_text=CITI_BODY))
    txns_grab = parser.parse(make_email(body_text=CITI_BODY_GRAB))
    assert txns_original[0]["imported_id"] != txns_grab[0]["imported_id"]


# ---------------------------------------------------------------------------
# Test 4 — Unparseable body returns empty list
# ---------------------------------------------------------------------------

def test_unparseable_body_returns_empty_list():
    txns = parser.parse(make_email(body_text="hello world nothing useful here"))
    assert txns == []
