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
        return r"noreply@maribank\.sg|maribank\.sg|maribank"

    def parse(self, email_data: dict) -> list[dict]:
        subject = email_data.get("subject", "")
        # Early-exit for non-transaction emails
        subject_lower = subject.lower()
        if any(kw in subject_lower for kw in self._NON_TX_SUBJECTS):
            logger.debug("Skipping non-transaction MariBank email: %s", subject)
            return []
        text = self.extract_text(email_data.get("body_text", ""), email_data.get("body_html", ""))
        msg_id = email_data.get("message_id", "")

        logger.debug("MariBank raw text:\n%s", text[:2000])

        txns = []
        txn = self._parse_alert(text, subject, msg_id)
        if txn:
            txns.append(txn)
        else:
            logger.warning("Could not parse MariBank email. Subject: %s", subject)
            logger.debug("Full text:\n%s", text)

        return txns

    def _parse_alert(self, text: str, subject: str, msg_id: str) -> dict | None:
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

            return {
                "date": self.parse_date(date_str),
                "amount": -self.to_cents(amount_str),
                "payee_name": merchant,
                "imported_id": msg_id,
                "notes": card_note,
            }

        # Strategy 2: Simpler pattern -- find any amount + merchant combo
        fallback = re.search(
            r"to\s+(.+?)(?:\s+on\s+your\s+card|\s*$)",
            text, re.IGNORECASE
        )
        if fallback and date_m and amount_m:
            return {
                "date": self.parse_date(date_m.group(1).strip()),
                "amount": -self.to_cents(amount_m.group(1)),
                "payee_name": fallback.group(1).strip().rstrip("."),
                "imported_id": msg_id,
                "notes": "",
            }

        return None
