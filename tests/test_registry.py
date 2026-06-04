import pytest
from bank_parsers.registry import get_parser, all_parsers
from bank_parsers.dbs import DbsParser
from bank_parsers.citibank import CitibankParser
from bank_parsers.trust import TrustParser
from bank_parsers.maribank import MaribankParser


# ---------------------------------------------------------------------------
# get_parser — known senders
# ---------------------------------------------------------------------------

class TestGetParser:
    def test_dbs_sender(self):
        parser = get_parser("paylah.alert@dbs.com")
        assert parser is not None
        assert isinstance(parser, DbsParser)
        assert parser.bank_name == "DBS"

    def test_citibank_sender(self):
        parser = get_parser("alerts@citibank.com.sg")
        assert parser is not None
        assert isinstance(parser, CitibankParser)
        assert parser.bank_name == "Citibank"

    def test_trust_sender(self):
        parser = get_parser("from_us@trustbank.sg")
        assert parser is not None
        assert isinstance(parser, TrustParser)
        assert parser.bank_name == "Trust Bank"

    def test_maribank_sender(self):
        parser = get_parser("notifications@maribank.sg")
        assert parser is not None
        assert isinstance(parser, MaribankParser)
        assert parser.bank_name == "MariBank"

    def test_unknown_sender_returns_none(self):
        assert get_parser("nobody@unknown.com") is None


# ---------------------------------------------------------------------------
# all_parsers
# ---------------------------------------------------------------------------

class TestAllParsers:
    def test_returns_five_parsers(self):
        assert len(all_parsers()) == 5

    def test_all_expected_bank_names_present(self):
        names = [p.bank_name for p in all_parsers()]
        assert "DBS" in names
        assert "Citibank" in names
        assert "Trust Bank" in names
        assert "MariBank" in names
        assert "HeyMax" in names
