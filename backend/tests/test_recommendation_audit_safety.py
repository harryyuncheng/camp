import asyncio
from datetime import date

import pytest

from camp import batching, feedback, filters, pipeline, scoring
from camp.ai.classify import MockClassifier
from camp.ai.craving import CravingQuery, keyword_query
from camp.ai.modifications import modify
from camp.ai.tagging import tag_item
from camp.contracts import MealContext, OfficeRef
from camp.models import (
    Batch, BatchRestaurant, Context, FeedbackEvent, FeeSchedule, ItemTags, LatLng,
    MealWindow, MenuItem, Order, OrderLine, Restaurant, Restriction, User,
)
from camp.offers import OfferService
from camp.search import CravingReq, CravingService
from camp.store import Store


def fixtures():
    loc = LatLng(lat=40.7424, lng=-73.9913)
    user = User(id="u", name="Eater", office_id="hq", home=loc)
    rest = Restaurant(id="r", name="Kitchen", cuisine="thai", location=loc, open_minutes=(0, 1440),
                      fees=FeeSchedule(delivery_fee_cents=0, service_fee_pct=0, tax_pct=0, tip_pct=0, min_order_cents=0),
                      prep_base_minutes=0, prep_per_item_minutes=0, eta_mean_minutes=0, eta_std_minutes=0)
    item = MenuItem(id="i", restaurant_id=rest.id, name="Rice bowl", price_cents=1000,
                    verified_allergens=set(), tags=ItemTags(dish_type="bowl", allergen_p={"peanut": 0.01}))
    ctx = Context(date=date.today().isoformat(), meal="lunch", weekday=date.today().weekday(), order_time_minutes=600)
    return user, rest, item, ctx


def offer_fixture():
    user, rest, item, context = fixtures()
    store = Store()
    line = OrderLine(item_id=item.id, restaurant_id=rest.id, price_cents=item.price_cents)
    order = Order(user_id=user.id, date=context.date, meal="lunch", location="office", line=line, default_line=line)
    store.put_many([user, rest, item, order])
    service = OfferService(store)
    service.offers["offer"] = dict(user_id=user.id, order_id=order.id, default_item_id=item.id, shown=[item.id],
                                  novel=True, meal="lunch", date=context.date, location="office", fee_share={rest.id: 0},
                                  plan_key=("hq", context.date, "lunch"), context=context.model_dump(), now_minutes=600,
                                  office=OfficeRef(id="hq", latitude=rest.location.lat, longitude=rest.location.lng).model_dump())
    return service, user, rest, item, order


def test_no_severe_allergy_fallback_reintroduces_rejected_items():
    user, rest, item, context = fixtures()
    user.restrictions = [Restriction(kind="allergen", value="peanut", severe=True)]
    item.verified_allergens = None
    rest.location = LatLng(lat=0, lng=0)
    item.price_cents = 100000
    feasible = filters.feasible([user], {rest.id: rest}, [item], context, user.home, lambda _: "office", lambda *_: 0)
    assert feasible.items_for(user.id) == []
    assert user.id in feasible.suggest_only


@pytest.mark.parametrize("tags", [None, ItemTags(), ItemTags(allergen_p={"peanut": 0.01}, confidence=0.2),
                                 ItemTags(allergen_p={"peanut": 0.01}, needs_review=True)])
def test_unknown_allergen_evidence_is_not_safe(tags):
    user, _, item, _ = fixtures()
    user.restrictions = [Restriction(kind="allergen", value="peanut")]
    item.verified_allergens, item.tags = None, tags
    assert not filters.passes_dietary(user, item)[0]


@pytest.mark.parametrize("diet,allergen", [("gluten_free", "gluten"), ("dairy_free", "dairy"), ("vegan", "egg")])
def test_verified_allergens_override_conflicting_diet_labels(diet, allergen):
    user, _, item, _ = fixtures()
    user.restrictions = [Restriction(kind="diet", value=diet)]
    item.verified_diets, item.verified_allergens = {diet}, {allergen}
    assert not filters.passes_dietary(user, item)[0]


def test_unknown_allergy_is_fail_closed():
    user, _, item, _ = fixtures()
    user.restrictions = [Restriction(kind="allergen", value="mustard")]
    assert not filters.passes_dietary(user, item)[0]


def test_meal_window_must_leave_enough_eating_time():
    user, rest, _, ctx = fixtures()
    user.windows["lunch"] = MealWindow(start=720, end=730, min_eat_minutes=20)
    assert not filters.passes_time(user, rest, ctx)[0]


