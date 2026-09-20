"""Real restaurants around Ramp HQ (28 W 23rd St, New York). Public listing data collected 2026-09-19 from
menus, delivery apps and review sites; it is the offline stand-in for a live Uber/DoorDash catalog.

`load()` returns the validated dataset. `to_models()` turns it into Restaurant / MenuItem with deterministic tags
(`synth.tags_for`), optionally translated so the same neighbourhood geometry sits around another office."""
from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .filters import haversine_km
from .models import ALLERGENS, CUISINES, DISH_TYPES, PROTEINS, Batch, FeeSchedule, LatLng, LunchGroup, MenuItem, Order, Restaurant

RAMP_HQ = LatLng(lat=40.7424, lng=-73.9913)          # 28 W 23rd St, Flatiron
FIXTURES = Path(__file__).parent / "providers" / "fixtures"
DATASET = FIXTURES / "ramp_hq_restaurants.json"       # meal places (collected 2026-09-19)
CAFES = FIXTURES / "ramp_hq_cafes.json"               # coffee / tea / bakeries (collected 2026-09-20); optional until present
# Meal places from the restaurants file that also serve morning coffee and pastries.
COFFEE_TOO = {"maman-nomad", "ole-steen", "bourke-street-bakery-nomad", "caf-chelsea", "pret-a-manger", "breads-bakery",
              "daily-provisions-union-square", "sullivan-street-bakery-chelsea"}


class CatalogDish(BaseModel):
    id: str
    name: str
    description: str = ""
    price_cents: int
    price_estimated: bool = False
    ingredients: list[str] = Field(default_factory=list)
    dish_type: str = "other"
    protein: str = "none"
    spice: int = 0
    vegetarian: bool = False
    vegan: bool = False
    gluten_free: bool = False
    halal: Optional[bool] = None
    allergens: list[str] = Field(default_factory=list)
    popular: bool = False
    kcal: Optional[int] = None


class CatalogRestaurant(BaseModel):
    id: str
    name: str
    address: str = ""
    lat: float
    lng: float
    neighborhood: str = ""
    cuisine: str = "other"
    cuisine_detail: str = ""
    price_level: int = 2
    google_rating: Optional[float] = None
    google_reviews: Optional[int] = None
    yelp_rating: Optional[float] = None
    yelp_reviews: Optional[int] = None
    other_ratings: dict[str, float] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    hours: dict[str, str] = Field(default_factory=lambda: {"open": "11:00", "close": "22:00"})
    platforms: list[str] = Field(default_factory=lambda: ["uber", "doordash"])
    has_allergen_info: bool = False
    chain: bool = False
    distance_km: float = 0.0
    dishes: list[CatalogDish] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=lambda: ["meal"])   # "coffee" and/or "meal"

    @property
    def rating(self) -> Optional[float]:
        """Review-count-weighted blend on a 5-point scale: Google and Yelp by review count; other 5-point sources
        (Tripadvisor, Uber Eats, DoorDash, OpenTable, ...) at a nominal 50 reviews; Infatuation (0-10) halved at 20."""
        pairs = [(r, n or 50) for r, n in ((self.google_rating, self.google_reviews), (self.yelp_rating, self.yelp_reviews)) if r]
        for k, v in self.other_ratings.items():
            if k == "infatuation":
                pairs.append((v / 2, 20))
            elif 0 < v <= 5:
                pairs.append((v, 50))
        return round(sum(r * n for r, n in pairs) / sum(n for _, n in pairs), 2) if pairs else None

    @property
    def review_count(self) -> int:
        return (self.google_reviews or 0) + (self.yelp_reviews or 0)

    @property
    def open_minutes(self) -> tuple[int, int]:
        def hm(s: str) -> int:
            h, m = s.split(":")[:2]
            return int(h) * 60 + int(m)
        o, c = hm(self.hours.get("open", "11:00")), hm(self.hours.get("close", "22:00"))
        return o, (c if c > o else 23 * 60 + 59)      # "02:00" closes after midnight: treat as open all evening


@lru_cache(maxsize=1)
def load() -> list[CatalogRestaurant]:
    """Both fixture files, de-duplicated by id. Meal places that also do coffee get both categories."""
    rows: dict[str, CatalogRestaurant] = {}
    for path in (DATASET, CAFES):
        if not path.exists():
            continue
        for raw in json.loads(path.read_text()):
            r = CatalogRestaurant.model_validate(raw)
            if r.id in rows:
                continue
            cats = list(dict.fromkeys(c for c in r.categories if c in ("coffee", "meal")))
            if r.id in COFFEE_TOO or _looks_like_cafe(r):
                cats = list(dict.fromkeys(["coffee", *cats]))
            r.categories = cats or ["meal"]
            rows[r.id] = r
    return list(rows.values())


def _looks_like_cafe(r: CatalogRestaurant) -> bool:
    text = f"{r.name} {r.cuisine_detail}".lower()
    return r.cuisine == "bakery" and any(w in text for w in ("coffee", "café", "cafe", "espresso", "bakery", "pastry"))


def _hours_ok(r: CatalogRestaurant) -> bool:
    """Meal-only places must serve lunch; a café is in regardless of its hours (coffee orders run all day)."""
    if "coffee" in r.categories:
        return True
    o, c = r.open_minutes
    return o <= 12 * 60 + 30 and c >= 13 * 60          # serves lunch


