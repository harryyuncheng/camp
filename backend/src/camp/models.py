"""Domain models for CAMP. Deliverable 1.

Conventions: money in integer cents, times in minutes from local midnight,
dates as ISO strings, locations as (lat, lng). Tags on items are optional;
an untagged item is "unknown", not "safe".
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- enums

Meal = Literal["lunch", "dinner"]
OrderCategory = Literal["coffee", "meal"]      # what an order is for: morning coffee/tea, or a meal
ORDER_CATEGORIES: list[OrderCategory] = ["coffee", "meal"]
LocationKind = Literal["office", "home"]
Scope = Literal["meal", "today", "ongoing", "restaurant"]

ALLERGENS = ["peanut", "tree_nut", "shellfish", "fish", "dairy", "egg", "gluten", "soy", "sesame"]
DIETS = ["vegetarian", "vegan", "halal", "kosher", "gluten_free", "dairy_free"]
CUISINES = ["american", "mexican", "italian", "japanese", "chinese", "thai", "indian",
            "mediterranean", "korean", "vietnamese", "salad", "sandwich", "pizza", "burger", "bakery"]
PROTEINS = ["chicken", "beef", "pork", "lamb", "fish", "shrimp", "tofu", "egg", "none"]
DISH_TYPES = ["bowl", "sandwich", "salad", "noodles", "rice", "pizza", "taco", "curry", "soup", "wrap", "burger", "other"]


class KcalBand(str, Enum):
    lt400 = "<400"
    b400_600 = "400-600"
    b600_800 = "600-800"
    gt800 = "800+"

    @property
    def midpoint(self) -> int:
        return {"<400": 320, "400-600": 500, "600-800": 700, "800+": 950}[self.value]


class ProteinBand(str, Enum):
    lt15 = "<15g"
    b15_30 = "15-30g"
    b30_45 = "30-45g"
    gt45 = "45g+"

    @property
    def midpoint(self) -> int:
        return {"<15g": 10, "15-30g": 22, "30-45g": 37, "45g+": 52}[self.value]


# ---------------------------------------------------------------- geography / time

class LatLng(BaseModel):
    lat: float
    lng: float


class MealWindow(BaseModel):
    """When the person can eat, minutes from midnight."""
    start: int
    end: int
    min_eat_minutes: int = 20


# ---------------------------------------------------------------- users

class Restriction(BaseModel):
    kind: Literal["allergen", "diet"]
    value: str                       # one of ALLERGENS or DIETS
    severe: bool = False             # severe allergen => verified data required to include
    source: Literal["onboarding", "nl_confirmed", "nl_provisional"] = "onboarding"


class HealthTargets(BaseModel):
    kcal_per_meal: int = 650
    protein_g_per_meal: int = 30


class Traits(BaseModel):
    """Learned per-user traits. epsilon_u is kept as Beta(a, b) so v3 can Thompson-sample it."""
    epsilon_a: float = 2.0
    epsilon_b: float = 2.0
    w_health: float = 0.5            # personal scale on the health term
    autonomy: float = 0.0            # 0 = happy to auto-order, 1 = wants to pick
    sacrifice_debt: float = 0.0      # grows when they yield in a batch, decays when they get their pick
    batch_breaks: int = 0            # how often they left a batch after it was formed

    @property
    def epsilon(self) -> float:
        return self.epsilon_a / (self.epsilon_a + self.epsilon_b)


class Preferences(BaseModel):
    """Stated (from onboarding/NL) and revealed (from behaviour) kept separately.
    Values are attribute -> weight in roughly [-1, 1]. Keys look like 'cuisine:thai',
    'protein:tofu', 'ingredient:onion', 'restaurant:<id>', 'item:<id>', 'spice', 'heaviness'."""
    stated: dict[str, float] = Field(default_factory=dict)
    revealed: dict[str, float] = Field(default_factory=dict)
    addons: dict[str, float] = Field(default_factory=dict)   # add-on habits: 'coke' -> weight


class ScheduleEntry(BaseModel):
    weekday: int                     # 0 = Monday
    meal: Meal
    location: LocationKind


class User(BaseModel):
    id: str = Field(default_factory=lambda: new_id("u"))
    name: str
    office_id: str
    synthetic: bool = False
    home: LatLng
    budget_cents: dict[str, int] = Field(default_factory=lambda: {"lunch": 2000, "dinner": 2500})
    restrictions: list[Restriction] = Field(default_factory=list)
    health: HealthTargets = Field(default_factory=HealthTargets)
    traits: Traits = Field(default_factory=Traits)
    prefs: Preferences = Field(default_factory=Preferences)
    schedule: list[ScheduleEntry] = Field(default_factory=list)
    windows: dict[str, MealWindow] = Field(default_factory=lambda: {
        "lunch": MealWindow(start=12 * 60, end=13 * 60 + 30),
        "dinner": MealWindow(start=18 * 60 + 30, end=20 * 60),
    })
    suggest_only: bool = False       # never auto-order (severe allergy w/o verified data, or high autonomy)
    app_settings: dict = Field(default_factory=dict)   # the native app's saved personal preferences, as last PUT to /v1/profile

    def budget(self, meal: Meal) -> int:
        return self.budget_cents[meal]

    def has_severe_allergy(self) -> bool:
        return any(r.kind == "allergen" and r.severe for r in self.restrictions)

    def location_for(self, weekday: int, meal: Meal, live: Optional[LocationKind] = None) -> LocationKind:
        if live:
            return live
        for e in self.schedule:
            if e.weekday == weekday and e.meal == meal:
                return e.location
        return "office"


# ---------------------------------------------------------------- restaurants & menu

class FeeSchedule(BaseModel):
    delivery_fee_cents: int = Field(default=499, ge=0)          # fixed per order: SHARED across a batch
    service_fee_pct: float = Field(default=0.10, ge=0, allow_inf_nan=False)  # percentage of item price: NOT shared
    tax_pct: float = Field(default=0.0875, ge=0, allow_inf_nan=False)
    tip_pct: float = Field(default=0.15, ge=0, allow_inf_nan=False)
    min_order_cents: int = Field(default=1500, ge=0)

    def per_item_overhead(self, price_cents: int) -> int:
        return round(price_cents * (self.service_fee_pct + self.tax_pct + self.tip_pct))


class Restaurant(BaseModel):
    id: str = Field(default_factory=lambda: new_id("r"))
    name: str
    location: LatLng
    cuisine: str
    fees: FeeSchedule = Field(default_factory=FeeSchedule)
    prep_base_minutes: int = 15
    prep_per_item_minutes: float = 0.5
    delivery_radius_km: float = 6.0
    eta_mean_minutes: int = 25
    eta_std_minutes: int = 8
    max_meals_per_slot: int = 60
    reliability: float = 0.9               # 0..1, updated by logistics feedback
    verified_allergen_data: bool = False   # restaurant supplies verified allergen info
    open_minutes: tuple[int, int] = (11 * 60, 22 * 60)
    platform: str = "mock"                 # uber | doordash | mock
    platform_ids: dict[str, str] = Field(default_factory=dict)   # platform -> external store id (same place on both)
    # public listing data (ratings are inputs to scoring, never a safety signal)
    address: str = ""
    neighborhood: str = ""
    cuisine_detail: str = ""
    price_level: int = 2                   # 1..4 ($..$$$$)
    rating: Optional[float] = None         # blended public rating on a 5-point scale
    review_count: int = 0
    ratings: dict[str, float] = Field(default_factory=dict)      # source -> rating (google, yelp, infatuation/10 ...)
    recommendations: list[str] = Field(default_factory=list)     # press / guide mentions
    chain: bool = False
    categories: list[str] = Field(default_factory=lambda: ["meal"])   # order categories served: "coffee" and/or "meal"

    def prep_minutes(self, n_items: int) -> float:
        return self.prep_base_minutes + self.prep_per_item_minutes * n_items


class ItemTags(BaseModel):
    """Output of Jev menu tagging (§7.3). Allergen probabilities are WARNING ONLY."""
    cuisine: Optional[str] = None
    protein: Optional[str] = None
    dish_type: Optional[str] = None
    spice: int = 0                         # 0..4
    heaviness: int = 2                     # 0..4
    warm: int = 2                          # 0 cold .. 4 hot
    kcal_band: Optional[KcalBand] = None
    protein_band: Optional[ProteinBand] = None
    vegetarian: float = 0.0
    vegan: float = 0.0
    halal: float = 0.0
    travels_well: float = 0.5
    allergen_p: dict[str, float] = Field(default_factory=dict)   # allergen -> P(contains)
    confidence: float = 1.0
    needs_review: bool = False


class MenuItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("i"))
    restaurant_id: str
    name: str
    description: str = ""
    ingredients: list[str] = Field(default_factory=list)
    price_cents: int = Field(ge=0)
    modifiers: list[str] = Field(default_factory=list)            # what the ordering system allows
    modifier_prices: dict[str, int] = Field(default_factory=dict)  # modifier -> cents
    platform: str = "mock"
    external_id: str = ""
    verified_allergens: Optional[set[str]] = None                # None = restaurant did not supply data
    verified_diets: set[str] = Field(default_factory=set)
    popular: bool = False                                         # "most ordered" / widely recommended
    kcal: Optional[int] = None                                    # published calories, when the restaurant lists them
    tags: Optional[ItemTags] = None


# ---------------------------------------------------------------- context, orders, batches

class Context(BaseModel):
    date: str                              # ISO date
    meal: Meal
    weekday: int
    temp_c: float = 18.0
    raining: bool = False
    order_time_minutes: int = 10 * 60      # when the order would be placed
    temporary_prefs: dict[str, float] = Field(default_factory=dict)   # "something light today"
    exploration: float = 0.0               # amplitude of per-request score jitter (0 = deterministic ranking)
    nonce: str = ""                        # changes per request so a refreshed offer explores different picks


class Recommendation(BaseModel):
    user_id: str
    item_id: str
    restaurant_id: str
    score: float
    breakdown: dict[str, float] = Field(default_factory=dict)
    novel: bool = False                    # never eaten this item/cuisine before (for ε learning)
    explanation: str = ""


class OrderLine(BaseModel):
    item_id: str
    restaurant_id: str
    price_cents: int = Field(ge=0)
    removed_ingredients: list[str] = Field(default_factory=list)
    addons: list[str] = Field(default_factory=list)


class Order(BaseModel):
    id: str = Field(default_factory=lambda: new_id("o"))
    user_id: str
    date: str
    meal: Meal
    location: LocationKind
    line: OrderLine
    default_line: OrderLine                # what we pre-selected
    shown_item_ids: list[str] = Field(default_factory=list)    # for pairwise training
    fee_share_cents: int = Field(default=0, ge=0)               # frozen at optimization time
    total_cents: int = Field(default=0, ge=0)
    baseline_cents: Optional[int] = Field(default=None, ge=0)
    item_name: Optional[str] = None
    restaurant_name: Optional[str] = None
    item_symbol: Optional[str] = None
    office_id: Optional[str] = None
    office_name: Optional[str] = None
    batch_id: Optional[str] = None
    status: Literal["proposed", "confirmed", "manual", "cancelled"] = "proposed"
    novel: bool = False
    source: Literal["recommender", "group", "manual"] = "recommender"
    group_id: Optional[str] = None         # LunchGroup the order belongs to, when it came from Today's groups
    created_at: datetime = Field(default_factory=utcnow)


class BatchRestaurant(BaseModel):
    restaurant_id: str
    user_ids: list[str]
    fee_share_cents: int                   # delivery fee / n, frozen
    company_absorbed_cents: int = 0


class Batch(BaseModel):
    id: str = Field(default_factory=lambda: new_id("b"))
    office_id: str
    date: str
    meal: Meal
    restaurants: list[BatchRestaurant]
    objective: float
    total_cost_cents: int
    regret: dict[str, float] = Field(default_factory=dict)
    cutoff_minutes: int = 10 * 60 + 30


# ---------------------------------------------------------------- feedback events

EventType = Literal["accept", "add_extras", "change_item", "change_restaurant", "go_manual",
                    "skip", "rating", "preference", "constraint", "logistics", "context", "meta"]


class FeedbackEvent(BaseModel):
    """Both taps and parsed NL become this. Raw text is never stored (decision 2026-09-19)."""
    id: str = Field(default_factory=lambda: new_id("e"))
    user_id: str
    type: EventType
    scope: Scope = "meal"
    order_id: Optional[str] = None
    item_id: Optional[str] = None
    restaurant_id: Optional[str] = None
    payload: dict = Field(default_factory=dict)   # type-specific details (aspects, attribute, direction, issue...)
    confidence: float = 1.0
    source: Literal["tap", "nl", "implicit"] = "tap"
    applied: bool = False
    needs_confirmation: bool = False
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------- lunch groups (Today page)

class GroupOption(BaseModel):
    """One meal a group offers. `subtotal_cents` is item + tax/service/tip; the delivery share is added on the wire
    from the group's current headcount, so prices shown in the app always reflect who has actually joined."""
    id: str                                # MenuItem id
    name: str
    detail: str = ""
    symbol: str = "fork.knife"
    item_cents: int
    subtotal_cents: int


