"""Parser for DBS PayLah! transaction alert emails."""
from . import BaseParser
import re
import logging

logger = logging.getLogger(__name__)


class DbsParser(BaseParser):
    """DBS PayLah! transaction alert email parser.

    Observed format (HTML email, table layout):

        From: PayLah! Alerts <paylah.alert@dbs.com>
        Subject: Transaction Alerts

        Transaction Ref: IPS00000000000000001

        We refer to your PayLah! Google Pay UEN transaction dated 31 May.
        [transaction was completed]

        Date & Time:   31 May 13:51 (SGT)
        Amount:        SGD1.80
        From:          PayLah! Wallet (Mobile ending 0000)
        To:            S-11 (BISHAN 504) FOOD HOUSE PTE LTD

    Note: date has no year -- extracted from the email Date header.
    Amount format: "SGD1.80" (no space, no decimal for round amounts like SGD5)
    """

    @property
    def bank_name(self) -> str:
        return "DBS"

    @property
    def sender_pattern(self) -> str:
        return r"(?:paylah|ibanking)\.alert@dbs\.com|dbs\.com"

    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        subject = email_data.get("subject", "")
        msg_id = email_data.get("message_id", "")
        email_date = email_data.get("email_date")
        txn = self._parse_card_payment(text, subject, msg_id, email_date)
        if txn:
            return txn
        txn = self._parse_card_alert(text, subject, msg_id, email_date)
        if txn:
            return txn
        txn = self._parse_paylah(text, subject, msg_id, email_date)
        if txn:
            return txn
        return self._parse_incoming(text, subject, msg_id, email_date)

    def _parse_card_payment(self, text: str, subject: str, msg_id: str, email_date) -> dict | None:
        """Parse ibanking 'Successful payment to another bank's card' alerts.

        Observed format:

            Transaction Ref: 10000000000000000001

            You've successfully made a payment for your other bank's credit card.
            Date and Time: 02 Jun 16:00 (SGT)
            Amount: SGD 100.00
            From: DBS Savings Plus Account (A/C ending 0000)
            To: Other bank's card ending 0000

        Note: date has no year -- extracted from the email Date header.
        """
        # Anchor: distinctive phrase in body
        if not re.search(r"payment for your other bank.s credit card", text, re.IGNORECASE):
            return None

        ref_m = re.search(r"Transaction\s+Ref[:\s]+([A-Z0-9]+)", text, re.IGNORECASE)

        # Date and Time: 02 Jun 16:00 (SGT)
        date_m = re.search(
            r"Date\s+and\s+Time[:\s]+(\d{1,2}\s+[A-Za-z]+)\s+\d{2}:\d{2}",
            text, re.IGNORECASE
        )

        amount_m = re.search(r"Amount[:\s]+SGD\s*([0-9,.]+)", text, re.IGNORECASE)

        # Card suffix from "To: Other bank's card ending XXXX"
        to_m = re.search(r"\bTo:\s*.*?card\s+ending\s+(\d+)", text, re.IGNORECASE)

        from_m = re.search(r"\bFrom:\s*(.+?)(?:\s*$|\s*\n|\s+To:)", text, re.IGNORECASE | re.MULTILINE)

        if not (date_m and amount_m):
            return None

        date_str = date_m.group(1).strip()
        amount_str = amount_m.group(1)
        suffix = to_m.group(1) if to_m else None
        payee_name = f"Credit Card Payment ({suffix})" if suffix else "Credit Card Payment"
        notes = from_m.group(1).strip() if from_m else ""

        # account_last4: use the source DBS account ending (the account being tracked),
        # not the third-party destination card which belongs to another bank.
        return {
            "date": self.parse_date(date_str, email_date),
            "amount": -self.to_cents(amount_str),
            "payee_name": payee_name,
            "imported_id": ref_m.group(1) if ref_m else msg_id,
            "notes": notes,
            "account_last4": self.extract_last4(notes),
        }

    def _parse_card_alert(self, text: str, subject: str, msg_id: str, email_date) -> dict | None:
        """Parse ibanking 'Card Transaction Alert' emails.

        Observed format:

            Transaction Ref: SP0000000000000000001

            We refer to your card transaction request dated 03/06/26.

            Date & Time: 03 JUN 05:36 (SGT)
            Amount: SGD3.64
            From: DBS/POSB card ending 0000
            To: BUS/MRT
        """
        if not re.search(r"card transaction (?:request|alert)", text, re.IGNORECASE):
            return None

        ref_m = re.search(r"Transaction\s+Ref[:\s]+([A-Z0-9]+)", text, re.IGNORECASE)

        date_m = re.search(
            r"Date\s*&\s*Time[:\s]+(\d{1,2}\s+[A-Za-z]+)\s+\d{2}:\d{2}",
            text, re.IGNORECASE
        )

        amount_m = re.search(r"Amount[:\s]+SGD\s*([0-9,.]+)", text, re.IGNORECASE)

        to_m = re.search(r"\bTo:\s*(.+)", text, re.IGNORECASE)

        from_m = re.search(r"\bFrom:\s*(.+?)(?:\s*\n|\s+To:)", text, re.IGNORECASE)

        if not (date_m and amount_m and to_m):
            return None

        merchant = re.sub(r"\s+", " ", to_m.group(1).strip()).split("\n")[0].strip()
        notes = from_m.group(1).strip() if from_m else ""

        return {
            "date": self.parse_date(date_m.group(1).strip(), email_date),
            "amount": -self.to_cents(amount_m.group(1)),
            "payee_name": merchant,
            "imported_id": ref_m.group(1) if ref_m else msg_id,
            "notes": notes,
            "account_last4": self.extract_last4(notes),
        }

    def _parse_paylah(self, text: str, subject: str, msg_id: str, email_date) -> dict | None:
        """Parse PayLah! format (table with Date & Time, Amount, From, To)."""
        # Transaction reference for dedup
        ref_m = re.search(r"Transaction\s+Ref[:\s]+([A-Z0-9]+)", text, re.IGNORECASE)

        # Date & Time: 31 May 13:51 (SGT) or 31 May 13:51 SGT
        date_m = re.search(
            r"Date\s*&?\s*Time[:\s]+(\d{1,2}\s+[A-Za-z]+)\s+\d{2}:\d{2}\s*(?:\(?\s*(?:SGT|GMT)\s*\)?)?",
            text, re.IGNORECASE
        )

        # Amount: SGD1.80 (no space after SGD, or with space)
        amount_m = re.search(
            r"Amount[:\s]+SGD\s*([0-9,.]+)",
            text, re.IGNORECASE
        )

        # To: (merchant) - always the last field in the email
        to_m = re.search(
            r"\bTo:\s*(.+)",
            text, re.IGNORECASE
        )

        # From: for notes (optional)
        from_m = re.search(
            r"(?<!To:\s)From[:\s]+(.+?)(?=\s+To:|$)",
            text, re.IGNORECASE
        )

        if date_m and amount_m and to_m:
            date_str = date_m.group(1).strip()
            amount_str = amount_m.group(1)
            merchant = to_m.group(1).strip().rstrip(".")
            # Clean up merchant - remove trailing whitespace/newlines
            merchant = re.sub(r"\s+", " ", merchant).strip()
            merchant = merchant.split("\n")[0].strip()

            imported_id = ref_m.group(1) if ref_m else msg_id
            notes = ""
            if from_m:
                notes = from_m.group(1).strip()

            return {
                "date": self.parse_date(date_str, email_date),
                "amount": -self.to_cents(amount_str),
                "payee_name": merchant,
                "imported_id": imported_id,
                "notes": notes,
                "account_last4": self.extract_last4(notes),
            }

        return None

    def _parse_incoming(self, text: str, subject: str, msg_id: str, email_date) -> dict | None:
        """Parse incoming transfer format from ibanking.alert@dbs.com.

        Transaction Ref: PIB00000000000000001   C000000000001

        You have received SGD 25.00 via PayNow on 30 May 2026 15:02  SGT.

        From: ALICE TAN
        To: Your DBS/ POSB account ending 0000
        """
        # Transaction reference
        ref_m = re.search(r"Transaction\s+Ref[:\s]+([A-Z0-9]+)", text, re.IGNORECASE)

        # "You have received SGD <amount> via PayNow on <date> <time> SGT"
        received_m = re.search(
            r"received\s+SGD\s*([0-9,.]+)\s+via\s+PayNow\s+on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            text, re.IGNORECASE
        )

        # From: <sender name>
        from_m = re.search(r"\bFrom:\s*(.+?)(?:\s*$|\s*\n|\s+To:)", text, re.IGNORECASE)

        # To: account info
        to_m = re.search(r"\bTo:\s*(.+)", text, re.IGNORECASE)

        if received_m:
            amount_str = received_m.group(1)
            date_str = received_m.group(2).strip()
            sender_name = from_m.group(1).strip() if from_m else "Unknown"
            account_info = to_m.group(1).strip() if to_m else ""

            return {
                "date": self.parse_date(date_str, email_date),
                "amount": self.to_cents(amount_str),  # positive = incoming
                "payee_name": sender_name,
                "imported_id": ref_m.group(1) if ref_m else msg_id,
                "notes": account_info,
                "account_last4": self.extract_last4(account_info),
            }

        return None
