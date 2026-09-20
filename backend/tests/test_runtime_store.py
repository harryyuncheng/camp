from concurrent.futures import ThreadPoolExecutor

import pytest

from camp.models import SyncState
from camp.store import Store


def test_failed_iterable_rolls_back_and_cannot_leak_into_later_commit(tmp_path):
    path = str(tmp_path / "camp.db")
    store = Store(path)
    store.put(SyncState(id="existing", seq=1))

    def rows():
        yield SyncState(id="existing", seq=2)
        yield SyncState(id="partial", seq=3)
        raise ValueError("interrupted import")

    with pytest.raises(ValueError, match="interrupted import"):
        store.put_many(rows())
    assert store.get(SyncState, "existing").seq == 1
    assert store.get(SyncState, "partial") is None
    store.put(SyncState(id="later"))
    store.close()
    reopened = Store(path)
    assert reopened.get(SyncState, "existing").seq == 1
    assert reopened.get(SyncState, "partial") is None
    reopened.close()


def test_outer_transaction_rolls_back_nested_writes_and_deletes():
    store = Store()
    store.put_many([SyncState(id="a"), SyncState(id="b")])
    with pytest.raises(RuntimeError):
        with store.transaction():
            assert store.delete(SyncState, "a")
            assert store.delete_all(SyncState) == 1
            store.put(SyncState(id="c"))
            raise RuntimeError("failed group update")
    assert {r.id for r in store.all(SyncState)} == {"a", "b"}


def test_nested_savepoint_can_fail_without_losing_outer_work():
    store = Store()
    with store.transaction():
        store.put(SyncState(id="outer"))
        with pytest.raises(ValueError):
            with store.transaction():
                store.delete_all(SyncState)
                store.put(SyncState(id="inner"))
                raise ValueError("inner failure")
        assert store.get(SyncState, "outer") is not None
        store.put(SyncState(id="after"))
    assert {r.id for r in store.all(SyncState)} == {"outer", "after"}


def test_transaction_serializes_read_modify_write_across_threads():
    store = Store()
    store.put(SyncState())

    def increment(_):
        for _ in range(25):
            with store.transaction():
                row = store.get(SyncState, "lunch")
                row.seq += 1
                store.put(row)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(increment, range(4)))
    assert store.get(SyncState, "lunch").seq == 100


def test_copy_from_rolls_back_all_tables_on_failure(monkeypatch):
    source, target = Store(), Store()
    source.put(SyncState(seq=12))
    original = target.put_many

    def fail_last_table(rows):
        original(rows)
        if target.get(SyncState, "lunch"):
            raise ValueError("failed copy")

    monkeypatch.setattr(target, "put_many", fail_last_table)
    with pytest.raises(ValueError, match="failed copy"):
        target.copy_from(source)
    assert target.get(SyncState, "lunch") is None