class GroupMember(BaseModel):
    """One person in a group order. A member can order several items; `option_ids` is the authority and
    `option_id` / `order_id` mirror its first entry so rows and clients written before multi-item orders
    keep working. The delivery share is charged once per member, on the first item's Order."""
    user_id: str
    display_name: str
    option_id: str
    option_ids: list[str] = Field(default_factory=list)
    order_id: Optional[str] = None
    order_ids: list[str] = Field(default_factory=list)
    joined_at: datetime = Field(default_factory=utcnow)

    def items(self) -> list[str]:
        return self.option_ids or ([self.option_id] if self.option_id else [])

    def set_items(self, ids: list[str]) -> None:
        self.option_ids = list(ids)
        self.option_id = ids[0] if ids else ""


class LunchGroup(BaseModel):
    """A pending office group order for one restaurant and delivery slot. The backend is the authority for
    membership; every join/leave also upserts the member's Order so spending history stays consistent."""
    id: str = Field(default_factory=lambda: new_id("g"))
    office_id: str
    office_name: str = ""
    date: str                              # ISO date
    meal: Meal = "lunch"
    category: OrderCategory = "meal"
    restaurant_id: str
    name: str                              # restaurant name at creation
    cuisine: str = ""
    symbol: str = "fork.knife"
    delivery_minutes: int = 750            # arrival, minutes from midnight
    delivery_fee_cents: int = 600
    options: list[GroupOption] = Field(default_factory=list)
    members: list[GroupMember] = Field(default_factory=list)
    created_by: Optional[str] = None
    status: Literal["collecting", "locked", "placed", "cancelled"] = "collecting"
    seeded: bool = False                   # created by the backend to populate an empty day (members are synthetic colleagues)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def participants(self) -> int:
        return len(self.members)

    @property
    def savings_cents(self) -> int:
        return max(0, self.participants - 1) * self.delivery_fee_cents


