"""Versioned contracts shared with the native app (docs/INTEGRATION-PLAN.md §0 and §4).
camelCase on the wire to match Swift Codable defaults."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True)


class OfficeRef(Wire):
    id: str = "demo-office"
    name: str = "Office"
    latitude: float
    longitude: float
    radius_meters: int = 200
    cutoff: int = 725                 # minutes from midnight
    delivery_start: int = 750
    delivery_end: int = 780


class MealContext(Wire):
    context_version: int = 1
    user_id: Optional[str] = None     # server-assigned; the app sends displayName the first time
    display_name: str = "You"
    office: OfficeRef
    presence: Literal["inside", "outside", "unknown"] = "unknown"
    lunch_start: int = 690
    lunch_end: int = 870
    lunch_duration: int = 30
    dietary_style: str = "No preference"
    allergies: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    budget_cents: int = 2000
    meal: Literal["lunch", "dinner"] = "lunch"
    temp_c: float = 18.0
    raining: bool = False
    now_minutes: Optional[int] = None


class MealOfferOption(Wire):
    id: str
    name: str
    detail: str                        # explanation shown on the card
    symbol: str                        # SF Symbol name
    price_cents: int                   # all-in per person under the batch (item + fees share + tax/tip)
    baseline_cents: int                # all-in if ordered alone (full delivery fee)
    item_price_cents: int
    restaurant: str
    restaurant_id: str
    item_id: str
    pricing: Literal["estimated", "quoted", "fixture"] = "estimated"
    score: float = 0.0
    novel: bool = False
    breakdown: dict[str, float] = Field(default_factory=dict)


class MealOffer(Wire):
    offer_id: str
    version: int = 1
    context_version: int = 1
    user_id: str
    office_id: str
    group_id: Optional[str] = None     # batch id when the user is in an office batch
    location: Literal["office", "home"]
    closes_at: str                     # ISO 8601
    arrives_at: str
    options: list[MealOfferOption]
    participants: int = 1
    shared_delivery_cents: int = 0
    separate_delivery_cents: int = 0
    suggest_only: bool = False
    note: str = ""
