from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep

import pytest
from pydantic import ValidationError

from camp import scoring
from camp.contracts import MealContext, OfficeRef
from camp.groups import CreateGroupReq, GroupService, JoinGroupReq, ScheduleReq
from camp.models import FeeSchedule, LatLng, LunchGroup, MenuItem, Order, Restaurant, Restriction, ScheduledOrder, User
from camp.store import Store


OFFICE = OfficeRef(id="audit-office", name="Audit HQ", latitude=40.7, longitude=-74)
DAY = "2026-09-21"


@pytest.fixture
def world():
    store = Store()
    restaurant = Restaurant(
        id="restaurant",
        name="Lunch place",
        location=LatLng(lat=40.7, lng=-74),
        cuisine="salad",
        fees=FeeSchedule(delivery_fee_cents=499, service_fee_pct=0, tax_pct=0, tip_pct=0),
    )
    users = [
        User(id=f"user-{i}", name=f"Person {i}", office_id=OFFICE.id, home=restaurant.location,
             budget_cents={"lunch": 10000, "dinner": 10000})
        for i in range(8)
    ]
    items = [
        MenuItem(id=f"item-{i}", restaurant_id=restaurant.id, name=f"Dish {i}", price_cents=500 + i * 100,
                 verified_allergens=set(), verified_diets={"vegetarian", "vegan"})
        for i in range(3)
    ]
    store.put_many([restaurant, *users, *items])
    yield store, GroupService(store), restaurant, users, items
    store.close()


def create(svc, user, restaurant, items, day=DAY):
    return svc.create(
        CreateGroupReq(office=OFFICE, user_id=user.id, restaurant_id=restaurant.id,
                       delivery_minutes=750, option_ids=[item.id for item in items]), day,
    )


@pytest.mark.parametrize("participants", [1, 2, 3, 7])
def test_delivery_fee_is_exact_and_only_charged_once_per_cart(world, participants):
    store, svc, restaurant, users, items = world
    group = create(svc, users[0], restaurant, items[:2])
    for user in users[1:participants]:
        svc.join(group.id, JoinGroupReq(office=OFFICE, user_id=user.id, option_ids=[i.id for i in items[:2]]))
    stored = store.get(LunchGroup, group.id)
    orders = [o for o in store.all(Order) if o.status == "confirmed"]
    assert sum(o.fee_share_cents for o in orders) == 499
    assert sum(o.total_cents for o in orders) == participants * 1100 + 499
    assert svc.wire(stored, users[0].id).total_cents == sum(o.total_cents for o in orders)
    for user in users[:participants]:
        mine = [o for o in orders if o.user_id == user.id]
        share = sum(o.fee_share_cents for o in mine)
        ledger = svc.ledger(user.id, month="2026-09")
        assert ledger.spent_month_cents == 1100 + share
        assert ledger.saved_month_cents == 499 - share
        assert sum(e.baseline_cents for e in ledger.entries) == 1599
        assert svc.wire(stored, user.id).options[0].price_cents == 500 + share
    if participants > 1:
        svc.leave(group.id, users[0].id)
        remaining = [o for o in store.all(Order) if o.status == "confirmed"]
        assert sum(o.fee_share_cents for o in remaining) == 499
        assert svc.ledger(users[0].id).entries == []


def test_ledger_survives_catalog_edits_and_removal(world):
    store, svc, restaurant, users, items = world
    create(svc, users[0], restaurant, items[:2])
    before = svc.ledger(users[0].id, month="2026-09").model_dump()
    restaurant.name = "Different name"
    restaurant.fees.delivery_fee_cents = 900
    restaurant.fees.tax_pct = 0.5
    items[0].name = "Different dish"
    items[0].price_cents = 9000
    store.put_many([restaurant, items[0]])
    assert svc.ledger(users[0].id, month="2026-09").model_dump() == before
    store.delete_all(Restaurant)
    store.delete_all(MenuItem)
    assert svc.ledger(users[0].id, month="2026-09").model_dump() == before


