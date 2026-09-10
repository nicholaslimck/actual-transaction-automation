"""Parser for HSBC Singapore credit card transaction alert emails.

Verified against real HSBC SG alerts (Sep 2026).

Sender:  HSBC.Bank.Singapore.Limited@notification.hsbc.com.hk
Subject: "Transaction Alerts  (Credit Card)"   (note the double space)

The body is HTML-only and renders as label/value pairs:

    Dear Customer
    Please note there was a transaction made on your HSBC credit card.

    Card Number        XXXX-XXXX-XXXX-6966
    Transaction Date   08/SEP/2026
    Transaction Time   23:53:13
    Transaction Amount SGD613.56
    Description        FLYSCOOT63924508282243

Notes
-----
* The ``Description`` value is the merchant, sometimes with a long reference
  number appended (e.g. ``FLYSCOOT63924508282243``). That trailing digit run
  is stripped so payee names stay stable for auto-categorisation rules.
* The same sender domain also delivers "Change of Transaction Alert
  Thresholds (Credit Card)" — not a transaction. It is filtered out by the
  plural subject include keyword ("transaction alerts").
"""
from . import BaseParser
from .fx import sgd_from
import re
import logging

logger = logging.getLogger(__name__)


class HsbcParser(BaseParser):
    """HSBC Singapore credit card transaction alert parser."""

    # Real alerts only. The thresholds-change email contains "Transaction
    # Alert" (singular) but not the plural "Transaction Alerts".
    subject_include_keywords = ["transaction alerts"]

    subject_exclude_keywords = [
        "thresholds",
        "enrolment",
        "enrollment",
        "online banking",
        "application",
        "welcome",
        "otp",
        "password",
        "statement",
    ]

    @property
    def bank_name(self) -> str:
        return "HSBC"

    @property
    def sender_pattern(self) -> str:
        return r"notification\.hsbc\.com"

    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        """Extract one transaction from the rendered HSBC alert text."""
        date_m = re.search(r"Transaction\s+Date\s+(\d{1,2}/[A-Za-z]{3}/\d{4})", text)
        amount_m = re.search(
            r"Transaction\s+Amount\s+([A-Za-z]{3})\s*([\d,]+(?:\.\d{2})?)", text
        )
        if not date_m or not amount_m:
            return None

        time_m = re.search(r"Transaction\s+Time\s+(\d{1,2}:\d{2}(?::\d{2})?)", text)
        card_m = re.search(r"Card\s+Number\s*[\dXx*\-]*?(\d{4})\b", text)
        desc_m = re.search(r"Description\s+(.+?)\s+You can also\b", text) or re.search(
            r"Description\s+(.+?)(?:\s*$)", text
        )

        raw_desc = self._clean_merchant(desc_m.group(1)) if desc_m else ""
        # Strip a long trailing reference number glued to the merchant name,
        # e.g. "FLYSCOOT63924508282243" -> "FLYSCOOT". Requires 6+ digits so
        # ordinary merchants (e.g. "TORI-Q BISHAN JUNCTION 8") are untouched.
        merchant = re.sub(r"^(.*?[A-Za-z])[0-9]{6,}$", r"\1", raw_desc).strip() or raw_desc

        # "08/SEP/2026" -> "08 SEP 2026"; strptime %b is case-insensitive.
        date_str = date_m.group(1).replace("/", " ")
        txn_time = time_m.group(1) if time_m else ""
        card_last4 = card_m.group(1) if card_m else None

        cur = amount_m.group(1).upper()
        amount_raw = self.to_cents(amount_m.group(2))

        if cur == "SGD":
            amount_cents = -amount_raw          # outflow
            cleared = True
            fx_note = ""
        else:
            sgd_cents, rate = sgd_from(cur, amount_raw)
            if rate is None:
                logger.error(
                    "HSBC foreign txn skipped: no FX rate for %s (%s %s). "
                    "Email left unread to retry.",
                    cur, cur, amount_m.group(2),
                )
                return None
            amount_cents = -sgd_cents
            cleared = False
            fx_note = f"{cur}{amount_m.group(2)} @ {rate:.4f}"

        notes_parts = []
        if card_last4:
            notes_parts.append(f"HSBC *{card_last4}")
        if fx_note:
            notes_parts.append(fx_note)
        if raw_desc and raw_desc != merchant:
            notes_parts.append(f"Raw: {raw_desc}")

        parsed_date = self.parse_date(date_str, email_data.get("email_date"))

        return {
            "date": parsed_date,
            "amount": amount_cents,
            "payee_name": merchant,
            "imported_id": self._content_id(
                "hsbc", parsed_date, amount_cents, merchant, txn_time
            ),
            "notes": " | ".join(notes_parts),
            "account_last4": card_last4,
            "cleared": cleared,
        }
