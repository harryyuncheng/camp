"""Versioned contracts shared with the native app (docs/INTEGRATION-PLAN.md §0 and §4).
camelCase on the wire to match Swift Codable defaults."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True)


class OfficeRef(Wire):
    id: str = "demo-office"
    name: str = "Office"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: int = Field(default=200, gt=0)
    cutoff: int = Field(default=725, ge=0, lt=1440)                 # minutes from midnight
    delivery_start: int = Field(default=750, ge=0, lt=1440)
    delivery_end: int = Field(default=780, ge=0, le=1440)


class MealContext(Wire):
    context_version: int = 1
    user_id: Optional[str] = None     # server-assigned; the app sends displayName the first time
    display_name: str = "You"
    office: OfficeRef
    presence: Literal["inside", "outside", "unknown"] = "unknown"
    lunch_start: int = Field(default=690, ge=0, lt=1440)
    lunch_end: int = Field(default=870, gt=0, le=1440)
    lunch_duration: int = Field(default=30, gt=0, le=1440)
    dietary_style: str = "No preference"
    allergies: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    budget_cents: int = Field(default=2000, ge=0)
    meal: Literal["lunch", "dinner"] = "lunch"
    temp_c: float = 18.0
    raining: bool = False
    now_minutes: Optional[int] = Field(default=None, ge=0, lt=1440)

    @model_validator(mode="after")
    def valid_meal_window(self) -> MealContext:
        if self.lunch_end - self.lunch_start < self.lunch_duration:
            raise ValueError("meal window must allow the requested eating duration")
        return self


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
