"""Lunch groups, spending ledger, profile and Ramp attempt ledger all live in the one store."""
import importlib

from fastapi.testclient import TestClient

from camp import synth
from camp.contracts import OfficeRef
from camp.groups import CreateGroupReq, GroupService, JoinGroupReq
from camp.models import LunchGroup, Order, RampAttempt, User
from camp.store import Store

OFFICE = OfficeRef(id="hq", name="HQ", latitude=40.7424, longitude=-73.9913)


def world():
    store = Store()
    u, r, i = synth.make_world(12, 20, 0)
    store.put_many(u); store.put_many(r); store.put_many(i)
    return store


def test_seed_join_create_leave_keep_orders_consistent():
    store = world()
    svc = GroupService(store)
    today = svc.today(OFFICE, None, "2026-09-21")
    # 3 meal groups; this small world has no café, so no coffee run is seeded (the full catalog adds one: see test_orders)
    assert len(today.groups) == 3 and all(g.seeded and g.participants >= 2 for g in today.groups)
    assert today.total_savings_cents == sum((g.participants - 1) * g.delivery_fee_cents for g in today.groups)
    # seeded colleagues have confirmed group orders
    assert store.count(Order) == sum(g.participants for g in today.groups)

    g = today.groups[0]
    before = g.options[0].price_cents
    joined = svc.join(g.id, JoinGroupReq(office=OFFICE, option_id=g.options[0].id, display_name="Harry"))
    me = next(m.user_id for m in joined.members if m.display_name == "Harry")
    assert joined.participants == g.participants + 1 and joined.my_option_id == g.options[0].id
    assert joined.options[0].price_cents < before                      # the delivery share dropped for everyone
    assert joined.people == g.participants                             # "people" excludes the requester
    mine = [o for o in store.orders_for(me) if o.status == "confirmed"]
    assert len(mine) == 1 and mine[0].source == "group" and mine[0].group_id == g.id

    # joining a second group moves the lunch (one per day) and cancels the first order
    other = today.groups[1]
    svc.join(other.id, JoinGroupReq(office=OFFICE, option_id=other.options[1].id, user_id=me))
    statuses = sorted(o.status for o in store.orders_for(me))
    assert statuses == ["cancelled", "confirmed"]
    assert not any(m.user_id == me for m in store.get(LunchGroup, g.id).members)

    # create your own group, then leave: it disappears from Today
    rest = svc.restaurants(6)[-1]
    created = svc.create(CreateGroupReq(office=OFFICE, restaurant_id=rest.id, delivery_minutes=790, option_id=rest.options[0].id, user_id=me), "2026-09-21")
    assert created.participants == 1 and created.cuisine.startswith("Started by you")
    names = [x.id for x in svc.today(OFFICE, me, "2026-09-21").groups]
    assert created.id in names
    svc.leave(created.id, me)
    assert created.id not in [x.id for x in svc.today(OFFICE, me, "2026-09-21").groups]

    ledger = svc.ledger(me, "HQ", "2026-09")
    assert ledger.entries == [] or all(e.status == "confirmed" for e in ledger.entries)
    assert ledger.monthly_budget_cents == 2000 * 20


