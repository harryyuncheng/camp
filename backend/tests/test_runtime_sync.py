import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from camp.models import SyncState
from camp.store import Store
from camp.sync import LunchSyncService, SyncConflict


def record(session_id="s1", revision=0):
    return {"sessionId": session_id, "revision": revision,
            "session": {"id": session_id, "revision": revision, "phase": "choosing", "arrivesAt": 1000}}


@pytest.mark.parametrize("change", [
    {"revision": True}, {"revision": "1"}, {"revision": None}, {"sessionId": None},
    {"session": []}, {"session": {"id": "different", "revision": 0, "phase": "choosing"}},
    {"session": {"id": "s1", "revision": 1, "phase": "choosing"}},
    {"session": {"id": "s1", "revision": 0, "phase": "bogus"}},
    {"session": {"id": "s1", "revision": 0, "phase": "choosing", "arrivesAt": float("nan")}},
    {"session": {"id": "s1", "revision": 0, "phase": "choosing", "arrivesAt": 10**1000}},
    {"group": []},
])
def test_invalid_records_never_change_state(change):
    service = LunchSyncService(Store())
    with pytest.raises(ValueError):
        asyncio.run(service.publish({**record(), **change}, None, None, "mac"))
    assert service.snapshot() == {"seq": 0, "record": None, "records": []}


def test_failed_persistence_does_not_publish_or_advance_sequence(monkeypatch):
    store = Store()
    service = LunchSyncService(store)
    original = store.put

    def fail(row):
        raise OSError("disk full")

    async def run():
        monkeypatch.setattr(store, "put", fail)
        with pytest.raises(OSError, match="disk full"):
            await service.publish(record(), None, None, "mac")
        assert service.seq == 0 and service.records == []
        monkeypatch.setattr(store, "put", original)
        assert (await service.publish(record(), None, None, "mac"))["seq"] == 1
        assert LunchSyncService(store).seq == 1

    asyncio.run(run())


def test_concurrent_updates_compare_revision_after_acquiring_lock():
    service = LunchSyncService(Store())

    async def run():
        await service.publish(record(), None, None, "mac")
        async with service._changed:
            writers = [asyncio.create_task(service.publish(record(revision=1), "s1", 0, device))
                       for device in ("mac", "phone")]
            await asyncio.sleep(0)
        results = await asyncio.gather(*writers, return_exceptions=True)
        assert sum(isinstance(result, SyncConflict) for result in results) == 1
        assert service.seq == 2

    asyncio.run(run())


def test_clear_prevents_a_stale_writer_resurrecting_the_last_order():
    service = LunchSyncService()

    async def run():
        await service.publish(record(), None, None, "mac")
        await service.clear()
        with pytest.raises(SyncConflict):
            await service.publish(record(revision=1), "s1", 0, "phone")
        assert service.records == []

    asyncio.run(run())


def test_restart_prunes_expired_records_and_normalizes_old_naive_timestamps(tmp_path):
    store = Store(str(tmp_path / "camp.db"))
    old = {**record("expired"), "updatedAt": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}
    fresh = {**record("fresh"), "updatedAt": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}
    store.put(SyncState(seq=4, records=[old, fresh]))
    service = LunchSyncService(store)
    assert service.seq == 5
    assert [row["sessionId"] for row in service.records] == ["fresh"]
    assert store.get(SyncState, "lunch").seq == 5


def test_snapshots_and_input_do_not_alias_authoritative_records():
    service = LunchSyncService()
    source = record()
    snapshot = asyncio.run(service.publish(source, None, None, "mac"))
    source["session"]["phase"] = "ended"
    snapshot["records"][0]["session"]["phase"] = "delivered"
    assert service.record["session"]["phase"] == "choosing"
