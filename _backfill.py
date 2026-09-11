#!/usr/bin/env python3
"""Targeted backfill for one bank (or all) that also scans READ emails.

main.py fetches only UNSEEN emails, so an alert you opened in Gmail before a
poll is never imported. This scans every email in the window, parses it, and
imports whatever Actual doesn't already hold.

Routing is shared with main.py (subject_filter, account_filter, senders mapped
to several accounts), so the backfill and the cron always agree on which
transaction belongs to which account.

Usage:
    ./_backfill.py                          # every bank, last 90 days
    ./_backfill.py --list                   # configured banks/accounts, then exit
    ./_backfill.py --bank trust             # one bank
    ./_backfill.py --bank dbs --days 45     # narrower window
    ./_backfill.py --bank trust --filter tripla   # only payees containing "tripla"
    ./_backfill.py --dry-run                # print the plan, write nothing
    ./_backfill.py --bank trust --unseen    # unread only (main.py behaviour)
    ./_backfill.py --bank trust --mark-seen # mark imported emails as read

Banks: dbs, citibank, trust, maribank, heymax, hsbc
"""
import argparse
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from actual_importer import ActualImporter          # noqa: E402
from bank_parsers.dedup import DedupCache           # noqa: E402
from bank_parsers.registry import get_parser        # noqa: E402
from email_fetcher import EmailFetcher              # noqa: E402
from logging_config import setup_logging            # noqa: E402

# Reuse main.py's routing: a private helper is acceptable here to guarantee the
# backfill cannot drift from the cron on account mapping.
from main import _account_matches, group_accounts_by_sender  # noqa: E402


def accounts_for_bank(config: dict, bank: str | None) -> dict[str, list[dict]]:
    """Group account configs by sender, optionally keeping one bank only.

    Returns {sender: [account_cfg, ...]}. Several accounts may share a sender
    (e.g. DBS PayLah and PayNow, or two DBS cards).
    """
    by_sender = group_accounts_by_sender(config)
    if bank is None:
        return by_sender

    want = bank.strip().lower()
    selected: dict[str, list[dict]] = {}
    for sender, accounts in by_sender.items():
        keep = [a for a in accounts if (a.get("bank") or "").lower() == want]
        if keep:
            selected[sender] = keep
    return selected


def known_banks(config: dict) -> list[str]:
    """Sorted bank names present in the config."""
    return sorted({(a.get("bank") or "?").lower() for a in config.get("accounts", [])})


def select_txns(email_txns, acct_cfg: dict):
    """Apply subject_filter (email level) then account_filter (per txn).

    Mirrors main.py.process_sender: both filters apply together when present.
    Returns [(email, [txn, ...]), ...] for this account only.
    """
    subject_filter = acct_cfg.get("subject_filter")
    cf = acct_cfg.get("account_filter")
    account_filter = str(cf).zfill(4) if cf is not None else None

    pairs = []
    for em, txns in email_txns:
        if not txns:
            continue
        if subject_filter and not re.search(
            subject_filter, em.get("subject", ""), re.IGNORECASE
        ):
            continue
        if account_filter is not None:
            sel = [t for t in txns if _account_matches(t, account_filter)]
        else:
            sel = txns
        if sel:
            pairs.append((em, sel))
    return pairs


def dedupe_batch(txns: list[dict]) -> list[dict]:
    """Drop repeated imported_ids within one batch (several emails, one txn)."""
    seen, unique = set(), []
    for t in txns:
        tid = t.get("imported_id")
        if tid not in seen:
            seen.add(tid)
            unique.append(t)
    return unique


