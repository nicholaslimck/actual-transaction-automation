#!/usr/bin/env python3
import argparse, logging, sys, os, json, yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from email_fetcher import EmailFetcher
from actual_importer import ActualImporter
from bank_parsers.registry import get_parser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("main")

def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)

def run_import(config, dry_run=False):
    lb = config["email"].get("lookback_days", 3)
    fetcher = EmailFetcher(config)
    importer = ActualImporter(config)
    if not dry_run and not importer.verify_connection():
        logger.error("Cannot connect to Actual Budget")
        return
    fetcher.connect()
    added, updated = 0, 0
    try:
        from collections import defaultdict
        by = defaultdict(list)
        for a in config.get("accounts", []):
            s = a.get("email_sender", "")
            if s and a.get("actual_account_id", ""):
                by[s].append(a)
        for sender, accounts in by.items():
            parser = get_parser(sender)
            if not parser:
                continue
            logger.info("Checking %s (%s)...", accounts[0].get("bank", "?"), sender)
            emails = fetcher.fetch_unread_from(sender, lookback_days=lb)
            if not emails:
                continue
            all_txns = []
            for e in emails:
                all_txns.extend(parser.parse(e))
            if not all_txns:
                continue
            attempted = False
            for acct in accounts:
                aid = acct["actual_account_id"]
                logger.info("Importing %d txn(s) to %s%s", len(all_txns), acct["name"], " (DRY)" if dry_run else "")
                if not dry_run:
                    r = importer.import_transactions(aid, all_txns)
                    attempted = True
                    a = r.get("added", 0)
                    u = r.get("updated", 0)
                    if a or u:
                        logger.info("  -> %d added, %d updated", a, u)
                    added += a; updated += u
            if attempted:
                for e in emails:
                    fetcher.mark_as_seen(e["raw_id"])
    finally:
        fetcher.disconnect()
    logger.info("Done: %d added, %d updated", added, updated)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.local.yaml")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--lookback", type=int, default=3)
    args = p.parse_args()
    config = load_config(args.config)
    config["email"]["lookback_days"] = args.lookback
    run_import(config, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
