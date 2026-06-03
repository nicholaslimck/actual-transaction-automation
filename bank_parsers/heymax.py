"""Parser for HeyMax Chocolate card miles confirmation emails.

Two email formats exist (both from max@heymax.ai):

  Format A — "earned" (pending, ~7 days to settle)
    Subject: 15.2 Max Miles earned on your Chocolate card! 💳

  Format B — "confirmed" (settled, miles ready to redeem)
    Subject: 🎊 52.2 Max Miles confirmed!

Both share the same structured field block:
    Merchant          <name>
    Miles Earned      <amount>
    Transaction Amnt  SGD <amount>
    Transaction Time  YYYY-MM-DD HH:MM:SS +0800

We only import FORMAT B (confirmed), emitting a tracking entry
with amount=0 and miles/merchant info in notes. The underlying
SGD transaction is already captured by the Trust parser.
"""

from . import BaseParser
import re
import logging

logger = logging.getLogger(__name__)

# Non-transaction subject keywords — skip promos, newsletters, etc.
_NON_TX_SUBJECTS = [
    "something huge",
    "giveaway",
    "bi-weekly scoop",
    "what's new",
    "your monthly",
    "your weekly",
]


class HeymaxParser(BaseParser):
    """HeyMax Chocolate card miles confirmation parser."""

    @property
    def bank_name(self) -> str:
        return "HeyMax"

    @property
    def sender_pattern(self) -> str:
        return r"max@heymax\.ai"

    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        """Parse a confirmed miles notification, or None to skip.

        Only processes "confirmed" format (Format B). Returns None for
        pending "earned" emails, promos, newsletters, etc.
        """
        subject = email_data.get("subject", "")

        # Skip non-transaction emails early
        subject_lower = subject.lower()
        if any(kw in subject_lower for kw in _NON_TX_SUBJECTS):
            return None

        # Only process "confirmed" format — skip pending "earned" notifications
        if "confirmed" not in subject_lower:
            return None

        return self._extract_confirmed(text, email_data)

    def _extract_confirmed(self, text: str, email_data: dict) -> dict | None:
        """Extract transaction from a confirmed miles notification.

        Expected plain-text block:

            Merchant
            <merchant name>

            Miles Earned
            <float>

            Transaction Amount
            SGD <amount>

            Transaction Time
            YYYY-MM-DD HH:MM:SS +0800
        """
        msg_id = email_data.get("message_id", "")

        # Merchant: text after "Merchant" line, before next blank or section
        merchant_m = re.search(
            r"^Merchant\s*\n\s*(.+?)(?:\n\s*\n|\n\s*(?:Miles\s+Earned|$))",
            text, re.MULTILINE | re.IGNORECASE
        )

        # Miles Earned
        miles_m = re.search(
            r"Miles\s+Earned\s*\n\s*([0-9,.]+)",
            text, re.IGNORECASE
        )

        # Transaction amount
        amount_m = re.search(
            r"Transaction\s+Amount\s*\n\s*SGD\s*([0-9,.]+)",
            text, re.IGNORECASE
        )

        # Transaction time: YYYY-MM-DD HH:MM:SS
        time_m = re.search(
            r"Transaction\s+Time\s*\n\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
            text, re.IGNORECASE
        )

        if not merchant_m and not amount_m and not time_m:
            return None

        merchant = merchant_m.group(1).strip() if merchant_m else ""
        if merchant:
            merchant = re.sub(r"\s+", " ", merchant).strip()

        miles_str = miles_m.group(1) if miles_m else "0"
        amount_str = amount_m.group(1) if amount_m else "0"

        # Date is already in YYYY-MM-DD from the email
        date_ymd = time_m.group(1).strip()[:10] if time_m else ""

        # Build notes with miles info
        notes_parts = [f"Miles: {miles_str}", f"SGD {amount_str}"]
        if merchant:
            notes_parts.append(merchant)
        notes = " | ".join(notes_parts)

        logger.debug(
            "HeyMax confirmed: merchant=%s miles=%s sgd=%s date=%s",
            merchant, miles_str, amount_str, date_ymd
        )

        return {
            "date": date_ymd,
            "amount": 0,  # non-monetary tracking entry
            "payee_name": f"HeyMax Miles — {merchant}" if merchant else "HeyMax Miles",
            "imported_id": msg_id,
            "notes": notes,
        }
