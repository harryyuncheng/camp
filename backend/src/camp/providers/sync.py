"""Catalog sync: providers → normalized DTOs → de-dupe across platforms → Restaurant/MenuItem → (optional) Jev tagging.

De-dupe rule: same normalized name AND within 150 m → one Restaurant with platform_ids for both. The platform with
the cheaper (fee + $ per ETA-minute) quote becomes the primary `platform`; its menu is used.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from ..filters import haversine_km
from ..models import ALLERGENS, FeeSchedule, LatLng, MenuItem, Restaurant
from ..store import Store
from .base import MenuProvider, NotConfigured, PItem, PQuote, PStore

DIET_MAP = {"vegetarian": "vegetarian", "vegan": "vegan", "halal": "halal", "kosher": "kosher", "gluten_free": "gluten_free",
            "gluten-free": "gluten_free", "dairy_free": "dairy_free", "dairy-free": "dairy_free"}
ALLERGEN_MAP = {"peanuts": "peanut", "tree nuts": "tree_nut", "tree_nuts": "tree_nut", "nuts": "tree_nut", "milk": "dairy",
                "wheat": "gluten", "eggs": "egg", "crustacean": "shellfish", "sesame seeds": "sesame"}


@dataclass
class SyncReport:
    stores_seen: dict[str, int] = field(default_factory=dict)
    restaurants: int = 0
    items: int = 0
    merged: int = 0
    skipped_providers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _quote_cost(q: PQuote) -> float:
    return q.delivery_fee_cents + 15 * q.eta_mean_minutes    # $0.15 per minute of ETA as a tiebreak


async def _fetch(p: MenuProvider, near: LatLng, radius_km: float, rep: SyncReport) -> list[tuple[PStore, list[PItem], PQuote]]:
    try:
        stores = await p.search_stores(near, radius_km)
    except NotConfigured as e:
        rep.skipped_providers.append(f"{p.name}: {e}")
        return []
    rep.stores_seen[p.name] = len(stores)

    async def one(s: PStore):
        try:
            menu, q = await asyncio.gather(p.get_menu(s.external_id), p.quote(s.external_id, near))
            return s, menu, q
        except Exception as e:   # one bad store must not kill the sync
            rep.errors.append(f"{p.name}/{s.external_id}: {e}")
            return None
    res = await asyncio.gather(*(one(s) for s in stores))
    return [r for r in res if r]


def _to_models(s: PStore, menu: list[PItem], q: PQuote, existing: Restaurant | None) -> tuple[Restaurant, list[MenuItem]]:
    r = existing or Restaurant(name=s.name, cuisine=s.cuisine, location=s.location)
    r.name, r.cuisine, r.location, r.platform = s.name, s.cuisine, s.location, s.platform
    r.platform_ids[s.platform] = s.external_id
    r.open_minutes, r.delivery_radius_km = s.open_minutes, s.delivery_radius_km
    r.verified_allergen_data = s.has_verified_allergen_data or any(i.allergens is not None for i in menu)
    r.fees = FeeSchedule(delivery_fee_cents=q.delivery_fee_cents, service_fee_pct=q.service_fee_pct, tax_pct=q.tax_pct,
                         min_order_cents=s.min_order_cents or 1500)
    r.eta_mean_minutes, r.eta_std_minutes = q.eta_mean_minutes, q.eta_std_minutes
    items = []
    for it in menu:
        if not it.available or it.price_cents <= 0:
            continue
        allergens = None if it.allergens is None else {ALLERGEN_MAP.get(a, a) for a in it.allergens if ALLERGEN_MAP.get(a, a) in ALLERGENS}
        items.append(MenuItem(restaurant_id=r.id, name=it.name, description=it.description, ingredients=it.ingredients, price_cents=it.price_cents,
                              modifiers=[m.name for m in it.modifiers], modifier_prices={m.name: m.price_cents for m in it.modifiers},
                              verified_allergens=allergens, verified_diets={DIET_MAP[d] for d in it.diets if d in DIET_MAP},
                              platform=s.platform, external_id=it.external_id))
    return r, items


async def sync_catalog(store: Store, providers: list[MenuProvider], near: LatLng, radius_km: float = 6.0,
                       tagger=None, keep_existing_tags: bool = True) -> SyncReport:
    rep = SyncReport()
    fetched = []
    for p in providers:
        fetched += await _fetch(p, near, radius_km, rep)
    # de-dupe across platforms
    groups: list[list[tuple[PStore, list[PItem], PQuote]]] = []
    for f in fetched:
        for g in groups:
            s0 = g[0][0]
            if _norm(s0.name) == _norm(f[0].name) and haversine_km(s0.location, f[0].location) < 0.15:
                g.append(f); break
        else:
            groups.append([f])
    old_items = {(i.platform, i.external_id): i for i in store.all(MenuItem)}
    old_rest = {}
    for r in store.all(Restaurant):
        for plat, ext in r.platform_ids.items():
            old_rest[(plat, ext)] = r
    new_rest, new_items = [], []
    for g in groups:
        if len(g) > 1:
            rep.merged += len(g) - 1
        g.sort(key=lambda t: _quote_cost(t[2]))
        s, menu, q = g[0]
        existing = next((old_rest[(x[0].platform, x[0].external_id)] for x in g if (x[0].platform, x[0].external_id) in old_rest), None)
        r, items = _to_models(s, menu, q, existing)
        for x in g[1:]:
            r.platform_ids[x[0].platform] = x[0].external_id
        for it in items:
            prev = old_items.get((it.platform, it.external_id))
            if prev and keep_existing_tags:
                it.id, it.tags = prev.id, prev.tags
        new_rest.append(r); new_items += items
    if tagger:
        untagged = [i for i in new_items if i.tags is None]
        if untagged:
            await tagger(untagged)
    store.put_many(new_rest); store.put_many(new_items)
    rep.restaurants, rep.items = len(new_rest), len(new_items)
    return rep


def providers_from_env() -> list[MenuProvider]:
    """Real adapters when their env vars exist, otherwise one mock per platform."""
    from .doordash import DoorDashProvider
    from .mock import MockProvider
    from .uber import UberEatsProvider
    out: list[MenuProvider] = []
    u, d = UberEatsProvider(), DoorDashProvider()
    out.append(u if u.configured() else MockProvider("uber"))
    out.append(d if d.configured() else MockProvider("doordash", seed=1))
    return out
