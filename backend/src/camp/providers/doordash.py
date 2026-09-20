"""DoorDash adapter.

VERIFIED against developer.doordash.com (2026-09-19): base https://openapi.doordash.com/marketplace,
JWT auth (developer id / key id / signing secret), GET /api/v1/stores/{location_id}/store_details and
/store_menu. These are MERCHANT-facing. ASSUMED (partner-only): store search near a point, delivery
quote for a consumer order, and order placement (Drive API `/drive/v2/quotes` is the closest public
analogue for delivery quotes). Marked `# ASSUMED`.

Env: DOORDASH_DEVELOPER_ID, DOORDASH_KEY_ID, DOORDASH_SIGNING_SECRET. Optional DOORDASH_BASE_URL.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import httpx

from ..models import LatLng
from .base import NotConfigured, PItem, PModifier, PQuote, PStore, PlacedOrder, ProviderError

DEFAULT_BASE = "https://openapi.doordash.com"


def make_jwt(developer_id: str, key_id: str, signing_secret: str, ttl_s: int = 300) -> str:
    """DoorDash JWT: HS256, header dd-ver DD-JWT-V1, secret is base64url-encoded."""
    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "dd-ver": "DD-JWT-V1"}).encode())
    now = int(time.time())
    payload = b64(json.dumps({"aud": "doordash", "iss": developer_id, "kid": key_id, "exp": now + ttl_s, "iat": now}).encode())
    secret = base64.urlsafe_b64decode(signing_secret + "=" * (-len(signing_secret) % 4))
    sig = b64(hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


class DoorDashProvider:
    name = "doordash"

    def __init__(self, developer_id: str | None = None, key_id: str | None = None, signing_secret: str | None = None,
                 base_url: str | None = None, client: httpx.AsyncClient | None = None):
        self.developer_id = developer_id or os.getenv("DOORDASH_DEVELOPER_ID")
        self.key_id = key_id or os.getenv("DOORDASH_KEY_ID")
        self.signing_secret = signing_secret or os.getenv("DOORDASH_SIGNING_SECRET")
        self.base = (base_url or os.getenv("DOORDASH_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self._client = client

    def configured(self) -> bool:
        return bool(self.developer_id and self.key_id and self.signing_secret)

    def _headers(self) -> dict[str, str]:
        if not self.configured():
            raise NotConfigured("DOORDASH_DEVELOPER_ID / KEY_ID / SIGNING_SECRET not set")
        return {"Authorization": f"Bearer {make_jwt(self.developer_id, self.key_id, self.signing_secret)}"}

    async def _req(self, method: str, path: str, **kw: Any) -> Any:
        c = self._client or httpx.AsyncClient(timeout=15)
        r = await c.request(method, f"{self.base}{path}", headers=self._headers(), **kw)
        if r.status_code >= 400:
            raise ProviderError(f"doordash {method} {path} {r.status_code}: {r.text[:200]}")
        return r.json()

    async def search_stores(self, near: LatLng, radius_km: float) -> list[PStore]:
        j = await self._req("GET", "/marketplace/api/v1/stores", params={"lat": near.lat, "lng": near.lng, "radius_km": radius_km})  # ASSUMED
        return [parse_store(s) for s in j.get("stores", [])]

    async def get_menu(self, store_external_id: str) -> list[PItem]:
        j = await self._req("GET", f"/marketplace/api/v1/stores/{store_external_id}/store_menu")   # documented
        return parse_menu(j)

    async def quote(self, store_external_id: str, dropoff: LatLng, n_items: int = 1) -> PQuote:
        j = await self._req("POST", "/drive/v2/quotes", json={"pickup_external_store_id": store_external_id,   # ASSUMED (Drive shape)
                                                             "dropoff_address": f"{dropoff.lat},{dropoff.lng}"})
        return parse_quote(j)

    async def place_order(self, store_external_id: str, dropoff: LatLng, lines: list[dict]) -> PlacedOrder:
        raise NotConfigured("DoorDash consumer order placement is partner-gated; not wired yet")   # ASSUMED


# ---------------------------------------------------------------- parsers (also used by the mock)

def parse_store(s: dict) -> PStore:
    addr = s.get("address", {})
    hrs = (s.get("open_hours") or [{}])[0]
    return PStore(external_id=str(s.get("location_id") or s.get("merchant_supplied_id")), platform="doordash", name=s.get("name", ""),
                  location=LatLng(lat=addr.get("lat", 0.0), lng=addr.get("lng", 0.0)),
                  cuisine=(s.get("cuisine") or "other").lower(),
                  open_minutes=(_hm(hrs.get("start_time", "11:00:00")), _hm(hrs.get("end_time", "22:00:00"))),
                  min_order_cents=int(s.get("minimum_order_subtotal", 0)), has_verified_allergen_data=bool(s.get("allergen_data_verified", False)),
                  address=addr.get("street", ""),
                  rating=s.get("average_rating"), review_count=int(s.get("number_of_ratings", 0)), price_level=int(s.get("price_range", 2)))


def parse_menu(j: dict) -> list[PItem]:
    """DoorDash store_menu JSON: {menu:{categories:[{name, items:[{merchant_supplied_id,name,description,price,
    dietary_tags?, allergens?, extras:[{name, options:[{name, price}]}]}]}]}}"""
    out = []
    menu = j.get("menu", j)
    for cat in menu.get("categories", []):
        for it in cat.get("items", []):
            mods = [PModifier(name=o["name"], price_cents=int(o.get("price", 0)), group=ex.get("name", ""))
                    for ex in it.get("extras", []) for o in ex.get("options", [])]
            alg = it.get("allergens")
            out.append(PItem(external_id=str(it.get("merchant_supplied_id") or it.get("id")), name=it.get("name", ""),
                             description=it.get("description", ""), price_cents=int(it.get("price", 0)),
                             ingredients=[x.lower() for x in it.get("ingredients", [])], modifiers=mods,
                             allergens=[a.lower() for a in alg] if isinstance(alg, list) else None,
                             diets=[d.lower() for d in it.get("dietary_tags", [])],
                             available=it.get("status", "ACTIVE") == "ACTIVE"))
    return out


def parse_quote(j: dict) -> PQuote:
    fee = int(j.get("fee", 599))
    dur = int(j.get("duration", 35))   # Drive quote returns minutes
    return PQuote(delivery_fee_cents=fee, service_fee_pct=float(j.get("service_fee_pct", 0.12)),
                  eta_mean_minutes=dur, eta_std_minutes=max(3, dur // 5))


def _hm(s: str) -> int:
    h, m = s.split(":")[:2]
    return int(h) * 60 + int(m)
