import asyncio

import httpx
import pytest

from camp.models import LatLng, MenuItem, Restaurant
from camp.providers import DoorDashProvider, MockProvider, NotConfigured, UberEatsProvider, sync_catalog
from camp.providers.doordash import make_jwt
from camp.store import Store
from camp.synth import OFFICE


def test_mock_goes_through_real_parsers():
    for plat in ("uber", "doordash"):
        p = MockProvider(plat)
        stores = asyncio.run(p.search_stores(OFFICE, 6.0))
        assert stores and all(s.platform == plat for s in stores)
        menu = asyncio.run(p.get_menu(stores[0].external_id))
        assert menu and all(i.price_cents > 0 for i in menu)
        assert any(m.name == "Add Coke" and m.price_cents == 250 for i in menu for m in i.modifiers)
        q = asyncio.run(p.quote(stores[0].external_id, OFFICE))
        assert q.delivery_fee_cents > 0 and q.eta_mean_minutes > 0


def test_real_adapters_refuse_without_credentials(monkeypatch):
    for v in ["UBER_CLIENT_ID", "UBER_CLIENT_SECRET", "DOORDASH_DEVELOPER_ID", "DOORDASH_KEY_ID", "DOORDASH_SIGNING_SECRET"]:
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(NotConfigured):
        asyncio.run(UberEatsProvider().search_stores(OFFICE, 5))
    with pytest.raises(NotConfigured):
        asyncio.run(DoorDashProvider().get_menu("x"))


def test_doordash_jwt_shape():
    tok = make_jwt("dev", "kid", "c2VjcmV0")   # base64url("secret")
    h, p, s = tok.split(".")
    assert h and p and s


def test_uber_adapter_against_fake_http():
    """Wire the Uber adapter to a fake transport so the auth + menu path runs end to end."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "auth.uber.com":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if req.url.path.endswith("/menus"):
            return httpx.Response(200, json={"items": [{"id": "i1", "title": {"translations": {"en_us": "Bowl"}}, "price_info": {"price": 1200},
                                                        "allergen_info": {"contains": ["Peanuts"]}}], "modifier_groups": []})
        return httpx.Response(404)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = UberEatsProvider(client_id="a", client_secret="b", client=client)
    menu = asyncio.run(p.get_menu("s1"))
    assert menu[0].name == "Bowl" and menu[0].allergens == ["peanuts"]


def test_sync_dedupes_and_maps_allergens():
    store = Store()
    rep = asyncio.run(sync_catalog(store, [MockProvider("uber"), MockProvider("doordash", seed=1)], OFFICE, 6.0))
    rests = store.all(Restaurant)
    assert rep.merged > 0
    assert any(len(r.platform_ids) == 2 for r in rests)
    items = store.all(MenuItem)
    assert items and all(i.restaurant_id in {r.id for r in rests} for i in items)
    verified = [i for i in items if i.verified_allergens is not None]
    assert verified and all(a in {"peanut", "tree_nut", "shellfish", "fish", "dairy", "egg", "gluten", "soy", "sesame"} for i in verified for a in i.verified_allergens)
    # second sync keeps item ids stable
    ids = {(i.platform, i.external_id): i.id for i in items}
    asyncio.run(sync_catalog(store, [MockProvider("uber"), MockProvider("doordash", seed=1)], OFFICE, 6.0))
    assert all(ids[(i.platform, i.external_id)] == i.id for i in store.all(MenuItem) if (i.platform, i.external_id) in ids)