def main() -> None:
    p = argparse.ArgumentParser(
        description="Backfill one bank (or all) from read and unread emails",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--config", default="config.local.yaml")
    p.add_argument("--bank", default=None, help="dbs|citibank|trust|maribank|heymax|hsbc")
    p.add_argument("--days", type=int, default=90, help="lookback in days (0 = all time)")
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    p.add_argument("--filter", dest="payee_filter", default=None,
                   help="only payees containing this substring (case-insensitive)")
    p.add_argument("--unseen", action="store_true", help="unread emails only")
    p.add_argument("--mark-seen", action="store_true",
                   help="mark emails as read after a successful import")
    p.add_argument("--list", action="store_true", help="list configured accounts, then exit")
    args = p.parse_args()

    setup_logging()
    with open(args.config) as fh:
        config = yaml.safe_load(fh)

    if args.list:
        print("Configured banks and accounts:")
        for acct in config.get("accounts", []):
            sender = acct.get("email_sender", "?")
            extras = []
            if acct.get("account_filter"):
                extras.append("account_filter=%s" % acct["account_filter"])
            if acct.get("subject_filter"):
                extras.append("subject_filter=%s" % acct["subject_filter"])
            print("  %-9s %-38s <- %s%s" % (
                acct.get("bank", "?"), acct.get("name", "?"), sender,
                ("  [" + ", ".join(extras) + "]") if extras else ""))
        return

    groups = accounts_for_bank(config, args.bank)
    if not groups:
        raise SystemExit(
            "No accounts for bank %r. Configured banks: %s"
            % (args.bank, ", ".join(known_banks(config)))
        )

    importer = ActualImporter(config)
    dedup = DedupCache()
    dedup.open()
    if not args.dry_run and not importer.verify_connection():
        raise SystemExit("Cannot connect to Actual Budget")

    fetcher = EmailFetcher(config)
    fetcher.unseen_only = args.unseen
    fetcher.connect()

    lookback = args.days or 3650      # 0 means "all time"
    window = "all time" if args.days == 0 else "last %dd" % args.days
    print("Backfilling %s (%s)" % (args.bank or "all banks", window))
    print("Scanning: %s" % ("unread only" if args.unseen else "read + unread"))

    total_added = total_updated = 0
    try:
        for sender, accounts in groups.items():
            bank_name = accounts[0].get("bank", "?")
            parser = get_parser(sender)
            if parser is None:
                print("\n%s: no parser registered for %s — skipped" % (bank_name, sender))
                continue

            emails = fetcher.fetch_unread_from(sender, lookback_days=lookback)
            email_txns = [(em, parser.parse(em)) for em in emails]
            print("\n%s (%s): %d emails, %d transactions parsed"
                  % (bank_name, sender, len(emails), sum(len(t) for _, t in email_txns)))

            routed_ids = set()
            for acct_cfg in accounts:
                account_id = acct_cfg["actual_account_id"]
                pairs = select_txns(email_txns, acct_cfg)
                txns = dedupe_batch([t for _, ts in pairs for t in ts])
                if args.payee_filter:
                    needle = args.payee_filter.lower()
                    txns = [t for t in txns
                            if needle in (t.get("payee_name") or "").lower()]
                if not txns:
                    continue

                known = dedup.check(account_id, [t["imported_id"] for t in txns])
                new = [t for t in txns if t["imported_id"] not in known]
                print("  %s: %d parsed, %d already cached, %d to import"
                      % (acct_cfg["name"], len(txns), len(known), len(new)))
                for t in new:
                    print("     %s %9.2f  %-40s %s" % (
                        t["date"], abs(t["amount"]) / 100,
                        (t.get("payee_name") or "")[:40], t["imported_id"]))

                if not new or args.dry_run:
                    continue

                result = importer.import_transactions(account_id, new)
                if "error" in result or "raw" in result:
                    print("     FAILED: %s" % (result.get("error") or result.get("raw")))
                    continue
                print("     -> %s added, %s updated"
                      % (result.get("added", 0), result.get("updated", 0)))
                total_added += result.get("added", 0)
                total_updated += result.get("updated", 0)
                dedup.record(account_id, [t["imported_id"] for t in new])
                routed_ids.update(em["raw_id"] for em, _ in pairs)

            if args.mark_seen and routed_ids and not args.dry_run:
                for raw_id in routed_ids:
                    fetcher.mark_as_seen(raw_id)
    finally:
        fetcher.disconnect()
        dedup.close()

    if args.dry_run:
        print("\n[Dry run — nothing written]")
    print("\nDone: %d added, %d updated" % (total_added, total_updated))


if __name__ == "__main__":
    main()
