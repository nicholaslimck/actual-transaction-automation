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

def test_same_payee_amount_different_time_produces_different_id():
    """Two purchases: same day, amount, merchant but different time must not collide."""
    body_a = (
        "You have made a payment to GRAB on your credit card ending 1111.\n"
        "Transaction Time:\n"
        "01 Jun 2026 10:00 SGT\n"
        "Amount:\n"
        "SGD 9.80"
    )
    body_b = (
        "You have made a payment to GRAB on your credit card ending 1111.\n"
        "Transaction Time:\n"
        "01 Jun 2026 18:45 SGT\n"
        "Amount:\n"
        "SGD 9.80"
    )
    email_a = make_email(subject="Transaction Notification", body_text=body_a)
    email_b = make_email(subject="Transaction Notification", body_text=body_b)
    txns_a = parser.parse(email_a)
    txns_b = parser.parse(email_b)
    assert len(txns_a) == 1 and len(txns_b) == 1
    assert txns_a[0]["imported_id"] != txns_b[0]["imported_id"]


def test_strategy1_account_last4():
    body = (
        "You have made a payment to FAIRPRICE FINEST on your credit card ending 9876.\n"
        "Transaction Time:\n"
        "15 May 2026 14:30 SGT\n"
        "Amount:\n"
        "SGD 32.50"
    )
    txns = parser.parse(make_email(subject="Transaction Notification", body_text=body))
    assert txns[0]["account_last4"] == "9876"


def test_strategy2_fallback_account_last4_is_none():
    """Strategy-2 fallback cannot extract a card ending -> account_last4 is None."""
    body = (
        "Payment to GRAB on your card\n"
        "Transaction Time:\n"
        "01 Jun 2026 10:00 SGT\n"
        "Amount:\n"
        "SGD 9.80"
    )
    txns = parser.parse(make_email(subject="Transaction Notification", body_text=body))
    assert len(txns) == 1
    assert txns[0]["account_last4"] is None


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


# ---------------------------------------------------------------------------
# Auto-repayment tests (new format)
# ---------------------------------------------------------------------------


def test_auto_repayment_basic():
    """Auto-repayment email: positive amount, proper payee, date from header."""
    body = (
        "Your auto repayment to your Mari Credit Card is successful. "
        "You have paid the statement due for your May statement. "
        "Payment Amount: SGD 882.90 "
        "Deducted from: Mari Savings Account ending 7744."
    )
    email = make_email(
        subject="Your auto repayment is successful",
        body_text=body,
        email_date=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )
    txns = parser.parse(email)

    assert len(txns) == 1
    txn = txns[0]
    assert txn["amount"] == 88290        # positive = inflow
    assert txn["payee_name"] == "MariCard Auto Repayment"
    assert txn["date"] == "2026-06-05"
    assert "From Mari Savings *7744" in txn["notes"]
    assert "May statement" in txn["notes"]
    assert txn["account_last4"] is None
    assert txn["imported_id"].startswith("mari-repay:")


def test_auto_repayment_no_savings_info():
    """Resilient when savings account detail is missing."""
    body = (
        "Your auto repayment to your Mari Credit Card is successful. "
        "You have paid the statement due for your June statement. "
        "Payment Amount: SGD 450.00"
    )
    email = make_email(
        subject="Your auto repayment is successful",
        body_text=body,
        email_date=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )
    txns = parser.parse(email)

    assert len(txns) == 1
    txn = txns[0]
    assert txn["amount"] == 45000
    assert txn["notes"] == "June statement"  # no savings part


def test_auto_repayment_subject_trigger():
    """Autopay email routed correctly even with minimal body match."""
    body = "auto repayment to your Mari Credit Card. Payment Amount: SGD 120.50"
    email = make_email(
        subject="Your auto repayment is successful",
        body_text=body,
        email_date=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )
    txns = parser.parse(email)
    assert len(txns) == 1
    assert txns[0]["amount"] == 12050


def test_auto_repayment_does_not_affect_standard_txns():
    """Regular purchase emails should still parse as before (not as repayment)."""
    body = (
        "You have made a payment to GRAB on your credit card ending 1111.\n"
        "Transaction Time:\n"
        "01 Jun 2026 10:00 SGT\n"
        "Amount:\n"
        "SGD 9.80"
    )
    email = make_email(subject="Transaction Notification", body_text=body)
    txns = parser.parse(email)
    assert len(txns) == 1
    assert txns[0]["amount"] == -980   # negative = outflow
    assert txns[0]["payee_name"] == "GRAB"


def test_auto_repayment_deterministic_id():
    """Same repayment email -> same imported_id."""
    body = (
        "Your auto repayment to your Mari Credit Card is successful. "
        "Payment Amount: SGD 200.00 "
        "Deducted from: Mari Savings Account ending 7744."
    )
    email = make_email(
        subject="Your auto repayment is successful",
        body_text=body,
        email_date=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )
    txns_a = parser.parse(email)
    txns_b = parser.parse(email)
    assert txns_a[0]["imported_id"] == txns_b[0]["imported_id"]


def test_auto_repayment_non_matching_body_returns_empty():
    """Auto-repayment subject but body lacks Payment Amount -> empty."""
    body = "Your auto repayment to your Mari Credit Card is successful. Some other content without amount."
    email = make_email(
        subject="Your auto repayment is successful",
        body_text=body,
        email_date=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )
    txns = parser.parse(email)
    assert txns == []


def test_auto_repayment_repayment_body_standard_subject_not_routed():
    """Repayment-like body but standard subject -> not routed to auto-repayment."""
    body = (
        "Your auto repayment to your Mari Credit Card is successful. "
        "Payment Amount: SGD 200.00"
    )
    email = make_email(
        subject="Transaction Notification",
        body_text=body,
        email_date=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )
    txns = parser.parse(email)
    # Standard subject -> _parse_alert path -> no match -> empty
    assert txns == []


def test_auto_repayment_different_statement_produces_different_id():
    """Same amount, same day, different statement period -> different imported_id."""
    body_may = (
        "Your auto repayment to your Mari Credit Card is successful. "
        "You have paid the statement due for your May statement. "
        "Payment Amount: SGD 500.00 "
        "Deducted from: Mari Savings Account ending 7744."
    )
    body_jun = (
        "Your auto repayment to your Mari Credit Card is successful. "
        "You have paid the statement due for your June statement. "
        "Payment Amount: SGD 500.00 "
        "Deducted from: Mari Savings Account ending 7744."
    )
    email_may = make_email(
        subject="Your auto repayment is successful",
        body_text=body_may,
        email_date=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )
    email_jun = make_email(
        subject="Your auto repayment is successful",
        body_text=body_jun,
        email_date=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )
    txn_may = parser.parse(email_may)[0]
    txn_jun = parser.parse(email_jun)[0]
    assert txn_may["imported_id"] != txn_jun["imported_id"]
