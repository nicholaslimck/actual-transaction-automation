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

        Account Number           : XXXX-XXXX-XXXX-0000
        Transaction date         : 28/05/26
        Transaction time         : 17:01:19
        Transaction amount       : SGD2100.00
        Transaction  details     : SAMPLE MERCHANT

    Amount is outflow (negative). Date format: dd/mm/yy.
    Merchant from "Transaction details" field.
    """

    @property
    def bank_name(self) -> str:
        return "Citibank"

    @property
    def sender_pattern(self) -> str:
        return r"alerts?@citibank\.com\.sg|citibank"

    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        """Parse Citibank structured alert.

        Fields in the email body:
          Account Number:      XXXX-XXXX-XXXX-0000
          Transaction date:    28/05/26
          Transaction time:    17:01:19
          Transaction amount:  SGD2100.00
          Transaction details: SAMPLE MERCHANT
        """
        email_date = email_data.get("email_date")

        # Transaction date: dd/mm/yy
        date_m = re.search(
            r"Transaction\s+date[:\s]+(\d{2}/\d{2}/\d{2,4})",
            text, re.IGNORECASE
        )

        # Transaction time: 17:01:19 (used to disambiguate same-day duplicates)
        time_m = re.search(
            r"Transaction\s+time[:\s]+(\d{2}:\d{2}(?::\d{2})?)",
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
            merchant = self._clean_merchant(merchant_raw)

            notes_parts = []
            if card_m:
                notes_parts.append(card_m.group(1).strip())
            if account_m:
                notes_parts.append(f"*{account_m.group(1)}")

            parsed_date = self.parse_date(date_str, email_date)
            amount_cents = -self.to_cents(amount_str)
            txn_time = time_m.group(1) if time_m else ""
            return {
                "date": parsed_date,
                "amount": amount_cents,  # negative = charge
                "payee_name": merchant,
                "imported_id": self._content_id("citi", parsed_date, amount_cents, merchant, txn_time),
                "notes": " | ".join(notes_parts),
                "account_last4": account_m.group(1) if account_m else None,
            }

        return None
