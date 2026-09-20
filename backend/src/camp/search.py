"""Craving search: "I want tacos" → places in the catalog that actually serve it.

The sentence is turned into typed search terms by OpenAI (`ai/craving.py`), and everything after that is
deterministic: menu items are matched and scored here, so the model never invents a restaurant, a dish or a
price. It is the escape hatch for the Today page when none of the offered groups or meals appeal.
"""
from __future__ import annotations

from typing import Optional

from . import filters
from .ai.craving import CravingQuery, parse_craving
from .contracts import Wire
from .groups import GroupOptionWire, RestaurantWire, cuisine_label, is_drink, shrunk_rating, symbol_for
from .models import MenuItem, OrderCategory, Restaurant, User

NAME_HIT, TEXT_HIT = 3.0, 1.2          # a keyword in the dish name counts for more than in its description
CUISINE_HIT, DISH_TYPE_HIT = 2.5, 2.0
MIN_SCORE = 1.0                        # below this a dish is not a real answer to what they asked for


class CravingReq(Wire):
    text: str
    category: Optional[OrderCategory] = None
    user_id: Optional[str] = None
    limit: int = 3
    options_per_place: int = 3


class CravingMatchWire(Wire):
    restaurant: RestaurantWire         # options are the dishes that matched, best first
    reason: str
    score: float


class CravingResponse(Wire):
    text: str                          # what the user typed
    summary: str                       # the craving in a few words, as the model read it
    interpretation: str                # human-readable search terms ("Mexican · taco · al pastor")
    backend: str                       # "llm" (OpenAI) or "keywords" (offline reader)
    matches: list[CravingMatchWire]
    note: str = ""


def _interpretation(q: CravingQuery) -> str:
    parts: list[str] = []
    if q.cuisine != "any":
        parts.append(q.cuisine.replace("_", " ").title())
    if q.dish_type != "any":
        parts.append(q.dish_type)
    parts += [k for k in q.keywords if k not in parts]
    parts += [f"no {a}" for a in q.avoid]
    parts += [d for d, on in (("vegetarian", q.vegetarian), ("vegan", q.vegan), ("gluten-free", q.gluten_free), ("spicy", q.spicy)) if on]
    if q.max_price_cents:
        parts.append(f"under ${q.max_price_cents // 100}")
    return " · ".join(parts)


class CravingService:
    def __init__(self, store):
        self.store = store

    async def search(self, req: CravingReq) -> CravingResponse:
        query, backend = await parse_craving(req.text)
        return self.rank(req, query, backend)

    # ---- deterministic half: the model's terms against the stored catalog
    def rank(self, req: CravingReq, query: CravingQuery, backend: str) -> CravingResponse:
        rests = {r.id: r for r in self.store.all(Restaurant)}
        by_restaurant: dict[str, list[MenuItem]] = {}
        for item in self.store.all(MenuItem):
            by_restaurant.setdefault(item.restaurant_id, []).append(item)
        user = self.store.get(User, req.user_id) if req.user_id else None

        matches: list[CravingMatchWire] = []
        for r in rests.values():
            if req.category and req.category not in r.categories:
                continue
            scored = [(s, i) for s, i in ((self._item_score(query, r, i, user), i) for i in by_restaurant.get(r.id, [])) if s >= MIN_SCORE]
            if not scored:
                continue
            scored.sort(key=lambda si: (-si[0], si[1].price_cents))
            picks = scored[:max(1, req.options_per_place)]
            score = picks[0][0] + 0.4 * (shrunk_rating(r) - 4.0) + (CUISINE_HIT if query.cuisine == r.cuisine else 0.0)
            matches.append(CravingMatchWire(restaurant=self._wire(r, [i for _, i in picks]),
                                            reason=self._reason(r, picks[0][1], query), score=round(score, 3)))
        matches.sort(key=lambda m: (-m.score, m.restaurant.name))
        matches = matches[:max(1, req.limit)]
        note = "" if matches else f"Nothing on the menus nearby matches “{req.text.strip()}”. Try another craving."
        return CravingResponse(text=req.text, summary=query.summary or req.text.strip()[:40], interpretation=_interpretation(query),
                               backend=backend, matches=matches, note=note)

    # ---- scoring
    def _item_score(self, q: CravingQuery, r: Restaurant, item: MenuItem, user: Optional[User]) -> float:
        haystack = " ".join([item.name, item.description, " ".join(item.ingredients)]).lower()
        name = item.name.lower()
        if any(a and a in haystack for a in q.avoid):
            return 0.0
        if q.max_price_cents and item.price_cents > q.max_price_cents:
            return 0.0
        if not self._diet_ok(q, item) or (user and not filters.passes_dietary(user, item)[0]):
            return 0.0
        tags = item.tags
        score = 0.0
        for word in q.keywords:
            if not word:
                continue
            if word in name:
                score += NAME_HIT
            elif word in haystack:
                score += TEXT_HIT
        if q.dish_type != "any":
            if tags and tags.dish_type == q.dish_type:
                score += DISH_TYPE_HIT
            elif q.dish_type in haystack:
                score += TEXT_HIT
        if q.cuisine != "any":
            if r.cuisine == q.cuisine:
                score += CUISINE_HIT
            elif tags and tags.cuisine == q.cuisine:
                score += 1.0
            elif q.cuisine in f"{r.cuisine_detail} {r.name}".lower():
                score += 1.5
        if score <= 0:
            return 0.0
        if q.spicy:
            score += 0.4 * (tags.spice if tags else 0)
        if item.popular:
            score += 0.3
        return score

    @staticmethod
    def _diet_ok(q: CravingQuery, item: MenuItem) -> bool:
        tags = item.tags
        if q.vegan and "vegan" not in item.verified_diets and not (tags and tags.vegan >= 0.9):
            return False
        if q.vegetarian and "vegetarian" not in item.verified_diets and not (tags and tags.vegetarian >= 0.9):
            return False
        if q.gluten_free and "gluten_free" not in item.verified_diets and not (
                tags and tags.allergen_p.get("gluten", 1.0) <= filters.ALLERGEN_WARN_THRESHOLD):
            return False
        return True

    # ---- wires
    @staticmethod
    def _wire(r: Restaurant, items: list[MenuItem]) -> RestaurantWire:
        options = [GroupOptionWire(id=i.id, name=i.name, detail=(i.description or ", ".join(i.ingredients[:3]))[:60],
                                   symbol=symbol_for(i), item_price_cents=i.price_cents,
                                   price_cents=i.price_cents + r.fees.per_item_overhead(i.price_cents) + r.fees.delivery_fee_cents,
                                   baseline_cents=i.price_cents + r.fees.per_item_overhead(i.price_cents) + r.fees.delivery_fee_cents)
                   for i in items]
        return RestaurantWire(id=r.id, name=r.name, cuisine=cuisine_label(r), symbol=options[0].symbol if options else "fork.knife",
                              rating=r.rating, review_count=r.review_count, categories=list(r.categories), options=options)

    @staticmethod
    def _reason(r: Restaurant, item: MenuItem, q: CravingQuery) -> str:
        craving = q.summary.strip() or (q.dish_type if q.dish_type != "any" else "")
        lead = f"{item.name} for {craving}" if craving else item.name
        bits = [lead, cuisine_label(r)]
        if r.rating:
            bits.append(f"{r.rating:.1f}★")
        if is_drink(item):
            bits.append("drink")
        return " · ".join(bits)