def test_group_menu_budget_and_orders_use_the_same_price_snapshot(world):
    store, svc, restaurant, users, items = world
    group = create(svc, users[0], restaurant, items[:1])
    items[0].price_cents = 9999
    store.put(items[0])
    users[1].budget_cents["lunch"] = 1349
    store.put(users[1])
    joined = svc.join(group.id, JoinGroupReq(office=OFFICE, user_id=users[1].id, option_ids=["item-0", "item-1"]))
    menu = svc.menu(restaurant.id, users[1].id, group.id)
    assert next(i for i in menu.items if i.id == "item-0").price_cents == 749
    assert next(o for o in joined.options if o.id == "item-0").price_cents == 749
    assert sum(o.total_cents for o in store.orders_for(users[1].id)) == 1349


def test_zero_total_snapshot_is_not_recalculated(world):
    store, svc, restaurant, users, items = world
    restaurant.fees.delivery_fee_cents = 0
    items[0].price_cents = 0
    store.put_many([restaurant, items[0]])
    create(svc, users[0], restaurant, items[:1])
    items[0].price_cents = 10000
    store.put(items[0])
    ledger = svc.ledger(users[0].id, month="2026-09")
    assert ledger.spent_month_cents == ledger.saved_month_cents == 0
    assert ledger.entries[0].amount_cents == ledger.entries[0].baseline_cents == 0


def test_legacy_multi_item_ledger_counts_one_solo_delivery_fee(world):
    store, svc, restaurant, users, items = world
    create(svc, users[0], restaurant, items[:2])
    for order in store.orders_for(users[0].id):
        order.baseline_cents = None
        order.item_name = order.restaurant_name = order.office_name = None
        store.put(order)
    ledger = svc.ledger(users[0].id, month="2026-09")
    assert ledger.saved_month_cents == 0
    assert sum(e.baseline_cents for e in ledger.entries) == 1599


def test_cross_office_and_unknown_users_cannot_join_or_create(world):
    store, svc, restaurant, users, items = world
    group = create(svc, users[0], restaurant, items[:1])
    other_office = OFFICE.model_copy(update={"id": "other"})
    with pytest.raises(ValueError, match="different office"):
        svc.join(group.id, JoinGroupReq(office=other_office, user_id=users[1].id, option_id=items[0].id))
    users[1].office_id = other_office.id
    store.put(users[1])
    with pytest.raises(ValueError, match="different office"):
        svc.join(group.id, JoinGroupReq(office=OFFICE, user_id=users[1].id, option_id=items[0].id))
    with pytest.raises(ValueError, match="different office"):
        create(svc, users[1], restaurant, items[:1])
    with pytest.raises(ValueError, match="unknown user"):
        svc.join(group.id, JoinGroupReq(office=OFFICE, user_id="missing", option_id=items[0].id))
    assert store.count(User) == 8
    assert store.count(Order) == 1
    assert store.get(LunchGroup, group.id).participants == 1


def test_stale_group_option_is_rejected_before_changing_existing_cart(world):
    store, svc, restaurant, users, items = world
    group = create(svc, users[0], restaurant, items[:1])
    before = store.get(LunchGroup, group.id).model_dump()
    store.delete(MenuItem, items[1].id)
    with pytest.raises(ValueError, match="restaurant's menu"):
        svc.join(group.id, JoinGroupReq(office=OFFICE, user_id=users[0].id, option_id=items[1].id))
    assert store.get(LunchGroup, group.id).model_dump() == before
    assert len([o for o in store.orders_for(users[0].id) if o.status == "confirmed"]) == 1


@pytest.mark.parametrize("status", ["locked", "placed"])
def test_closed_group_cannot_be_left_or_replaced(world, status):
    store, svc, restaurant, users, items = world
    group = create(svc, users[0], restaurant, items[:1])
    stored = store.get(LunchGroup, group.id)
    stored.status = status
    store.put(stored)
    with pytest.raises(ValueError, match="no longer collecting"):
        svc.leave(group.id, users[0].id)
    with pytest.raises(ValueError, match="no longer collecting"):
        create(svc, users[0], restaurant, items[1:2])
    assert store.get(LunchGroup, group.id).status == status
    assert store.count(LunchGroup) == 1
    assert store.orders_for(users[0].id)[0].status == "confirmed"