def test_exact_solver_keeps_capacity_feasible_assignment():
    user, rest, item, _ = fixtures()
    other_user = user.model_copy(update={"id": "v"})
    other_rest = rest.model_copy(update={"id": "s"}, deep=True)
    other_item = item.model_copy(update={"id": "j", "restaurant_id": "s"})
    rest.max_meals_per_slot = other_rest.max_meals_per_slot = 1
    candidate = batching.Candidate(users={"u": user, "v": other_user}, restaurants={"r": rest, "s": other_rest},
                                   items={"i": item, "j": other_item}, scores={"u": {"i": 3, "j": 2.5}, "v": {"i": 3, "j": 2.5}}, meal="lunch")
    selected, assigned = batching.solve_exact(candidate)
    assert set(selected) == {"r", "s"}
    assert len(assigned.assign) == 2
    assert assigned.n == {"r": 1, "s": 1}
    assert assigned.total_cost == 2000


def test_iteration_limit_cannot_leave_underpriced_fee_shares():
    user, rest, item, _ = fixtures()
    user.budget_cents["lunch"] = 1300
    rest.fees.delivery_fee_cents, rest.max_meals_per_slot = 500, 1
    other = user.model_copy(update={"id": "v"}, deep=True)
    candidate = batching.Candidate(users={"u": user, "v": other}, restaurants={"r": rest}, items={"i": item},
                                   scores={"u": {"i": 1}, "v": {"i": 1}}, meal="lunch")
    assigned = batching._assign(candidate, ["r"], iters=1)
    assert assigned.assign == {}
    assert assigned.n == {"r": 0}


def test_batch_prep_time_is_checked_at_actual_headcount():
    user, rest, item, ctx = fixtures()
    user.windows["lunch"] = MealWindow(start=620, end=650, min_eat_minutes=20)
    rest.prep_per_item_minutes = 10
    store = Store()
    store.put_many([rest, item, *[user.model_copy(update={"id": f"u{i}"}, deep=True) for i in range(4)]])
    plan = pipeline.plan_office(store, "hq", user.home, ctx)
    for order in plan.orders:
        headcount = next(len(br.user_ids) for br in plan.batch.restaurants if br.restaurant_id == rest.id)
        assert filters.passes_time(user, rest, ctx, headcount)[0]
    assert len(plan.orders) < 4


def test_suggest_only_options_use_full_fee_without_batch():
    user, rest, item, ctx = fixtures()
    user.suggest_only = True
    user.budget_cents["lunch"], rest.fees.delivery_fee_cents = 1100, 500
    store = Store()
    store.put_many([user, rest, item])
    assert pipeline.plan_office(store, "hq", user.home, ctx).recommendations[user.id] == []


def test_planning_does_not_change_fairness_debt():
    user, rest, item, ctx = fixtures()
    user.traits.sacrifice_debt = 3
    store = Store()
    store.put_many([user, rest, item])
    for _ in range(2):
        pipeline.plan_office(store, "hq", user.home, ctx)
    assert store.get(User, user.id).traits.sacrifice_debt == 3


def test_search_uses_all_in_price_and_rejects_unknown_user():
    user, rest, item, _ = fixtures()
    rest.fees.delivery_fee_cents = 500
    store = Store()
    store.put_many([user, rest, item])
    service = CravingService(store)
    query = CravingQuery(cuisine="thai", dish_type="any", max_price_cents=1200)
    assert not service.rank(CravingReq(text="Thai under $12"), query, "keywords").matches
    query.max_price_cents = 2000
    result = service.rank(CravingReq(text="Thai", user_id="missing"), query, "keywords")
    assert not result.matches and "Unknown user" in result.note


def test_search_uses_verified_allergens_even_when_menu_text_omits_them():
    _, rest, item, _ = fixtures()
    item.verified_allergens = {"peanut", "gluten"}
    item.tags.allergen_p = {"gluten": 0.01}
    store = Store()
    store.put_many([rest, item])
    service = CravingService(store)
    for query in [CravingQuery(cuisine="thai", dish_type="any", avoid=["Peanuts"]),
                  CravingQuery(cuisine="thai", dish_type="any", gluten_free=True)]:
        assert not service.rank(CravingReq(text="safe Thai"), query, "keywords").matches


def test_keyword_reader_preserves_cents_and_does_not_recommend_negations():
    query = keyword_query("no tacos; Thai under $15.75")
    assert query.max_price_cents == 1575
    assert query.cuisine == "thai" and query.dish_type == "any"
    assert query.avoid == ["tacos"]
    assert not keyword_query("Thai, not vegan").vegan