# ---------------------------------------------------------------- Ramp sandbox allocation attempts

class RampAttempt(BaseModel):
    """Idempotency ledger for sandbox fund issuance. `state`: submitting → ready | unknown."""
    id: str                                # client request UUID
    fingerprint: str                       # sha256(user_id:amount) so a retry cannot change owner or amount
    payload: dict
    state: Literal["submitting", "ready", "unknown"] = "submitting"
    result: Optional[dict] = None
    created_at: datetime = Field(default_factory=utcnow)


class RampOverageRequest(BaseModel):
    """One ask to spend above the employee's Ramp limit. `state`: pending → approved | denied. Approving raises the
    limit in Ramp; `baseline_cents` records what it was beforehand so the original ceiling is never lost."""
    id: str                                # client request UUID
    ramp_user_id: str                      # the Ramp employee the limit belongs to
    limit_id: str                          # the Ramp limit (fund) that would be raised
    limit_name: str = ""
    requester: str = ""                    # display name, so the approver sees who asked
    baseline_cents: int                    # the limit as Ramp reported it when the request was made
    requested_cents: int                   # the ceiling being asked for
    reason: str = ""
    state: Literal["pending", "approved", "denied"] = "pending"
    decided_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    decided_at: Optional[datetime] = None


# ---------------------------------------------------------------- shared lunch session (Mac <-> iPhone)

