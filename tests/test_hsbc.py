"""Tests for HsbcParser (bank_parsers/hsbc.py).

Real-world samples taken from HSBC Singapore credit card alert emails
(sender HSBC.Bank.Singapore.Limited@notification.hsbc.com.hk, subject
"Transaction Alerts  (Credit Card)"). HSBC sends HTML-only mail.
"""
import re
import pytest
from datetime import datetime, timezone
from bank_parsers.hsbc import HsbcParser

parser = HsbcParser()

# Real alert, verbatim field values (FlyScoot, 8 Sep 2026).
REAL_FLYSCOOT_HTML = """
<html><body>
<p>Dear Customer <br><br>
Please note there was a transaction made on your HSBC credit card. <br><br></p>
<table width="100%" cellspacing="0" border="1"><tbody>
<tr><td><p>Card Number</p></td><td><p>XXXX-XXXX-XXXX-6966</p></td></tr>
<tr><td><p>Transaction Date</p></td><td><p>08/SEP/2026</p></td></tr>
<tr><td><p>Transaction Time</p></td><td><p>23:53:13</p></td></tr>
<tr><td><p>Transaction Amount</p></td><td><p>SGD613.56</p></td></tr>
<tr><td><p>Description</p></td><td><p>FLYSCOOT63924508282243</p></td></tr>
</tbody></table>
<p>You can also log on to the HSBC Singapore app to view your recent transactions.</p>
</body></html>
"""

# Real alert with a clean merchant name (no glued reference number).
REAL_TORIQ_HTML = """
<html><body>
<p>Dear Customer <br><br>
Please note there was a transaction made on your HSBC credit card. <br><br></p>
<table><tbody>
<tr><td><p>Card Number</p></td><td><p>XXXX-XXXX-XXXX-6966</p></td></tr>
<tr><td><p>Transaction Date</p></td><td><p>10/SEP/2026</p></td></tr>
<tr><td><p>Transaction Time</p></td><td><p>18:12:49</p></td></tr>
<tr><td><p>Transaction Amount</p></td><td><p>SGD11.70</p></td></tr>
<tr><td><p>Description</p></td><td><p>TORI-Q BISHAN JUNCTION 8</p></td></tr>
</tbody></table>
</body></html>
"""


def make_email(subject="Transaction Alerts  (Credit Card)", body_text="", body_html="",
               message_id="<test-msg-1>", email_date=None, raw_id="1"):
    return {
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "date": "",
        "message_id": message_id,
        "email_date": email_date or datetime(2026, 9, 8, tzinfo=timezone.utc),
        "raw_id": raw_id,
    }


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def test_sgd_transaction_with_reference_number():
    """Real FlyScoot alert: SGD outflow, reference digits stripped from payee."""
    txns = parser.parse(make_email(body_html=REAL_FLYSCOOT_HTML))

    assert len(txns) == 1
    txn = txns[0]
    assert txn["amount"] == -61356                      # outflow
    assert txn["payee_name"] == "FLYSCOOT"              # 63924508282243 stripped
    assert txn["date"] == "2026-09-08"
    assert txn["account_last4"] == "6966"
    assert txn["cleared"] is True
    assert txn["imported_id"].startswith("hsbc:")
    assert "HSBC *6966" in txn["notes"]
    assert "FLYSCOOT63924508282243" in txn["notes"]     # raw preserved for traceability


def test_sgd_transaction_clean_merchant_untouched():
    """Merchant ending in a short number ('JUNCTION 8') must NOT be stripped."""
    txns = parser.parse(make_email(body_html=REAL_TORIQ_HTML))

    assert len(txns) == 1
    assert txns[0]["amount"] == -1170
    assert txns[0]["payee_name"] == "TORI-Q BISHAN JUNCTION 8"
    assert txns[0]["date"] == "2026-09-10"
    # No raw duplicate when nothing was stripped
    assert txns[0]["notes"] == "HSBC *6966"


def test_plain_text_body_also_parses():
    """Rendered label/value text (non-HTML) parses identically."""
    body = (
        "Dear Customer  Please note there was a transaction made on your HSBC credit card.  "
        "Card Number  XXXX-XXXX-XXXX-6966  Transaction Date  08/SEP/2026  "
        "Transaction Time  23:53:13  Transaction Amount  SGD613.56  "
        "Description  FLYSCOOT63924508282243  You can also log on to the HSBC Singapore app."
    )
    txns = parser.parse(make_email(body_text=body))
    assert len(txns) == 1
    assert txns[0]["payee_name"] == "FLYSCOOT"
    assert txns[0]["amount"] == -61356


# ---------------------------------------------------------------------------
# Subject filtering — non-transaction mail from the same bank must be skipped
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("subject", [
    "Change of Transaction Alert Thresholds (Credit Card)",   # singular 'Alert'
    "Your HSBC Credit Card Enrolment on Digital wallet is successful",
    "You've successfully registered for HSBC online banking",
    "We received your HSBC Credit Card Application",
    "Earn accelerated rewards with your HSBC Revolution Credit Card",
])
def test_non_transaction_subjects_skipped(subject):
    txns = parser.parse(make_email(subject=subject, body_html=REAL_FLYSCOOT_HTML))
    assert txns == []


# ---------------------------------------------------------------------------
# Sender routing
# ---------------------------------------------------------------------------

def test_sender_pattern():
    pattern = parser.sender_pattern
    assert re.search(pattern, "HSBC.Bank.Singapore.Limited@notification.hsbc.com.hk", re.IGNORECASE)
    assert not re.search(pattern, "hsbc.notification@message.hsbc.com.sg", re.IGNORECASE)
    assert not re.search(pattern, "nobody@example.com", re.IGNORECASE)


# ---------------------------------------------------------------------------
# imported_id stability
# ---------------------------------------------------------------------------

def test_imported_id_deterministic():
    a = parser.parse(make_email(body_html=REAL_FLYSCOOT_HTML))
    b = parser.parse(make_email(body_html=REAL_FLYSCOOT_HTML))
    assert a[0]["imported_id"] == b[0]["imported_id"]


def test_same_day_amount_payee_different_time_not_colliding():
    """Two identical purchases at different times must get different ids."""
    body = REAL_FLYSCOOT_HTML.replace("23:53:13", "09:05:00")
    a = parser.parse(make_email(body_html=REAL_FLYSCOOT_HTML))
    b = parser.parse(make_email(body_html=body))
    assert a[0]["imported_id"] != b[0]["imported_id"]


def test_different_merchant_different_id():
    a = parser.parse(make_email(body_html=REAL_FLYSCOOT_HTML))
    b = parser.parse(make_email(body_html=REAL_TORIQ_HTML))
    assert a[0]["imported_id"] != b[0]["imported_id"]


# ---------------------------------------------------------------------------
# Unparseable / malformed
# ---------------------------------------------------------------------------

def test_missing_amount_returns_empty():
    body = REAL_FLYSCOOT_HTML.replace("SGD613.56", "N/A")
    assert parser.parse(make_email(body_html=body)) == []


def test_missing_date_returns_empty():
    body = REAL_FLYSCOOT_HTML.replace("08/SEP/2026", "N/A")
    assert parser.parse(make_email(body_html=body)) == []
