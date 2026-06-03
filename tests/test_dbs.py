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


# ---------------------------------------------------------------------------
# Test 5 — Card transaction alert (ibanking.alert@dbs.com)
# ---------------------------------------------------------------------------

CARD_TXN_BODY = """\
Card Transaction Alert

Transaction Ref: SP0000000000000000001

Dear Sir / Madam,

We refer to your card transaction request dated 03/06/26. We are pleased to confirm that the transaction was completed.

Date & Time: 03 JUN 05:36 (SGT)
Amount: SGD3.64
From: DBS/POSB card ending 0000
To: BUS/MRT

If unauthorised, please login to DBS digibank mobile to report fraud dispute immediately.
"""


def test_card_txn_alert_amount():
    txns = parser.parse(make_email(
        subject="Card Transaction Alert",
        body_text=CARD_TXN_BODY,
        email_date=datetime(2026, 6, 3, tzinfo=timezone.utc),
    ))
    assert len(txns) == 1
    assert txns[0]["amount"] == -364


def test_card_txn_alert_payee():
    txns = parser.parse(make_email(
        subject="Card Transaction Alert",
        body_text=CARD_TXN_BODY,
        email_date=datetime(2026, 6, 3, tzinfo=timezone.utc),
    ))
    assert txns[0]["payee_name"] == "BUS/MRT"


def test_card_txn_alert_imported_id():
    txns = parser.parse(make_email(
        subject="Card Transaction Alert",
        body_text=CARD_TXN_BODY,
        email_date=datetime(2026, 6, 3, tzinfo=timezone.utc),
    ))
    assert txns[0]["imported_id"] == "SP0000000000000000001"


def test_card_txn_alert_date():
    txns = parser.parse(make_email(
        subject="Card Transaction Alert",
        body_text=CARD_TXN_BODY,
        email_date=datetime(2026, 6, 3, tzinfo=timezone.utc),
    ))
    assert txns[0]["date"] == "2026-06-03"


def test_card_txn_alert_account_last4():
    txns = parser.parse(make_email(
        subject="Card Transaction Alert",
        body_text=CARD_TXN_BODY,
        email_date=datetime(2026, 6, 3, tzinfo=timezone.utc),
    ))
    assert txns[0]["account_last4"] == "0000"


# ---------------------------------------------------------------------------
# Test 6 — account_last4 across DBS formats
# ---------------------------------------------------------------------------

def test_paylah_account_last4():
    txns = parser.parse(make_email(body_text=PAYLAH_BODY,
                                   email_date=datetime(2026, 5, 31, tzinfo=timezone.utc)))
    assert txns[0]["account_last4"] == "0000"


def test_incoming_paynow_account_last4():
    txns = parser.parse(make_email(body_text=INCOMING_BODY,
                                   email_date=datetime(2026, 5, 30, tzinfo=timezone.utc)))
    assert txns[0]["account_last4"] == "0000"


CARD_PAYMENT_BODY_DISTINCT = """\
Transaction Ref: 10000000000000000001

You've successfully made a payment for your other bank's credit card.
Date and Time: 02 Jun 16:00 (SGT)
Amount: SGD 100.00
From: DBS Savings Plus Account (A/C ending 1111)
To: Other bank's card ending 9999
"""


def test_card_payment_account_last4_is_source_not_destination():
    """account_last4 must be the source DBS account ending, not the third-party destination."""
    txns = parser.parse(make_email(body_text=CARD_PAYMENT_BODY_DISTINCT,
                                   email_date=datetime(2026, 6, 2, tzinfo=timezone.utc)))
    assert txns[0]["account_last4"] == "1111"
