import asyncio
from datetime import date

from camp import batching, filters, synth
from camp.ai import schemas as S
from camp.ai.classify import MockClassifier
from camp.ai.feedback_parse import parse_feedback
from camp.ai.modifications import modify
from camp import feedback as fb
from camp.models import Batch, FeedbackEvent, LatLng, MenuItem, Restaurant, Restriction, User
from camp.pipeline import plan_home, plan_office
from camp.store import Store


def world(n=30, seed=1):
    store = Store()
    u, r, i = synth.make_world(n, 10, seed)
    store.put_many(u); store.put_many(r); store.put_many(i)
    return store


def test_allergen_filter_excludes_on_jev_warning_and_requires_verified_for_severe():
    u, r, items = synth.make_world(1, 12, 0)
    user = u[0]; user.restrictions = [Restriction(kind="allergen", value="peanut")]
    pad_thai = next(i for i in items if i.name == "Pad Thai")
    assert filters.passes_dietary(user, pad_thai)[0] is False
    safe = next(i for i in items if "peanut" not in i.ingredients and i.verified_allergens is None)
    assert filters.passes_dietary(user, safe)[0] is True
    user.restrictions[0].severe = True
    assert filters.passes_dietary(user, safe)[0] is False          # unverified → excluded for severe
    verified = next(i for i in items if i.verified_allergens is not None and "peanut" not in i.verified_allergens)
    assert filters.passes_dietary(user, verified)[0] is True


def test_office_batch_respects_budget_and_frozen_fee_on_alternatives():
    store = world()
    ctx = synth.make_context("lunch", date(2026, 9, 21))
    plan = plan_office(store, "hq", synth.OFFICE, ctx)
    assert plan.batch and plan.orders
    rests = {r.id: r for r in store.all(Restaurant)}
    items = {i.id: i for i in store.all(MenuItem)}
    share = {b.restaurant_id: b.fee_share_cents for b in plan.batch.restaurants}
    for o in plan.orders:
        u = store.get(User, o.user_id)
        assert o.total_cents <= u.budget("lunch")
        for alt in plan.recommendations[u.id][1:]:
            assert alt.restaurant_id in share
            assert filters.total_cost_cents(items[alt.item_id], rests[alt.restaurant_id], share[alt.restaurant_id]) <= u.budget("lunch")
    # every batch restaurant meets its minimum and capacity
    for b in plan.batch.restaurants:
        subtotal = sum(items[o.line.item_id].price_cents for o in plan.orders if o.line.restaurant_id == b.restaurant_id)
        assert subtotal >= rests[b.restaurant_id].fees.min_order_cents
        assert len(b.user_ids) <= rests[b.restaurant_id].max_meals_per_slot


def test_batching_stretches_budget():
    """An item that is over budget alone becomes affordable when the fee is shared."""
    store = world(40, 3)
    items = {i.id: i for i in store.all(MenuItem)}
    rests = {r.id: r for r in store.all(Restaurant)}
    plan = plan_office(store, "hq", synth.OFFICE, synth.make_context())
    stretched = [o for o in plan.orders if filters.total_cost_cents(items[o.line.item_id], rests[o.line.restaurant_id],
                 rests[o.line.restaurant_id].fees.delivery_fee_cents) > store.get(User, o.user_id).budget("lunch")]
    assert stretched, "expected at least one pick that only fits under a shared fee"


def test_home_order_uses_full_fee():
    store = world(5)
    u = store.all(User)[0]
    plan = plan_home(store, u, synth.OFFICE, synth.make_context("dinner"))
    assert plan.orders
    r = store.get(Restaurant, plan.orders[0].line.restaurant_id)
    assert plan.orders[0].fee_share_cents == r.fees.delivery_fee_cents


def test_repetition_penalty_rotates():
    store = world(20, 5)
    first = plan_office(store, "hq", synth.OFFICE, synth.make_context("lunch", date(2026, 9, 21)))
    for o in first.orders:            # only meals actually taken count as eaten
        o.status = "confirmed"
        store.put(o)
    second = plan_office(store, "hq", synth.OFFICE, synth.make_context("lunch", date(2026, 9, 22)))
    a = {o.user_id: o.line.item_id for o in first.orders}
    b = {o.user_id: o.line.item_id for o in second.orders}
    same = sum(1 for k in a if b.get(k) == a[k])
    assert same < len(a) * 0.5