def test_feedback_replay_does_not_decay_or_learn_twice():
    user, rest, item, _ = fixtures()
    store = Store()
    store.put_many([user, rest, item])
    event = FeedbackEvent(user_id=user.id, type="accept", item_id=item.id, payload={"novel": True})
    feedback.apply_event(store, event)
    after = store.get(User, user.id)
    feedback.apply_event(store, event.model_copy())
    assert store.get(User, user.id) == after
    assert store.count(FeedbackEvent) == 1


def test_constraint_can_be_confirmed_once_without_downgrading_severity():
    user, _, _, _ = fixtures()
    user.restrictions = [Restriction(kind="allergen", value="peanut")]
    store = Store()
    store.put(user)
    event = FeedbackEvent(user_id=user.id, type="constraint", needs_confirmation=True,
                          payload={"which": "allergen:peanut", "action": "add", "severe": True})
    feedback.apply_event(store, event)
    event.payload["confirmed"] = True
    feedback.apply_event(store, event)
    constraint = store.get(User, user.id).restrictions[0]
    assert constraint.severe and constraint.source == "nl_confirmed"
    assert store.get(FeedbackEvent, event.id).applied


def test_skip_without_reason_does_not_decay_preferences():
    user, _, _, _ = fixtures()
    user.prefs.revealed["cuisine:thai"] = 1
    store = Store()
    store.put(user)
    feedback.apply_event(store, FeedbackEvent(user_id=user.id, type="skip"))
    assert store.get(User, user.id).prefs == user.prefs


def test_offer_replays_do_not_duplicate_learning_or_rating():
    service, user, _, item, order = offer_fixture()
    assert service.lunch_event("offer", item.id, "confirmed")["status"] == "confirmed"
    after = service.store.get(User, user.id)
    service.lunch_event("offer", item.id, "confirmed")
    assert service.store.get(User, user.id) == after
    service.lunch_event("offer", None, "delivered", 4)
    rated = service.store.get(User, user.id)
    service.lunch_event("offer", None, "delivered", 4)
    assert service.store.get(User, user.id) == rated
    assert service.store.count(FeedbackEvent) == 2
    assert service.store.get(Order, order.id).status == "confirmed"


@pytest.mark.parametrize("event,option,rating", [("confirmed", "unshown", None), ("delivered", None, None),
                                                ("delivered", None, 99), ("unknown", None, None)])
def test_invalid_offer_events_do_not_change_persisted_state(event, option, rating):
    service, user, _, _, order = offer_fixture()
    assert "error" in service.lunch_event("offer", option, event, rating)
    assert service.store.get(Order, order.id) == order
    assert service.store.get(User, user.id) == user
    assert service.store.count(FeedbackEvent) == 0


def test_cancelled_offer_cannot_be_resurrected():
    service, _, _, item, order = offer_fixture()
    service.lunch_event("offer", None, "ended")
    assert "error" in service.lunch_event("offer", item.id, "confirmed")
    assert "error" in service.lunch_event("offer", None, "delivered")
    assert service.store.get(Order, order.id).status == "cancelled"


@pytest.mark.parametrize("change", ["budget", "allergy", "expired", "window"])
def test_offer_confirmation_revalidates_current_constraints(change):
    service, user, _, item, order = offer_fixture()
    if change == "budget":
        user.budget_cents["lunch"] = 1
    elif change == "allergy":
        user.restrictions = [Restriction(kind="allergen", value="peanut", severe=True)]
        item.verified_allergens = {"peanut"}
        service.store.put(item)
    elif change == "expired":
        service.offers["offer"]["now_minutes"] = 1000
    else:
        user.windows["lunch"] = MealWindow(start=600, end=601, min_eat_minutes=20)
    service.store.put(user)
    assert "error" in service.lunch_event("offer", item.id, "confirmed")
    assert service.store.get(Order, order.id).status == "proposed"


def test_onboarding_does_not_add_substring_allergies_or_drop_confirmed_severity():
    service, user, rest, _, _ = offer_fixture()
    user.restrictions = [Restriction(kind="allergen", value="peanut", severe=True, source="nl_confirmed")]
    service.store.put(user)
    ctx = MealContext(user_id=user.id, office=OfficeRef(id="hq", latitude=rest.location.lat, longitude=rest.location.lng),
                      allergies=["peanut", "shellfish"])
    updated, _ = service.user_for(ctx)
    assert {r.value for r in updated.restrictions} == {"peanut", "shellfish"}
    assert next(r for r in updated.restrictions if r.value == "peanut").severe


def test_context_does_not_backdate_a_request_after_cutoff():
    service, _, rest, _, _ = offer_fixture()
    ctx = MealContext(office=OfficeRef(latitude=rest.location.lat, longitude=rest.location.lng), now_minutes=900)
    assert service._context(ctx).order_time_minutes == 900


