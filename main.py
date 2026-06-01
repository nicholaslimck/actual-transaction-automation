#!/usr/bin/env python3
import argparse, logging, sys, os, json, yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from email_fetcher import EmailFetcher
from actual_importer import ActualImporter
from bank_parsers.registry import get_parser
from bank_parsers.dedup import DedupCache
from logging_config import setup_logging

logger = logging.getLogger("main")

def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)

def run_import(config, dry_run=False):
    import time
    lb = config["email"].get("lookback_days", 3)
    fetcher = EmailFetcher(config)
    importer = ActualImporter(config)
    dedup = DedupCache()
    if not dry_run:
        if not importer.verify_connection():
            logger.error("Cannot connect to Actual Budget")
            return
        dedup.open()
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
            bank_name = accounts[0].get("bank", "?")
            t0 = time.time()
            try:
                parser = get_parser(sender)
                if not parser:
                    continue
                logger.info("Checking %s (%s)...", bank_name, sender)
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
                    # Filter out already-known transactions via local dedup
                    if not dry_run:
                        candidate_ids = [t.get("imported_id", "") for t in all_txns]
                        known = dedup.check(aid, candidate_ids)
                        if known:
                            logger.info("  -> %d already cached, skipping", len(known))
                        filtered = [t for t in all_txns if t.get("imported_id", "") not in known]
                        if not filtered:
                            continue
                    else:
                        filtered = all_txns
                    logger.info("Importing %d txn(s) to %s%s", len(filtered), acct["name"], " (DRY)" if dry_run else "")
                    if not dry_run:
                        r = importer.import_transactions(aid, filtered)
                        attempted = True
                        a = r.get("added", 0)
                        u = r.get("updated", 0)
                        if a or u:
                            logger.info("  -> %d added, %d updated", a, u)
                        added += a; updated += u
                        # Record successfully imported IDs in local cache
                        all_ids = [t.get("imported_id", "") for t in filtered]
                        dedup.record(aid, all_ids)
                if attempted:
                    for e in emails:
                        fetcher.mark_as_seen(e["raw_id"])
            except Exception as e:
                logger.error("Error processing %s (%s): %s", bank_name, sender, e, exc_info=True)
                continue
            elapsed = time.time() - t0
            logger.info("%s done in %.1fs", bank_name, elapsed)
    finally:
        fetcher.disconnect()
        if not dry_run:
            dedup.close()
    logger.info("Done: %d added, %d updated", added, updated)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.local.yaml")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--lookback", type=int, default=3)
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()
    log_file = setup_logging(verbose=args.verbose)
    config = load_config(args.config)
    config["email"]["lookback_days"] = args.lookback
    logger.info("Starting bank automation (log: %s)", log_file)
    run_import(config, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