def test_constraint_requires_confirmation_and_removal_never_inferred():
    store = world(3)
    u = store.all(User)[0]
    clf = MockClassifier(confidence=0.9)
    res = asyncio.run(parse_feedback(clf, "I'm allergic to shellfish", u.id))
    ev = res.events[0]
    assert ev.type == "constraint" and ev.needs_confirmation and res.clarify
    fb.apply_event(store, ev)
    u = store.get(User, u.id)
    assert any(r.value == "shellfish" and r.source == "nl_provisional" for r in u.restrictions)
    res = asyncio.run(parse_feedback(clf, "Turns out I'm not allergic to shellfish anymore", u.id))
    fb.apply_event(store, res.events[0])
    assert any(r.value == "shellfish" for r in store.get(User, u.id).restrictions)   # still there


def test_feedback_updates_profile():
    store = world(3)
    u = store.all(User)[0]
    ev = FeedbackEvent(user_id=u.id, type="preference", scope="ongoing", payload=dict(attribute="cuisine:thai", direction="never"), source="nl")
    fb.apply_event(store, ev)
    assert store.get(User, u.id).prefs.stated["cuisine:thai"] < -1
    ev = FeedbackEvent(user_id=u.id, type="meta", payload=dict(wants="pick_myself"))
    fb.apply_event(store, ev)
    assert store.get(User, u.id).suggest_only


def test_modification_pipeline_swaps_within_budget():
    store = world(20, 2)
    plan = plan_office(store, "hq", synth.OFFICE, synth.make_context())
    o = plan.orders[0]
    items = store.items_for(o.line.restaurant_id)
    other = next(i for i in items if i.id != o.line.item_id)
    res = asyncio.run(modify(MockClassifier(), store, o, f"swap to {other.name.lower()} no onions", 9 * 60))
    if res.ok:
        assert res.new_line.item_id == other.id and "no onions" in res.new_line.removed_ingredients
        assert res.total_cents <= store.get(User, o.user_id).budget("lunch")
    else:
        assert "budget" in res.message or "conflicts" in res.message
    late = asyncio.run(modify(MockClassifier(), store, o, "cancel", 23 * 60))
    assert not late.ok and "cutoff" in late.message


def test_exact_solver_not_worse_than_greedy_on_small_group():
    store = world(8, 7)
    users = {u.id: u for u in store.all(User)}
    rests = {r.id: r for r in store.all(Restaurant)}
    items = {i.id: i for i in store.all(MenuItem)}
    import random
    rng = random.Random(0)
    scores = {uid: {iid: rng.random() for iid in items} for uid in users}
    c = batching.Candidate(users, rests, items, scores, "lunch")
    _, g = batching.solve_greedy(c)
    ex = batching.solve_exact(c)
    assert ex is not None
    assert ex[1].objective >= g.objective - 0.5


def test_lunch_events_record_pick_and_update_profile():
    from camp.contracts import MealContext, OfficeRef
    from camp.offers import OfferService
    store = Store()
    svc = OfferService(store)
    ctx = MealContext(display_name="Harry", office=OfficeRef(latitude=42.36, longitude=-71.09), presence="inside", budget_cents=2000, now_minutes=600)
    offer = svc.offer(ctx)
    assert len(offer.options) == 3
    alt = offer.options[1]
    res = svc.lunch_event(offer.offer_id, alt.id, "confirmed")
    assert res["status"] == "confirmed" and res["events"][0]["type"] in ("change_item", "change_restaurant")
    order = store.orders_for(offer.user_id)[-1]
    assert order.line.item_id == alt.id and order.status == "confirmed"
    res = svc.lunch_event(offer.offer_id, None, "delivered", rating=4)
    assert res["events"][0]["type"] == "rating"
    u = store.get(User, offer.user_id)
    assert u.prefs.revealed.get(f"item:{alt.id}", 0) > 0
    assert svc.lunch_event("nope", None, "confirmed")["error"]
