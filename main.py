#!/usr/bin/env python3
import argparse, logging, sys, os, json, yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from email_fetcher import EmailFetcher
from actual_importer import ActualImporter
from bank_parsers.registry import get_parser, all_parsers
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
                # Track which emails had at least one successful account import
                emails_with_success = set()
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
                        attempted = True
                        r = importer.import_transactions(aid, filtered)
                        import_succeeded = "error" not in r
                        if not import_succeeded:
                            logger.error("  -> import failed for %s: %s", acct["name"], r.get("error"))
                            continue
                        a = r.get("added", 0)
                        u = r.get("updated", 0)
                        if a or u:
                            logger.info("  -> %d added, %d updated", a, u)
                        added += a; updated += u
                        # Record successfully imported IDs in local cache
                        all_ids = [t.get("imported_id", "") for t in filtered]
                        dedup.record(aid, all_ids)
                        for e in emails:
                            emails_with_success.add(e["raw_id"])
                if attempted:
                    for e in emails:
                        if e["raw_id"] in emails_with_success:
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

def run_test_parser(bank_arg):
    """Read a raw email JSON dict from stdin, run the matching parser, and print results."""
    from bank_parsers.registry import all_parsers
    # Find parser by bank_name
    parser = None
    for p in all_parsers():
        if p.bank_name.lower() == bank_arg.lower():
            parser = p
            break
    if parser is None:
        # Try matching against sender patterns as a fallback
        import re
        for p in all_parsers():
            pattern = getattr(p, "sender_pattern", None)
            if pattern and re.search(pattern, bank_arg, re.IGNORECASE):
                parser = p
                break
    if parser is None:
        print(f"Error: no parser found for '{bank_arg}'", file=sys.stderr)
        print("Available parsers:", file=sys.stderr)
        for p in all_parsers():
            print(f"  {p.bank_name}", file=sys.stderr)
        sys.exit(1)
    try:
        raw = sys.stdin.read()
        email_data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: could not parse JSON from stdin: {e}", file=sys.stderr)
        sys.exit(1)
    txns = parser.parse(email_data)
    print(json.dumps(txns, indent=2, default=str))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.local.yaml")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--lookback", type=int, default=None)
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--test-parser", metavar="BANK")
    args = p.parse_args()
    log_file = setup_logging(verbose=args.verbose)

    # --test-parser does not need config.local.yaml
    if args.test_parser:
        run_test_parser(args.test_parser)
        return

    config = load_config(args.config)
    # Only override config value when flag was explicitly passed
    if args.lookback is not None:
        config["email"]["lookback_days"] = args.lookback
    logger.info("Starting bank automation (log: %s)", log_file)
    run_import(config, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
