"""Tests for ActualImporter — return-shape parsing and _sanitize.

Monkeypatches _run so no subprocess or Actual server is needed.
"""
import json
import subprocess
import pytest
from actual_importer import ActualImporter


_CFG = {"actual": {"server_url": "http://localhost:5006", "password": "pw"}}


@pytest.fixture
def importer():
    return ActualImporter(_CFG)


def _completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _txns():
    return [{"date": "2026-06-01", "amount": -100, "payee_name": "ACME",
             "imported_id": "x:abc123", "notes": "test"}]


# ---------------------------------------------------------------------------
# Empty input — short-circuit before calling CLI
# ---------------------------------------------------------------------------

def test_empty_transactions_returns_zero_without_calling_cli(importer, monkeypatch):
    called = []
    monkeypatch.setattr(importer, "_run", lambda *a, **kw: called.append(1) or _completed("{}"))
    r = importer.import_transactions("acct-1", [])
    assert r == {"added": 0, "updated": 0}
    assert not called


# ---------------------------------------------------------------------------
# List shape: [[added_id, ...], [updated_id, ...]]
# ---------------------------------------------------------------------------

def test_list_shape_two_elements(importer, monkeypatch):
    payload = json.dumps([["id-a", "id-b"], ["id-c"]])
    monkeypatch.setattr(importer, "_run", lambda *a, **kw: _completed(payload))
    r = importer.import_transactions("acct-1", _txns())
    assert r["added"] == 2
    assert r["updated"] == 1
    assert r["added_ids"] == ["id-a", "id-b"]
    assert r["updated_ids"] == ["id-c"]


def test_list_shape_one_element_treated_as_raw(importer, monkeypatch):
    """A list with <2 elements is an unrecognized shape → {"raw": ...}.
    The CLI always returns [added_ids, updated_ids]; a 1-element list is
    treated conservatively as an uncertain result."""
    payload = json.dumps([["id-a"]])
    monkeypatch.setattr(importer, "_run", lambda *a, **kw: _completed(payload))
    r = importer.import_transactions("acct-1", _txns())
    assert "raw" in r


# ---------------------------------------------------------------------------
# Dict shape: {"added": [...], "updated": [...]}
# ---------------------------------------------------------------------------

def test_dict_shape_list_values(importer, monkeypatch):
    payload = json.dumps({"added": ["id-a"], "updated": ["id-b", "id-c"]})
    monkeypatch.setattr(importer, "_run", lambda *a, **kw: _completed(payload))
    r = importer.import_transactions("acct-1", _txns())
    assert r["added"] == 1
    assert r["updated"] == 2


def test_dict_shape_scalar_values(importer, monkeypatch):
    """Some CLI versions return scalar counts directly."""
    payload = json.dumps({"added": 3, "updated": 0})
    monkeypatch.setattr(importer, "_run", lambda *a, **kw: _completed(payload))
    r = importer.import_transactions("acct-1", _txns())
    assert r["added"] == 3
    assert r["updated"] == 0


# ---------------------------------------------------------------------------
# Non-JSON / unrecognized shape → {"raw": ...}  (H2 shape — lock it in)
# ---------------------------------------------------------------------------

def test_non_json_stdout_returns_raw(importer, monkeypatch):
    monkeypatch.setattr(importer, "_run", lambda *a, **kw: _completed("not json!"))
    r = importer.import_transactions("acct-1", _txns())
    assert "raw" in r
    assert "error" not in r


def test_unexpected_json_shape_returns_raw(importer, monkeypatch):
    """A truthy non-list non-dict (e.g. bare string JSON) hits the raw branch."""
    monkeypatch.setattr(importer, "_run", lambda *a, **kw: _completed(json.dumps("ok")))
    r = importer.import_transactions("acct-1", _txns())
    assert "raw" in r


# ---------------------------------------------------------------------------
# Non-zero returncode → {"error": stderr}
# ---------------------------------------------------------------------------

def test_nonzero_returncode_returns_error(importer, monkeypatch):
    monkeypatch.setattr(importer, "_run",
                        lambda *a, **kw: _completed(returncode=1, stderr="CLI exploded"))
    r = importer.import_transactions("acct-1", _txns())
    assert r == {"error": "CLI exploded"}
    assert "added" not in r


# ---------------------------------------------------------------------------
# _sanitize — internal-only fields stripped before piping to CLI
# ---------------------------------------------------------------------------

def test_sanitize_drops_internal_fields(importer, monkeypatch):
    """account_last4 must not reach the CLI; only _CLI_FIELDS allowed."""
    captured = {}

    def fake_run(cmd, input_data=None):
        captured["input"] = input_data
        return _completed(json.dumps([[], []]))

    monkeypatch.setattr(importer, "_run", fake_run)

    txns = [{
        "date": "2026-06-01",
        "amount": -500,
        "payee_name": "NTUC",
        "imported_id": "x:abc",
        "notes": "test",
        "cleared": False,
        "account_last4": "1234",   # internal-only — must be stripped
    }]
    importer.import_transactions("acct-1", txns)
    piped = json.loads(captured["input"])
    assert len(piped) == 1
    assert "account_last4" not in piped[0]
    # Verify the CLI fields are present
    for field in ("date", "amount", "payee_name", "imported_id", "notes", "cleared"):
        assert field in piped[0]


def test_sanitize_preserves_all_cli_fields(importer):
    txn = {k: "v" for k in ActualImporter._CLI_FIELDS}
    txn["account_last4"] = "9999"   # extra internal field
    result = ActualImporter._sanitize([txn])
    assert len(result) == 1
    assert set(result[0].keys()) == ActualImporter._CLI_FIELDS
