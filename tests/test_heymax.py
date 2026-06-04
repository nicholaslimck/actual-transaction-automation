"""Tests for HeymaxParser (bank_parsers/heymax.py)."""
import pytest
from datetime import datetime, timezone
from bank_parsers.heymax import HeymaxParser

parser = HeymaxParser()

_BASE_BODY = (
    "Merchant\n"
    "NTUC Fairprice\n"
    "\n"
    "Miles Earned\n"
    "15.2\n"
    "\n"
    "Transaction Amount\n"
    "SGD 6.98\n"
    "\n"
    "Transaction Time\n"
    "2026-06-01 12:30:00 +0800"
)


def make_email(subject="15.2 Max Miles earned on your Chocolate card! 💳",
               body_text=_BASE_BODY, body_html="",
               message_id="<test-heymax-1>", raw_id="1"):
    return {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "date": "",
        "message_id": message_id,
        "email_date": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "raw_id": raw_id,
    }


# ---------------------------------------------------------------------------
# Format A — SGD prefix ("SGD 6.98")
# ---------------------------------------------------------------------------

def test_earned_sgd_format():
    txns = parser.parse(make_email())
    assert len(txns) == 1
    t = txns[0]
    assert t["amount"] == -698
    assert t["payee_name"] == "NTUC Fairprice"
    assert t["date"] == "2026-06-01"
    assert t["cleared"] is False
    assert t["imported_id"].startswith("heymax:")
    assert "Miles: 15.2" in t["notes"]
    assert "SGD 6.98" in t["notes"]


# ---------------------------------------------------------------------------
# Format A (old) — dollar-sign prefix ("$6.98")
# Regression for commit 9f2a6e4
# ---------------------------------------------------------------------------

def test_earned_dollar_format():
    body = _BASE_BODY.replace("SGD 6.98", "$6.98")
    txns = parser.parse(make_email(body_text=body))
    assert len(txns) == 1
    assert txns[0]["amount"] == -698


# ---------------------------------------------------------------------------
# Format B — "confirmed" subject → skip
# ---------------------------------------------------------------------------

def test_confirmed_subject_skipped():
    txns = parser.parse(make_email(subject="🎊 52.2 Max Miles confirmed!"))
    assert txns == []


# ---------------------------------------------------------------------------
# Non-transaction subjects (promos / newsletters) → skip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kw", [
    "Something huge",
    "Giveaway",
    "Bi-Weekly Scoop",
    "What's New",
    "Your Monthly",
    "Your Weekly",
])
def test_non_tx_subjects_skipped(kw):
    txns = parser.parse(make_email(subject=kw))
    assert txns == []


# ---------------------------------------------------------------------------
# Amount missing in earned email → skip (guards against $0 import bug)
# ---------------------------------------------------------------------------

def test_amount_missing_returns_empty():
    body = _BASE_BODY.replace("\n\nTransaction Amount\nSGD 6.98", "")
    txns = parser.parse(make_email(body_text=body))
    assert txns == []


# ---------------------------------------------------------------------------
# Time missing in earned email → skip (guards against empty-date import bug)
# ---------------------------------------------------------------------------

def test_time_missing_returns_empty():
    body = _BASE_BODY.replace("\n\nTransaction Time\n2026-06-01 12:30:00 +0800", "")
    txns = parser.parse(make_email(body_text=body))
    assert txns == []


# ---------------------------------------------------------------------------
# content-id stability — same inputs always produce same id
# ---------------------------------------------------------------------------

def test_imported_id_is_stable():
    t1 = parser.parse(make_email())[0]
    t2 = parser.parse(make_email())[0]
    assert t1["imported_id"] == t2["imported_id"]


# ---------------------------------------------------------------------------
# content-id time disambiguation — same date/amount/payee, different times
# ---------------------------------------------------------------------------

def test_imported_id_differs_by_time():
    body_a = _BASE_BODY  # 12:30:00
    body_b = _BASE_BODY.replace("12:30:00", "14:45:00")
    t_a = parser.parse(make_email(body_text=body_a))[0]
    t_b = parser.parse(make_email(body_text=body_b))[0]
    assert t_a["imported_id"] != t_b["imported_id"]

