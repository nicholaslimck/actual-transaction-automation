#!/usr/bin/env python3
"""Rewrite legacy imported_ids to the current stable content hash.

Foreign-currency ids used to hash the converted SGD amount (rate-dependent), and
some older rows still carry the raw Gmail Message-ID. Either way the id no longer
matches what the parser computes, so a broad backfill would insert a duplicate.

This rewrites the stored id on the *existing* row — one field, no amounts or
payees touched. Reconciled rows are skipped (the CLI cannot modify them) and are
reported instead.

    python3 migrate_imported_ids.py                 # dry run (default)
    python3 migrate_imported_ids.py --bank trust    # one bank
    python3 migrate_imported_ids.py --apply         # write changes

Safety: a timestamped JSON backup of every row it is about to touch is written
before the first update, so the rewrite can be reversed with the same command.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime

import yaml

sys.path.insert(0, "/home/hermes/bank-automation")
from bank_parsers.registry import get_parser          # noqa: E402
from email_fetcher import EmailFetcher                # noqa: E402

REPO = "/home/hermes/bank-automation"
CONFIG_PATH = os.path.join(REPO, "config.local.yaml")
BACKUP_DIR = os.path.join(REPO, "migrations")
LOOKBACK_DAYS = 150
AMOUNT_TOLERANCE = 0.02


def norm(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def actual_env(cfg):
    env = os.environ.copy()
    env["ACTUAL_SERVER_URL"] = cfg["server_url"]
    env["ACTUAL_PASSWORD"] = cfg["password"]
    env["ACTUAL_SYNC_ID"] = cfg["budget_id"]
    env["PATH"] = os.path.expanduser("~/.npm-global/bin") + ":" + env["PATH"]
    return env


def fetch_rows(account_id, env):
    r = subprocess.run(
        ["actual", "query", "run", "--table", "transactions",
         "--filter", json.dumps({"account": account_id}),
         "--select", "id,date,amount,payee.name,imported_id,reconciled",
         "--order-by", "date:desc", "--limit", "500", "--format", "json"],
        capture_output=True, text=True, env=env, timeout=240,
    )
    if r.returncode != 0:
        raise SystemExit("CLI error: " + r.stderr[:400])
    return json.loads(r.stdout)


def rewrite(row_id, new_id, env):
    r = subprocess.run(
        ["actual", "transactions", "update", row_id,
         "--data", json.dumps({"imported_id": new_id})],
        capture_output=True, text=True, env=env, timeout=120,
    )
    return r.returncode == 0, (r.stderr or r.stdout or "").strip()[:200]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bank", default=None, help="trust|maribank|... (default: all)")
    p.add_argument("--apply", action="store_true", help="actually write changes")
    args = p.parse_args()

    cfg_all = yaml.safe_load(open(CONFIG_PATH))
    cfg = cfg_all["actual"]
    env = actual_env(cfg)

    banks = [args.bank] if args.bank else sorted(
        {(a.get("bank") or "") for a in cfg_all["accounts"]})
    banks = [b for b in banks if b in {"trust", "maribank", "hsbc", "dbs", "citibank", "heymax"}]

    fetcher = EmailFetcher(cfg_all)
    fetcher.unseen_only = False
    fetcher.connect()

    planned, blocked, ambiguous, unchanged = [], [], [], 0
    for bank in banks:
        entries = [a for a in cfg_all["accounts"] if a.get("bank") == bank]
        for acct in entries:
            account_id = acct["actual_account_id"]
            parser = get_parser(acct["email_sender"])
            if parser is None:
                continue
            parsed = []
            for em in fetcher.fetch_unread_from(acct["email_sender"], lookback_days=LOOKBACK_DAYS):
                parsed.extend(parser.parse(em))
            seen, unique = set(), []
            for t in parsed:
                if t["imported_id"] not in seen:
                    seen.add(t["imported_id"])
                    unique.append(t)

            rows = fetch_rows(account_id, env)
            for t in unique:
                tol = max(100, int(abs(t["amount"]) * AMOUNT_TOLERANCE))
                cands = [r for r in rows
                         if r.get("date") == t["date"]
                         and abs((r.get("amount") or 0) - t["amount"]) <= tol]
                if not cands:
                    continue
                if len(cands) > 1:
                    tight = [c for c in cands
                             if norm(t["payee_name"])[:12] in norm(c.get("payee.name"))]
                    if len(tight) != 1:
                        ambiguous.append((bank, t, len(cands)))
                        continue
                    cands = tight
                row = cands[0]
                if row.get("imported_id") == t["imported_id"]:
                    unchanged += 1
                    continue
                if row.get("reconciled"):
                    blocked.append((bank, acct["name"], row, t))
                    continue
                planned.append((bank, acct["name"], row, t))
    fetcher.disconnect()

    print("=" * 74)
    print("PLAN: rewrite %d row(s) | %d unchanged | %d reconciled (cannot rewrite) | %d ambiguous"
          % (len(planned), unchanged, len(blocked), len(ambiguous)))
    print("=" * 74)
    for bank, acct_name, row, t in planned:
        print("  %-8s %s  %9.2f  %-30s" % (bank, t["date"], t["amount"] / 100, t["payee_name"][:30]))
        print("           %s -> %s" % (row.get("imported_id"), t["imported_id"]))
    if blocked:
        print("\n  Reconciled (skipped, CLI cannot modify):")
        for bank, _acct, row, t in blocked:
            print("    %-8s %s %9.2f %s" % (bank, t["date"], t["amount"] / 100, t["payee_name"][:30]))
    if ambiguous:
        print("\n  Ambiguous (needs a human):")
        for bank, t, n in ambiguous:
            print("    %-8s %s %9.2f %s (%d candidates)" % (bank, t["date"], t["amount"] / 100, t["payee_name"][:30], n))

    if not planned:
        print("\nNothing to rewrite.")
        return
    if not args.apply:
        print("\n[Dry run — nothing written. Re-run with --apply to write.]")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, "imported_id_backup_%s.json" % stamp)
    with open(backup_path, "w") as fh:
        json.dump([{
            "bank": b, "account": a, "id": r.get("id"), "date": r.get("date"),
            "amount": r.get("amount"), "payee": r.get("payee.name"),
            "old_imported_id": r.get("imported_id"), "new_imported_id": t["imported_id"],
        } for b, a, r, t in planned], fh, indent=2)
    print("\nBackup written: %s (%d rows)" % (backup_path, len(planned)))

    ok, failed = 0, []
    for bank, acct_name, row, t in planned:
        good, msg = rewrite(row["id"], t["imported_id"], env)
        if good:
            ok += 1
        else:
            failed.append((row.get("id"), msg))
    print("Rewrites applied: %d ok, %d failed" % (ok, len(failed)))
    for row_id, msg in failed:
        print("  FAILED %s: %s" % (row_id, msg))

    # Verify by reading the ids back — never trust the exit code alone.
    still_wrong = []
    for bank, acct_name, row, t in planned:
        acct = [a for a in cfg_all["accounts"] if a["name"] == acct_name][0]
        current = {r.get("id"): r.get("imported_id")
                   for r in fetch_rows(acct["actual_account_id"], env)}
        if current.get(row["id"]) != t["imported_id"]:
            still_wrong.append(row["id"])
    print("Read-back verification: %d/%d now carry the new id"
          % (len(planned) - len(still_wrong), len(planned)))
    if still_wrong:
        print("  NOT updated: %s" % ", ".join(still_wrong))
        print("  Restore any of these from %s if needed." % backup_path)

    # Seed the dedup cache with every new id (rewritten AND reconciled). For the
    # reconciled rows the stored id cannot change, so the cache is the only guard
    # that stops a re-parse from inserting a duplicate.
    from bank_parsers.dedup import DedupCache
    dedup = DedupCache()
    dedup.open()
    seeded = 0
    by_account = {}
    for bank, acct_name, row, t in planned:
        by_account.setdefault(acct_name, []).append(t["imported_id"])
    for bank, acct_name, row, t in blocked:
        by_account.setdefault(acct_name, []).append(t["imported_id"])
    for acct_name, ids in by_account.items():
        acct = [a for a in cfg_all["accounts"] if a["name"] == acct_name][0]
        dedup.record(acct["actual_account_id"], ids)
        seeded += len(ids)
    dedup.close()
    print("Dedup cache seeded with %d id(s) across %d account(s)" % (seeded, len(by_account)))
    print("Reconciled rows left with legacy ids (cannot be modified by the CLI): %d" % len(blocked))


if __name__ == "__main__":
    main()
