"""Uber Eats adapter.

VERIFIED against developer.uber.com (2026-09-19): OAuth 2.0 client credentials; menu endpoints
  GET /eats/stores/{store_id}/menus, store details endpoints. Those are MERCHANT-facing (you manage
  your own stores). ASSUMED (partner-only, not public): store discovery near a point and consumer order
  placement. Marked `# ASSUMED` below. Re-check paths when access arrives.

Env: UBER_CLIENT_ID, UBER_CLIENT_SECRET. Optional UBER_BASE_URL.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

from ..models import LatLng
from .base import NotConfigured, PItem, PModifier, PQuote, PStore, PlacedOrder, ProviderError

AUTH_URL = "https://auth.uber.com/oauth/v2/token"
DEFAULT_BASE = "https://api.uber.com/v1"


class UberEatsProvider:
    name = "uber"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None, base_url: str | None = None,
                 client: httpx.AsyncClient | None = None):
        self.client_id = client_id or os.getenv("UBER_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("UBER_CLIENT_SECRET")
        self.base = (base_url or os.getenv("UBER_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self._client = client
        self._token: str | None = None
        self._token_exp = 0.0

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _auth(self) -> str:
        if not self.configured():
            raise NotConfigured("UBER_CLIENT_ID / UBER_CLIENT_SECRET not set")
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        c = self._client or httpx.AsyncClient(timeout=15)
        r = await c.post(AUTH_URL, data={"client_id": self.client_id, "client_secret": self.client_secret,
                                         "grant_type": "client_credentials", "scope": "eats.store eats.order"})
        if r.status_code != 200:
            raise ProviderError(f"uber auth {r.status_code}: {r.text[:200]}")
        j = r.json()
        self._token, self._token_exp = j["access_token"], time.time() + j.get("expires_in", 3600)
        return self._token

    async def _get(self, path: str, **params: Any) -> Any:
        tok = await self._auth()
        c = self._client or httpx.AsyncClient(timeout=15)
        r = await c.get(f"{self.base}{path}", params=params, headers={"Authorization": f"Bearer {tok}"})
        if r.status_code >= 400:
            raise ProviderError(f"uber GET {path} {r.status_code}: {r.text[:200]}")
        return r.json()

    async def search_stores(self, near: LatLng, radius_km: float) -> list[PStore]:
        j = await self._get("/eats/stores", latitude=near.lat, longitude=near.lng, radius_km=radius_km)   # ASSUMED
        return [parse_store(s) for s in j.get("stores", [])]

    async def get_menu(self, store_external_id: str) -> list[PItem]:
        j = await self._get(f"/eats/stores/{store_external_id}/menus")     # documented
        return parse_menu(j)

    async def quote(self, store_external_id: str, dropoff: LatLng, n_items: int = 1) -> PQuote:
        j = await self._get(f"/eats/stores/{store_external_id}/delivery_quote", dropoff_latitude=dropoff.lat,
                            dropoff_longitude=dropoff.lng)                   # ASSUMED
        return parse_quote(j)

    async def place_order(self, store_external_id: str, dropoff: LatLng, lines: list[dict]) -> PlacedOrder:
        raise NotConfigured("Uber consumer order placement is partner-gated; not wired yet")   # ASSUMED


# ---------------------------------------------------------------- parsers (also used by the mock)

def parse_store(s: dict) -> PStore:
    loc = s.get("location", {})
    hours = s.get("hours", [{}])[0] if s.get("hours") else {}
    return PStore(external_id=str(s["store_id"]), platform="uber", name=s.get("name", ""),
                  location=LatLng(lat=loc.get("latitude", 0.0), lng=loc.get("longitude", 0.0)),
                  cuisine=(s.get("cuisine_types") or ["other"])[0].lower(),
                  open_minutes=(_hm(hours.get("start_time", "11:00")), _hm(hours.get("end_time", "22:00"))),
                  min_order_cents=s.get("min_order_amount", {}).get("amount", 0),
                  has_verified_allergen_data=bool(s.get("allergen_info_verified", False)),
                  address=loc.get("address", ""))


def parse_menu(j: dict) -> list[PItem]:
    """Uber menu JSON: {items:[{id,title{translations{en_us}},description,price_info{price},modifier_group_ids{ids},
    nutritional_info, dietary_label_info{labels}, allergen_info?}], modifier_groups:[{id,title,modifier_options{ids}}]}"""
    groups = {g["id"]: g for g in j.get("modifier_groups", [])}
    items_by_id = {i["id"]: i for i in j.get("items", [])}
    out = []
    for it in j.get("items", []):
        if it.get("is_modifier_option"):
            continue
        mods = []
        for gid in (it.get("modifier_group_ids", {}) or {}).get("ids", []):
            g = groups.get(gid, {})
            for oid in (g.get("modifier_options", {}) or {}).get("ids", []):
                o = items_by_id.get(oid, {})
                mods.append(PModifier(name=_title(o), price_cents=(o.get("price_info") or {}).get("price", 0), group=_title(g)))
        allergens = it.get("allergen_info")
        out.append(PItem(external_id=str(it["id"]), name=_title(it), description=_title(it, "description"),
                         price_cents=(it.get("price_info") or {}).get("price", 0),
                         ingredients=[x.lower() for x in it.get("ingredients", [])], modifiers=mods,
                         allergens=[a.lower() for a in allergens.get("contains", [])] if isinstance(allergens, dict) else None,
                         diets=[d.lower() for d in (it.get("dietary_label_info") or {}).get("labels", [])],
                         available=(it.get("quantity_info") or {}).get("in_stock", True)))
    return out


def parse_quote(j: dict) -> PQuote:
    eta = j.get("estimated_delivery_minutes", {})
    lo, hi = eta.get("min", 25), eta.get("max", 45)
    return PQuote(delivery_fee_cents=j.get("delivery_fee", {}).get("amount", 499), service_fee_pct=j.get("service_fee_pct", 0.15),
                  eta_mean_minutes=(lo + hi) // 2, eta_std_minutes=max(3, (hi - lo) // 4))


def _title(o: dict, key: str = "title") -> str:
    v = o.get(key)
    if isinstance(v, dict):
        return (v.get("translations") or {}).get("en_us", "") or ""
    return v or ""


def _hm(s: str) -> int:
    h, m = s.split(":")[:2]
    return int(h) * 60 + int(m)