def test_different_dates_do_not_replace_each_other(world):
    store, svc, restaurant, users, items = world
    first = create(svc, users[0], restaurant, items[:1])
    second = create(svc, users[0], restaurant, items[:1], "2026-09-22")
    assert first.id != second.id
    assert all(o.status == "confirmed" for o in store.orders_for(users[0].id))
    svc.leave(second.id, users[0].id)
    assert store.get(LunchGroup, first.id).participants == 1
    assert [o.status for o in store.orders_for(users[0].id)] == ["confirmed", "cancelled"]


@pytest.mark.parametrize("day", ["20260921", "2026-02-30", "2026-9-21", "", "2026-09-21T00:00:00"])
def test_invalid_dates_are_rejected_before_writes(world, day):
    store, svc, restaurant, users, items = world
    with pytest.raises(ValueError):
        create(svc, users[0], restaurant, items[:1], day)
    with pytest.raises(ValueError):
        svc.today(OFFICE, users[0].id, day)
    assert store.count(Order) == store.count(LunchGroup) == 0


@pytest.mark.parametrize("budget", [0, 1, 1098])
def test_expensive_first_item_is_allowed_but_extras_need_budget(world, budget):
    store, svc, restaurant, users, items = world
    users[0].budget_cents["lunch"] = budget
    store.put(users[0])
    group = create(svc, users[0], restaurant, items[:1])
    with pytest.raises(ValueError, match="budget"):
        svc.join(group.id, JoinGroupReq(office=OFFICE, user_id=users[0].id, option_ids=[i.id for i in items[:2]]))
    assert store.get(LunchGroup, group.id).members[0].items() == [items[0].id]
    assert store.orders_for(users[0].id)[0].status == "confirmed"


@pytest.mark.parametrize("restriction", [
    Restriction(kind="allergen", value="peanut", severe=True),
    Restriction(kind="diet", value="vegan"),
])
def test_menu_and_cart_honor_dietary_constraints(world, restriction):
    store, svc, restaurant, users, items = world
    items[1].verified_allergens = {"peanut"}
    items[1].verified_diets = set()
    users[0].restrictions = [restriction]
    store.put_many([items[1], users[0]])
    group = create(svc, users[0], restaurant, items[:1])
    assert items[1].id not in {o.id for o in group.options}
    menu = svc.menu(restaurant.id, users[0].id, group.id)
    assert items[1].id not in {i.id for i in menu.items}
    with pytest.raises(ValueError, match="dietary restrictions"):
        svc.join(group.id, JoinGroupReq(office=OFFICE, user_id=users[0].id, option_ids=[i.id for i in items[:2]]))
    with pytest.raises(ValueError, match="dietary restrictions"):
        create(svc, users[0], restaurant, items[1:2])
    assert store.get(LunchGroup, group.id).members[0].items() == [items[0].id]


def test_severe_allergy_never_treats_missing_verification_as_safe(world):
    store, svc, restaurant, users, items = world
    users[0].restrictions = [Restriction(kind="allergen", value="peanut", severe=True)]
    items[0].verified_allergens = None
    store.put_many([users[0], items[0]])
    with pytest.raises(ValueError, match="unverified"):
        create(svc, users[0], restaurant, items[:1])
    assert store.count(Order) == 0


def test_menu_rejects_mismatched_group_restaurant(world):
    store, svc, restaurant, users, items = world
    group = create(svc, users[0], restaurant, items[:1])
    other = restaurant.model_copy(update={"id": "other-restaurant"})
    store.put(other)
    with pytest.raises(LookupError, match="group not found"):
        svc.menu(other.id, users[0].id, group.id)


def test_zero_score_is_ranked_above_negative_scores(world, monkeypatch):
    _, svc, restaurant, users, items = world
    monkeypatch.setattr(scoring, "rank", lambda *args: [
        (items[0], 0.0, {"health": 0.0}), (items[1], -0.2, {"health": -0.2}), (items[2], -0.5, {"health": -0.5}),
    ])
    assert svc.menu(restaurant.id, users[0].id).top[0].id == items[0].id


