import importlib
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import timedelta
from multiprocessing import get_context
from threading import Barrier
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from camp import feedback
from camp.contracts import MealContext, OfficeRef
from camp.groups import CreateGroupReq, GroupService, JoinGroupReq, ScheduleReq
from camp.models import (
    FeedbackEvent, FeeSchedule, LatLng, LunchGroup, MenuItem, OfferRecord, Order,
    Restaurant, ScheduledOrder, User, utcnow,
)
from camp.offers import OfferService
from camp.store import Store


OFFICE = OfficeRef(id="hq", name="HQ", latitude=40.7424, longitude=-73.9913)


@pytest.fixture(params=["sqlite"] + (["postgres"] if os.getenv("CAMP_INTEGRATION_DATABASE_URL") else []))
def database_url(request, tmp_path):
    if request.param == "sqlite":
        yield str(tmp_path / "integration.db")
        return
    url = os.environ["CAMP_INTEGRATION_DATABASE_URL"]
    name = f"camp_integration_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield urlunsplit(urlsplit(url)._replace(path=f"/{name}"))
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture
def world(database_url):
    path = database_url
    store = Store(path)
    rest = Restaurant(id="r", name="Lunch", cuisine="thai", location=LatLng(lat=OFFICE.latitude, lng=OFFICE.longitude),
                      open_minutes=(0, 1440), prep_base_minutes=0, prep_per_item_minutes=0,
                      eta_mean_minutes=0, eta_std_minutes=0,
                      fees=FeeSchedule(delivery_fee_cents=499, service_fee_pct=0, tax_pct=0, tip_pct=0, min_order_cents=0))
    users = [User(id=f"u{i}", name=f"Eater {i}", office_id=OFFICE.id, home=rest.location,
                  budget_cents={"lunch": 10000, "dinner": 10000}) for i in range(4)]
    items = [MenuItem(id=f"i{i}", name=f"Rice {i}", restaurant_id=rest.id, price_cents=500 + i * 100,
                      verified_allergens=set()) for i in range(3)]
    store.put_many([rest, *users, *items])
    yield path, store, rest, users, items
    store.close()


def issue(store, user, monkeypatch):
    service = OfferService(store)
    monkeypatch.setattr(service, "ensure_world", lambda office: None)
    offer = service.offer(MealContext(user_id=user.id, office=OFFICE, presence="outside", now_minutes=600))
    assert offer.options
    return offer


def confirm_in_process(args):
    path, offer_id, option_id = args
    store = Store(path)
    try:
        return OfferService(store).lunch_event(offer_id, option_id, "confirmed")
    finally:
        store.close()


def test_offer_confirmation_replays_across_processes(world, monkeypatch):
    path, store, _, users, _ = world
    offer = issue(store, users[0], monkeypatch)
    args = (path, offer.offer_id, offer.options[0].id)
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        results = list(pool.map(confirm_in_process, [args] * 4))
    assert all(result["status"] == "confirmed" for result in results)
    assert len({result["orderId"] for result in results}) == 1
    assert store.count(FeedbackEvent) == 1


def test_durable_offer_survives_copy_and_ends_without_resurrection(world, monkeypatch):
    _, store, _, users, _ = world
    offer = issue(store, users[0], monkeypatch)
    destination = Store()
    try:
        assert destination.copy_from(store)["offers"] == 1
        service = OfferService(destination)
        service.lunch_event(offer.offer_id, None, "ended")
        result = OfferService(destination).lunch_event(offer.offer_id, offer.options[0].id, "confirmed")
        assert "error" in result
        record = destination.get(OfferRecord, offer.offer_id)
        assert record.state == "ended" and record.ended
        assert destination.get(Order, record.order_id).status == "cancelled"
        assert store.get(OfferRecord, offer.offer_id).state == "offered"
    finally:
        destination.close()


