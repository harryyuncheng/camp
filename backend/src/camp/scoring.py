"""Per-user scoring (§3), v1 heuristic weights. Deliverable 2.

s(u,i,c) = w_a·aff + ε_u·nov + w_h·health + w_c·ctx − w_r·rep  (+ learned term, 0 in v1)
No price term.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .models import Context, MenuItem, Order, Restaurant, User

# v1 hand-set weights. Flagged for tuning; v2 replaces with a learned ranker.
W_AFF, W_NOV, W_HEALTH, W_CTX, W_REP = 1.0, 0.6, 0.4, 0.3, 0.8
GAMMA = 0.85          # daily decay for repetition and feedback
ALPHA = 0.5           # blend of P(keep) vs E[enjoy] once learned (v2)


# ---------------------------------------------------------------- item vectors

def item_attributes(item: MenuItem, r: Restaurant) -> dict[str, float]:
    """Sparse attribute vector: Jev tags + bag of ingredients/description words."""
    a: dict[str, float] = {f"restaurant:{r.id}": 1.0, f"item:{item.id}": 1.0}
    t = item.tags
    a[f"cuisine:{(t.cuisine if t else None) or r.cuisine}"] = 1.0
    if t:
        if t.protein:
            a[f"protein:{t.protein}"] = 1.0
        if t.dish_type:
            a[f"dish:{t.dish_type}"] = 1.0
        a["spice"] = t.spice / 4
        a["heaviness"] = t.heaviness / 4
        a["warm"] = t.warm / 4
        a["travels_well"] = t.travels_well
    for ing in item.ingredients:
        a[f"ingredient:{ing.lower()}"] = 1.0
    for w in item.description.lower().replace(",", " ").split():
        if len(w) > 3:
            a[f"word:{w}"] = 0.3
    return a


def affinity(u: User, attrs: dict[str, float]) -> float:
    """Dot product of item attributes with the user's stated + revealed weights, scaled to ~[-1,1]."""
    prefs = {}
    for k, v in u.prefs.stated.items():
        prefs[k] = prefs.get(k, 0) + v
    for k, v in u.prefs.revealed.items():
        prefs[k] = prefs.get(k, 0) + v
    if not prefs:
        return 0.0
    dot = sum(attrs.get(k, 0.0) * v for k, v in prefs.items())
    return math.tanh(dot)


# ---------------------------------------------------------------- history-derived signals

@dataclass
class History:
    item_last_seen: dict[str, int]        # item_id -> days ago
    cuisine_last_seen: dict[str, int]
    cuisines_eaten: Counter
    items_eaten: set[str]

    @classmethod
    def from_orders(cls, orders: list[Order], items: dict[str, MenuItem], restaurants: dict[str, Restaurant],
                    today_ordinal: int) -> "History":
        from datetime import date
        il, cl, ce, ie = {}, {}, Counter(), set()
        for o in orders:
            if o.status in ("cancelled", "proposed"):   # only meals that were actually taken count as eaten
                continue
            days = today_ordinal - date.fromisoformat(o.date).toordinal()
            it = items.get(o.line.item_id)
            if not it:
                continue
            cuisine = (it.tags.cuisine if it.tags and it.tags.cuisine else restaurants[it.restaurant_id].cuisine)
            il[it.id] = min(days, il.get(it.id, 10**6))
            cl[cuisine] = min(days, cl.get(cuisine, 10**6))
            ce[cuisine] += 1
            ie.add(it.id)
        return cls(il, cl, ce, ie)

    def entropy(self) -> float:
        n = sum(self.cuisines_eaten.values())
        if n == 0:
            return 0.0
        return -sum((c / n) * math.log(c / n) for c in self.cuisines_eaten.values())


def novelty(h: History, item: MenuItem, cuisine: str) -> float:
    if item.id in h.items_eaten:
        return 0.0
    return 1.0 if cuisine not in h.cuisines_eaten else 0.4