def test_schedule_leave_stays_cancelled_on_refresh_and_new_service(world):
    store, svc, restaurant, users, items = world
    schedule = svc.add_schedule(ScheduleReq(
        office=OFFICE, user_id=users[0].id, restaurant_id=restaurant.id, option_id=items[0].id,
        time_minutes=750, weekdays=[0, 1],
    ))
    assert svc.materialize_schedules(OFFICE, users[0].id, DAY)
    group = store.groups_for(OFFICE.id, DAY)[0]
    assert not svc.materialize_schedules(OFFICE, users[0].id, DAY)
    svc.leave(group.id, users[0].id)
    restarted = GroupService(store)
    assert not restarted.materialize_schedules(OFFICE, users[0].id, DAY)
    assert store.orders_for(users[0].id)[0].status == "cancelled"
    assert store.get(ScheduledOrder, schedule.id).materialized_dates == [DAY]
    assert restarted.materialize_schedules(OFFICE, users[0].id, "2026-09-22")
    assert [o.status for o in store.orders_for(users[0].id)] == ["cancelled", "confirmed"]


def test_leaving_manual_group_skips_due_schedule_for_the_day(world):
    store, svc, restaurant, users, items = world
    svc.add_schedule(ScheduleReq(office=OFFICE, user_id=users[0].id, restaurant_id=restaurant.id,
                                time_minutes=750, weekdays=[0]))
    group = create(svc, users[0], restaurant, items[:1])
    svc.leave(group.id, users[0].id)
    assert not svc.materialize_schedules(OFFICE, users[0].id, DAY)
    assert len(store.orders_for(users[0].id)) == 1


@pytest.mark.parametrize("change", ["missing-item", "missing-restaurant", "diet", "suggest-only", "autonomy"])
def test_schedule_does_not_silently_substitute_or_ignore_constraints(world, change):
    store, svc, restaurant, users, items = world
    svc.add_schedule(ScheduleReq(
        office=OFFICE, user_id=users[0].id, restaurant_id=restaurant.id, option_id=items[0].id,
        time_minutes=750, weekdays=[0],
    ))
    if change == "missing-item":
        store.delete(MenuItem, items[0].id)
    elif change == "missing-restaurant":
        store.delete(Restaurant, restaurant.id)
    elif change == "diet":
        users[0].restrictions = [Restriction(kind="allergen", value="peanut", severe=True)]
        items[0].verified_allergens = {"peanut"}
        store.put(items[0])
    elif change == "suggest-only":
        users[0].suggest_only = True
    else:
        users[0].traits.autonomy = 1
    store.put(users[0])
    assert not svc.materialize_schedules(OFFICE, users[0].id, DAY)
    assert store.count(Order) == store.count(LunchGroup) == 0


@pytest.mark.parametrize("changes", [
    {"weekdays": [-1, 0]}, {"weekdays": [0, 7]}, {"weekdays": []},
    {"option_id": "item-0", "restaurant_id": None}, {"time_minutes": 100},
])
def test_invalid_schedules_are_rejected_without_writes(world, changes):
    store, svc, restaurant, users, _ = world
    request = dict(office=OFFICE, user_id=users[0].id, restaurant_id=restaurant.id,
                   time_minutes=750, weekdays=[0])
    request.update(changes)
    with pytest.raises(ValueError):
        svc.add_schedule(ScheduleReq(**request))
    assert store.count(ScheduledOrder) == 0


def test_schedule_revalidates_user_office(world):
    store, svc, restaurant, users, _ = world
    svc.add_schedule(ScheduleReq(office=OFFICE, user_id=users[0].id, restaurant_id=restaurant.id,
                                time_minutes=750, weekdays=[0]))
    users[0].office_id = "other-office"
    store.put(users[0])
    with pytest.raises(ValueError, match="different office"):
        svc.materialize_schedules(OFFICE, users[0].id, DAY)
    assert store.count(Order) == 0


@pytest.mark.parametrize("changes", [
    {"budget_cents": -1}, {"lunch_start": 1500}, {"lunch_end": 600},
    {"lunch_duration": 0}, {"lunch_duration": 181}, {"now_minutes": 1440},
])
def test_invalid_profile_contracts_are_rejected(changes):
    with pytest.raises(ValidationError):
        MealContext(office=OFFICE, **changes)


