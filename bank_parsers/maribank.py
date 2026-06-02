"""Parser for MariBank transaction alert emails."""
from . import BaseParser
import re
import logging

logger = logging.getLogger(__name__)


class MaribankParser(BaseParser):
    """MariBank Singapore transaction alert email parser.

    Observed format (plain text or HTML):

        You have made a payment to <MERCHANT> on your credit card ending <CARD>.
        Transaction Time:
        <DD MMM YYYY> <HH:MM> SGT
        Amount:
        SGD <AMOUNT>

    Subject: likely "Transaction Notification" or similar
    """

    # Known non-transaction subject keywords — skip early
    _NON_TX_SUBJECTS = [
        "email address has been updated",
        "welcome to maribank",
        "password",
        "otp",
        "login",
        "security",
        "registered",
        "updated successfully",
    ]

    @property
    def bank_name(self) -> str:
        return "MariBank"

    @property
    def sender_pattern(self) -> str:
        return r"notifications@maribank\.sg|(?<!noreply@)maribank\.sg"

    def parse(self, email_data: dict) -> list[dict]:
        subject = email_data.get("subject", "")
        subject_lower = subject.lower()
        if any(kw in subject_lower for kw in self._NON_TX_SUBJECTS):
            logger.debug("Skipping non-transaction MariBank email: %s", subject)
            return []
        return super().parse(email_data)

    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        """Parse the structured Maribank email.

        Pattern:
          You have made a payment to <MERCHANT> on your credit card ending XXXX.
          Transaction Time:
          <DATE> <TIME> SGT
          Amount:
          SGD <AMOUNT>
        """
        # Strategy 1: Full structured format
        m = re.search(
            r"made\s+a\s+payment\s+to\s+(.+?)(?:\s+on\s+your\s+|\s*$)",
            text, re.IGNORECASE
        )
        date_m = re.search(r"Transaction\s*Time[:\s]*\n?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text, re.IGNORECASE)
        amount_m = re.search(r"Amount[:\s]*\n?\s*SGD\s*([0-9,.]+)", text, re.IGNORECASE)
        card_m = re.search(r"(?:card\s+ending|card\s+\*{3,}|XXXX)\s*(\d{4})", text, re.IGNORECASE)

        if m and date_m and amount_m:
            merchant = m.group(1).strip().rstrip(".")
            date_str = date_m.group(1).strip()
            amount_str = amount_m.group(1)

            card_note = ""
            if card_m:
                card_note = f"MariCard *{card_m.group(1)}"

            parsed_date = self.parse_date(date_str)
            amount_cents = -self.to_cents(amount_str)
            return {
                "date": parsed_date,
                "amount": amount_cents,
                "payee_name": merchant,
                "imported_id": self._content_id("mari", parsed_date, amount_cents, merchant),
                "notes": card_note,
            }

        # Strategy 2: Looser fallback for MariBank email variants where the phrasing
        # differs from "made a payment to ... on your" (e.g. future template changes).
        # Fires when Strategy-1 fails but Transaction Time + Amount are still present.
        # If both strategies produce a result, Strategy-1 takes precedence.
        fallback = re.search(
            r"to\s+(.+?)(?:\s+on\s+your\s+card|\s*$)",
            text, re.IGNORECASE
        )
        if fallback and date_m and amount_m:
            parsed_date = self.parse_date(date_m.group(1).strip())
            amount_cents = -self.to_cents(amount_m.group(1))
            payee = fallback.group(1).strip().rstrip(".")
            return {
                "date": parsed_date,
                "amount": amount_cents,
                "payee_name": payee,
                "imported_id": self._content_id("mari", parsed_date, amount_cents, payee),
                "notes": "",
            }

        return None
