"""Parser for Citibank Singapore transaction alert emails."""
from . import BaseParser
import re
import logging

logger = logging.getLogger(__name__)


class CitibankParser(BaseParser):
    """Citibank Singapore transaction alert email parser.

    Observed format (plain text, multipart/alternative):

        Subject: Citi Alerts - Credit Card/Ready Credit Transaction
        From: Citibank Singapore <alerts@citibank.com.sg>

        Dear Customer,
        We would like to inform you that there is a charge made on
        your Citi Cash Back+ Card:

        Account Number           : XXXX-XXXX-XXXX-2575
        Transaction date         : 28/05/26
        Transaction time         : 17:01:19
        Transaction amount       : SGD2100.00
        Transaction  details     : PAYALL RENTAL      -Awakened Essence Pte

    Amount is outflow (negative). Date format: dd/mm/yy.
    Merchant from "Transaction details" field.
    """

    @property
    def bank_name(self) -> str:
        return "Citibank"

    @property
    def sender_pattern(self) -> str:
        return r"alerts?@citibank\.com\.sg|citibank"

    def parse(self, email_data: dict) -> list[dict]:
        subject = email_data.get("subject", "")
        text = self.extract_text(email_data.get("body_text", ""), email_data.get("body_html", ""))
        msg_id = email_data.get("message_id", "")
        email_date = email_data.get("email_date")

        logger.debug("Citibank raw text:\n%s", text[:2000])

        txns = []
        txn = self._parse_alert(text, subject, msg_id, email_date)
        if txn:
            txns.append(txn)
        else:
            logger.warning("Could not parse Citibank email. Subject: %s", subject)
            logger.debug("Full text:\n%s", text)

        return txns

    def _parse_alert(self, text: str, subject: str, msg_id: str, email_date) -> dict | None:
        """Parse Citibank structured alert.

        Fields in the email body:
          Account Number:      XXXX-XXXX-XXXX-2575
          Transaction date:    28/05/26
          Transaction time:    17:01:19
          Transaction amount:  SGD2100.00
          Transaction details: PAYALL RENTAL -Awakened Essence Pte
        """

        # Transaction date: dd/mm/yy
        date_m = re.search(
            r"Transaction\s+date[:\s]+(\d{2}/\d{2}/\d{2,4})",
            text, re.IGNORECASE
        )

        # Transaction amount: SGD2100.00
        amount_m = re.search(
            r"Transaction\s+amount[:\s]+SGD\s*([0-9,.]+)",
            text, re.IGNORECASE
        )

        # Transaction details (merchant name)
        details_m = re.search(
            r"Transaction\s+details[:\s]+(.+?)(?:\s*$|\s*\n)",
            text, re.IGNORECASE | re.DOTALL
        )

        # Account number for notes (last 4 digits)
        account_m = re.search(
            r"Account\s+Number?[:\s]+.*?(\d{4})(?:\s*$|\s*\n)",
            text, re.IGNORECASE
        )

        # Card name from the preamble
        card_m = re.search(
            r"your\s+(.+?Card)",
            text, re.IGNORECASE
        )

        if date_m and amount_m and details_m:
            date_str = date_m.group(1).strip()
            amount_str = amount_m.group(1)
            merchant_raw = details_m.group(1).strip().rstrip(".")

            # Clean up merchant name - collapse whitespace, strip trailing junk
            merchant = re.sub(r"\s+", " ", merchant_raw).strip()
            merchant = merchant.split("\n")[0].strip()
            merchant = merchant.strip(" -").strip()

            notes_parts = []
            if card_m:
                notes_parts.append(card_m.group(1).strip())
            if account_m:
                notes_parts.append(f"*{account_m.group(1)}")

            return {
                "date": self.parse_date(date_str, email_date),
                "amount": -self.to_cents(amount_str),  # negative = charge
                "payee_name": merchant,
                "imported_id": msg_id,
                "notes": " | ".join(notes_parts),
            }

        return None