def repetition(h: History, item: MenuItem, cuisine: str) -> float:
    pen = 0.0
    if item.id in h.item_last_seen:
        pen += GAMMA ** h.item_last_seen[item.id]
    if cuisine in h.cuisine_last_seen:
        pen += 0.5 * GAMMA ** h.cuisine_last_seen[cuisine]
    return pen


def health(u: User, item: MenuItem, remaining_kcal_today: int | None = None) -> float:
    t = item.tags
    if not t or not t.kcal_band:
        return 0.0
    target = remaining_kcal_today if remaining_kcal_today is not None else u.health.kcal_per_meal
    kcal_fit = -abs(t.kcal_band.midpoint - target) / 500.0
    protein_bonus = 0.3 if (t.protein_band and t.protein_band.midpoint >= u.health.protein_g_per_meal) else 0.0
    return kcal_fit + protein_bonus


def context_fit(item: MenuItem, ctx: Context, where: str) -> float:
    t = item.tags
    if not t:
        return 0.0
    s = 0.0
    warm = t.warm / 4
    if ctx.temp_c < 12 or ctx.raining:
        s += 0.5 * warm
    elif ctx.temp_c > 26:
        s += 0.5 * (1 - warm) + 0.3 * (1 - t.heaviness / 4)
    if ctx.weekday == 4 and ctx.meal == "lunch":     # Friday lunch: a little indulgence
        s += 0.1 * t.heaviness / 4
    if where == "home":
        s += 0.6 * t.travels_well
    else:
        s += 0.2 * t.travels_well
    # temporary NL context ("something light today") lives in ctx.temporary_prefs
    for k, v in ctx.temporary_prefs.items():
        if k == "heaviness":
            s += v * (t.heaviness / 4)
        elif k == "spice":
            s += v * (t.spice / 4)
    return s


def exploration_noise(u: User, item: MenuItem, ctx: Context) -> float:
    """Deterministic jitter in [-1, 1] keyed by (request nonce, user, item): the same request ranks the same way,
    a refreshed request reshuffles near-ties so people see different options instead of the same three."""
    if ctx.exploration <= 0:
        return 0.0
    h = hashlib.blake2b(f"{ctx.nonce}|{u.id}|{item.id}".encode(), digest_size=8).digest()
    return (int.from_bytes(h, "big") / 2**64) * 2 - 1


def learned_term(u: User, item: MenuItem, ctx: Context) -> float:
    """α·P(keep) + (1−α)·E[enjoy]. v1: no trained models, returns 0. Interface kept for v2."""
    return 0.0


# ---------------------------------------------------------------- scorer

def score(u: User, item: MenuItem, r: Restaurant, ctx: Context, h: History, where: str,
          remaining_kcal_today: int | None = None) -> tuple[float, dict[str, float]]:
    attrs = item_attributes(item, r)
    cuisine = (item.tags.cuisine if item.tags and item.tags.cuisine else r.cuisine)
    eps = u.traits.epsilon
    comps = {
        "affinity": W_AFF * affinity(u, attrs),
        "novelty": W_NOV * eps * novelty(h, item, cuisine),
        "health": W_HEALTH * u.traits.w_health * health(u, item, remaining_kcal_today),
        "context": W_CTX * context_fit(item, ctx, where),
        "repetition": -W_REP * (1 - 0.5 * (1 - eps)) * repetition(h, item, cuisine),
        "learned": learned_term(u, item, ctx),
        "reliability": 0.2 * (r.reliability - 0.9),
        "rating": 0.15 * ((r.rating or 4.2) - 4.2) + (0.05 if item.popular else 0.0),
        "exploration": ctx.exploration * exploration_noise(u, item, ctx),
    }
    return sum(comps.values()), comps


def rank(u: User, items: list[MenuItem], restaurants: dict[str, Restaurant], ctx: Context, h: History,
         where: str) -> list[tuple[MenuItem, float, dict[str, float]]]:
    out = [(i, *score(u, i, restaurants[i.restaurant_id], ctx, h, where)) for i in items]
    out.sort(key=lambda t: -t[1])
    return out
