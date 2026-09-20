"""First-run setup, shared by both devices.

Onboarding collects what a person sets once — diet and allergies, their meal window, the office and its delivery
policy, calendar and notification choices — and writes it to this database, not to the device it was filled in on.
The Mac and the phone therefore read back the same answers: whichever one ran the flow, the other adopts it.

The recommender-relevant part of the answers is the existing `MealContext`, so saving here applies exactly what
`PUT /v1/profile` applies (restrictions, budget, meal window) and additionally keeps the app's whole configuration
document in `OnboardingProfile.settings`, opaque to the backend, for the other device to restore.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from .contracts import MealContext, Wire
from .models import OnboardingProfile, utcnow
from .offers import OfferService
from .store import Store


class OnboardingReq(Wire):
    context: MealContext                       # same mapping the app sends to /v1/profile
    settings: dict = Field(default_factory=dict)   # the app's CampConfiguration document, verbatim
    completed: bool = True
    device: str = "unknown"                    # "mac" | "iphone" | …


class OnboardingWire(Wire):
    user_id: str
    display_name: str
    office_id: str
    settings: dict = Field(default_factory=dict)
    completed: bool = False
    completed_at: Optional[datetime] = None
    updated_at: datetime
    device: str = "unknown"


def _wire(row: OnboardingProfile) -> OnboardingWire:
    return OnboardingWire(user_id=row.id, display_name=row.display_name, office_id=row.office_id, settings=row.settings,
                          completed=row.completed, completed_at=row.completed_at, updated_at=row.updated_at, device=row.device)


class OnboardingService:
    def __init__(self, store: Store, offers: OfferService):
        self.store = store
        self.offers = offers

    def save(self, req: OnboardingReq) -> OnboardingWire:
        """Creates or updates the person's row, applies their answers to the user profile, and records the setup."""
        ctx = req.context
        self.offers.ensure_world(ctx.office)
        user, _ = self.offers.user_for(ctx)
        user.app_settings = ctx.model_dump(by_alias=True, exclude={"user_id", "now_minutes"})
        self.store.put(user)
        row = self.store.get(OnboardingProfile, user.id) or OnboardingProfile(id=user.id, office_id=ctx.office.id)
        row.office_id = ctx.office.id
        row.display_name = ctx.display_name
        row.settings = req.settings or row.settings
        row.device = req.device
        row.updated_at = utcnow()
        if req.completed and not row.completed:
            row.completed_at = row.updated_at
        row.completed = req.completed
        self.store.put(row)
        return _wire(row)

    def find(self, user_id: Optional[str] = None, display_name: Optional[str] = None,
             office_id: Optional[str] = None) -> Optional[OnboardingWire]:
        """The setup a device should adopt: its own row when it knows its user id, otherwise the row of a person with
        the same name in that office, otherwise the office's most recently completed setup — which is what lets a
        phone that has never talked to this database pick up the one the laptop already finished."""
        if user_id:
            row = self.store.get(OnboardingProfile, user_id)
            if row:
                return _wire(row)
        rows = [r for r in self.store.all(OnboardingProfile) if office_id is None or r.office_id == office_id]
        if display_name:
            named = [r for r in rows if r.display_name == display_name]
            if named:
                return _wire(max(named, key=lambda r: r.updated_at))
        done = [r for r in rows if r.completed]
        return _wire(max(done, key=lambda r: r.updated_at)) if done else None

    def reset(self, user_id: str) -> OnboardingWire:
        """Marks the setup unfinished so the flow can be demoed again. The answers themselves are kept, so relaunching
        onboarding starts from them rather than from an empty form."""
        row = self.store.get(OnboardingProfile, user_id)
        if row is None:
            raise LookupError("no onboarding for this user")
        row.completed = False
        row.completed_at = None
        row.updated_at = utcnow()
        self.store.put(row)
        return _wire(row)
