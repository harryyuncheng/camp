import asyncio

import pytest

from camp.store import Store
from camp.sync import LunchSyncService, SyncConflict


def rec(session_id="s1", revision=0, phase="choosing"):
    return {"sessionId": session_id, "revision": revision, "session": {"id": session_id, "phase": phase, "revision": revision}}


def test_cas_accepts_forward_moves_and_rejects_stale(tmp_path):
    store = Store(str(tmp_path / "camp.db"))
    svc = LunchSyncService(store)

    async def go():
        first = await svc.publish(rec(), None, None, "mac")
        assert first["seq"] == 1 and first["record"]["device"] == "mac"
        # phone moves it forward from revision 0
        second = await svc.publish(rec(revision=1, phase="reviewing"), "s1", 0, "iphone")
        assert second["seq"] == 2 and second["record"]["revision"] == 1
        # mac still thinks revision 0 → conflict carries the newer record
        with pytest.raises(SyncConflict) as e:
            await svc.publish(rec(revision=1, phase="confirmed"), "s1", 0, "mac")
        assert e.value.record["revision"] == 1 and e.value.seq == 2
        # a brand-new order is added alongside the existing one (a coffee and a meal can both be active)
        third = await svc.publish(rec(session_id="s2"), "s1", 1, "mac")
        assert {r["sessionId"] for r in third["records"]} == {"s1", "s2"} and third["seq"] == 3
        # ...but a writer who believes an order is current that we no longer hold must look first
        await svc.clear("s1")
        with pytest.raises(SyncConflict):
            await svc.publish(rec(session_id="s3"), "s1", 1, "iphone")
        # persisted across restarts
        again = LunchSyncService(Store(str(tmp_path / "camp.db")))
        assert again.seq == 4 and again.record["sessionId"] == "s2"

    asyncio.run(go())


def test_long_poll_wakes_on_publish():
    svc = LunchSyncService()

    async def go():
        assert (await svc.wait_for_change(None, 0))["seq"] == 0
        waiter = asyncio.create_task(svc.wait_for_change(0, 5))
        await asyncio.sleep(0.05)
        await svc.publish(rec(), None, None, "mac")
        got = await asyncio.wait_for(waiter, 1)
        assert got["seq"] == 1 and got["record"]["sessionId"] == "s1"
        # timing out returns the unchanged snapshot instead of hanging
        assert (await svc.wait_for_change(1, 0.05))["seq"] == 1

    asyncio.run(go())


def test_http_contract_and_token(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMP_DB", ":memory:")
    monkeypatch.setenv("CAMP_DATABASE_URL", "")
    monkeypatch.setenv("CAMP_TOKEN", "secret")
    from fastapi.testclient import TestClient
    import importlib, camp.api
    api = importlib.reload(camp.api)
    c = TestClient(api.app)
    assert c.get("/v1/lunch-session").status_code == 401
    h = {"X-Camp-Token": "secret"}
    assert c.get("/v1/lunch-session", headers=h).json() == {"seq": 0, "record": None, "records": []}
    r = c.put("/v1/lunch-session", headers=h, json={"record": rec(), "device": "mac"})
    assert r.status_code == 200 and r.json()["seq"] == 1
    r = c.put("/v1/lunch-session", headers=h, json={"record": rec(revision=1), "expectedSessionId": "s1", "expectedRevision": 5})
    assert r.status_code == 409 and r.json()["record"]["revision"] == 0
    assert c.delete("/v1/lunch-session", headers=h).json() == {"seq": 2, "record": None, "records": []}
