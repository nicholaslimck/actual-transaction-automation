"""Unit tests for the DBS email parser."""
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
Transaction Ref: IPS00000000000000001

We refer to your PayLah! Google Pay UEN transaction dated 31 May.

Date & Time:   31 May 13:51 (SGT)
Amount:        SGD1.80
From:          PayLah! Wallet (Mobile ending 0000)
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
    assert txns[0]["imported_id"] == "IPS00000000000000001"


def test_paylah_outflow_date_uses_email_year():
    txns = parser.parse(make_email(body_text=PAYLAH_BODY,
                                   email_date=datetime(2026, 5, 31, tzinfo=timezone.utc)))
    assert txns[0]["date"] == "2026-05-31"


# ---------------------------------------------------------------------------
# Test 2 — Incoming PayNow (ibanking)
# ---------------------------------------------------------------------------

INCOMING_BODY = """\
Transaction Ref: PIB00000000000000001   C000000000001

You have received SGD 25.00 via PayNow on 30 May 2026 15:02  SGT.

From: ALICE TAN
To: Your DBS/ POSB account ending 0000
"""


def test_incoming_paynow_amount_is_positive():
    txns = parser.parse(make_email(body_text=INCOMING_BODY,
                                   email_date=datetime(2026, 5, 30, tzinfo=timezone.utc)))
    assert len(txns) == 1
    assert txns[0]["amount"] == 2500


def test_incoming_paynow_payee():
    txns = parser.parse(make_email(body_text=INCOMING_BODY,
                                   email_date=datetime(2026, 5, 30, tzinfo=timezone.utc)))
    assert txns[0]["payee_name"] == "ALICE TAN"


def test_incoming_paynow_imported_id():
    txns = parser.parse(make_email(body_text=INCOMING_BODY,
                                   email_date=datetime(2026, 5, 30, tzinfo=timezone.utc)))
    assert txns[0]["imported_id"] == "PIB00000000000000001"


def test_incoming_paynow_date():
    txns = parser.parse(make_email(body_text=INCOMING_BODY,
                                   email_date=datetime(2026, 5, 30, tzinfo=timezone.utc)))
    assert txns[0]["date"] == "2026-05-30"


# ---------------------------------------------------------------------------
# Test 3 — Payment to another bank's card
# ---------------------------------------------------------------------------

CARD_PAYMENT_BODY = """\
Transaction Ref: 10000000000000000001

You've successfully made a payment for your other bank's credit card.
Date and Time: 02 Jun 16:00 (SGT)
Amount: SGD 100.00
From: DBS Savings Plus Account (A/C ending 0000)
To: Other bank's card ending 1234
"""


def test_card_payment_amount_is_negative():
    txns = parser.parse(make_email(body_text=CARD_PAYMENT_BODY,
                                   email_date=datetime(2026, 6, 2, tzinfo=timezone.utc)))
    assert len(txns) == 1
    assert txns[0]["amount"] == -10000


def test_card_payment_payee():
    txns = parser.parse(make_email(body_text=CARD_PAYMENT_BODY,
                                   email_date=datetime(2026, 6, 2, tzinfo=timezone.utc)))
    assert txns[0]["payee_name"] == "Credit Card Payment (1234)"


def test_card_payment_imported_id():
    txns = parser.parse(make_email(body_text=CARD_PAYMENT_BODY,
                                   email_date=datetime(2026, 6, 2, tzinfo=timezone.utc)))
    assert txns[0]["imported_id"] == "10000000000000000001"


def test_card_payment_date():
    txns = parser.parse(make_email(body_text=CARD_PAYMENT_BODY,
                                   email_date=datetime(2026, 6, 2, tzinfo=timezone.utc)))
    assert txns[0]["date"] == "2026-06-02"


# ---------------------------------------------------------------------------
# Test 4 — Unparseable body returns empty list
# ---------------------------------------------------------------------------

def test_unparseable_body_returns_empty_list():
    txns = parser.parse(make_email(body_text="hello world nothing useful here"))
    assert txns == []
