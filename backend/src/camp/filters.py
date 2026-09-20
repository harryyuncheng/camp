"""Hard filters (§2). Never traded off against score. Deliverable 2.

`feasible(...)` returns the set of (user, item) pairs that pass every filter, plus a
per-user reason log so the UI can say "nothing fits" honestly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from .models import ALLERGENS, DIETS, Context, LatLng, LocationKind, MenuItem, Restaurant, Restriction, User

ALLERGEN_WARN_THRESHOLD = 0.10   # §7.3: exclude if P(contains) > ~0.1
BUFFER_BASE_MIN = 5
BUFFER_K = 1.5


def haversine_km(a: LatLng, b: LatLng) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def eta_buffer_minutes(r: Restaurant) -> float:
    """t_buffer from ETA variance and reliability."""
    return BUFFER_BASE_MIN + BUFFER_K * r.eta_std_minutes * (1.0 - r.reliability)


# ---------------------------------------------------------------- individual filters

def passes_dietary(u: User, item: MenuItem) -> tuple[bool, str]:
    return passes_restrictions(u.restrictions, item)


def passes_restrictions(restrictions: list[Restriction], item: MenuItem) -> tuple[bool, str]:
    tags = item.tags
    for rst in restrictions:
        if rst.value not in (ALLERGENS if rst.kind == "allergen" else DIETS):
            return False, f"{rst.kind}:{rst.value}:unsupported"
        if rst.kind == "allergen":
            a = rst.value
            # Jev tag may only EXCLUDE
            if tags and tags.allergen_p.get(a, 0.0) > ALLERGEN_WARN_THRESHOLD:
                return False, f"allergen:{a}:jev_warning"
            if item.verified_allergens is not None:
                if a in item.verified_allergens:
                    return False, f"allergen:{a}:verified"
            elif rst.severe:
                # severe allergy: only include with restaurant-verified data
                return False, f"allergen:{a}:unverified"
            elif tags is None or tags.needs_review or tags.confidence < 0.60 or a not in tags.allergen_p:
                return False, f"allergen:{a}:unknown"
        else:  # diet
            d = rst.value
            excluded = {"gluten_free": {"gluten"}, "dairy_free": {"dairy"}, "vegan": {"dairy", "egg", "fish", "shellfish"},
                        "vegetarian": {"fish", "shellfish"}}.get(d, set())
            if excluded & (item.verified_allergens or set()) or any(
                    tags and tags.allergen_p.get(a, 0.0) > ALLERGEN_WARN_THRESHOLD for a in excluded):
                return False, f"diet:{d}:allergen_conflict"
            if d in item.verified_diets:
                continue
            trusted_tags = tags is not None and not tags.needs_review and tags.confidence >= 0.60
            p = {"vegetarian": tags.vegetarian if trusted_tags else 0,
                 "vegan": tags.vegan if trusted_tags else 0,
                 "halal": tags.halal if trusted_tags else 0}.get(d)
            if p is None:  # kosher / gluten_free / dairy_free: need verified data or allergen tag
                if d in ("gluten_free", "dairy_free") and item.verified_allergens is not None:
                    continue
                return False, f"diet:{d}:unverified"
            if p < 0.9:
                return False, f"diet:{d}:p={p:.2f}"
    return True, ""


def passes_location(u: User, r: Restaurant, where: LocationKind, office_loc: LatLng) -> tuple[bool, str]:
    target = office_loc if where == "office" else u.home
    d = haversine_km(r.location, target)
    return (d <= r.delivery_radius_km), f"distance:{d:.1f}km"


def passes_time(u: User, r: Restaurant, ctx: Context, n_items_at_restaurant: int = 1) -> tuple[bool, str]:
    w = u.windows[ctx.meal]
    if w.end - w.start < w.min_eat_minutes or w.min_eat_minutes <= 0:
        return False, "window:insufficient_eating_time"
    # pre-orders are allowed: prep starts at the later of order time and opening time
    prep_start = max(ctx.order_time_minutes, r.open_minutes[0])
    if prep_start >= r.open_minutes[1]:
        return False, "closed"
    arrival = prep_start + r.prep_minutes(n_items_at_restaurant) + r.eta_mean_minutes + eta_buffer_minutes(r)
    if arrival > w.start and arrival + w.min_eat_minutes > w.end:
        return False, f"arrival:{arrival:.0f}>window"
    if arrival > w.start:  # allowed: arrives late but still time to eat
        return True, "late_ok"
    return True, ""


def total_cost_cents(item: MenuItem, r: Restaurant, fee_share_cents: int) -> int:
    return item.price_cents + r.fees.per_item_overhead(item.price_cents) + fee_share_cents


def passes_budget(u: User, item: MenuItem, r: Restaurant, meal: str, fee_share_cents: int) -> tuple[bool, str]:
    c = total_cost_cents(item, r, fee_share_cents)
    return c <= u.budget(meal), f"cost:{c}>budget:{u.budget(meal)}"


# ---------------------------------------------------------------- combined

@dataclass
class Feasibility:
    pairs: dict[str, list[MenuItem]] = field(default_factory=dict)          # user_id -> items
    reasons: dict[str, dict[str, str]] = field(default_factory=dict)         # user_id -> item_id -> reason
    suggest_only: set[str] = field(default_factory=set)                      # users we must not auto-order for

    def items_for(self, user_id: str) -> list[MenuItem]:
        return self.pairs.get(user_id, [])


def feasible(users: list[User], restaurants: dict[str, Restaurant], items: list[MenuItem],
             ctx: Context, office_loc: LatLng, where_for: Callable[[User], LocationKind],
             fee_share_for: Callable[[User, Restaurant], int]) -> Feasibility:
    """fee_share_for decides how much delivery fee the user bears. Home: full fee. Office: depends on
    the batch, so the optimizer passes a closure and re-runs the budget check as n_r changes."""
    out = Feasibility()
    for u in users:
        where = where_for(u)
        ok_items: list[MenuItem] = []
        reasons: dict[str, str] = {}
        for item in items:
            r = restaurants[item.restaurant_id]
            for check, why in (passes_dietary(u, item),
                               passes_location(u, r, where, office_loc),
                               passes_time(u, r, ctx),
                               passes_budget(u, item, r, ctx.meal, fee_share_for(u, r))):
                if not check:
                    reasons[item.id] = why
                    break
            else:
                ok_items.append(item)
        out.pairs[u.id] = ok_items
        out.reasons[u.id] = reasons
        if u.suggest_only or u.traits.autonomy > 0.8:
            out.suggest_only.add(u.id)
        elif u.has_severe_allergy() and not ok_items:
            out.suggest_only.add(u.id)
    return out
