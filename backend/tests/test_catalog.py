"""The Ramp HQ catalog: real restaurants near 28 W 23rd St, used as the offline mock dataset."""
from camp import catalog, synth
from camp.filters import haversine_km
from camp.models import ALLERGENS, CUISINES, DISH_TYPES, PROTEINS, LatLng, Restaurant


def test_catalog_is_near_ramp_hq_and_well_formed():
    rows = catalog.load()
    assert len(rows) >= 80
    names = {r.name.lower() for r in rows}
    assert any("sweetgreen" in n for n in names) and any(n.startswith("dig") for n in names)   # the corporate-lunch staples
    for r in rows:
        assert haversine_km(LatLng(lat=r.lat, lng=r.lng), catalog.RAMP_HQ) <= 2.6, r.name
        assert r.cuisine in CUISINES and 1 <= r.price_level <= 4 and len(r.dishes) >= 3
        for d in r.dishes:
            assert 100 <= d.price_cents <= 20000 and d.dish_type in DISH_TYPES and d.protein in PROTEINS
            assert set(d.allergens) <= set(ALLERGENS)
    rated = [r for r in rows if r.rating]
    assert len(rated) >= 0.8 * len(rows)
    assert sum(len(r.dishes) for r in rows) >= 600


def test_to_models_tags_and_translates():
    rests, items = catalog.to_models(n=20, seed=3)
    assert len(rests) == 20 and all(i.tags for i in items)
    assert any(r.verified_allergen_data for r in rests) and any(i.verified_allergens is not None for i in items)
    assert any(r.rating for r in rests) and any(i.popular for i in items)
    boston = LatLng(lat=42.36, lng=-71.09)
    moved, _ = catalog.to_models(n=20, seed=3, center=boston)
    assert all(haversine_km(r.location, boston) <= 2.7 for r in moved)
    assert moved[0].id == rests[0].id     # ids are stable across centres


def test_world_uses_whole_catalog_by_default():
    _, rests, items = synth.make_world(5)
    assert len(rests) == len([r for r in catalog.load() if r.dishes and catalog._hours_ok(r)])
    assert len({i.restaurant_id for i in items}) == len(rests)


def test_ensure_current_replaces_legacy_world():
    from camp.models import FeeSchedule, MenuItem, Restaurant, User
    from camp.store import Store
    store = Store()
    old = Restaurant(name="Thai Place 5", cuisine="thai", location=LatLng(lat=37.78, lng=-122.41))
    store.put(old); store.put(MenuItem(restaurant_id=old.id, name="Pad Thai", price_cents=1200))
    store.put(User(name="keep me", office_id="hq", home=catalog.RAMP_HQ))
    assert catalog.ensure_current(store) is True
    names = {r.name for r in store.all(Restaurant)}
    assert "Thai Place 5" not in names and any("Sweetgreen" in n for n in names)
    assert store.all(User)[0].name == "keep me"
    assert catalog.ensure_current(store) is False       # idempotent


def test_refreshed_offers_explore_different_options():
    from camp.contracts import MealContext, OfficeRef
    from camp.offers import OfferService
    from camp.store import Store
    svc = OfferService(Store())
    ctx = MealContext(display_name="Harry", office=OfficeRef(latitude=40.7424, longitude=-73.9913), presence="inside", budget_cents=2200, now_minutes=600)
    seen = {tuple(o.id for o in svc.offer(ctx).options) for _ in range(4)}
    assert len(seen) > 1                                  # not the same three every time
    first = svc.offer(ctx)
    assert all(o.price_cents <= 2200 for o in first.options)   # jitter never breaks the hard filters


def test_postgres_store_roundtrip_and_indexed_queries():
    import os
    import pytest
    from camp.models import MenuItem, Restaurant, User
    from camp.store import Store
    url = os.getenv("CAMP_TEST_DATABASE_URL", "postgresql://localhost/camp_test")
    try:
        import psycopg
        with psycopg.connect("postgresql://localhost/postgres", autocommit=True) as c:
            c.execute("CREATE DATABASE camp_test") if not c.execute("SELECT 1 FROM pg_database WHERE datname='camp_test'").fetchone() else None
        store = Store(url)
    except Exception as e:      # no local Postgres: the SQLite path is covered by every other test
        pytest.skip(f"postgres unavailable: {e}")
    for cls in (Restaurant, MenuItem, User):
        store.delete_all(cls)
    rests, items = catalog.to_models(n=3)
    store.put_many(rests); store.put_many(items)
    store.put(User(name="pg", office_id="hq", home=catalog.RAMP_HQ))
    assert store.count(Restaurant) == 3 and store.get(Restaurant, rests[0].id).name == rests[0].name
    assert {i.id for i in store.items_for(rests[0].id)} == {i.id for i in items if i.restaurant_id == rests[0].id}
    assert store.users_in_office("hq")[0].name == "pg" and store.users_in_office("nope") == []
    rests[0].name = "renamed"; store.put(rests[0])
    assert store.get(Restaurant, rests[0].id).name == "renamed" and store.count(Restaurant) == 3   # upsert, not duplicate
    store.close()


def test_startup_check_keeps_a_catalog_centred_elsewhere():
    from camp.models import Order, OrderLine
    from camp.store import Store
    store = Store()
    boston = LatLng(lat=42.36, lng=-71.09)
    assert catalog.ensure_current(store, center=boston) is True
    r = store.all(Restaurant)[0]
    line = OrderLine(item_id="x", restaurant_id=r.id, price_cents=1)
    store.put(Order(user_id="u", date="2026-09-21", meal="lunch", location="office", line=line, default_line=line))
    assert catalog.ensure_current(store) is False                 # startup: same membership, keep it
    assert store.count(Order) == 1
    assert catalog.ensure_current(store, center=catalog.RAMP_HQ) is True   # a different office re-centres
