# Actual Transaction Automation

Automatically import bank and credit card transactions into [Actual Budget](https://actualbudget.org/) by parsing email transaction alerts from Gmail.

Supports **Singapore banks**: DBS/POSB, Citibank, Trust Bank, MariBank.

## How it works

1. **Gmail IMAP polling** -- checks for unread transaction alert emails every 5 minutes
2. **Per-bank parsers** -- extracts date, amount, merchant, and card info from each bank's email format
3. **Actual Budget CLI** -- imports via `@actual-app/cli` with deduplication via `imported_id`

## Accounts configured

| Account | Email sender | Type |
|---|---|---|
| DBS Savings Account | paylah.alert@dbs.com | PayLah! outgoing payments |
| DBS Savings Account | ibanking.alert@dbs.com | PayNow incoming transfers |
| Citibank Credit Card | alerts@citibank.com.sg | Credit card charges |
| Trust Credit Card | from_us@trustbank.sg | Local & overseas transactions |
| Maribank Credit Card | notifications@maribank.sg | Credit card charges |

## Setup

### 1. Prerequisites

- Node.js v22+ (`actual` CLI)
- Python 3.13+
- Gmail account with [app password](https://myaccount.google.com/apppasswords)
- Self-hosted Actual Budget instance

### 2. Install dependencies

```bash
npm install -g @actual-app/cli
pip install PyYAML
```

### 3. Configure

Copy the template and fill in your credentials:

```bash
cp config.yaml config.local.yaml
```

Edit `config.local.yaml`:

```yaml
email:
  email: "your-email@gmail.com"
  app_password: "your-gmail-app-password"

actual:
  server_url: "http://your-server:5006"
  password: "your-actual-password"
  budget_id: "your-budget-uuid"   # Settings > Advanced > Budget Sync ID

accounts:
  - name: "Trust Credit"
    bank: trust
    email_sender: "from_us@trustbank.sg"
    actual_account_id: "..."      # Run: actual accounts list
```

### 4. Find account IDs

```bash
actual accounts list
```

### 5. Run

```bash
# Preview what would be imported
python3 main.py --dry-run

# Import everything
python3 main.py

# Scan further back (e.g. 60 days)
python3 main.py --lookback 60

# Debug a specific bank parser
python3 main.py --test-parser trust
```

## Adding a new bank

1. Create a parser in `bank_parsers/` extending `BaseParser`
2. Register it in `bank_parsers/registry.py`
3. Add an account entry in `config.local.yaml`

## Overseas transactions

Trust Bank overseas transactions are converted to SGD using live exchange rates from [open.er-api.com](https://open.er-api.com) (free, no API key). Falls back to approximate rates if the API is unreachable.

## Project structure

```
├── main.py                 # Entry point
├── email_fetcher.py        # Gmail IMAP connection
├── actual_importer.py      # Actual Budget CLI wrapper
├── bank_parsers/
│   ├── __init__.py         # Base parser class
│   ├── registry.py         # Parser auto-discovery
│   ├── fx.py               # Live FX rates module
│   ├── dbs.py              # DBS PayLah! and ibanking alerts
│   ├── citibank.py         # Citibank credit card alerts
│   ├── trust.py            # Trust Bank transaction alerts
│   └── maribank.py         # MariBank transaction notifications
├── config.yaml             # Configuration template
└── config.local.yaml       # Local credentials (gitignored)
```
