import subprocess
import json
import logging
import os

logger = logging.getLogger(__name__)

_NPM_BIN = os.path.expanduser("~/.npm-global/bin")

ACTUAL_CLI = os.path.join(_NPM_BIN, "actual")


class ActualImporter:
    """Pushes transactions into Actual Budget via the official CLI."""

    def __init__(self, config: dict):
        self.server_url = config["actual"]["server_url"]
        self.password = config["actual"]["password"]
        self.budget_id = config["actual"].get("budget_id", "")
        self.encryption_pw = config["actual"].get("encryption_password", "")

    def verify_connection(self) -> bool:
        """Test that the CLI can talk to the Actual server."""
        try:
            result = self._run(["budgets", "list"])
            if result.returncode == 0:
                data = json.loads(result.stdout)
                logger.debug("Connected to Actual. Budgets: %s", data)
                return True
            else:
                logger.error("Connection failed: %s", result.stderr)
                return False
        except Exception as e:
            logger.error("Connection error: %s", e)
            return False

    _CLI_FIELDS = {"date", "amount", "imported_id", "payee_name", "notes", "category", "cleared"}

    @staticmethod
    def _sanitize(txns: list[dict]) -> list[dict]:
        """Strip internal-only fields not accepted by the Actual CLI."""
        return [{k: v for k, v in t.items() if k in ActualImporter._CLI_FIELDS} for t in txns]

    def import_transactions(self, account_id: str, transactions: list[dict]) -> dict:
        """Import transactions to an account.

        Each transaction dict can have:
          date (YYYY-MM-DD), amount (int in cents, negative=outflow),
          payee_name, notes, imported_id (for dedup), category, cleared (bool)

        Returns one of:
          {"added": int, "updated": int}  — success (may also contain "added_ids", "updated_ids")
          {"error": str}                  — CLI non-zero exit
          {"raw": str}                    — CLI succeeded but response was non-JSON
        Caller should gate on "error" not in result.
        """
        if not transactions:
            return {"added": 0, "updated": 0}

        cmd = ["transactions", "import", "--account", account_id, "--file", "-"]

        # Strip internal-only fields before sending to CLI
        clean = self._sanitize(transactions)
        # Pipe JSON data via stdin
        result = self._run(cmd, input_data=json.dumps(clean))
        if result.returncode == 0:
            try:
                raw = json.loads(result.stdout)
                # CLI returns [added_ids, updated_ids]
                if isinstance(raw, list) and len(raw) >= 2:
                    added_ids = raw[0] if isinstance(raw[0], list) else []
                    updated_ids = raw[1] if isinstance(raw[1], list) else []
                    return {"added": len(added_ids), "updated": len(updated_ids), "added_ids": added_ids, "updated_ids": updated_ids}
                # CLI returns {"added": [...], "updated": [...]}
                if isinstance(raw, dict):
                    added = raw.get("added", [])
                    updated = raw.get("updated", [])
                    if isinstance(added, list):
                        return {"added": len(added), "updated": len(updated) if isinstance(updated, list) else updated}
                    return {"added": added, "updated": updated}
                return {"raw": raw}
            except json.JSONDecodeError:
                logger.warning("Non-JSON response: %s", result.stdout)
                return {"raw": result.stdout}
        else:
            logger.error("Import failed: %s", result.stderr)
            return {"error": result.stderr}

    def _run(self, args: list[str], input_data: str | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PATH"] = f"{_NPM_BIN}:{env.get('PATH', '')}"
        env["ACTUAL_SERVER_URL"] = self.server_url
        env["ACTUAL_PASSWORD"] = self.password
        if self.budget_id:
            env["ACTUAL_SYNC_ID"] = self.budget_id
        if self.encryption_pw:
            env["ACTUAL_ENCRYPTION_PASSWORD"] = self.encryption_pw

        full_cmd = [ACTUAL_CLI, *args]
        logger.debug("Running: %s", " ".join(full_cmd))

        return subprocess.run(
            full_cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
