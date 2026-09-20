"""Craving search: the sentence is read by OpenAI (keyword reader offline), the catalog does the answering."""
import asyncio
import importlib

from fastapi.testclient import TestClient

from camp import catalog
from camp.ai.craving import CravingQuery, keyword_query
from camp.models import MenuItem, Restaurant, User
from camp.search import CravingReq, CravingService
from camp.store import Store


def world() -> Store:
    store = Store()
    r, i = catalog.to_models()
    store.put_many(r); store.put_many(i)
    return store


def search(store: Store, text: str, **kw) -> "CravingResponse":   # noqa: F821 - response type is internal
    svc = CravingService(store)
    return asyncio.run(svc.search(CravingReq(text=text, **kw)))


def test_keyword_reader_maps_a_craving_to_search_terms():
    q = keyword_query("I'm really craving tacos")
    assert q.cuisine == "mexican" and q.dish_type == "taco" and "tacos" in q.keywords
    assert keyword_query("something spicy thai under $15").cuisine == "thai"
    assert keyword_query("something spicy thai under $15").spicy
    assert keyword_query("something spicy thai under $15").max_price_cents == 1500


def test_tacos_find_a_mexican_place_with_tacos_on_the_menu():
    store = world()
    res = search(store, "I want tacos")
    assert res.backend == "keywords" and res.matches
    top = res.matches[0]
    items = {i.id: i for i in store.all(MenuItem)}
    assert all("taco" in items[o.id].name.lower() or "taco" in items[o.id].description.lower() for o in top.restaurant.options)
    assert top.restaurant.options[0].price_cents > top.restaurant.options[0].item_price_cents   # all-in with fees
    assert top.reason and res.interpretation


def test_a_different_craving_finds_a_different_cuisine():
    store = world()
    tacos = search(store, "I want tacos").matches[0].restaurant
    thai = search(store, "actually I'd rather have Thai").matches[0].restaurant
    assert thai.id != tacos.id


def test_nothing_matching_says_so_instead_of_recommending_anything():
    store = world()
    res = search(store, "I want haggis")
    assert res.matches == [] and "haggis" in res.note


def test_ranking_respects_diet_price_and_category():
    store = world()
    svc = CravingService(store)
    rests = {r.id: r for r in store.all(Restaurant)}
    q = CravingQuery(cuisine="any", dish_type="salad", keywords=["salad"], vegetarian=True, max_price_cents=1600, summary="a light salad")
    res = svc.rank(CravingReq(text="something light and vegetarian", category="meal", limit=5), q, "llm")
    assert res.backend == "llm"
    items = {i.id: i for i in store.all(MenuItem)}
    for match in res.matches:
        assert "meal" in rests[match.restaurant.id].categories
        for option in match.restaurant.options:
            item = items[option.id]
            assert item.price_cents <= 1600
            assert "vegetarian" in item.verified_diets or (item.tags and item.tags.vegetarian >= 0.9)


def test_http_craving_endpoint(monkeypatch):
    monkeypatch.setenv("CAMP_DB", ":memory:")
    monkeypatch.setenv("CAMP_DATABASE_URL", "")
    monkeypatch.delenv("CAMP_TOKEN", raising=False)
    monkeypatch.setenv("CAMP_USERS", "8")
    import camp.api
    c = TestClient(importlib.reload(camp.api).app)
    body = c.post("/v1/craving", json=dict(text="I want tacos", category="meal", limit=2)).json()
    assert body["backend"] in {"keywords", "llm"} and 1 <= len(body["matches"]) <= 2
    assert body["matches"][0]["restaurant"]["options"]
    assert c.post("/v1/craving", json=dict(text="   ")).status_code == 422


def test_user_restrictions_filter_the_results():
    store = world()
    svc = CravingService(store)
    user = User(name="Harry", office_id="hq", home=catalog.RAMP_HQ,
                restrictions=[{"kind": "diet", "value": "vegan"}])
    store.put(user)
    res = asyncio.run(svc.search(CravingReq(text="I want a burger", user_id=user.id)))
    items = {i.id: i for i in store.all(MenuItem)}
    for match in res.matches:
        for option in match.restaurant.options:
            item = items[option.id]
            assert "vegan" in item.verified_diets or (item.tags and item.tags.vegan >= 0.9)