@pytest.mark.parametrize("month", ["2026-13", "2026-9", "202609", "garbage"])
def test_invalid_ledger_month_is_rejected(world, month):
    _, svc, _, users, _ = world
    with pytest.raises(ValueError):
        svc.ledger(users[0].id, month=month)


def test_demo_seed_never_enrolls_real_profiles(world):
    store, svc, _, users, _ = world
    today = svc.today(OFFICE, None, DAY)
    assert today.groups
    assert not ({m.user_id for g in today.groups for m in g.members} & {u.id for u in users})
    assert all(store.get(User, m.user_id).synthetic for g in today.groups for m in g.members)
    assert all(not svc.ledger(u.id).entries for u in users)


def test_collecting_group_can_be_left_after_catalog_removal(world):
    store, svc, restaurant, users, items = world
    group = create(svc, users[0], restaurant, items[:1])
    svc.join(group.id, JoinGroupReq(office=OFFICE, user_id=users[1].id, option_id=items[0].id))
    store.delete_all(MenuItem)
    store.delete_all(Restaurant)
    left = svc.leave(group.id, users[0].id)
    assert left.participants == 1
    assert svc.ledger(users[0].id).entries == []
    assert svc.ledger(users[1].id, month="2026-09").spent_month_cents == 999
    svc.leave(group.id, users[1].id)
    assert store.get(LunchGroup, group.id).status == "cancelled"
    assert svc.ledger(users[1].id).entries == []


def test_unknown_menu_user_is_rejected(world):
    _, svc, restaurant, _, _ = world
    with pytest.raises(ValueError, match="unknown user"):
        svc.menu(restaurant.id, "missing")


@pytest.mark.parametrize("changes", [
    {"delivery_fee_cents": -1}, {"tax_pct": -0.1},
    {"tip_pct": float("inf")}, {"service_fee_pct": float("nan")},
])
def test_invalid_fee_amounts_are_rejected(changes):
    with pytest.raises(ValidationError):
        FeeSchedule(**changes)


def test_concurrent_joins_preserve_every_member_and_order(world, monkeypatch):
    store, svc, restaurant, users, items = world
    group = create(svc, users[0], restaurant, items[:1])
    read = store.get
    ready = Barrier(len(users) - 1)

    def delayed_read(model, identifier):
        row = read(model, identifier)
        if model is LunchGroup and identifier == group.id:
            sleep(0.01)
        return row

    monkeypatch.setattr(store, "get", delayed_read)

    def join(user):
        ready.wait(timeout=5)
        return svc.join(group.id, JoinGroupReq(office=OFFICE, user_id=user.id, option_id=items[0].id))

    with ThreadPoolExecutor(max_workers=len(users) - 1) as pool:
        list(pool.map(join, users[1:]))
    stored = store.get(LunchGroup, group.id)
    orders = [o for o in store.all(Order) if o.status == "confirmed"]
    assert {m.user_id for m in stored.members} == {u.id for u in users}
    assert len(orders) == len(users)
    assert {m.order_id for m in stored.members} == {o.id for o in orders}
    assert sum(o.fee_share_cents for o in orders) == restaurant.fees.delivery_fee_cents


def test_schedule_receipt_failure_rolls_back_membership_and_orders(world, monkeypatch):
    store, svc, restaurant, users, _ = world
    schedule = svc.add_schedule(ScheduleReq(office=OFFICE, user_id=users[0].id, restaurant_id=restaurant.id,
                                          time_minutes=750, weekdays=[0]))
    write = store.put

    def fail_receipt(row):
        if isinstance(row, ScheduledOrder) and row.materialized_dates:
            raise RuntimeError("receipt write failed")
        write(row)

    with monkeypatch.context() as context:
        context.setattr(store, "put", fail_receipt)
        with pytest.raises(RuntimeError, match="receipt write failed"):
            svc.materialize_schedules(OFFICE, users[0].id, DAY)
    assert store.count(LunchGroup) == 0
    assert store.count(Order) == 0
    assert store.get(ScheduledOrder, schedule.id).materialized_dates == []
    assert svc.materialize_schedules(OFFICE, users[0].id, DAY)
    assert store.count(Order) == 1
