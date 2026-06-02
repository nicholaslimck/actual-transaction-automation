"""Tests for MaribankParser (bank_parsers/maribank.py)."""
import re
import pytest
from datetime import datetime, timezone
from bank_parsers.maribank import MaribankParser

parser = MaribankParser()


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
# Test 1 — Strategy-1 structured payment
# ---------------------------------------------------------------------------

def test_strategy1_structured_payment():
    body = (
        "You have made a payment to FAIRPRICE FINEST on your credit card ending 9876.\n"
        "Transaction Time:\n"
        "15 May 2026 14:30 SGT\n"
        "Amount:\n"
        "SGD 32.50"
    )
    email = make_email(subject="Transaction Notification", body_text=body)
    txns = parser.parse(email)

    assert len(txns) == 1
    txn = txns[0]
    assert txn["amount"] == -3250
    assert txn["payee_name"] == "FAIRPRICE FINEST"
    assert txn["notes"] == "MariCard *9876"
    assert txn["date"] == "2026-05-15"
    assert txn["imported_id"].startswith("mari:")


# ---------------------------------------------------------------------------
# Test 2 — Non-transaction subjects are skipped (early-exit guard)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("subject", [
    "Your email address has been updated",
    "Welcome to MariBank",
    "Password reset notification",
])
def test_non_transaction_subjects_skipped(subject):
    email = make_email(subject=subject, body_text="Some body content here.")
    txns = parser.parse(email)
    assert txns == []


# ---------------------------------------------------------------------------
# Test 3 — sender_pattern correctness (regression guard)
# ---------------------------------------------------------------------------

def test_sender_pattern():
    pattern = parser.sender_pattern
    assert re.search(pattern, "notifications@maribank.sg", re.IGNORECASE)
    assert not re.search(pattern, "noreply@maribank.sg", re.IGNORECASE)
    assert re.search(pattern, "alerts@maribank.sg", re.IGNORECASE)   # domain match


# ---------------------------------------------------------------------------
# Test 4 — imported_id is deterministic
# ---------------------------------------------------------------------------

def test_imported_id_determinism():
    body = (
        "You have made a payment to GRAB on your credit card ending 1111.\n"
        "Transaction Time:\n"
        "01 Jun 2026 10:00 SGT\n"
        "Amount:\n"
        "SGD 9.80"
    )
    email = make_email(subject="Transaction Notification", body_text=body)
    txns_a = parser.parse(email)
    txns_b = parser.parse(email)

    assert len(txns_a) == 1
    assert len(txns_b) == 1
    assert txns_a[0]["imported_id"] == txns_b[0]["imported_id"]


# ---------------------------------------------------------------------------
# Test 5 — Different amount/merchant → different imported_id
# ---------------------------------------------------------------------------

def test_different_transactions_have_different_imported_ids():
    body_a = (
        "You have made a payment to GRAB on your credit card ending 1111.\n"
        "Transaction Time:\n"
        "01 Jun 2026 10:00 SGT\n"
        "Amount:\n"
        "SGD 9.80"
    )
    body_b = (
        "You have made a payment to MCDONALDS on your credit card ending 1111.\n"
        "Transaction Time:\n"
        "01 Jun 2026 10:00 SGT\n"
        "Amount:\n"
        "SGD 15.40"
    )
    email_a = make_email(subject="Transaction Notification", body_text=body_a)
    email_b = make_email(subject="Transaction Notification", body_text=body_b)

    txns_a = parser.parse(email_a)
    txns_b = parser.parse(email_b)

    assert len(txns_a) == 1
    assert len(txns_b) == 1
    assert txns_a[0]["imported_id"] != txns_b[0]["imported_id"]
