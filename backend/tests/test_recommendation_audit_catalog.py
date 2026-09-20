import asyncio

import pytest

from camp import catalog
from camp.models import Batch, BatchRestaurant, ItemTags, MenuItem, Order, OrderLine, Restaurant
from camp.providers.base import PItem, PQuote, PStore
from camp.providers.mock import MockProvider
from camp.providers.sync import _to_models, sync_catalog
from camp.store import Store


def test_catalog_repair_preserves_history_and_referenced_restaurants():
    store = Store()
    old = Restaurant(id="old", name="Legacy", cuisine="thai", location=catalog.RAMP_HQ)
    item = MenuItem(id="old-item", restaurant_id=old.id, name="Rice", price_cents=1000)
    line = OrderLine(item_id=item.id, restaurant_id=old.id, price_cents=item.price_cents)
    order = Order(user_id="user", date="2026-09-21", meal="lunch", location="office", line=line, default_line=line, status="confirmed")
    batch = Batch(office_id="hq", date=order.date, meal="lunch", objective=0, total_cost_cents=1000,
                  restaurants=[BatchRestaurant(restaurant_id=old.id, user_ids=["user"], fee_share_cents=0)])
    store.put_many([old, item, order, batch])
    assert catalog.ensure_current(store)
    assert store.get(Order, order.id) == order
    assert store.get(Batch, batch.id) == batch
    assert store.get(Restaurant, old.id) == old
    assert store.get(MenuItem, item.id) == item
    assert not catalog.ensure_current(store)


def test_missing_item_repair_does_not_overwrite_persisted_quotes_or_tags():
    store = Store()
    restaurants, items = catalog.to_models()
    restaurant, item, missing = restaurants[0], items[0], items[-1]
    restaurant.fees.delivery_fee_cents = 1234
    restaurant.reliability = 0.4
    item.price_cents = 4321
    item.tags = ItemTags(needs_review=True)
    store.put_many([*restaurants, *items[:-1]])
    assert catalog.ensure_current(store, seed=99)
    assert store.get(MenuItem, missing.id)
    assert store.get(MenuItem, item.id) == item
    assert store.get(Restaurant, restaurant.id) == restaurant
    assert not catalog.ensure_current(store)


def test_provider_catalog_survives_fixture_bootstrap():
    store = Store()
    restaurant = Restaurant(name="Provider restaurant", cuisine="thai", location=catalog.RAMP_HQ,
                            platform="uber", platform_ids={"uber": "real-store"})
    item = MenuItem(restaurant_id=restaurant.id, name="Bowl", price_cents=1500, platform="uber", external_id="real-item")
    store.put_many([restaurant, item])
    assert catalog.ensure_current(store)
    assert store.get(Restaurant, restaurant.id) == restaurant
    assert store.get(MenuItem, item.id) == item
    assert not catalog.ensure_current(store)


def test_recentring_catalog_preserves_orders_and_learned_reliability():
    store = Store()
    catalog.ensure_current(store)
    restaurant = store.all(Restaurant)[0]
    restaurant.reliability = 0.4
    item = store.items_for(restaurant.id)[0]
    line = OrderLine(item_id=item.id, restaurant_id=restaurant.id, price_cents=item.price_cents)
    order = Order(user_id="user", date="2026-09-21", meal="lunch", location="office", line=line, default_line=line)
    store.put_many([restaurant, order])
    assert catalog.ensure_current(store, center=catalog.LatLng(lat=42.36, lng=-71.09))
    assert store.get(Order, order.id) == order
    assert store.get(Restaurant, restaurant.id).reliability == 0.4


class FixtureProvider:
    name = "uber"

    def __init__(self):
        self.menu = [PItem(external_id="item", name="Rice", description="Plain rice", ingredients=["rice"],
                           price_cents=1000, allergens=[])]

    async def search_stores(self, near, radius_km):
        return [PStore(external_id="store", platform=self.name, name="Kitchen", location=catalog.RAMP_HQ, min_order_cents=0)]

    async def get_menu(self, external_id):
        return self.menu

    async def quote(self, external_id, dropoff, n_items=1):
        return PQuote(delivery_fee_cents=100, service_fee_pct=0.1, eta_mean_minutes=20, eta_std_minutes=1)


@pytest.mark.parametrize("keep_existing_tags", [True, False])
def test_provider_refresh_preserves_identity_without_reusing_stale_tags(keep_existing_tags):
    store = Store()
    provider = FixtureProvider()
    asyncio.run(sync_catalog(store, [provider], catalog.RAMP_HQ))
    original = store.all(MenuItem)[0]
    original.tags = ItemTags(vegan=0.99, allergen_p={"peanut": 0.01})
    store.put(original)
    provider.menu[0].ingredients.append("peanut")
    asyncio.run(sync_catalog(store, [provider], catalog.RAMP_HQ, keep_existing_tags=keep_existing_tags))
    assert store.count(MenuItem) == 1
    refreshed = store.all(MenuItem)[0]
    assert refreshed.id == original.id
    assert refreshed.tags is None
    assert store.all(Restaurant)[0].fees.min_order_cents == 0


def test_unknown_provider_allergen_is_unknown_instead_of_verified_empty():
    provider = FixtureProvider()
    store = asyncio.run(provider.search_stores(catalog.RAMP_HQ, 6))[0]
    quote = asyncio.run(provider.quote("store", catalog.RAMP_HQ))
    provider.menu[0].allergens = ["Unmapped allergen"]
    _, items = _to_models(store, provider.menu, quote, None)
    assert items[0].verified_allergens is None
    provider.menu[0].allergens = [" Peanuts ", "MILK"]
    _, items = _to_models(store, provider.menu, quote, None)
    assert items[0].verified_allergens == {"peanut", "dairy"}


def test_mock_placement_is_explicitly_simulated():
    result = asyncio.run(MockProvider(n_stores=1).place_order("fixture", catalog.RAMP_HQ, []))
    assert result.status == "simulated"
    assert result.external_order_id.startswith("mock-")
