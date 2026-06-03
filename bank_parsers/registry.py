"""Bank email parser registry -- auto-discovers all parser classes."""
from . import BaseParser
from .dbs import DbsParser
from .citibank import CitibankParser
from .trust import TrustParser
from .maribank import MaribankParser
from .heymax import HeymaxParser

# Registered parsers -- add new ones here
_PARSERS: list[BaseParser] = [
    DbsParser(),
    CitibankParser(),
    TrustParser(),
    MaribankParser(),
    HeymaxParser(),
]


def get_parser(sender: str) -> BaseParser | None:
    """Find the parser that matches this sender email address."""
    for parser in _PARSERS:
        if parser.can_handle(sender):
            return parser
    return None


def all_parsers() -> list[BaseParser]:
    return list(_PARSERS)
