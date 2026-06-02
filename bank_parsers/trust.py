"""Parser for Trust Bank Singapore transaction alert emails."""
from . import BaseParser
from .fx import get_rate_or_fallback
import hashlib
import re
import logging

logger = logging.getLogger(__name__)


class TrustParser(BaseParser):
    """Trust Bank Singapore transaction alert email parser.

    Local: You've spent SGD <amt> at <merchant> on <date> <time>SGT with <card>.
    Overseas: You('ve| have) spent <CUR> <amt> using <card> at <merchant> on <date> <time>SGT.
    """

    @property
    def bank_name(self) -> str:
        return "Trust Bank"

    @property
    def sender_pattern(self) -> str:
        return r"from_us@trustbank\.sg|trustbank\.sg|trust\s*bank"

    def parse(self, email_data: dict) -> list[dict]:
        subject = email_data.get("subject", "")
        text = self.extract_text(email_data.get("body_text", ""), email_data.get("body_html", ""))
        msg_id = email_data.get("message_id", "")

        txn = self._parse_local(text, subject, msg_id)
        if not txn:
            txn = self._parse_overseas(text, subject, msg_id)
        return [txn] if txn else []

    def _parse_local(self, text, subject, msg_id):
        m = re.search(
            r"You(?:'ve| have) spent SGD ([0-9,.]+) at (.+?) on "
            r"(\d{1,2} [A-Za-z]+ \d{4}) \d{2}:\d{2}SGT with (.+?)(?:\.|\s*$)",
            text, re.IGNORECASE
        )
        if m:
            parsed_date = self.parse_date(m.group(3).strip())
            amount_cents = -self.to_cents(m.group(1))
            merchant = self._clean_merchant(m.group(2))
            return {
                "date": parsed_date,
                "amount": amount_cents,
                "payee_name": merchant,
                "imported_id": self._content_id("trust-local", parsed_date, amount_cents, merchant),
                "notes": m.group(4).strip(),
            }
        return None

    def _parse_overseas(self, text, subject, msg_id):
        m = re.search(
            r"You(?:'ve| have) spent ([A-Z]{3}) ([0-9,.]+) using (.+?) at (.+?) on "
            r"(\d{1,2} [A-Za-z]+ \d{4}) \d{2}:\d{2}SGT",
            text, re.IGNORECASE
        )
        if m:
            cur = m.group(1).upper()
            amount_cents = self.to_cents(m.group(2))
            card_info = m.group(3).strip()
            merchant = self._clean_merchant(m.group(4))

            # Try live rate, fall back to hardcoded
            rate = get_rate_or_fallback(cur)
            if rate:
                sgd_cents = int(round(amount_cents * rate))
                notes = f"{card_info} | {cur}{m.group(2)} @ {rate:.4f}"
            else:
                sgd_cents = amount_cents
                notes = f"{card_info} | {cur}{m.group(2)} (no rate)"

            parsed_date = self.parse_date(m.group(5).strip())
            return {
                "date": parsed_date,
                "amount": -sgd_cents,
                "payee_name": merchant,
                "imported_id": self._content_id("trust", parsed_date, -sgd_cents, merchant),
                "notes": notes,
            }
        return None

    @staticmethod
    def _content_id(prefix: str, date: str, amount: int, payee: str) -> str:
        raw = f"{date}|{amount}|{payee}"
        return f"{prefix}:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    @staticmethod
    def _clean_merchant(raw):
        m = re.sub(r"\s+", " ", raw).strip()
        m = re.sub(r"\s+Singapore\s+SG\s*$", "", m)
        m = re.sub(r"\s+SG\s*$", "", m)
        m = re.sub(r"\s+[A-Za-z0-9]+-[A-Za-z0-9]+\s*$", "", m)
        m = re.sub(r"\s+US\s*$", "", m)
        return m.strip()