def test_live_offer_expiration_and_terminal_state(world, monkeypatch):
    _, store, _, users, _ = world
    offer = issue(store, users[0], monkeypatch)
    record = store.get(OfferRecord, offer.offer_id)
    record.now_minutes = None
    record.wire.closes_at = (utcnow() - timedelta(seconds=1)).isoformat()
    store.put(record)
    service = OfferService(store)
    assert "expired" in service.lunch_event(offer.offer_id, offer.options[0].id, "confirmed")["error"]
    assert store.get(Order, record.order_id).status == "proposed"
    record.wire.closes_at = (utcnow() + timedelta(hours=1)).isoformat()
    store.put(record)
    assert service.lunch_event(offer.offer_id, offer.options[0].id, "confirmed")["status"] == "confirmed"
    assert service.lunch_event(offer.offer_id, offer.options[0].id, "ended")["status"] == "confirmed"
    assert "ended" in service.lunch_event(offer.offer_id, offer.options[0].id, "delivered")["error"]
    assert store.get(OfferRecord, offer.offer_id).state == "ended"


def test_offer_restart_confirmation_and_ledger_snapshots(world, monkeypatch):
    path, store, rest, users, _ = world
    offer = issue(store, users[0], monkeypatch)
    record = store.get(OfferRecord, offer.offer_id)
    assert record.wire == offer
    assert record.state == "offered"
    second = Store(path)
    try:
        service = OfferService(second)
        confirmed = service.lunch_event(offer.offer_id, offer.options[0].id, "confirmed")
        assert confirmed["status"] == "confirmed"
        order = store.get(Order, confirmed["orderId"])
        assert order.office_name == OFFICE.name and order.restaurant_name == rest.name
        before = GroupService(store).ledger(users[0].id).model_dump()
        second.delete_all(MenuItem)
        second.delete_all(Restaurant)
        assert GroupService(store).ledger(users[0].id).model_dump() == before
        assert store.get(OfferRecord, offer.offer_id).selected_option_id == offer.options[0].id
    finally:
        second.close()


def test_concurrent_offer_replay_across_connections_learns_once(world, monkeypatch):
    path, store, _, users, _ = world
    offer = issue(store, users[0], monkeypatch)
    connections = [Store(path) for _ in range(4)]
    barrier = Barrier(4)

    def confirm(connection):
        barrier.wait()
        return OfferService(connection).lunch_event(offer.offer_id, offer.options[0].id, "confirmed")

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(confirm, connections))
        assert len({result["orderId"] for result in responses}) == 1
        assert store.count(FeedbackEvent) == 1
        learned = store.get(User, users[0].id)
        OfferService(store).lunch_event(offer.offer_id, offer.options[0].id, "confirmed")
        assert store.get(User, users[0].id) == learned
        OfferService(store).lunch_event(offer.offer_id, None, "delivered", 4)
        rated = store.get(User, users[0].id)
        OfferService(connections[0]).lunch_event(offer.offer_id, None, "delivered", 4)
        assert store.get(User, users[0].id) == rated
        assert store.count(FeedbackEvent) == 2
        assert store.get(OfferRecord, offer.offer_id).state == "delivered"
    finally:
        for connection in connections:
            connection.close()


def test_offer_event_failure_rolls_back_all_state_then_retries(world, monkeypatch):
    _, store, _, users, _ = world
    offer = issue(store, users[0], monkeypatch)
    before = store.get(OfferRecord, offer.offer_id)
    profile = store.get(User, users[0].id)
    original = store.put

    def fail_offer(row):
        if isinstance(row, OfferRecord):
            raise OSError("offer write failed")
        original(row)

    with monkeypatch.context() as patch:
        patch.setattr(store, "put", fail_offer)
        with pytest.raises(OSError, match="offer write failed"):
            OfferService(store).lunch_event(offer.offer_id, offer.options[0].id, "confirmed")
    assert store.get(OfferRecord, offer.offer_id) == before
    assert store.get(User, users[0].id) == profile
    assert store.count(FeedbackEvent) == 0
    assert store.get(Order, before.order_id).status == "proposed"
    assert OfferService(store).lunch_event(offer.offer_id, offer.options[0].id, "confirmed")["status"] == "confirmed"


