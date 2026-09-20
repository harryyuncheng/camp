"""Mock provider. Generates RAW JSON in the target platform's shape (Uber or DoorDash) and runs it through
the real parsers, so adapter parsing is exercised offline. Some restaurants appear on both platforms
(to test de-duplication); quotes vary per platform so the sync picks the cheaper/faster one."""
from __future__ import annotations

import json
import random
from pathlib import Path

from ..models import CUISINES, LatLng
from ..synth import _DISHES, _ING_ALLERGEN, OFFICE
from . import doordash, uber
from .base import PItem, PQuote, PStore, PlacedOrder

FIXTURES = Path(__file__).parent / "fixtures"


class MockProvider:
    def __init__(self, platform: str = "uber", n_stores: int = 12, seed: int = 0, overlap: float = 0.5, latency_ms: int = 0):
        assert platform in ("uber", "doordash")
        self.name = platform
        self.rng = random.Random(seed)
        self.n_stores, self.overlap, self.latency_ms = n_stores, overlap, latency_ms
        self._raw_stores: dict[str, dict] = {}
        self._raw_menus: dict[str, dict] = {}
        self._build()

    # ---- raw generation in platform shape
    def _build(self) -> None:
        for k in range(self.n_stores):
            cuisine = CUISINES[k % len(CUISINES)]
            # shared physical identity across platforms: same name + coords when overlapping
            shared = random.Random(1000 + k)
            lat, lng = OFFICE.lat + shared.uniform(-0.03, 0.03), OFFICE.lng + shared.uniform(-0.03, 0.03)
            name = f"{cuisine.title()} Place {k}"
            if self.rng.random() > self.overlap and self.name == "doordash":
                name, lat, lng = f"{cuisine.title()} Kitchen {k}", lat + 0.01, lng - 0.01   # doordash-only store
            sid = f"{self.name}-{k}"
            verified = self.rng.random() < 0.3
            dishes = _DISHES[cuisine] + [(f"{cuisine.title()} Feast", ["chicken", "rice"], "rice", 1)]
            if self.name == "uber":
                self._raw_stores[sid] = {"store_id": sid, "name": name, "location": {"latitude": lat, "longitude": lng, "address": f"{k} Market St"},
                                         "cuisine_types": [cuisine], "hours": [{"start_time": "11:00", "end_time": "22:00"}],
                                         "min_order_amount": {"amount": self.rng.choice([1500, 2500, 4000])}, "allergen_info_verified": verified}
                self._raw_menus[sid] = self._uber_menu(sid, dishes, verified)
            else:
                self._raw_stores[sid] = {"location_id": sid, "name": name, "address": {"lat": lat, "lng": lng, "street": f"{k} Market St"},
                                         "cuisine": cuisine, "open_hours": [{"start_time": "11:00:00", "end_time": "22:00:00"}],
                                         "minimum_order_subtotal": self.rng.choice([1500, 2500, 4000]), "allergen_data_verified": verified}
                self._raw_menus[sid] = self._dd_menu(sid, dishes, verified)

    def _uber_menu(self, sid: str, dishes, verified: bool) -> dict:
        items, groups = [], []
        opt_ids = []
        for j, (oname, price) in enumerate([("No onions", 0), ("Extra sauce", 100), ("Add Coke", 250), ("Add side salad", 350)]):
            oid = f"{sid}-opt{j}"
            opt_ids.append(oid)
            items.append({"id": oid, "title": {"translations": {"en_us": oname}}, "price_info": {"price": price}, "is_modifier_option": True})
        groups.append({"id": f"{sid}-g0", "title": {"translations": {"en_us": "Customize"}}, "modifier_options": {"ids": opt_ids}})
        for j, (name, ings, dish, spice) in enumerate(dishes):
            it = {"id": f"{sid}-i{j}", "title": {"translations": {"en_us": name}}, "description": {"translations": {"en_us": f"{name} with {', '.join(ings)}"}},
                  "price_info": {"price": self.rng.randint(1100, 1900)}, "ingredients": ings, "modifier_group_ids": {"ids": [f"{sid}-g0"]},
                  "dietary_label_info": {"labels": [] if any(i in ("chicken", "beef", "pork", "fish", "salmon", "shrimp", "turkey", "bacon") for i in ings) else ["VEGETARIAN"]},
                  "quantity_info": {"in_stock": True}}
            if verified:
                it["allergen_info"] = {"contains": sorted({_ING_ALLERGEN[i] for i in ings if i in _ING_ALLERGEN})}
            items.append(it)
        return {"items": items, "modifier_groups": groups}

    def _dd_menu(self, sid: str, dishes, verified: bool) -> dict:
        items = []
        for j, (name, ings, dish, spice) in enumerate(dishes):
            it = {"merchant_supplied_id": f"{sid}-i{j}", "name": name, "description": f"{name} with {', '.join(ings)}", "price": self.rng.randint(1100, 1900),
                  "ingredients": ings, "status": "ACTIVE",
                  "dietary_tags": [] if any(i in ("chicken", "beef", "pork", "fish", "salmon", "shrimp", "turkey", "bacon") for i in ings) else ["vegetarian"],
                  "extras": [{"name": "Customize", "options": [{"name": "No onions", "price": 0}, {"name": "Extra sauce", "price": 100},
                                                               {"name": "Add Coke", "price": 250}, {"name": "Add side salad", "price": 350}]}]}
            if verified:
                it["allergens"] = sorted({_ING_ALLERGEN[i] for i in ings if i in _ING_ALLERGEN})
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
        r = random.Random(hash((store_external_id, self.name)) & 0xFFFF)
        if self.name == "uber":
            lo = r.randint(15, 35)
            return uber.parse_quote({"delivery_fee": {"amount": r.choice([399, 499, 699])}, "service_fee_pct": 0.15,
                                     "estimated_delivery_minutes": {"min": lo, "max": lo + r.randint(10, 25)}})
        return doordash.parse_quote({"fee": r.choice([499, 599, 899]), "service_fee_pct": 0.12, "duration": r.randint(20, 45)})

    async def place_order(self, store_external_id: str, dropoff: LatLng, lines: list[dict]) -> PlacedOrder:
        await self._lag()
        return PlacedOrder(external_order_id=f"{self.name}-ord-{self.rng.randint(10**6, 10**7)}", platform=self.name)

    def dump_fixtures(self) -> None:
        FIXTURES.mkdir(exist_ok=True)
        (FIXTURES / f"{self.name}_stores.json").write_text(json.dumps(list(self._raw_stores.values()), indent=1))
        first = next(iter(self._raw_menus))
        (FIXTURES / f"{self.name}_menu_sample.json").write_text(json.dumps(self._raw_menus[first], indent=1))
