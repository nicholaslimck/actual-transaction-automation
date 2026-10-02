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


# ---------------------------------------------------------------------------
# H1 — GIRO deduction (label set: "Date and Time" / "Paying to" / "Payment amount")
# ---------------------------------------------------------------------------

GIRO_BODY = """\
Your GIRO payment is successful
Transaction Ref: SGA02106JKP5KIMA
Dear Customer,
Your GIRO deduction is successful. Details
Date and Time: 02 Oct 09:36 (SGT)
From: DBS/POSB A/C ending 4831
Paying to: SYFE PTE. LTD. 8 CROSS STREET #21-01 MANULIFE TOWER SINGAPORE 048424
Payment amount: SGD 200.00
Bill Reference number: 17540217414901l8Rwla7rl5zzviAULJ9Ox
"""


def test_giro_deduction_parses():
    t = parser.parse(make_email(subject="digibank Alerts - Successful GIRO deduction",
                                body_text=GIRO_BODY,
                                email_date=datetime(2026, 10, 2, tzinfo=timezone.utc)))[0]
    assert t["date"] == "2026-10-02"
    assert t["amount"] == -20000
    assert t["payee_name"] == "SYFE PTE. LTD."      # address trimmed
    assert t["account_last4"] == "4831"             # the source account
    assert t["imported_id"] == "SGA02106JKP5KIMA"


def test_giro_reports_untracked_source_account():
    """A GIRO from an account this budget does not track must still report it,
    so the config's account_filter can skip it rather than mis-file it."""
    t = parser.parse(make_email(body_text=GIRO_BODY.replace("4831", "0676"),
                                email_date=datetime(2026, 10, 2, tzinfo=timezone.utc)))[0]
    assert t["account_last4"] == "0676"


# ---------------------------------------------------------------------------
# H2 — bill payment (money out of the source account)
# ---------------------------------------------------------------------------

BILL_BODY = """\
Transaction Ref: 17887102259656223177
Dear Customer,
You've successfully made a bill payment.
Date and Time: 06 Sep 23:57 (SGT)
Amount: SGD 145.71
From: DBS Savings Plus Account (A/C ending 4831)
To: Yuu Visa Platinum (Ref ending 7654)
If unauthorised, please call our DBS hotline.
"""


def test_bill_payment_parses():
    t = parser.parse(make_email(subject="digibank Alert - Successful bill payment",
                                body_text=BILL_BODY,
                                email_date=datetime(2026, 9, 6, tzinfo=timezone.utc)))[0]
    assert t["amount"] == -14571
    assert t["payee_name"] == "Yuu Visa Platinum"   # trailing "(Ref ...)" trimmed
    assert t["account_last4"] == "4831"
    assert t["date"] == "2026-09-06"


# ---------------------------------------------------------------------------
# H3 — PayLah! refund: no space between date and time, and money flows IN
# ---------------------------------------------------------------------------

REFUND_BODY = """\
Transaction Ref: 260914000041MC018549
Dear Sir/Madam,
We refer to your PayLah! refund transaction below and are pleased to confirm that the transaction was completed.
Date & Time: 14 Sep00:00 (SGT)
Amount: SGD 0.10
From: BCRS LTD
To: PayLah! Wallet (Mobile ending 7269)
To view your transactions, login to your PayLah! Wallet.
"""


def test_paylah_refund_is_positive_and_uses_from_party():
    t = parser.parse(make_email(subject="Transaction Alert", body_text=REFUND_BODY,
                                email_date=datetime(2026, 9, 13, tzinfo=timezone.utc)))[0]
    assert t["amount"] == 10                       # POSITIVE: money in
    assert t["payee_name"] == "BCRS LTD"           # counterparty is "From", not "To"
    assert t["date"] == "2026-09-14"
    assert t["account_last4"] == "7269"


def test_glued_date_and_time_parses():
    """'30 Sep10:21(SGT)' — no space between date and time."""
    body = (
        "Transaction Ref: FT260930MB76389064\n"
        "Your Funds Transfer to Other DBS/POSB account dated 30 Sep has been completed.\n"
        "Date & Time: 30 Sep10:21(SGT)\n"
        "Amount: SGD 500.00\n"
        "From: DBS eMulti-Currency Autosave Account A/C ending 2145\n"
        "To: Ah Gong (A/C ending 7910)\n"
        "If unauthorised, please call DBS hotline.\n"
    )
    t = parser.parse(make_email(subject="iBanking Alerts", body_text=body,
                                email_date=datetime(2026, 9, 30, tzinfo=timezone.utc)))[0]
    assert t["amount"] == -50000
    assert t["date"] == "2026-09-30"
    assert t["payee_name"] == "Ah Gong (A/C ending 7910)"
    assert t["account_last4"] == "2145"


# ---------------------------------------------------------------------------
# H4 — incoming transfer via FAST (not just PayNow)
# ---------------------------------------------------------------------------

FAST_BODY = """\
Transaction Ref: IEBGPP60908533710
Dear Customer,
You have received SGD 271.12 via FAST transfer on 08 Sep 2026 19:20 SGT.
From: SYFE PTE. LTD. - CLIENTS A/C
To: Your DBS/ POSB account ending 0676
"""


def test_incoming_fast_transfer_is_parsed():
    t = parser.parse(make_email(subject="digibank Alerts - You've received a transfer",
                                body_text=FAST_BODY,
                                email_date=datetime(2026, 9, 8, tzinfo=timezone.utc)))[0]
    assert t["amount"] == 27112                    # positive: money in
    assert t["payee_name"] == "SYFE PTE. LTD. - CLIENTS A/C"
    assert t["date"] == "2026-09-08"
    assert t["account_last4"] == "0676"


# ---------------------------------------------------------------------------
# H5 — non-transaction DBS mail shares the generic subject, so it is detected
#      by body and must be skipped without poisoning the "Could not parse" canary
# ---------------------------------------------------------------------------

def test_egiro_admin_mail_is_skipped():
    body = ("Your eGIRO application for SYFE PTE. LTD. submitted on 04/Sep/2026 "
            "was unsuccessful.")
    assert parser.parse(make_email(subject="Transaction alert", body_text=body)) == []


def test_egiro_setup_confirmation_is_skipped():
    body = ("We refer to your request dated 04/Sep/2026 to set up eGIRO arrangement. "
            "We are pleased to confirm that the request has been completed successfully.")
    assert parser.parse(make_email(subject="Transaction alert", body_text=body)) == []


def test_edocument_notice_is_skipped():
    body = "Dear Customer, Your eDocument(s) are ready for viewing: Credit Card Statement."
    assert parser.parse(make_email(subject="Your eDocument(s) are ready for viewing",
                                   body_text=body)) == []


def test_real_alert_still_warns_when_unhandled():
    """A genuinely new transaction alert must NOT be swallowed by the admin
    filter — it has to reach the parser and log a warning."""
    body = "Transaction Ref: XYZ1\nAn alert format nobody has seen before.\n"
    assert parser.parse(make_email(subject="Some New Alert", body_text=body)) == []
