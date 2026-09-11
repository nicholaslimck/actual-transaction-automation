"""imported_id stability across FX-rate drift (all banks).

The SGD figure for a foreign-currency transaction is a live-rate estimate, so a
content hash built from it changes whenever the rate moves — and the same email
then imports a second time as a duplicate. Real case (Sep 2026): a single Trust
alert per purchase produced two rows, e.g. USD 176.00 -> 224.63 @1.2763 and
223.58 @1.2703.

The rule these tests pin down:
  * foreign-currency txns hash the ORIGINAL currency amount, and
  * SGD txns keep the exact legacy recipe, so rows already in Actual still match.
"""
import hashlib
from datetime import datetime, timezone

from bank_parsers.hsbc import HsbcParser
from bank_parsers.maribank import MaribankParser
import bank_parsers.hsbc as hsbc_mod
import bank_parsers.maribank as maribank_mod


def make_email(subject="", body_text="", body_html=""):
    return {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "date": "",
        "message_id": "<stability-test>",
        "email_date": datetime(2026, 9, 11, tzinfo=timezone.utc),
        "raw_id": "1",
    }


def legacy_id(prefix, date, amount, payee, time=""):
    """The pre-fix recipe: no amount_key override."""
    raw = f"{date}|{time}|{amount}|{payee}" if time else f"{date}|{amount}|{payee}"
    return f"{prefix}:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


# ---------------------------------------------------------------------------
# HSBC
# ---------------------------------------------------------------------------

HSBC_BODY = (
    "Dear Customer Please note there was a transaction made on your HSBC credit card. "
    "Card Number XXXX-XXXX-XXXX-6966 Transaction Date 08/SEP/2026 "
    "Transaction Time 23:53:13 Transaction Amount USD550.00 Description AMAZON US"
)


def test_hsbc_foreign_id_stable_across_rate_drift(monkeypatch):
    parser = HsbcParser()
    email = make_email(subject="Transaction Alerts  (Credit Card)", body_text=HSBC_BODY)

    monkeypatch.setattr(hsbc_mod, "sgd_from", lambda cur, cents: (int(cents * 1.30), 1.30))
    first = parser.parse(email)
    monkeypatch.setattr(hsbc_mod, "sgd_from", lambda cur, cents: (int(cents * 1.35), 1.35))
    second = parser.parse(email)

    assert len(first) == 1 and len(second) == 1
    assert first[0]["amount"] != second[0]["amount"]
    assert first[0]["imported_id"] == second[0]["imported_id"]


def test_hsbc_sgd_id_keeps_legacy_recipe():
    """Protects the SGD rows already in Actual (e.g. the FLYSCOOT purchase)."""
    parser = HsbcParser()
    body = (
        "Card Number XXXX-XXXX-XXXX-6966 Transaction Date 08/SEP/2026 "
        "Transaction Time 23:53:13 Transaction Amount SGD613.56 "
        "Description FLYSCOOT63924508282243"
    )
    txn = parser.parse(
        make_email(subject="Transaction Alerts  (Credit Card)", body_text=body)
    )[0]
    assert txn["amount"] == -61356
    assert txn["payee_name"] == "FLYSCOOT"
    assert txn["imported_id"] == legacy_id(
        "hsbc", "2026-09-08", -61356, "FLYSCOOT", "23:53:13"
    )


# ---------------------------------------------------------------------------
# MariBank
# ---------------------------------------------------------------------------

MARI_BODY = (
    "You have made a payment to WEST COAST VETCARE PL on your credit card ending 1730.\n"
    "Transaction Time:\n08 May 2026 18:01 SGT\nAmount:\nUSD 116.41\n"
)


def test_maribank_foreign_id_stable_across_rate_drift(monkeypatch):
    parser = MaribankParser()
    email = make_email(subject="Transaction Notification", body_text=MARI_BODY)

    monkeypatch.setattr(
        maribank_mod, "sgd_from", lambda cur, cents: (int(cents * 1.30), 1.30)
    )
    first = parser.parse(email)
    monkeypatch.setattr(
        maribank_mod, "sgd_from", lambda cur, cents: (int(cents * 1.36), 1.36)
    )
    second = parser.parse(email)

    assert len(first) == 1 and len(second) == 1
    assert first[0]["amount"] != second[0]["amount"]
    assert first[0]["imported_id"] == second[0]["imported_id"]


def test_maribank_sgd_id_keeps_legacy_recipe():
    parser = MaribankParser()
    body = (
        "You have made a payment to WEST COAST VETCARE PL on your credit card ending 1730.\n"
        "Transaction Time:\n08 May 2026 18:01 SGT\nAmount:\nSGD 116.41\n"
    )
    txn = parser.parse(make_email(subject="Transaction Notification", body_text=body))[0]
    assert txn["amount"] == -11641
    assert txn["imported_id"] == legacy_id(
        "mari", "2026-05-08", -11641, "WEST COAST VETCARE PL", "18:01"
    )
