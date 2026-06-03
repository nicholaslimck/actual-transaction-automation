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

    def parse(self, email_data: dict) -> list[dict]:
        """Override to filter by subject before extracting/logging raw text.

        The base class logs 2000 chars of raw text for every email, but
        HeyMax gets many promos/confirmed emails we skip. Filter first.
        """
        subject = email_data.get("subject", "").lower()
        if any(kw in subject for kw in _NON_TX_SUBJECTS):
            return []
        if "earned" not in subject:
            return []

        # Only reach here for earned emails — now extract text and process
        text = self.extract_text(
            email_data.get("body_text", ""),
            email_data.get("body_html", ""),
        )
        logger.debug("%s raw text:\n%s", self.bank_name, text[:2000])
        txn = self._extract_earned(text, email_data)
        return [txn] if txn else []

    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        """Unused — parse() handles routing. Kept for abstract conformance."""
        return self._extract_earned(text, email_data)

    def _extract_earned(self, text: str, email_data: dict) -> dict | None:
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

        if not merchant_m and not amount_m and not time_m:
            return None

        merchant = merchant_m.group(1).strip() if merchant_m else ""
        if merchant:
            merchant = re.sub(r"\s+", " ", merchant).strip()

        miles_str = miles_m.group(1) if miles_m else "0"
        amount_str = amount_m.group(1) if amount_m else "0"

        # Date is already in YYYY-MM-DD from the email
        date_ymd = time_m.group(1).strip()[:10] if time_m else ""

        # Time portion for content hash (disambiguates same-date purchases)
        time_str = time_m.group(1).strip()[11:19] if time_m else ""

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
