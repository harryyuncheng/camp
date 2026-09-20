"""Orders generalisation: categories on the catalog and groups, full menus with top picks, standing orders, and a
multi-order sync record."""
import asyncio
from datetime import date

import pytest

from camp import catalog, synth
from camp.contracts import OfficeRef
from camp.groups import CreateGroupReq, GroupService, JoinGroupReq, ScheduleReq
from camp.models import LunchGroup, User
from camp.store import Store
from camp.sync import LunchSyncService, SyncConflict, nearest

OFFICE = OfficeRef(id="hq", name="HQ", latitude=40.7424, longitude=-73.9913)


def world():
    store = Store()
    rests, items = catalog.to_models(seed=0)
    users, _, _ = synth.make_world(12, 0, 0)
    for u in users:
        u.office_id = OFFICE.id
    store.put_many(users); store.put_many(rests); store.put_many(items)
    return store


def test_catalog_has_both_categories():
    rows = catalog.load()
    coffee = [r for r in rows if "coffee" in r.categories]
    meal = [r for r in rows if "meal" in r.categories]
    assert coffee and meal
    assert all(set(r.categories) <= {"coffee", "meal"} and r.categories for r in rows)
    assert any("coffee" in r.categories and "meal" in r.categories for r in rows)      # a bakery-café does both
    rests, _ = catalog.to_models(seed=0)
    assert {c for r in rests for c in r.categories} == {"coffee", "meal"}


def test_restaurants_filter_by_category_and_seed_includes_coffee():
    svc = GroupService(world())
    coffee = svc.restaurants(limit=50, category="coffee")
    meal = svc.restaurants(limit=50, category="meal")
    assert coffee and all("coffee" in r.categories for r in coffee)
    assert meal and all("meal" in r.categories for r in meal)
    today = svc.today(OFFICE, None, "2026-09-21")
    cats = {g.category for g in today.groups}
    assert cats == {"coffee", "meal"}
    assert next(g for g in today.groups if g.category == "coffee").arrival_minutes < 11 * 60


def test_one_order_per_category_per_day():
    store = world()
    svc = GroupService(store)
    today = svc.today(OFFICE, None, "2026-09-22")
    coffee = next(g for g in today.groups if g.category == "coffee")
    meals = [g for g in today.groups if g.category == "meal"]
    a = svc.join(coffee.id, JoinGroupReq(office=OFFICE, option_id=coffee.options[0].id, display_name="Harry"))
    me = a.user_id
    b = svc.join(meals[0].id, JoinGroupReq(office=OFFICE, option_id=meals[0].options[0].id, user_id=me))
    mine = [g for g in store.groups_for(OFFICE.id, "2026-09-22") if any(m.user_id == me for m in g.members)]
    assert {g.category for g in mine} == {"coffee", "meal"} and len(mine) == 2        # both active at once
    svc.join(meals[1].id, JoinGroupReq(office=OFFICE, option_id=meals[1].options[0].id, user_id=me))
    mine = [g for g in store.groups_for(OFFICE.id, "2026-09-22") if any(m.user_id == me for m in g.members)]
    assert len(mine) == 2 and {g.id for g in mine} == {coffee.id, meals[1].id}          # meal moved, coffee kept
    assert len([o for o in store.orders_for(me) if o.status == "confirmed"]) == 2


def test_menu_lists_everything_with_top_picks_and_rating():
    store = world()
    svc = GroupService(store)
    today = svc.today(OFFICE, None, "2026-09-23")
    g = next(x for x in today.groups if x.category == "meal")
    joined = svc.join(g.id, JoinGroupReq(office=OFFICE, option_id=g.options[0].id, display_name="Harry"))
    m = svc.menu(g.restaurant_id, joined.user_id, g.id)
    assert m.name == g.name and m.rating is not None and m.review_count >= 0
    assert len(m.items) >= len(g.options) and len(m.top) == 3
    assert {t.id for t in m.top} <= {i.id for i in m.items}
    assert all(i.score is not None for i in m.items)
    assert all(i.price_cents > i.item_price_cents for i in m.items)     # all-in with the delivery share
    # ordering off the group's short list works: the option joins the group's list
    off = next(i for i in m.items if i.id not in {o.id for o in g.options})
    updated = svc.join(g.id, JoinGroupReq(office=OFFICE, option_id=off.id, user_id=joined.user_id))
    assert updated.my_option_id == off.id and any(o.id == off.id for o in updated.options)
    # unknown user → popularity/price top picks, no scores
    anon = svc.menu(g.restaurant_id, None)
    assert anon.top and all(i.score is None for i in anon.items)
    with pytest.raises(LookupError):
        svc.menu("nope", None)