def translate(loc: LatLng, center: LatLng | None) -> LatLng:
    """Keep the real geometry, but re-centre it on another office when the app's office is not Ramp HQ."""
    if center is None:
        return loc
    return LatLng(lat=loc.lat - RAMP_HQ.lat + center.lat, lng=loc.lng - RAMP_HQ.lng + center.lng)


def ensure_current(store, center: LatLng | None = None, seed: int = 0) -> bool:
    """Fill missing fixture records without overwriting stored quotes, tags, or order history."""
    want, items = to_models(seed=seed, center=center)
    have = store.all(Restaurant)
    have_by_id = {r.id: r for r in have}
    have_items = {i.id for i in store.all(MenuItem)}
    protected = {line.restaurant_id for order in store.all(Order) for line in (order.line, order.default_line)}
    protected.update(br.restaurant_id for batch in store.all(Batch) for br in batch.restaurants)
    protected.update(group.restaurant_id for group in store.all(LunchGroup))
    want_ids = {r.id for r in want}
    changed = False
    for r in have:
        if r.id not in want_ids and r.platform == "mock" and not r.platform_ids and r.id not in protected:
            for item in store.items_for(r.id):
                store.delete(MenuItem, item.id)
            store.delete(Restaurant, r.id)
            changed = True
    updates = []
    for r in want:
        previous = have_by_id.get(r.id)
        if previous is None:
            updates.append(r)
        elif center is not None and haversine_km(previous.location, center) > 8:
            previous.location = r.location
            updates.append(previous)
    missing = [item for item in items if item.id not in have_items]
    if updates or missing:
        store.put_many([*updates, *missing])
        changed = True
    return changed


def to_models(n: int | None = None, seed: int = 0, center: LatLng | None = None, lunch_only: bool = True,
              tagger=None) -> tuple[list[Restaurant], list[MenuItem]]:
    """Restaurant/MenuItem for the recommender. Fees, ETA and reliability are not public data, so they are drawn
    deterministically from `seed` (real quotes come from the provider layer at sync time)."""
    from .synth import tags_for
    rng = random.Random(seed)
    rows = [r for r in load() if r.dishes and (not lunch_only or _hours_ok(r))]
    rows.sort(key=lambda r: r.distance_km)
    if n is not None:
        # Small worlds (tests, `camp synth`) are meal worlds: `n` counts the nearest meal places and cafés stay out,
        # so the batching solver is exercised on lunches rather than on a latte-and-croissant "group order".
        rows = [r for r in rows if "coffee" not in r.categories][:n]
    restaurants, items = [], []
    for c in rows:
        rr = random.Random(f"{seed}:{c.id}")
        eta = 15 + int(c.distance_km * 6) + rr.randint(0, 10)
        r = Restaurant(id=f"r_{c.id}", name=c.name, cuisine=c.cuisine if c.cuisine in CUISINES else "american",
                       location=translate(LatLng(lat=c.lat, lng=c.lng), center),
                       fees=FeeSchedule(delivery_fee_cents=rr.choice([299, 399, 499, 599, 699]), min_order_cents=rr.choice([1000, 1500, 2000])),
                       eta_mean_minutes=eta, eta_std_minutes=rr.randint(3, 10),
                       max_meals_per_slot=rr.choice([15, 30, 60]) if not c.chain else 60,
                       reliability=round(min(0.98, 0.72 + 0.05 * ((c.rating or 4.0) - 3.5) * 2 + rr.uniform(-0.03, 0.03)), 2),
                       verified_allergen_data=c.has_allergen_info, open_minutes=c.open_minutes,
                       address=c.address, neighborhood=c.neighborhood, cuisine_detail=c.cuisine_detail, price_level=c.price_level,
                       rating=c.rating, review_count=c.review_count,
                       ratings={k: v for k, v in (("google", c.google_rating), ("yelp", c.yelp_rating), *c.other_ratings.items()) if v},
                       recommendations=c.recommendations, chain=c.chain, categories=list(c.categories),
                       platform=c.platforms[0] if c.platforms else "mock",
                       platform_ids={p: f"{p}-{c.id}" for p in c.platforms})
        restaurants.append(r)
        for d in c.dishes:
            dish_type = d.dish_type if d.dish_type in DISH_TYPES else "other"
            protein = d.protein if d.protein in PROTEINS else "none"
            allergens = [a for a in d.allergens if a in ALLERGENS]
            diets = {k for k, on in (("vegetarian", d.vegetarian or d.vegan), ("vegan", d.vegan), ("gluten_free", d.gluten_free), ("halal", bool(d.halal))) if on}
            tags = tags_for(d.ingredients, dish_type, d.spice, r.cuisine, rng, protein=protein, allergens=allergens,
                            vegetarian=d.vegetarian or d.vegan, vegan=d.vegan, kcal=d.kcal)
            items.append(MenuItem(id=f"i_{c.id}_{d.id}", restaurant_id=r.id, name=d.name, description=d.description, ingredients=d.ingredients,
                                  price_cents=d.price_cents, modifiers=["no onions", "extra sauce", "add drink", "add side"],
                                  modifier_prices={"no onions": 0, "extra sauce": 100, "add drink": 300, "add side": 450},
                                  platform=r.platform, external_id=f"{r.platform}-{c.id}-{d.id}",
                                  verified_allergens=set(allergens) if c.has_allergen_info else None, verified_diets=diets if c.has_allergen_info else set(),
                                  popular=d.popular, kcal=d.kcal, tags=tags))
    return restaurants, items
