"""Delivery-platform provider interface. Adapters return these normalized DTOs; `sync.py` maps them
onto Restaurant / MenuItem. Real adapters raise NotConfigured until credentials exist."""
from __future__ import annotations

from typing import Optional, Protocol

from pydantic import BaseModel, Field

from ..models import LatLng


class NotConfigured(RuntimeError):
    """Credentials for this provider are missing; use MockProvider or set env vars."""


class ProviderError(RuntimeError):
    pass


class PModifier(BaseModel):
    name: str
    price_cents: int = 0
    group: str = ""


class PItem(BaseModel):
    external_id: str
    name: str
    description: str = ""
    price_cents: int
    ingredients: list[str] = Field(default_factory=list)
    modifiers: list[PModifier] = Field(default_factory=list)
    allergens: Optional[list[str]] = None      # None = platform gave no allergen data; [] = verified none
    diets: list[str] = Field(default_factory=list)
    available: bool = True


class PStore(BaseModel):
    external_id: str
    platform: str
    name: str
    location: LatLng
    cuisine: str = "other"
    open_minutes: tuple[int, int] = (11 * 60, 22 * 60)
    min_order_cents: int = 0
    delivery_radius_km: float = 6.0
    has_verified_allergen_data: bool = False
    address: str = ""
    rating: Optional[float] = None             # platform-displayed rating, 5-point scale
    review_count: int = 0
    price_level: int = 2


class PQuote(BaseModel):
    delivery_fee_cents: int
    service_fee_pct: float
    eta_mean_minutes: int
    eta_std_minutes: int
    tax_pct: float = 0.0875


class PlacedOrder(BaseModel):
    external_order_id: str
    platform: str
    status: str = "created"


class MenuProvider(Protocol):
    name: str

    async def search_stores(self, near: LatLng, radius_km: float) -> list[PStore]: ...
    async def get_menu(self, store_external_id: str) -> list[PItem]: ...
    async def quote(self, store_external_id: str, dropoff: LatLng, n_items: int = 1) -> PQuote: ...
    async def place_order(self, store_external_id: str, dropoff: LatLng, lines: list[dict]) -> PlacedOrder: ...
