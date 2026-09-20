"""End-to-end recommendation pipeline: filters → scoring → (batch | argmax) → presentation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date

from . import batching, filters, scoring
from .models import Batch, Context, LatLng, LocationKind, MenuItem, Order, OrderLine, Recommendation, Restaurant, User
from .store import Store


@dataclass
class MealPlan:
    batch: Batch | None
    orders: list[Order]
    recommendations: dict[str, list[Recommendation]]   # uid -> [default, alt1, alt2]
    suggest_only: set[str]
    unassigned: list[str]
    solver: str = "n/a"


def _history(store: Store, u: User, items: dict[str, MenuItem], rests: dict[str, Restaurant], ctx: Context) -> scoring.History:
    return scoring.History.from_orders(store.orders_for(u.id), items, rests, _date.fromisoformat(ctx.date).toordinal())


def _remaining_kcal(store: Store, u: User, ctx: Context, items: dict[str, MenuItem]) -> int | None:
    """Daily carry-over: a heavy lunch shifts the dinner target (§3 health)."""
    if ctx.meal != "dinner":
        return None
    lunch = [o for o in store.orders_for(u.id) if o.date == ctx.date and o.meal == "lunch" and o.status == "confirmed"]
    if not lunch:
        return None
    meals = [items.get(o.line.item_id) for o in lunch]
    if any(not it or (it.kcal is None and (not it.tags or not it.tags.kcal_band)) for it in meals):
        return None
    daily = 2 * u.health.kcal_per_meal
    consumed = sum(it.kcal if it.kcal is not None else it.tags.kcal_band.midpoint for it in meals)
    return max(300, daily - consumed)


def _rec(u: User, it: MenuItem, s: float, br: dict[str, float], h: scoring.History, rests: dict[str, Restaurant]) -> Recommendation:
    cuisine = (it.tags.cuisine if it.tags and it.tags.cuisine else rests[it.restaurant_id].cuisine)
    return Recommendation(user_id=u.id, item_id=it.id, restaurant_id=it.restaurant_id, score=s, breakdown=br,
                          novel=scoring.novelty(h, it, cuisine) > 0)


def plan_office(store: Store, office_id: str, office_loc: LatLng, ctx: Context, live_location: dict[str, LocationKind] | None = None) -> MealPlan:
    users = [u for u in store.users_in_office(office_id)
             if u.location_for(ctx.weekday, ctx.meal, (live_location or {}).get(u.id)) == "office"]
    rests = {r.id: r for r in store.all(Restaurant) if "meal" in r.categories}      # coffee-only places never make a meal offer
    items_all = [i for i in store.all(MenuItem) if i.restaurant_id in rests]
    items = {i.id: i for i in items_all}
    # non-budget filters first (fee share 0 = most permissive); the optimizer re-checks budget per fee share
    feas = filters.feasible(users, rests, items_all, ctx, office_loc, lambda u: "office", lambda u, r: 0)
    scores: dict[str, dict[str, float]] = {}
    breakdowns: dict[str, dict[str, tuple[float, dict]]] = {}
    hist: dict[str, scoring.History] = {}
    for u in users:
        h = _history(store, u, items, rests, ctx)
        hist[u.id] = h
        rk = u.id
        scores[rk], breakdowns[rk] = {}, {}
        for it in feas.items_for(u.id):
            s, br = scoring.score(u, it, rests[it.restaurant_id], ctx, h, "office", _remaining_kcal(store, u, ctx, items))
            scores[rk][it.id] = s
            breakdowns[rk][it.id] = (s, br)
    batch_users = {u.id: u for u in users if u.id not in feas.suggest_only}
    cand = batching.Candidate(users=batch_users, restaurants=rests, items=items,
                              scores={k: v for k, v in scores.items() if k in batch_users}, meal=ctx.meal)
    while True:
        R, a, solver = batching.solve(cand)
        late = [(uid, rid) for uid, (rid, _) in a.assign.items()
                if not filters.passes_time(batch_users[uid], rests[rid], ctx, a.n[rid])[0]]
        if not late:
            break
        for uid, rid in late:
            cand.scores[uid] = {iid: s for iid, s in cand.scores[uid].items() if items[iid].restaurant_id != rid}
    batch = batching.to_batch(cand, R, a, office_id, ctx.date)
    share = {br.restaurant_id: br.fee_share_cents for br in batch.restaurants}

    recs: dict[str, list[Recommendation]] = {}
    orders: list[Order] = []
    for u in users:
        if u.id in feas.suggest_only or u.id not in a.assign:
            # suggest-only or stranded: show global top 3, no auto-order
            top = [(iid, sb) for iid, sb in sorted(breakdowns[u.id].items(), key=lambda kv: -kv[1][0])
                   if filters.passes_budget(u, items[iid], rests[items[iid].restaurant_id], ctx.meal,
                                            share.get(items[iid].restaurant_id, rests[items[iid].restaurant_id].fees.delivery_fee_cents))[0]
                   and filters.passes_time(u, rests[items[iid].restaurant_id], ctx, a.n.get(items[iid].restaurant_id, 0) + 1)[0]][:3]
            recs[u.id] = [_rec(u, items[iid], s, br, hist[u.id], rests) for iid, (s, br) in top]
            continue
        rid, iid = a.assign[u.id]
        default = _rec(u, items[iid], *breakdowns[u.id][iid], hist[u.id], rests)
        # alternatives: from batch restaurants, budget-safe under the FROZEN fee share
        alts = []
        for iid2, (s, br) in sorted(breakdowns[u.id].items(), key=lambda kv: -kv[1][0]):
            it2 = items[iid2]
            if iid2 == iid or it2.restaurant_id not in share:
                continue
            if filters.total_cost_cents(it2, rests[it2.restaurant_id], share[it2.restaurant_id]) > u.budget(ctx.meal):
                continue
            if not filters.passes_time(u, rests[it2.restaurant_id], ctx, a.n[it2.restaurant_id] + (it2.restaurant_id != rid))[0]:
                continue
            alts.append(_rec(u, it2, s, br, hist[u.id], rests))
            if len(alts) == 2:
                break
        recs[u.id] = [default] + alts
        line = OrderLine(item_id=iid, restaurant_id=rid, price_cents=items[iid].price_cents)
        orders.append(Order(user_id=u.id, date=ctx.date, meal=ctx.meal, location="office", line=line, default_line=line,
                            shown_item_ids=[r.item_id for r in recs[u.id]], fee_share_cents=share[rid],
                            total_cents=filters.total_cost_cents(items[iid], rests[rid], share[rid]),
                            batch_id=batch.id, novel=default.novel))
    store.put(batch)
    store.put_many(orders)
    unassigned = [u.id for u in users if u.id not in a.assign and u.id not in feas.suggest_only]
    return MealPlan(batch=batch, orders=orders, recommendations=recs, suggest_only=feas.suggest_only, unassigned=unassigned, solver=solver)


def plan_home(store: Store, u: User, office_loc: LatLng, ctx: Context) -> MealPlan:
    """Home orders skip the optimizer: argmax over the feasible set with the full delivery fee."""
    rests = {r.id: r for r in store.all(Restaurant) if "meal" in r.categories}      # coffee-only places never make a meal offer
    items_all = [i for i in store.all(MenuItem) if i.restaurant_id in rests]
    items = {i.id: i for i in items_all}
    feas = filters.feasible([u], rests, items_all, ctx, office_loc, lambda _: "home", lambda _, r: r.fees.delivery_fee_cents)
    h = _history(store, u, items, rests, ctx)
    ranked = scoring.rank(u, feas.items_for(u.id), rests, ctx, h, "home")
    recs = [_rec(u, it, s, br, h, rests) for it, s, br in ranked[:3]]
    orders = []
    if recs and u.id not in feas.suggest_only:
        it = items[recs[0].item_id]
        r = rests[it.restaurant_id]
        line = OrderLine(item_id=it.id, restaurant_id=r.id, price_cents=it.price_cents)
        orders.append(Order(user_id=u.id, date=ctx.date, meal=ctx.meal, location="home", line=line, default_line=line,
                            shown_item_ids=[x.item_id for x in recs], fee_share_cents=r.fees.delivery_fee_cents,
                            total_cents=filters.total_cost_cents(it, r, r.fees.delivery_fee_cents), novel=recs[0].novel))
        store.put_many(orders)
    return MealPlan(batch=None, orders=orders, recommendations={u.id: recs}, suggest_only=feas.suggest_only,
                    unassigned=[] if recs else [u.id])
