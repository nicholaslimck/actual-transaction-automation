"""Parser for MariBank transaction alert emails."""
from . import BaseParser
from .fx import sgd_from
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

    subject_exclude_keywords = [
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

    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        """Route to the right handler based on subject (and body signature)."""
        subject_lower = email_data.get("subject", "").lower()
        if "auto repayment" in subject_lower:
            return self._parse_auto_repayment(text, email_data)
        # "Your credit card repayment is successful" (new format). MUST run
        # before _parse_structured_alert: that method's loose fallback regex
        # would otherwise swallow the rest of the collapsed email as the payee.
        if (
            "credit card repayment" in subject_lower
            or re.search(
                r"repayment\s+to\s+your\s+credit\s+card\s+ending",
                text, re.IGNORECASE,
            )
        ):
            return self._parse_credit_card_repayment(text, email_data)
        return self._parse_structured_alert(text, email_data)

    def _parse_auto_repayment(self, text: str, email_data: dict) -> dict | None:
        """Parse the Maribank auto repayment (credit card bill payment) email format.

        Pattern (single paragraph, no explicit transaction-time field):

            Your auto repayment to your Mari Credit Card is successful.
            You have paid the statement due for your May statement.
            Payment Amount: SGD <AMOUNT>
            Deducted from: Mari Savings Account ending <LAST4>.

        WARNING: amount is returned AS-IS (positive = inflow to credit card).
        Unlike _parse_structured_alert which negates for outflows, this method
        does NOT negate. This is intentional — do NOT add a negation here.
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
            # The alert carries no card number, but it is always MariBank's own
            # card: stamp it so this keeps landing on the Maribank Credit entry
            # (account_filter "1730") rather than a savings-filtered entry.
            "account_last4": self.MARI_CARD_LAST4,
        }

    # MariBank's own credit-card ending. "Your auto repayment is successful"
    # alerts carry no card number, so _parse_auto_repayment stamps this to keep
    # them landing on the MariBank Credit entry (account_filter "1730").
    MARI_CARD_LAST4 = "1730"

    def _parse_credit_card_repayment(self, text: str, email_data: dict) -> dict | None:
        """Parse the "Your credit card repayment is successful" email format.

        HTML-only body, collapsed to a single line by extract_text():

            Your repayment to your credit card ending (6600) is successful.
            Payment Amount: SGD 2,000.00
            Deducted from: Mari Savings Account ending 7744
            Transaction Time: 26 Sep 2026 19:13

        This is MariBank's BILL-PAYMENT notification: the card being paid is
        ANOTHER bank's card, and the money leaves the Mari Savings account.
        (Repayments to MariBank's own card use the "auto repayment" format —
        see _parse_auto_repayment.)

        The debit is therefore posted on the SOURCE account: `amount` is
        NEGATIVE (money leaving Mari Savings) and `account_last4` is the
        *savings* ending, so the config entry whose `account_filter` matches
        that account picks it up. The payee names the destination card
        ("credit card ending (6600)") so an Actual payee rule can tie the
        payment to the card account being settled.
        """
        amount_m = re.search(
            r"(?:Payment\s+)?Amount:\s*([A-Z]{3})?\s*([0-9,.]+)",
            text, re.IGNORECASE,
        )
        if not amount_m:
            return None

        currency = (amount_m.group(1) or "SGD").upper()
        if currency != "SGD":
            # Repayments are always SGD; a foreign currency means we caught a
            # card spend alert — leave it to the structured path.
            return None

        card_m = re.search(
            r"credit\s+card\s+ending\s*\(?(\d{4})\)?", text, re.IGNORECASE
        )
        savings_m = re.search(
            r"Mari\s+Savings\s+Account\s+ending\s+(\d{4})", text, re.IGNORECASE
        )
        time_m = re.search(
            r"Transaction\s*Time:?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s+(\d{1,2}:\d{2})",
            text, re.IGNORECASE,
        )

        card_last4 = card_m.group(1) if card_m else ""
        savings_last4 = savings_m.group(1) if savings_m else ""

        # NEGATIVE = the money leaves the Mari Savings account (see docstring).
        amount_cents = -self.to_cents(amount_m.group(2))

        if time_m:
            parsed_date = self.parse_date(time_m.group(1).strip())
            txn_time = time_m.group(2)
        else:
            # No transaction time in the body — fall back to the email date.
            email_dt = email_data.get("email_date") or datetime.now()
            parsed_date = email_dt.strftime("%Y-%m-%d")
            txn_time = ""

        payee = (
            f"credit card ending ({card_last4})" if card_last4
            else "credit card repayment"
        )
        notes = f"To credit card *{card_last4}" if card_last4 else ""

        return {
            "date": parsed_date,
            "amount": amount_cents,  # negative = outflow from Mari Savings
            "payee_name": payee,
            "imported_id": self._content_id(
                "mari-repay", parsed_date, amount_cents, payee, txn_time
            ),
            "notes": notes,
            # Route on the SOURCE account's ending, not the destination card.
            "account_last4": savings_last4 or None,
            "cleared": True,
        }

    def _parse_structured_alert(self, text: str, email_data: dict) -> dict | None:
        """Parse the structured Maribank email (SGD or foreign currency).

        Pattern (SGD):
          You have made a payment to <MERCHANT> on your credit card ending XXXX.
          Transaction Time:
          <DATE> <TIME> SGT
          Amount:
          SGD <AMOUNT>

        Pattern (foreign):
          ... Amount: EUR <AMOUNT>
        """
        # Strategy 1: Full structured format
        m = re.search(
            r"made\s+a\s+payment\s+to\s+(.+?)"
            r"(?:\s+on\s+your\s+|\s+(?:Transaction\s*Time|Amount)\s*:|\n|$)",
            text, re.IGNORECASE
        )
        date_m = re.search(r"Transaction\s*Time[:\s]*\n?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+(\d{2}:\d{2})", text, re.IGNORECASE)
        amount_m = re.search(r"Amount[:\s]*\n?\s*([A-Z]{3})\s*([0-9,.]+)", text, re.IGNORECASE)
        card_m = re.search(r"(?:card\s+ending|card\s+\*{3,}|XXXX)\s*(\d{4})", text, re.IGNORECASE)

        if m and date_m and amount_m:
            txn = self._build_txn(
                cur=amount_m.group(1).upper(),
                amount_str=amount_m.group(2),
                merchant=m.group(1).strip().rstrip("."),
                date_str=date_m.group(1).strip(),
                card_m=card_m,
                txn_time=date_m.group(2) if date_m.lastindex >= 2 else "",
            )
            if txn:
                return txn

        # Strategy 2: Looser fallback. The terminator intentionally includes the
        # structured field labels/newlines so the payee can never swallow the
        # whole (single-line) email body.
        fallback = re.search(
            r"to\s+(.+?)"
            r"(?:\s+on\s+your\s+card|\s+(?:Transaction\s*Time|Amount|Deducted\s+from)\s*:|\n|$)",
            text, re.IGNORECASE
        )
        if fallback and date_m and amount_m:
            txn = self._build_txn(
                cur=amount_m.group(1).upper(),
                amount_str=amount_m.group(2),
                merchant=fallback.group(1).strip().rstrip("."),
                date_str=date_m.group(1).strip(),
                card_m=None,
                txn_time=date_m.group(2) if date_m.lastindex >= 2 else "",
            )
            if txn:
                return txn

        return None

    def _build_txn(self, cur: str, amount_str: str, merchant: str, date_str: str,
                   card_m, txn_time: str) -> dict | None:
        """Build transaction dict from parsed fields, handling FX conversion.

        Follows the Trust parser pattern: foreign currencies are converted via
        sgd_from(), annotated in notes with original amount and rate, and
        marked cleared=False. SGD transactions have cleared=True explicitly.
        """
        amount_raw = self.to_cents(amount_str)

        if cur == "SGD":
            amount_cents = -amount_raw
            cleared = True
            fx_note = ""
        else:
            sgd_cents, rate = sgd_from(cur, amount_raw)
            if rate is None:
                logger.error(
                    "MariBank foreign txn skipped: no FX rate for %s (%s %s). "
                    "Email left unread to retry.",
                    cur, cur, amount_str,
                )
                return None
            amount_cents = -sgd_cents
            cleared = False
            fx_note = f"{cur}{amount_str} @ {rate:.4f}"

        parsed_date = self.parse_date(date_str)

        card_note = ""
        if card_m:
            card_note = f"MariCard *{card_m.group(1)}"

        notes_parts = [p for p in [card_note, fx_note] if p]
        notes = " | ".join(notes_parts)

        return {
            "date": parsed_date,
            "amount": amount_cents,
            "payee_name": merchant,
            "imported_id": self._content_id(
                "mari", parsed_date, amount_cents, merchant, txn_time,
                # Hash the ORIGINAL currency amount, not the converted SGD
                # figure — see BaseParser._content_id. SGD ids are unchanged.
                amount_key=f"{cur}{amount_str}" if cur != "SGD" else None,
            ),
            "notes": notes,
            "account_last4": card_m.group(1) if card_m else None,
            "cleared": cleared,
        }
