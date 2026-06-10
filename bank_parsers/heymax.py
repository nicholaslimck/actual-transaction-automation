"""Parser for HeyMax Chocolate card miles earned emails.

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

We only import FORMAT A (earned), creating an uncleared transaction
with the real SGD outflow amount so it shows up same-day.
The subject_filter config routes "earned" emails at the account level.

Note: HeyMax earned emails carry no card last-4 digits, so account_filter
is unsupported for this parser. Route via subject_filter only.
"""

from . import BaseParser
import re
import logging

logger = logging.getLogger(__name__)


class HeymaxParser(BaseParser):
    """HeyMax Chocolate card miles confirmation parser."""

    subject_exclude_keywords = [
        "something huge",
        "giveaway",
        "bi-weekly scoop",
        "what's new",
        "your monthly",
        "your weekly",
        "confirmed",
    ]
    subject_include_keywords = ["earned"]

    @property
    def bank_name(self) -> str:
        return "HeyMax"

    @property
    def sender_pattern(self) -> str:
        return r"max@heymax\.ai"

    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        """Extract transaction from an earned miles notification.

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

        # Transaction amount — "SGD 6.98" or "$6.98"
        amount_m = re.search(
            r"Transaction\s+Amount\s*\n\s*(?:SGD\s*)?\$?\s*([0-9,.]+)",
            text, re.IGNORECASE
        )

        # Transaction time: YYYY-MM-DD HH:MM:SS
        time_m = re.search(
            r"Transaction\s+Time\s*\n\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
            text, re.IGNORECASE
        )

        # amount and time are required: amount drives the ledger entry,
        # time provides the date. A partial match must not emit a $0 / empty-date txn.
        if not amount_m or not time_m:
            return None

        merchant = merchant_m.group(1).strip() if merchant_m else ""
        if merchant:
            merchant = re.sub(r"\s+", " ", merchant).strip()

        miles_str = miles_m.group(1) if miles_m else "0"
        amount_str = amount_m.group(1)          # guaranteed by guard above

        # Date is already in YYYY-MM-DD from the email
        date_ymd = time_m.group(1).strip()[:10]  # guaranteed by guard above

        # Time portion for content hash (disambiguates same-date purchases)
        time_str = time_m.group(1).strip()[11:19]

        # Build notes with miles info
        notes_parts = [f"Miles: {miles_str}", f"SGD {amount_str}"]
        if merchant:
            notes_parts.append(merchant)
        notes = " | ".join(notes_parts)

        amount_cents = -self.to_cents(amount_str)
        imported_id = self._content_id("heymax", date_ymd, amount_cents, merchant, time_str)

        logger.debug(
            "HeyMax earned: merchant=%s miles=%s sgd=%s date=%s",
            merchant, miles_str, amount_str, date_ymd
        )

        return {
            "date": date_ymd,
            "amount": amount_cents,
            "payee_name": merchant or "HeyMax Miles",
            "imported_id": imported_id,
            "notes": notes,
            "cleared": False,
        }
