"""Tests for TrustParser (bank_parsers/trust.py)."""
import pytest
from datetime import datetime, timezone
from bank_parsers.trust import TrustParser
import bank_parsers.trust as trust_mod

parser = TrustParser()


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
# Test 1 — Local SGD payment
# ---------------------------------------------------------------------------

def test_local_sgd_payment():
    body = (
        "You've spent SGD 45.50 at Starbucks Singapore SG on 15 May 2026 "
        "10:30SGT with Visa Infinite ending 1234."
    )
    email = make_email(subject="Trust Bank transaction", body_text=body)
    txns = parser.parse(email)

    assert len(txns) == 1
    txn = txns[0]
    assert txn["amount"] == -4550
    assert txn["payee_name"] == "Starbucks"
    assert txn["date"] == "2026-05-15"
    assert txn["imported_id"].startswith("trust-local:")


# ---------------------------------------------------------------------------
# Test 2 — Overseas payment (monkeypatched FX)
# ---------------------------------------------------------------------------

def test_overseas_payment_monkeypatched_fx(monkeypatch):
    monkeypatch.setattr(trust_mod, "sgd_from", lambda cur, cents: (int(cents * 1.30), 1.30))

    body = (
        "You've spent USD 100.00 using Visa Infinite ending 1234 "
        "at Amazon US on 20 May 2026 08:00SGT"
    )
    email = make_email(subject="Trust Bank transaction", body_text=body)
    txns = parser.parse(email)

    assert len(txns) == 1
    txn = txns[0]
    # 100.00 USD * 1.30 = 130.00 SGD = 13000 cents, outflow
    assert txn["amount"] == -13000
    assert txn["payee_name"] == "Amazon"
    assert "USD" in txn["notes"]
    assert "1.3000" in txn["notes"]
    assert txn["imported_id"].startswith("trust:")
    assert txn["cleared"] is False


# ---------------------------------------------------------------------------
# Test 3 — _clean_merchant cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Starbucks Singapore SG", "Starbucks"),
    ("Amazon US", "Amazon"),
    ("Netflix", "Netflix"),
    ("Grab SG", "Grab"),
])
def test_clean_merchant(raw, expected):
    assert TrustParser._clean_merchant(raw) == expected


# ---------------------------------------------------------------------------
# Test 4 — imported_id is deterministic
# ---------------------------------------------------------------------------

def test_imported_id_determinism():
    body = (
        "You've spent SGD 12.00 at Coffee Bean SG on 01 Jun 2026 "
        "09:00SGT with Visa ending 5678."
    )
    email = make_email(body_text=body)
    txns_a = parser.parse(email)
    txns_b = parser.parse(email)

    assert len(txns_a) == 1
    assert len(txns_b) == 1
    assert txns_a[0]["imported_id"] == txns_b[0]["imported_id"]


# ---------------------------------------------------------------------------
# Test 5 — Same payee/amount/date at different times → different imported_id
# ---------------------------------------------------------------------------

def test_same_payee_amount_different_time_produces_different_id():
    """Two separate purchases at same merchant, same day, same price must not collide."""
    body_a = (
        "You've spent SGD 5.00 at Koufu SG on 01 Jun 2026 "
        "08:00SGT with Visa ending 5678."
    )
    body_b = (
        "You've spent SGD 5.00 at Koufu SG on 01 Jun 2026 "
        "12:30SGT with Visa ending 5678."
    )
    txns_a = parser.parse(make_email(body_text=body_a))
    txns_b = parser.parse(make_email(body_text=body_b))
    assert len(txns_a) == 1 and len(txns_b) == 1
    assert txns_a[0]["imported_id"] != txns_b[0]["imported_id"]


# ---------------------------------------------------------------------------
# Test 6 — Unparseable body returns empty list
# ---------------------------------------------------------------------------

def test_local_account_last4_from_ending_in_card_name():
    """Trust card name 'Visa Infinite ending 1234' contains digits; extract_last4 finds them."""
    body = (
        "You've spent SGD 45.50 at Starbucks Singapore SG on 15 May 2026 "
        "10:30SGT with Visa Infinite ending 1234."
    )
    txns = parser.parse(make_email(body_text=body))
    assert txns[0]["account_last4"] == "1234"


def test_local_account_last4_none_when_no_digits():
    """Card name with no digits -> account_last4 is None."""
    body = (
        "You've spent SGD 10.00 at Kopitiam SG on 01 Jun 2026 "
        "09:00SGT with Trust Platinum."
    )
    txns = parser.parse(make_email(body_text=body))
    assert len(txns) == 1
    assert txns[0]["account_last4"] is None


def test_overseas_account_last4(monkeypatch):
    monkeypatch.setattr(trust_mod, "sgd_from", lambda cur, cents: (cents, 1.0))
    body = (
        "You've spent USD 50.00 using Visa ending 5678 "
        "at Netflix US on 10 Jun 2026 00:00SGT"
    )
    txns = parser.parse(make_email(body_text=body))
    assert len(txns) == 1
    assert txns[0]["account_last4"] == "5678"


def test_unparseable_body_returns_empty():
    email = make_email(
        subject="Trust Bank",
        body_text="Your account statement is ready. Please log in to view.",
    )
    txns = parser.parse(email)
    assert txns == []


# ---------------------------------------------------------------------------
# H1 — overseas txn skipped when FX rate unavailable
# ---------------------------------------------------------------------------

def test_overseas_no_rate_returns_empty(monkeypatch):
    """When sgd_from cannot resolve a rate, the txn must be dropped so the
    email stays unread and retries rather than importing the wrong amount."""
    monkeypatch.setattr(trust_mod, "sgd_from", lambda cur, cents: (cents, None))
    body = (
        "You've spent USD 100.00 using Visa Infinite ending 1234 "
        "at Amazon US on 20 May 2026 08:00SGT"
    )
    txns = parser.parse(make_email(body_text=body))
    assert txns == []
