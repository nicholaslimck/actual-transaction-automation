import pytest
from bank_parsers.dedup import DedupCache


@pytest.fixture
def cache(tmp_path):
    c = DedupCache(db_path=str(tmp_path / "test_dedup.db"))
    c.open()
    yield c
    c.close()


def test_record_then_check_returns_known_ids(cache):
    """Recorded ids are returned by check; unrecorded ids are not."""
    cache.record("acct-1", ["id-a", "id-b"])
    known = cache.check("acct-1", ["id-a", "id-b", "id-c"])
    assert known == {"id-a", "id-b"}
    assert "id-c" not in known


def test_account_isolation(cache):
    """The same imported_id under different accounts is independent."""
    cache.record("acct-1", ["shared-id"])
    # Different account: unknown
    assert cache.check("acct-2", ["shared-id"]) == set()
    # Original account: known
    assert cache.check("acct-1", ["shared-id"]) == {"shared-id"}


def test_batched_check(cache):
    """check() correctly identifies known vs unknown across a larger batch."""
    recorded = [f"id-{i}" for i in range(5)]
    extra = [f"new-{i}" for i in range(3)]
    cache.record("acct-1", recorded)
    known = cache.check("acct-1", recorded + extra)
    assert known == set(recorded)
    for nid in extra:
        assert nid not in known


def test_idempotent_record(cache):
    """Recording the same ids twice does not raise and check still works."""
    cache.record("acct-1", ["id-x", "id-y"])
    cache.record("acct-1", ["id-x", "id-y"])  # second record — INSERT OR IGNORE
    assert cache.check("acct-1", ["id-x", "id-y"]) == {"id-x", "id-y"}


def test_empty_inputs(cache):
    """check with an empty list returns an empty set; record with empty list is a no-op."""
    assert cache.check("acct", []) == set()
    cache.record("acct", [])  # must not raise
    assert cache.check("acct", []) == set()