def test_schedules_materialize_into_groups():
    store = world()
    svc = GroupService(store)
    coffee_place = svc.restaurants(limit=1, category="coffee")[0]
    day = "2026-09-21"                                                    # a Monday
    assert date.fromisoformat(day).weekday() == 0
    s = svc.add_schedule(ScheduleReq(office=OFFICE, display_name="Harry", category="coffee", label="Morning coffee",
                                     restaurant_id=coffee_place.id, time_minutes=9 * 60, weekdays=[0, 2, 4]))
    me = next(u.id for u in store.all(User) if u.name == "Harry")
    lunch = svc.add_schedule(ScheduleReq(office=OFFICE, user_id=me, category="meal", time_minutes=12 * 60 + 30, weekdays=[0]))
    assert lunch.restaurant_id is None and lunch.label == "Meal"
    with pytest.raises(ValueError):
        svc.add_schedule(ScheduleReq(office=OFFICE, user_id=me, category="coffee", time_minutes=60, weekdays=[0]))
    if "meal" not in coffee_place.categories:
        with pytest.raises(ValueError):
            svc.add_schedule(ScheduleReq(office=OFFICE, user_id=me, category="meal", restaurant_id=coffee_place.id, time_minutes=750, weekdays=[0]))
    today = svc.today(OFFICE, me, day)
    mine = [g for g in today.groups if g.my_option_id]
    assert {g.category for g in mine} == {"coffee", "meal"}
    coffee = next(g for g in mine if g.category == "coffee")
    assert coffee.restaurant_id == coffee_place.id and coffee.arrival_minutes == 9 * 60 and "scheduled" in coffee.cuisine
    # idempotent: a second refresh does not duplicate
    again = svc.today(OFFICE, me, day)
    n = store.count(LunchGroup)
    assert len([g for g in again.groups if g.my_option_id]) == 2 and store.count(LunchGroup) == n
    # a Tuesday: only weekday-0 schedules are skipped, the M/W/F coffee too
    tue = svc.today(OFFICE, me, "2026-09-22")
    assert not [g for g in tue.groups if g.my_option_id]
    # removing
    assert svc.remove_schedule(s.id, me).id == s.id and len(svc.schedules(me)) == 1
    with pytest.raises(LookupError):
        svc.remove_schedule(s.id, me)
    ev = svc.set_schedule_event(lunch.id, "EK-123")
    assert ev.calendar_event_id == "EK-123"


def rec(session_id="s1", revision=0, phase="choosing", arrives=1000.0):
    return {"sessionId": session_id, "revision": revision,
            "session": {"id": session_id, "phase": phase, "revision": revision, "arrivesAt": arrives}}


def test_sync_holds_several_orders_and_prioritises_the_nearest(tmp_path):
    store = Store(str(tmp_path / "camp.db"))
    svc = LunchSyncService(store)

    async def go():
        await svc.publish(rec("meal", arrives=5000), None, None, "mac")
        snap = await svc.publish(rec("coffee", arrives=2000), None, None, "iphone")
        assert len(snap["records"]) == 2 and snap["record"]["sessionId"] == "coffee"     # nearest first
        # the phone moves coffee forward; the mac's stale write is refused with the whole list
        await svc.publish(rec("coffee", revision=1, phase="reviewing", arrives=2000), "coffee", 0, "iphone")
        with pytest.raises(SyncConflict) as e:
            await svc.publish(rec("coffee", revision=1, phase="confirmed", arrives=2000), "coffee", 0, "mac")
        assert len(e.value.records) == 2 and e.value.record["revision"] == 1
        # finishing coffee makes the meal the nearest
        await svc.publish(rec("coffee", revision=2, phase="delivered", arrives=2000), "coffee", 1, "iphone")
        assert svc.record["sessionId"] == "meal"
        # a brand-new order is added, not a replacement
        snap = await svc.publish(rec("s3", arrives=9000), "meal", 0, "mac")
        assert {r["sessionId"] for r in snap["records"]} == {"coffee", "meal", "s3"}
        # forget one
        snap = await svc.clear("meal")
        assert {r["sessionId"] for r in snap["records"]} == {"coffee", "s3"} and snap["record"]["sessionId"] == "s3"
        # survives restart
        again = LunchSyncService(Store(str(tmp_path / "camp.db")))
        assert again.seq == snap["seq"] and len(again.records) == 2
        assert (await svc.clear())["records"] == []

    asyncio.run(go())


def test_nearest_ignores_finished_unless_nothing_else():
    assert nearest([]) is None
    done = {**rec("a", phase="ended", arrives=1), "updatedAt": "2026-09-20T10:00:00+00:00"}
    assert nearest([done, rec("b", arrives=99)])["sessionId"] == "b"
    assert nearest([done])["sessionId"] == "a"


def test_sync_http_lists_records(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMP_DB", ":memory:")
    monkeypatch.setenv("CAMP_DATABASE_URL", "")
    monkeypatch.setenv("CAMP_TOKEN", "")
    from fastapi.testclient import TestClient
    import importlib, camp.api
    api = importlib.reload(camp.api)
    c = TestClient(api.app)
    assert c.get("/v1/lunch-session").json() == {"seq": 0, "record": None, "records": []}
    c.put("/v1/lunch-session", json={"record": rec("a", arrives=10), "device": "mac"})
    r = c.put("/v1/lunch-session", json={"record": rec("b", arrives=5), "device": "iphone"}).json()
    assert r["record"]["sessionId"] == "b" and len(r["records"]) == 2
    assert c.delete("/v1/lunch-session", params={"sessionId": "b"}).json()["record"]["sessionId"] == "a"
    assert c.get("/v1/restaurants", params={"category": "coffee"}).status_code == 200
    assert c.get("/v1/restaurants", params={"category": "brunch"}).status_code == 422


def test_catalog_growth_keeps_orders():
    """Adding cafés to the catalog must not wipe the ledger the way a catalog swap does."""
    from camp.models import Order, OrderLine, Restaurant
    store = Store()
    rests, items = catalog.to_models(seed=0)
    meals = [r for r in rests if "coffee" not in r.categories]
    store.put_many(meals); store.put_many([i for i in items if i.restaurant_id in {r.id for r in meals}])
    line = OrderLine(item_id=items[0].id, restaurant_id=items[0].restaurant_id, price_cents=items[0].price_cents)
    store.put(Order(user_id="u1", date="2026-09-19", meal="lunch", location="office", line=line, default_line=line, status="confirmed"))
    assert catalog.ensure_current(store) is True
    assert store.count(Order) == 1 and len(store.all(Restaurant)) == len(rests)
    assert catalog.ensure_current(store) is False