def test_manual_and_future_orders_are_not_eaten_history():
    user, rest, item, ctx = fixtures()
    line = OrderLine(item_id=item.id, restaurant_id=rest.id, price_cents=item.price_cents)
    orders = [Order(user_id=user.id, date=ctx.date, meal="lunch", location="office", line=line, default_line=line, status="manual"),
              Order(user_id=user.id, date="2099-01-01", meal="lunch", location="office", line=line, default_line=line, status="confirmed")]
    history = scoring.History.from_orders(orders, {item.id: item}, {rest.id: rest}, date.today().toordinal())
    assert not history.items_eaten


def test_rejected_modification_has_no_batch_side_effects():
    service, user, rest, item, order = offer_fixture()
    other_rest = rest.model_copy(update={"id": "s"}, deep=True)
    other_item = item.model_copy(update={"id": "j", "restaurant_id": "s", "name": "Peanut bowl", "verified_allergens": {"peanut"}})
    user.restrictions = [Restriction(kind="allergen", value="peanut", severe=True)]
    batch = Batch(office_id="hq", date=order.date, meal="lunch", objective=0, total_cost_cents=2400,
                  restaurants=[BatchRestaurant(restaurant_id="r", user_ids=["u"], fee_share_cents=200),
                               BatchRestaurant(restaurant_id="s", user_ids=["v"], fee_share_cents=200)])
    order.batch_id = batch.id
    service.store.put_many([user, other_rest, other_item, batch, order])
    result = asyncio.run(modify(MockClassifier(), service.store, order, "different restaurant peanut bowl", 500))
    assert not result.ok and "conflicts" in result.message
    assert service.store.get(Batch, batch.id) == batch
    assert service.store.get(User, user.id) == user


def test_tag_cache_does_not_cross_classifier_boundaries():
    _, _, item, _ = fixtures()
    plain = MockClassifier(rules=lambda *_: {"contains_peanut": False})
    warning = MockClassifier(rules=lambda *_: {"contains_peanut": True})
    assert asyncio.run(tag_item(plain, item)).allergen_p["peanut"] < 0.1
    assert asyncio.run(tag_item(warning, item)).allergen_p["peanut"] > 0.1


def test_tag_cache_cannot_be_modified_through_returned_values():
    _, _, item, _ = fixtures()
    classifier = MockClassifier(rules=lambda *_: {"contains_peanut": True})
    tags = asyncio.run(tag_item(classifier, item))
    tags.allergen_p["peanut"] = 0
    cached = asyncio.run(tag_item(classifier, item))
    assert cached.allergen_p["peanut"] > 0.1
    cached.allergen_p["peanut"] = 0
    assert asyncio.run(tag_item(classifier, item)).allergen_p["peanut"] > 0.1


def test_modification_addon_cost_includes_overhead_and_is_not_duplicated():
    service, user, rest, item, order = offer_fixture()
    rest.fees.service_fee_pct = 0.2
    item.modifiers, item.modifier_prices = ["Extra sauce"], {"Extra sauce": 100}
    order.line.addons = ["Extra sauce"]
    service.store.put_many([rest, item, order])
    result = asyncio.run(modify(MockClassifier(), service.store, order, "extra sauce", 500))
    assert result.ok
    assert result.new_line.addons == ["Extra sauce"]
    assert result.total_cents == 1320


def test_calorie_carryover_ignores_proposals_and_sums_confirmed_items():
    service, user, _, item, order = offer_fixture()
    item.kcal = 400
    service.store.put(item)
    ctx = Context(date=order.date, meal="dinner", weekday=0)
    assert pipeline._remaining_kcal(service.store, user, ctx, {item.id: item}) is None
    order.status = "confirmed"
    another = order.model_copy(update={"id": "another"})
    service.store.put_many([order, another])
    assert pipeline._remaining_kcal(service.store, user, ctx, {item.id: item}) == 500


def test_fairness_debt_changes_only_once_when_offer_confirmed():
    service, user, _, item, order = offer_fixture()
    user.traits.sacrifice_debt = 2
    batch = Batch(office_id="hq", date=order.date, meal="lunch", objective=0, total_cost_cents=1000,
                  restaurants=[BatchRestaurant(restaurant_id="r", user_ids=[user.id], fee_share_cents=0)],
                  regret={user.id: 1.5})
    order.batch_id = batch.id
    service.store.put_many([user, batch, order])
    service.lunch_event("offer", item.id, "confirmed")
    assert service.store.get(User, user.id).traits.sacrifice_debt == 3
    service.lunch_event("offer", item.id, "confirmed")
    assert service.store.get(User, user.id).traits.sacrifice_debt == 3
