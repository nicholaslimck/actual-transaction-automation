"""Parser for MariBank transaction alert emails."""
from . import BaseParser
import re
import logging
from datetime import datetime

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

        # Non-transaction emails — skip before any parsing
        if any(kw in subject_lower for kw in self._NON_TX_SUBJECTS):
            logger.debug("Skipping non-transaction MariBank email: %s", subject)
            return []

        # Shared text extraction (single call, used by both paths)
        text = self.extract_text(
            email_data.get("body_text", ""), email_data.get("body_html", "")
        )
        logger.debug("%s raw text:\n%s", self.bank_name, text[:2000])

        # Route by subject
        if "auto repayment" in subject_lower:
            txn = self._parse_auto_repayment(text, email_data)
        else:
            txn = self._parse_alert(text, email_data)

        if not txn:
            logger.warning("Could not parse %s. Subject: %s", self.bank_name, subject)
        return [txn] if txn else []

    def _parse_auto_repayment(self, text: str, email_data: dict) -> dict | None:
        """Parse the Maribank auto repayment (credit card bill payment) email format.

        Pattern (single paragraph, no explicit transaction-time field):

            Your auto repayment to your Mari Credit Card is successful.
            You have paid the statement due for your May statement.
            Payment Amount: SGD <AMOUNT>
            Deducted from: Mari Savings Account ending <LAST4>.

        WARNING: amount is returned AS-IS (positive = inflow to credit card).
        Unlike _parse_alert which negates for outflows, this method does NOT
        negate. This is intentional — do NOT add a negation here.
        """
        if "auto repayment" not in text.lower():
            return None

        amount_m = re.search(
            r"Payment\s*Amount:\s*SGD\s*([0-9,.]+)", text, re.IGNORECASE
        )
        savings_m = re.search(
            r"Mari\s+Savings\s+Account\s+ending\s+(\d{4})", text, re.IGNORECASE
        )
        statement_m = re.search(
            r"statement\s+due\s+for\s+your\s+(.+?)(?:\s*\.|$)", text, re.IGNORECASE
        )

        if not amount_m:
            return None

        # DO NOT NEGATE — repayment is an inflow to the credit card account
        amount_cents = self.to_cents(amount_m.group(1))

        # No explicit transaction datetime in body — use email date header
        email_dt = email_data.get("email_date")
        if email_dt is None:
            email_dt = datetime.now()
        parsed_date = email_dt.strftime("%Y-%m-%d")

        savings_last4 = savings_m.group(1) if savings_m else ""
        statement_period = statement_m.group(1).strip() if statement_m else ""

        parts = []
        if savings_last4:
            parts.append(f"From Mari Savings *{savings_last4}")
        if statement_period:
            parts.append(statement_period)
        notes = " | ".join(parts)

        # Include statement period in content id if available, so two same-day
        # same-amount repayments for different statement months don't collide
        id_key = savings_last4 or "auto-repay"
        if statement_period:
            id_key += f" | {statement_period}"

        return {
            "date": parsed_date,
            "amount": amount_cents,  # positive = inflow (see WARNING above)
            "payee_name": "MariCard Auto Repayment",
            "imported_id": self._content_id(
                "mari-repay", parsed_date, amount_cents, id_key
            ),
            "notes": notes,
            "account_last4": None,
        }

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
        date_m = re.search(r"Transaction\s*Time[:\s]*\n?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+(\d{2}:\d{2})", text, re.IGNORECASE)
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
            txn_time = date_m.group(2) if date_m.lastindex >= 2 else ""
            return {
                "date": parsed_date,
                "amount": amount_cents,
                "payee_name": merchant,
                "imported_id": self._content_id("mari", parsed_date, amount_cents, merchant, txn_time),
                "notes": card_note,
                "account_last4": card_m.group(1) if card_m else None,
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
            txn_time = date_m.group(2) if date_m.lastindex >= 2 else ""
            return {
                "date": parsed_date,
                "amount": amount_cents,
                "payee_name": payee,
                "imported_id": self._content_id("mari", parsed_date, amount_cents, payee, txn_time),
                "notes": "",
                "account_last4": None,
            }

        return None