class SyncState(BaseModel):
    """The shared active orders. A single row (id 'lunch'); `seq` increases on every accepted write. `records` holds
    one record per session (coffee and a meal can be active together); `record` is kept for rows written by older builds."""
    id: str = "lunch"
    seq: int = 0
    record: Optional[dict] = None
    records: list[dict] = Field(default_factory=list)


class ScheduledOrder(BaseModel):
    """A standing order the user asked camp to put on their calendar: e.g. coffee at 9:00 on weekdays, or a meal at
    12:30 Mon/Wed/Fri. Each matching day, `GroupService.today` makes sure a group exists at that restaurant and time
    and that the user is in it. The Mac mirrors it as a recurring event in the dedicated "camp" calendar."""
    id: str = Field(default_factory=lambda: new_id("sch"))
    user_id: str
    office_id: str
    category: OrderCategory = "meal"
    label: str = ""                        # "Morning coffee", "Lunch"
    restaurant_id: Optional[str] = None    # None: camp picks the best-rated place in the category that day
    option_id: Optional[str] = None
    time_minutes: int = 750                # arrival, minutes from midnight (office timezone)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])   # 0 = Monday
    active: bool = True
    calendar_event_id: Optional[str] = None   # EventKit identifier on the device that created the event
    materialized_dates: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
