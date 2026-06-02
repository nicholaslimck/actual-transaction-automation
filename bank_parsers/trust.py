"""Parser for Trust Bank Singapore transaction alert emails."""
from . import BaseParser
from .fx import sgd_from
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

    def _parse_alert(self, text: str, email_data: dict) -> dict | None:
        msg_id = email_data.get("message_id", "")
        txn = self._parse_local(text, msg_id)
        if not txn:
            txn = self._parse_overseas(text, msg_id)
        return txn

    def _parse_local(self, text, msg_id):
        m = re.search(
            r"You(?:'ve| have) spent SGD ([0-9,.]+) at (.+?) on "
            r"(\d{1,2} [A-Za-z]+ \d{4}) (\d{2}:\d{2})SGT with (.+?)(?:\.|\s*$)",
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
                "imported_id": self._content_id("trust-local", parsed_date, amount_cents, merchant, m.group(4)),
                "notes": m.group(5).strip(),
            }
        return None

    def _parse_overseas(self, text, msg_id):
        m = re.search(
            r"You(?:'ve| have) spent ([A-Z]{3}) ([0-9,.]+) using (.+?) at (.+?) on "
            r"(\d{1,2} [A-Za-z]+ \d{4}) (\d{2}:\d{2})SGT",
            text, re.IGNORECASE
        )
        if m:
            cur = m.group(1).upper()
            amount_cents = self.to_cents(m.group(2))
            card_info = m.group(3).strip()
            merchant = self._clean_merchant(m.group(4))

            sgd_cents, rate = sgd_from(cur, amount_cents)
            if rate is not None:
                notes = f"{card_info} | {cur}{m.group(2)} @ {rate:.4f}"
            else:
                notes = f"{card_info} | {cur}{m.group(2)} (no rate)"

            parsed_date = self.parse_date(m.group(5).strip())
            txn_time = m.group(6)
            return {
                "date": parsed_date,
                "amount": -sgd_cents,
                "payee_name": merchant,
                "imported_id": self._content_id("trust", parsed_date, -sgd_cents, merchant, txn_time),
                "notes": notes,
            }
        return None

    @staticmethod
    def _clean_merchant(raw):
        m = re.sub(r"\s+", " ", raw).strip()
        m = re.sub(r"\s+Singapore\s+SG\s*$", "", m)
        m = re.sub(r"\s+SG\s*$", "", m)
        m = re.sub(r"\s+[A-Za-z0-9]+-[A-Za-z0-9]+\s*$", "", m)
        m = re.sub(r"\s+US\s*$", "", m)
        return m.strip()
