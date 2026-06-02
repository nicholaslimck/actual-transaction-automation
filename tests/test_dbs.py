"""Unit tests for the DBS email parser."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from bank_parsers.dbs import DbsParser

parser = DbsParser()


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
# Test 1 — PayLah! outflow
# ---------------------------------------------------------------------------

PAYLAH_BODY = """\
Transaction Ref: IPS69792811780206674

We refer to your PayLah! Google Pay UEN transaction dated 31 May.

Date & Time:   31 May 13:51 (SGT)
Amount:        SGD1.80
From:          PayLah! Wallet (Mobile ending 7269)
To:            S-11 (BISHAN 504) FOOD HOUSE PTE LTD
"""


def test_paylah_outflow_amount():
    txns = parser.parse(make_email(body_text=PAYLAH_BODY,
                                   email_date=datetime(2026, 5, 31, tzinfo=timezone.utc)))
    assert len(txns) == 1
    assert txns[0]["amount"] == -180


def test_paylah_outflow_payee():
    txns = parser.parse(make_email(body_text=PAYLAH_BODY,
                                   email_date=datetime(2026, 5, 31, tzinfo=timezone.utc)))
    assert txns[0]["payee_name"] == "S-11 (BISHAN 504) FOOD HOUSE PTE LTD"


def test_paylah_outflow_imported_id_uses_transaction_ref():
    txns = parser.parse(make_email(body_text=PAYLAH_BODY,
                                   email_date=datetime(2026, 5, 31, tzinfo=timezone.utc)))
    assert txns[0]["imported_id"] == "IPS69792811780206674"


def test_paylah_outflow_date_uses_email_year():
    txns = parser.parse(make_email(body_text=PAYLAH_BODY,
                                   email_date=datetime(2026, 5, 31, tzinfo=timezone.utc)))
    assert txns[0]["date"] == "2026-05-31"


# ---------------------------------------------------------------------------
# Test 2 — Incoming PayNow (ibanking)
# ---------------------------------------------------------------------------

INCOMING_BODY = """\
Transaction Ref: PIB2605300506945590   C130547350396

You have received SGD 25.00 via PayNow on 30 May 2026 15:02  SGT.

From: TOPAZ TAN
To: Your DBS/ POSB account ending 4831
"""


def test_incoming_paynow_amount_is_positive():
    txns = parser.parse(make_email(body_text=INCOMING_BODY,
                                   email_date=datetime(2026, 5, 30, tzinfo=timezone.utc)))
    assert len(txns) == 1
    assert txns[0]["amount"] == 2500


def test_incoming_paynow_payee():
    txns = parser.parse(make_email(body_text=INCOMING_BODY,
                                   email_date=datetime(2026, 5, 30, tzinfo=timezone.utc)))
    assert txns[0]["payee_name"] == "TOPAZ TAN"


def test_incoming_paynow_imported_id():
    txns = parser.parse(make_email(body_text=INCOMING_BODY,
                                   email_date=datetime(2026, 5, 30, tzinfo=timezone.utc)))
    assert txns[0]["imported_id"] == "PIB2605300506945590"


def test_incoming_paynow_date():
    txns = parser.parse(make_email(body_text=INCOMING_BODY,
                                   email_date=datetime(2026, 5, 30, tzinfo=timezone.utc)))
    assert txns[0]["date"] == "2026-05-30"


# ---------------------------------------------------------------------------
# Test 3 — Unparseable body returns empty list
# ---------------------------------------------------------------------------

def test_unparseable_body_returns_empty_list():
    txns = parser.parse(make_email(body_text="hello world nothing useful here"))
    assert txns == []
