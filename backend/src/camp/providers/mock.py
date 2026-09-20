"""Mock provider. Serves the real Ramp HQ catalog (`catalog.py`) as RAW JSON in the target platform's shape (Uber or
DoorDash) and runs it through the real parsers, so adapter parsing is exercised offline. Restaurants listed on both
platforms appear on both (to test de-duplication); quotes vary per platform so the sync picks the cheaper/faster one."""
from __future__ import annotations

import json
import random
from pathlib import Path

from ..catalog import CatalogRestaurant, load
from ..models import LatLng
from . import doordash, uber
from .base import PItem, PQuote, PStore, PlacedOrder

FIXTURES = Path(__file__).parent / "fixtures"
_MODIFIERS = [("No onions", 0), ("Extra sauce", 100), ("Add Coke", 250), ("Add side salad", 350)]
_DIET_LABELS = (("vegetarian", "VEGETARIAN"), ("vegan", "VEGAN"), ("gluten_free", "GLUTEN_FREE"))


class MockProvider:
    def __init__(self, platform: str = "uber", seed: int = 0, latency_ms: int = 0, n_stores: int | None = None):
        assert platform in ("uber", "doordash")
        self.name = platform
        self.rng = random.Random(seed)
        self.latency_ms = latency_ms
        self._raw_stores: dict[str, dict] = {}
        self._raw_menus: dict[str, dict] = {}
        rows = [r for r in load() if platform in r.platforms and r.dishes]
        for c in rows[:n_stores] if n_stores else rows:
            sid = f"{platform}-{c.id}"
            self._raw_stores[sid] = self._uber_store(sid, c) if platform == "uber" else self._dd_store(sid, c)
            self._raw_menus[sid] = self._uber_menu(sid, c) if platform == "uber" else self._dd_menu(sid, c)

    # ---- raw generation in platform shape
    @staticmethod
    def _uber_store(sid: str, c: CatalogRestaurant) -> dict:
        return {"store_id": sid, "name": c.name, "location": {"latitude": c.lat, "longitude": c.lng, "address": c.address},
                "cuisine_types": [c.cuisine], "hours": [{"start_time": c.hours.get("open", "11:00"), "end_time": c.hours.get("close", "22:00")}],
                "min_order_amount": {"amount": 1500 if c.price_level <= 2 else 2500}, "allergen_info_verified": c.has_allergen_info,
                "rating": {"value": c.rating, "count": c.review_count}, "price_bucket": c.price_level}

    @staticmethod
    def _dd_store(sid: str, c: CatalogRestaurant) -> dict:
        return {"location_id": sid, "name": c.name, "address": {"lat": c.lat, "lng": c.lng, "street": c.address}, "cuisine": c.cuisine,
                "open_hours": [{"start_time": c.hours.get("open", "11:00") + ":00", "end_time": c.hours.get("close", "22:00") + ":00"}],
                "minimum_order_subtotal": 1500 if c.price_level <= 2 else 2500, "allergen_data_verified": c.has_allergen_info,
                "average_rating": c.rating, "number_of_ratings": c.review_count, "price_range": c.price_level}

    @staticmethod
    def _uber_menu(sid: str, c: CatalogRestaurant) -> dict:
        items, opt_ids = [], []
        for j, (oname, price) in enumerate(_MODIFIERS):
            oid = f"{sid}-opt{j}"
            opt_ids.append(oid)
            items.append({"id": oid, "title": {"translations": {"en_us": oname}}, "price_info": {"price": price}, "is_modifier_option": True})
        groups = [{"id": f"{sid}-g0", "title": {"translations": {"en_us": "Customize"}}, "modifier_options": {"ids": opt_ids}}]
        for d in c.dishes:
            it = {"id": f"{sid}-{d.id}", "title": {"translations": {"en_us": d.name}}, "description": {"translations": {"en_us": d.description}},
                  "price_info": {"price": d.price_cents}, "ingredients": d.ingredients, "modifier_group_ids": {"ids": [f"{sid}-g0"]},
                  "dietary_label_info": {"labels": [lab for k, lab in _DIET_LABELS if getattr(d, k)]},
                  "quantity_info": {"in_stock": True}}
            if d.kcal:
                it["nutritional_info"] = {"calories": {"display_type": "calories", "lower_range": d.kcal}}
            if c.has_allergen_info:
                it["allergen_info"] = {"contains": sorted(d.allergens)}
            items.append(it)
        return {"items": items, "modifier_groups": groups}

    @staticmethod
    def _dd_menu(sid: str, c: CatalogRestaurant) -> dict:
        items = []
        for d in c.dishes:
            it = {"merchant_supplied_id": f"{sid}-{d.id}", "name": d.name, "description": d.description, "price": d.price_cents,
                  "ingredients": d.ingredients, "status": "ACTIVE", "dietary_tags": [k for k, _ in _DIET_LABELS if getattr(d, k)],
                  "extras": [{"name": "Customize", "options": [{"name": n, "price": p} for n, p in _MODIFIERS]}]}
            if c.has_allergen_info:
                it["allergens"] = sorted(d.allergens)
            items.append(it)
        return {"menu": {"categories": [{"name": "Mains", "items": items}]}}

    # ---- MenuProvider interface (through the real parsers)
    async def _lag(self) -> None:
        if self.latency_ms:
            import asyncio
            await asyncio.sleep(self.latency_ms / 1000)

    async def search_stores(self, near: LatLng, radius_km: float) -> list[PStore]:
        await self._lag()
        parse = uber.parse_store if self.name == "uber" else doordash.parse_store
        from ..filters import haversine_km
        return [s for s in (parse(r) for r in self._raw_stores.values()) if haversine_km(s.location, near) <= radius_km]

    async def get_menu(self, store_external_id: str) -> list[PItem]:
        await self._lag()
        parse = uber.parse_menu if self.name == "uber" else doordash.parse_menu
        return parse(self._raw_menus[store_external_id])

    async def quote(self, store_external_id: str, dropoff: LatLng, n_items: int = 1) -> PQuote:
        await self._lag()
        r = random.Random(f"{store_external_id}:{self.name}")
        if self.name == "uber":
            lo = r.randint(15, 35)
            return uber.parse_quote({"delivery_fee": {"amount": r.choice([399, 499, 699])}, "service_fee_pct": 0.15,
                                     "estimated_delivery_minutes": {"min": lo, "max": lo + r.randint(10, 25)}})
        return doordash.parse_quote({"fee": r.choice([499, 599, 899]), "service_fee_pct": 0.12, "duration": r.randint(20, 45)})

    async def place_order(self, store_external_id: str, dropoff: LatLng, lines: list[dict]) -> PlacedOrder:
        await self._lag()
        return PlacedOrder(external_order_id=f"mock-{self.name}-ord-{self.rng.randint(10**6, 10**7)}", platform=self.name, status="simulated")

    def dump_fixtures(self) -> None:
        FIXTURES.mkdir(exist_ok=True)
        (FIXTURES / f"{self.name}_stores.json").write_text(json.dumps(list(self._raw_stores.values()), indent=1))
        first = next(iter(self._raw_menus))
        (FIXTURES / f"{self.name}_menu_sample.json").write_text(json.dumps(self._raw_menus[first], indent=1))
