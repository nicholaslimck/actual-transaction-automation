# CLAUDE.md

Guidance to Claude Code (claude.ai/code) for working in this repo.

## Commands

```bash
# Run (requires config.local.yaml)
python3 main.py

# Dry run (no writes to Actual, emails stay unread)
python3 main.py --dry-run

# Scan further back
python3 main.py --lookback 60

# Verbose logging (DEBUG to console)
python3 main.py --verbose

# Install deps (uv manages the venv)
uv sync
npm install -g @actual-app/cli

# Find Actual account IDs (needed for config)
actual accounts list

# Test a specific bank parser (pipe a JSON email dict via stdin)
echo '{"subject":"...","body_text":"...","body_html":"","date":"","message_id":"<id>","email_date":null,"raw_id":"1"}' | python3 main.py --test-parser trust

# Run tests (pytest via uv)
uv run pytest -v
uv run pytest tests/test_trust.py -v   # single file
```

Parser logic: exercise via `--dry-run` and `--test-parser <bank>`.

## Architecture

Pipeline runs once per invocation (no daemon):

1. `main.py` loads config, groups accounts by `email_sender`
2. `EmailFetcher` (Gmail IMAP) fetches UNSEEN emails from each sender within `lookback_days`
3. `bank_parsers/registry.py` returns matching parser for each sender
4. Parser extracts transaction dicts; overseas amounts converted to SGD via `bank_parsers/fx.py`
5. `DedupCache` (SQLite at `data/dedup.db`) filters already-imported `imported_id`s
6. `ActualImporter` shells out to `actual` CLI, passing JSON via stdin; env vars carry credentials
7. Emails marked SEEN only after successful import attempt

**Transaction dict schema** (defined in `bank_parsers/__init__.py::BaseParser.parse`):
```python
{
    "date": "YYYY-MM-DD",
    "amount": int,        # cents, negative = outflow
    "payee_name": str,
    "imported_id": str,   # used for dedup in both SQLite and Actual Budget
    "notes": str,         # optional
}
```

## Adding a bank parser

1. Create `bank_parsers/<bank>.py` subclassing `BaseParser`
2. Implement `bank_name`, `sender_pattern` (regex against From address), and `parse(email_data) -> list[dict]`
3. Instantiate and append to `_PARSERS` in `bank_parsers/registry.py`
4. Add account entry to `config.local.yaml`

Key helpers on `BaseParser`:
- `extract_text(body_text, body_html)` — prefers plain text, strips HTML as fallback
- `to_cents(amount_str)` — handles currency prefixes, returns negative-by-default int
- `parse_date(date_str, email_date)` — tries many formats; falls back to `email_date.year` when no year in string

## Config

`config.yaml` committed template. `config.local.yaml` (gitignored) holds real credentials. `--config` flag overrides path.

Multiple accounts can share same `email_sender` (e.g. DBS PayLah + ibanking). Parser runs once per sender; each matching account gets same parsed transactions.

`email.unseen_only: true` (default) — set `false` to reprocess read emails (useful for backfills with `--lookback`).

## Logs

Rotating log at `logs/bank-automation.log` (DEBUG). Console: INFO by default; `--verbose` adds DEBUG.