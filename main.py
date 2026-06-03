#!/usr/bin/env python3
import argparse, logging, sys, os, json, yaml, time, re
from collections import defaultdict
from email_fetcher import EmailFetcher
from actual_importer import ActualImporter
from bank_parsers.registry import get_parser, all_parsers
from bank_parsers.dedup import DedupCache
from logging_config import setup_logging

logger = logging.getLogger("main")

def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)

def group_accounts_by_sender(config: dict) -> dict[str, list[dict]]:
    """Group configured accounts by their email sender address."""
    by: dict[str, list[dict]] = defaultdict(list)
    for acct_cfg in config.get("accounts", []):
        s = acct_cfg.get("email_sender", "")
        if s and acct_cfg.get("actual_account_id", ""):
            by[s].append(acct_cfg)
    return dict(by)

def _account_matches(txn: dict, wanted: str) -> bool:
    """Return True if txn's account_last4 zero-padded to 4 digits equals wanted."""
    got = txn.get("account_last4")
    return got is not None and str(got).zfill(4) == wanted


def process_sender(
    sender: str,
    accounts: list[dict],
    fetcher,
    parser,
    importer,
    dedup,
    dry_run: bool,
    lookback_days: int,
) -> tuple[int, int]:
    """Fetch, parse, dedup, import, and mark-seen for one email sender."""
    emails = fetcher.fetch_unread_from(sender, lookback_days=lookback_days)
    if not emails:
        return 0, 0

    # Preserve email→txns association so subject_filter can route per account
    email_txns = [(em, parser.parse(em)) for em in emails]
    if not any(txns for _, txns in email_txns):
        return 0, 0

    n_added, n_updated = 0, 0
    attempted = False
    emails_routed: set[str] = set()   # email had >=1 txn routed to some account
    emails_failed: set[str] = set()   # >=1 routed leg for this email failed import

    for acct_cfg in accounts:
        aid = acct_cfg["actual_account_id"]
        subject_filter = acct_cfg.get("subject_filter")
        cf = acct_cfg.get("account_filter")
        account_filter = str(cf).zfill(4) if cf is not None else None

        acct_pairs = []
        for em, txns in email_txns:
            if not txns:
                continue
            # subject_filter: email-level gate (unchanged semantics)
            if subject_filter and not re.search(subject_filter, em.get("subject", ""), re.IGNORECASE):
                continue
            # account_filter: per-txn gate (AND with subject_filter)
            if account_filter is not None:
                sel = [t for t in txns if _account_matches(t, account_filter)]
            else:
                sel = txns
            if sel:
                acct_pairs.append((em, sel))

        acct_txns = [t for _, txns in acct_pairs for t in txns]
        if not acct_txns:
            continue
        for em, _ in acct_pairs:
            emails_routed.add(em["raw_id"])

        if not dry_run:
            candidate_ids = [t.get("imported_id", "") for t in acct_txns]
            known = dedup.check(aid, candidate_ids)
            if known:
                logger.info("  -> %d already cached, skipping", len(known))
            filtered = [t for t in acct_txns if t.get("imported_id", "") not in known]
            if not filtered:
                continue
        else:
            filtered = acct_txns

        logger.info("Importing %d txn(s) to %s%s", len(filtered), acct_cfg["name"], " (DRY)" if dry_run else "")

        if not dry_run:
            attempted = True
            r = importer.import_transactions(aid, filtered)
            import_succeeded = "error" not in r
            if not import_succeeded:
                logger.error("  -> import failed for %s: %s", acct_cfg["name"], r.get("error"))
                for em, _ in acct_pairs:
                    emails_failed.add(em["raw_id"])
                continue
            n_add = r.get("added", 0)
            n_upd = r.get("updated", 0)
            if n_add or n_upd:
                logger.info("  -> %d added, %d updated", n_add, n_upd)
            n_added += n_add
            n_updated += n_upd
            all_ids = [t.get("imported_id", "") for t in filtered]
            dedup.record(aid, all_ids)

    if attempted:
        for em, _ in email_txns:
            rid = em["raw_id"]
            if rid in emails_routed and rid not in emails_failed:
                fetcher.mark_as_seen(rid)

    return n_added, n_updated

def run_import(config: dict, dry_run: bool = False) -> None:
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
    total_added, total_updated = 0, 0
    try:
        by = group_accounts_by_sender(config)
        for sender, accounts in by.items():
            bank_name = accounts[0].get("bank", "?")
            t0 = time.time()
            try:
                parser = get_parser(sender)
                if not parser:
                    continue
                logger.info("Checking %s (%s)...", bank_name, sender)
                n_added, n_updated = process_sender(sender, accounts, fetcher, parser, importer, dedup, dry_run, lb)
                total_added += n_added
                total_updated += n_updated
            except Exception as exc:
                logger.error("Error processing %s (%s): %s", bank_name, sender, exc, exc_info=True)
                continue
            elapsed = time.time() - t0
            logger.info("%s done in %.1fs", bank_name, elapsed)
    finally:
        fetcher.disconnect()
        if not dry_run:
            dedup.close()
    logger.info("Done: %d added, %d updated", total_added, total_updated)

def run_test_parser(bank_arg):
    """Read a raw email JSON dict from stdin, run the matching parser, and print results."""
    parser = None
    for p in all_parsers():
        if p.bank_name.lower() == bank_arg.lower():
            parser = p
            break
    if parser is None:
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