def test_concurrent_feedback_claim_is_atomic(world):
    path, store, _, users, items = world
    event = FeedbackEvent(user_id=users[0].id, type="accept", item_id=items[0].id, payload={"novel": True})
    before = users[0].traits.epsilon_a
    connections = [Store(path) for _ in range(4)]
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda connection: feedback.apply_event(connection, event.model_copy(deep=True)), connections))
        assert store.get(User, users[0].id).traits.epsilon_a == before + 1
        assert store.count(FeedbackEvent) == 1
    finally:
        for connection in connections:
            connection.close()


def test_group_fee_wire_matches_concurrent_multi_item_orders(world):
    path, store, rest, users, items = world
    service = GroupService(store)
    group = service.create(CreateGroupReq(office=OFFICE, restaurant_id=rest.id, user_id=users[0].id,
                                          delivery_minutes=750, option_ids=[items[0].id, items[1].id]))
    connections = [Store(path) for _ in users[1:]]
    barrier = Barrier(len(connections))

    def join(pair):
        connection, user = pair
        barrier.wait()
        return GroupService(connection).join(group.id, JoinGroupReq(office=OFFICE, user_id=user.id,
                                                                    option_ids=[items[0].id, items[1].id]))

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(join, zip(connections, users[1:])))
        stored = store.get(LunchGroup, group.id)
        assert len(stored.members) == 4
        assert sum(o.fee_share_cents for o in store.all(Order)) == 499
        for user in users:
            wire = service.wire(stored, user.id)
            cart = [next(o for o in wire.options if o.id == item.id) for item in items[:2]]
            total = sum(option.price_cents for option in cart) - cart[1].delivery_share_cents
            assert total == sum(order.total_cents for order in store.orders_for(user.id))
            menu = service.menu(rest.id, user.id, group.id)
            assert all(item.delivery_share_cents == cart[0].delivery_share_cents for item in menu.items)
            assert "deliveryShareCents" in cart[0].model_dump(by_alias=True)
    finally:
        for connection in connections:
            connection.close()


def test_offers_do_not_reuse_synthetic_profiles(world):
    _, store, _, users, _ = world
    users[0].synthetic = True
    store.put(users[0])
    actual, created = OfferService(store).user_for(MealContext(display_name=users[0].name, office=OFFICE))
    assert created and actual.id != users[0].id and not actual.synthetic
    with pytest.raises(ValueError):
        OfferService(store).user_for(MealContext(user_id=users[0].id, office=OFFICE))


def test_schedule_event_route_requires_owner_and_maps_validation(world, monkeypatch, tmp_path):
    path, store, rest, users, items = world
    schedule = GroupService(store).add_schedule(ScheduleReq(office=OFFICE, user_id=users[0].id,
                                                           restaurant_id=rest.id, option_id=items[0].id,
                                                           time_minutes=750))
    monkeypatch.setenv("CAMP_DATABASE_URL", "")
    monkeypatch.setenv("CAMP_DB", path)
    monkeypatch.setenv("CAMP_TOKEN", "")
    monkeypatch.setenv("CAMP_ENV_FILE", str(tmp_path / "absent.env"))
    api = importlib.reload(importlib.import_module("camp.api"))
    try:
        client = TestClient(api.app)
        endpoint = f"/v1/schedules/{schedule.id}/event"
        assert client.put(endpoint, json={"calendarEventId": "event"}).status_code == 422
        assert client.put(endpoint, json={"calendarEventId": "event", "userId": users[1].id}).status_code == 404
        assert api.store.get(ScheduledOrder, schedule.id).calendar_event_id is None
        assert client.put(endpoint, json={"calendarEventId": "event", "userId": users[0].id}).status_code == 200
        assert client.put(endpoint, json={"userId": users[0].id}).status_code == 200
        assert api.store.get(ScheduledOrder, schedule.id).calendar_event_id is None
        assert client.get("/v1/groups?officeId=hq&userId=missing").status_code == 422
        assert client.get(f"/v1/restaurants/{rest.id}/menu?userId=missing").status_code == 422
        assert client.get(f"/v1/ledger/{users[0].id}?month=0000-01").status_code == 422
    finally:
        api.store.close()