def test_http_groups_ledger_profile_and_ramp_guard(monkeypatch):
    monkeypatch.setenv("CAMP_DB", ":memory:")
    monkeypatch.setenv("CAMP_DATABASE_URL", "")
    monkeypatch.delenv("CAMP_TOKEN", raising=False)
    monkeypatch.setenv("CAMP_USERS", "8")
    import camp.api
    api = importlib.reload(camp.api)
    c = TestClient(api.app)
    h = api.health()
    assert h["database"] == "sqlite" and h["groups"] == 0

    office = dict(id="hq", name="HQ", latitude=40.7424, longitude=-73.9913, radiusMeters=200, cutoff=725, deliveryStart=750, deliveryEnd=780)
    r = c.put("/v1/profile", json=dict(displayName="Harry", office=office, dietaryStyle="Vegetarian", allergies=["peanuts"], dislikes=["onion"], budgetCents=2500))
    assert r.status_code == 200
    me = r.json()["userId"]
    prof = c.get(f"/v1/profile/{me}").json()
    assert prof["settings"]["dietaryStyle"] == "Vegetarian" and {"peanut", "vegetarian"} <= {x["value"] for x in prof["restrictions"]}

    groups = c.get("/v1/groups", params=dict(officeId="hq", userId=me, date="2026-09-21")).json()
    assert len(groups["groups"]) == 4 and groups["peopleOrdering"] >= 6
    g = groups["groups"][0]
    j = c.post(f"/v1/groups/{g['id']}/join", json=dict(office=office, optionId=g["options"][0]["id"], userId=me))
    assert j.status_code == 200 and j.json()["myOptionId"] == g["options"][0]["id"]
    led = c.get(f"/v1/ledger/{me}", params=dict(officeName="HQ", month="2026-09")).json()
    assert len(led["entries"]) == 1 and led["entries"][0]["source"] == "group" and led["spentMonthCents"] == led["entries"][0]["amountCents"]
    assert c.delete(f"/v1/groups/{g['id']}/members/{me}").json()["participants"] == g["participants"]
    assert c.post(f"/v1/groups/{g['id']}/join", json=dict(office=office, optionId="nope", userId=me)).status_code == 422
    assert c.get("/v1/restaurants", params=dict(limit=3)).json()[0]["options"]

    # Ramp: native-client guard, then a clean 503 when no sandbox credentials are configured
    monkeypatch.delenv("RAMP_CLIENT_ID", raising=False)
    api.ramp.ramp.client_id = api.ramp.ramp.secret = ""
    assert c.get("/v1/ramp").status_code == 403
    r = c.get("/v1/ramp", headers={"X-Camp-Client": "camp-native"})
    assert r.status_code == 503 and "RAMP_CLIENT_ID" in r.json()["detail"]
    assert api.store.count(RampAttempt) == 0


def test_ramp_attempt_ledger_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("RAMP_CLIENT_ID", "x"); monkeypatch.setenv("RAMP_CLIENT_SECRET", "y")
    from camp.ramp import RampService
    store = Store(str(tmp_path / "camp.db"))
    store.put(RampAttempt(id="a" * 32, fingerprint="f", payload={}, state="submitting"))
    RampService(Store(str(tmp_path / "camp.db")))
    assert Store(str(tmp_path / "camp.db")).get(RampAttempt, "a" * 32).state == "unknown"   # interrupted → never blindly re-issued


def test_multi_item_orders_share_one_delivery_fee_and_respect_the_budget():
    store = world()
    svc = GroupService(store)
    today = svc.today(OFFICE, None, "2026-09-21")
    g = today.groups[0]
    picks = [o.id for o in g.options[:2]]
    me = svc.join(g.id, JoinGroupReq(office=OFFICE, option_id=picks[0], display_name="Harry")).user_id
    u = store.get(User, me)
    u.budget_cents["lunch"] = 10_000          # room for two items; the cap is checked below
    store.put(u)
    joined = svc.join(g.id, JoinGroupReq(office=OFFICE, option_ids=picks, user_id=me))
    assert joined.my_option_ids == picks and joined.my_option_id == picks[0]
    assert joined.participants == g.participants + 1        # two items, still one person

    mine = [o for o in store.orders_for(me) if o.status == "confirmed"]
    assert sorted(o.line.item_id for o in mine) == sorted(picks)
    assert sum(o.fee_share_cents for o in mine) == joined.delivery_fee_cents // joined.participants   # charged once
    assert len(svc.ledger(me, "HQ", "2026-09").entries) == 2

    # dropping back to one item cancels the extra order
    svc.join(g.id, JoinGroupReq(office=OFFICE, option_ids=[picks[1]], user_id=me))
    assert sorted(o.status for o in store.orders_for(me)) == ["cancelled", "confirmed"]

    # the first item always goes through; extras have to fit the per-order cap
    u = store.get(User, me)
    u.budget_cents["lunch"] = 1
    store.put(u)
    assert svc.join(g.id, JoinGroupReq(office=OFFICE, option_ids=[picks[0]], user_id=me)).my_option_ids == [picks[0]]
    try:
        svc.join(g.id, JoinGroupReq(office=OFFICE, option_ids=picks, user_id=me))
        raise AssertionError("expected the second item to be refused")
    except ValueError as e:
        assert "budget" in str(e)
