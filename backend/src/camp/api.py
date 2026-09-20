"""FastAPI service over the core. Run: uv run uvicorn camp.api:app --reload"""
from __future__ import annotations

import os
from datetime import date

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import feedback as fb
from . import catalog, synth
from .ai.classify import default_classifier
from .ai.feedback_parse import parse_feedback
from .ai.modifications import modify
from .ai.tagging import tag_menu
from .explain import explain_llm
from .models import ORDER_CATEGORIES, Context, FeedbackEvent, LunchGroup, MenuItem, Order, Restaurant, User
from .pipeline import plan_home, plan_office
from .providers import providers_from_env, sync_catalog
from typing import Literal, Optional

from .contracts import MealContext, MealOffer, OfficeRef, Wire
from .groups import (CreateGroupReq, GroupService, GroupsResponse, JoinGroupReq, LedgerWire, LunchGroupWire, MenuWire, RestaurantWire,
                     ScheduleReq, ScheduleWire)
from .offers import OfferService
from .onboarding import OnboardingReq, OnboardingService, OnboardingWire
from .ramp import Problem, RampService
from .search import CravingReq, CravingResponse, CravingService
from .store import Store
from .sync import LunchSyncService, SyncConflict

def _load_env_file(path: str | None = None) -> None:
    """backend/.env → os.environ (setdefault, so the shell wins). Same convention as server.py."""
    from pathlib import Path
    p = Path(path or os.getenv("CAMP_ENV_FILE") or Path(__file__).resolve().parents[2] / ".env")
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env_file()
app = FastAPI(title="CAMP recommender")
store = Store.from_env()
clf = default_classifier()
offers = OfferService(store)
lunch_sync = LunchSyncService(store)
groups = GroupService(store)
onboarding = OnboardingService(store, offers)
cravings = CravingService(store)
ramp = RampService(store)


@app.middleware("http")
async def require_camp_token(request: Request, call_next):
    """Set CAMP_TOKEN when binding beyond loopback (`--host 0.0.0.0` for the phone): every request must carry
    it as X-Camp-Token. Unset, the service stays open, which is only acceptable on 127.0.0.1."""
    token = os.getenv("CAMP_TOKEN", "")
    if token and request.headers.get("x-camp-token", "") != token:
        return JSONResponse({"detail": "X-Camp-Token header missing or wrong"}, status_code=401)
    return await call_next(request)
if not store.all(User):
    u, r, i = synth.make_world(int(os.getenv("CAMP_USERS", "40")), None, 0)
    store.put_many(u); store.put_many(r); store.put_many(i)
elif catalog.ensure_current(store):
    print("camp: replaced the stored restaurant catalog with the Ramp HQ dataset")


class RecommendReq(BaseModel):
    office_id: str = "hq"
    meal: str = "lunch"
    date: str | None = None
    temp_c: float = 18.0
    raining: bool = False


class FeedbackReq(BaseModel):
    user_id: str
    text: str | None = None
    order_id: str | None = None
    tap: dict | None = None            # {"type": "accept"|"change_item"|..., ...payload}
    confirm_constraint: bool = False


class ModifyReq(BaseModel):
    order_id: str
    text: str
    now_minutes: int = 10 * 60


@app.post("/batch/run")
async def batch_run(req: RecommendReq):
    d = date.fromisoformat(req.date) if req.date else date.today()
    ctx = Context(date=d.isoformat(), meal=req.meal, weekday=d.weekday(), temp_c=req.temp_c, raining=req.raining)
    plan = plan_office(store, req.office_id, synth.OFFICE, ctx)
    items = {i.id: i for i in store.all(MenuItem)}
    out = {}
    for uid, recs in plan.recommendations.items():
        u = store.get(User, uid)
        out[uid] = [dict(item=items[r.item_id].name, restaurant=r.restaurant_id, score=round(r.score, 3), novel=r.novel,
                         why=await explain_llm(u, items[r.item_id], r) if k == 0 else None) for k, r in enumerate(recs)]
    return dict(batch=plan.batch, solver=plan.solver, suggest_only=list(plan.suggest_only), unassigned=plan.unassigned,
                orders=[o.id for o in plan.orders], recommendations=out)


@app.post("/recommend/home/{user_id}")
async def recommend_home(user_id: str, req: RecommendReq):
    u = store.get(User, user_id)
    if not u:
        raise HTTPException(404)
    d = date.fromisoformat(req.date) if req.date else date.today()
    ctx = Context(date=d.isoformat(), meal=req.meal, weekday=d.weekday(), temp_c=req.temp_c, raining=req.raining)
    plan = plan_home(store, u, synth.OFFICE, ctx)
    return dict(recommendations=plan.recommendations[u.id], orders=plan.orders)


@app.post("/modify")
async def modify_order(req: ModifyReq):
    o = store.get(Order, req.order_id)
    if not o:
        raise HTTPException(404)
    res = await modify(clf, store, o, req.text, req.now_minutes)
    logs = []
    for e in res.events:
        ev = FeedbackEvent(user_id=o.user_id, type=e.pop("type"), order_id=o.id, item_id=e.get("item_id"), payload=e, source="tap")
        logs += fb.apply_event(store, ev)
    return dict(ok=res.ok, message=res.message, options=res.options, total_cents=res.total_cents, profile_updates=logs)


@app.post("/feedback")
async def feedback(req: FeedbackReq):
    o = store.get(Order, req.order_id) if req.order_id else None
    logs, clarify, events = [], None, []
    if req.tap:
        t = dict(req.tap)
        ev = FeedbackEvent(user_id=req.user_id, type=t.pop("type"), order_id=req.order_id, item_id=t.pop("item_id", o.line.item_id if o else None),
                           payload=t, source="tap")
        events.append(ev)
    if req.text:
        res = await parse_feedback(clf, req.text, req.user_id, req.order_id, o.line.item_id if o else None, o.line.restaurant_id if o else None)
        clarify = res.clarify
        events += res.events
    for ev in events:
        if ev.type == "constraint" and req.confirm_constraint:
            ev.payload["confirmed"] = True
            ev.needs_confirmation = False
        if ev.type == "change_item" and ev.payload.get("needs_modification_pipeline"):
            continue   # handled by /modify
        logs += fb.apply_event(store, ev)
    return dict(events=[dict(type=e.type, scope=e.scope, confidence=e.confidence, payload=e.payload, needs_confirmation=e.needs_confirmation) for e in events],
                clarify=clarify, profile_updates=logs, learned=fb.learned_view(store.get(User, req.user_id)))


@app.get("/profile/{user_id}")
def profile(user_id: str):
    u = store.get(User, user_id)
    if not u:
        raise HTTPException(404)
    return dict(user=u, learned=fb.learned_view(u))


@app.post("/menu/tag")
async def menu_tag():
    items = await tag_menu(clf, store.all(MenuItem))
    store.put_many(items)
    return dict(tagged=len(items), needs_review=sum(1 for i in items if i.tags and i.tags.needs_review))


@app.get("/users")
def users():
    return [dict(id=u.id, name=u.name, budget=u.budget_cents, restrictions=[r.value for r in u.restrictions]) for u in store.all(User)]


@app.post("/catalog/sync")
async def catalog_sync(radius_km: float = 6.0, tag: bool = False):
    provs = providers_from_env()
    tagger = (lambda items: tag_menu(clf, items)) if tag else None
    rep = await sync_catalog(store, provs, synth.OFFICE, radius_km, tagger=tagger)
    return dict(providers=[p.name for p in provs], stores_seen=rep.stores_seen, merged=rep.merged, restaurants=rep.restaurants,
                items=rep.items, skipped=rep.skipped_providers, errors=rep.errors[:10])


# ---------------------------------------------------------------- native app contract (docs/INTEGRATION-PLAN.md §4)

@app.get("/v1/health")
def health():
    return dict(service="camp-recommender", version="0.2.0", classifier=type(clf).__name__,
                database="postgres" if store.pg else "sqlite", databaseUrl=store.url.split("@")[-1] if store.pg else store.url,
                providers=[p.name for p in providers_from_env()], users=len(store.all(User)), restaurants=len(store.all(Restaurant)),
                items=len(store.all(MenuItem)), orders=store.count(Order), groups=store.count(LunchGroup), ramp=ramp.configured)


@app.post("/v1/meal-offers", response_model=MealOffer)
def meal_offers(ctx: MealContext, force: bool = False):
    return offers.offer(ctx, force=force)


class LunchEventReq(Wire):
    offer_id: str
    option_id: Optional[str] = None
    event: Literal["confirmed", "delivered", "ended"]
    rating: Optional[int] = None       # 0..4, optional post-meal thumbs


@app.post("/v1/lunch-events")
def lunch_events(req: LunchEventReq):
    res = offers.lunch_event(req.offer_id, req.option_id, req.event, req.rating)
    if "error" in res:
        raise HTTPException(404, res["error"])
    return res


class DebugFeedbackReq(BaseModel):
    user_id: str
    text: str
    confirm_constraint: bool = False


# ---------------------------------------------------------------- shared lunch session (Mac ↔ iPhone)

class LunchSyncPublish(Wire):
    record: dict                              # LunchSyncRecord as the Swift app encodes it (opaque here)
    expected_session_id: Optional[str] = None  # what the device believed was current
    expected_revision: Optional[int] = None
    device: str = "unknown"


@app.get("/v1/lunch-session")
async def lunch_session(since: Optional[int] = None, wait: float = 0):
    """Current shared lunch. With `since=<seq>` this long-polls up to `wait` seconds (max 30) for a change."""
    return await lunch_sync.wait_for_change(since, min(max(wait, 0), 30))


@app.put("/v1/lunch-session")
async def lunch_session_publish(req: LunchSyncPublish):
    try:
        return await lunch_sync.publish(req.record, req.expected_session_id, req.expected_revision, req.device)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except SyncConflict as e:
        return JSONResponse({"detail": str(e), "seq": e.seq, "record": e.record, "records": e.records}, status_code=409)


@app.delete("/v1/lunch-session")
async def lunch_session_clear(sessionId: Optional[str] = None):
    """Forget one shared order (`?sessionId=`) or all of them."""
    return await lunch_sync.clear(sessionId)


@app.get("/v1/debug/snapshot")
def debug_snapshot():
    return dict(health=health(), **offers.snapshot())


@app.get("/v1/debug/user/{user_id}")
def debug_user(user_id: str):
    return offers.user_debug(user_id)


@app.get("/v1/debug/events")
def debug_events(limit: int = 50):
    evs = sorted(store.all(FeedbackEvent), key=lambda e: e.created_at)[-limit:]
    return [e.model_dump() for e in evs]


@app.post("/v1/debug/feedback")
async def debug_feedback(req: DebugFeedbackReq):
    res = await parse_feedback(clf, req.text, req.user_id)
    logs = []
    for ev in res.events:
        if ev.type == "constraint" and req.confirm_constraint:
            ev.payload["confirmed"] = True; ev.needs_confirmation = False
        if ev.type == "change_item":
            continue
        logs += fb.apply_event(store, ev)
    u = store.get(User, req.user_id)
    return dict(events=[dict(type=e.type, scope=e.scope, confidence=e.confidence, payload=e.payload, needsConfirmation=e.needs_confirmation) for e in res.events],
                clarify=res.clarify, profileUpdates=logs, learned=fb.learned_view(u) if u else None, backend=type(clf).__name__)


# ---------------------------------------------------------------- profile (the app's saved preferences, stored on the user row)

@app.put("/v1/profile")
def profile_put(ctx: MealContext):
    """The Settings page saves here. Same mapping as an offer request (name, diet, allergies, dislikes, window, budget),
    plus the raw preferences kept on the user so another device can read them back."""
    offers.ensure_world(ctx.office)
    u, created = offers.user_for(ctx)
    u.app_settings = ctx.model_dump(by_alias=True, exclude={"user_id", "now_minutes"})
    store.put(u)
    return dict(userId=u.id, created=created, learned=fb.learned_view(u), restrictions=[r.model_dump() for r in u.restrictions],
                budgetCents=u.budget_cents.get(ctx.meal, 0))


@app.get("/v1/profile/{user_id}")
def profile_get(user_id: str):
    u = store.get(User, user_id)
    if not u:
        raise HTTPException(404, "unknown user")
    return dict(userId=u.id, name=u.name, officeId=u.office_id, settings=u.app_settings, learned=fb.learned_view(u),
                restrictions=[r.model_dump() for r in u.restrictions], budgetCents=u.budget_cents, orders=len(store.orders_for(u.id)))


# ---------------------------------------------------------------- onboarding (first-run setup, shared by both devices)

@app.put("/v1/onboarding", response_model=OnboardingWire)
def onboarding_put(req: OnboardingReq):
    """Finishing (or revisiting) the setup flow on either device writes the answers here, never only on the device."""
    return onboarding.save(req)


@app.get("/v1/onboarding", response_model=OnboardingWire)
def onboarding_get(userId: Optional[str] = None, displayName: Optional[str] = None, officeId: Optional[str] = None):
    """What this device should start from. A phone with no user id of its own adopts the office's finished setup."""
    found = onboarding.find(userId, displayName, officeId)
    if found is None:
        raise HTTPException(404, "no onboarding saved yet")
    return found


@app.delete("/v1/onboarding/{user_id}", response_model=OnboardingWire)
def onboarding_reset(user_id: str):
    try:
        return onboarding.reset(user_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- lunch groups (Today page)

@app.get("/v1/groups", response_model=GroupsResponse)
def groups_today(officeId: str = "demo-office", userId: Optional[str] = None, date: Optional[str] = None, deliveryStart: int = 750,
                 latitude: float = 40.7424, longitude: float = -73.9913, officeName: str = "Office"):
    office = OfficeRef(id=officeId, name=officeName, latitude=latitude, longitude=longitude, delivery_start=deliveryStart)
    return groups.today(office, userId, date)


@app.get("/v1/restaurants", response_model=list[RestaurantWire])
def restaurants(limit: int = 12, category: Optional[str] = None):
    """Best-rated catalog places; `category=coffee|meal` narrows to places that take that kind of order."""
    if category is not None and category not in ORDER_CATEGORIES:
        raise HTTPException(422, "category must be coffee or meal")
    return groups.restaurants(limit, category)


@app.post("/v1/craving", response_model=CravingResponse)
async def craving(req: CravingReq):
    """"I want tacos" when none of the offered places appeal: OpenAI reads the sentence, the catalog answers it."""
    if not req.text.strip():
        raise HTTPException(422, "say what you are craving")
    return await cravings.search(req)


@app.get("/v1/restaurants/{restaurant_id}/menu", response_model=MenuWire)
def restaurant_menu(restaurant_id: str, userId: Optional[str] = None, groupId: Optional[str] = None):
    """The whole menu with the public rating, and the requesting user's top picks first."""
    try:
        return groups.menu(restaurant_id, userId, groupId)
    except LookupError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- standing orders (You → Schedule a new order)

@app.get("/v1/schedules/{user_id}", response_model=list[ScheduleWire])
def schedules(user_id: str):
    return groups.schedules(user_id)


@app.post("/v1/schedules", response_model=ScheduleWire)
def schedules_add(req: ScheduleReq):
    try:
        return groups.add_schedule(req)
    except ValueError as e:
        raise HTTPException(422, str(e))


class ScheduleEventReq(Wire):
    calendar_event_id: Optional[str] = None


@app.put("/v1/schedules/{schedule_id}/event", response_model=ScheduleWire)
def schedules_event(schedule_id: str, req: ScheduleEventReq):
    try:
        return groups.set_schedule_event(schedule_id, req.calendar_event_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.delete("/v1/schedules/{schedule_id}", response_model=ScheduleWire)
def schedules_remove(schedule_id: str, userId: str):
    try:
        return groups.remove_schedule(schedule_id, userId)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.post("/v1/groups", response_model=LunchGroupWire)
def groups_create(req: CreateGroupReq, date: Optional[str] = None):
    try:
        return groups.create(req, date)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/v1/groups/{group_id}/join", response_model=LunchGroupWire)
def groups_join(group_id: str, req: JoinGroupReq):
    try:
        return groups.join(group_id, req)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.delete("/v1/groups/{group_id}/members/{user_id}", response_model=LunchGroupWire)
def groups_leave(group_id: str, user_id: str):
    try:
        return groups.leave(group_id, user_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.get("/v1/ledger/{user_id}", response_model=LedgerWire)
def ledger(user_id: str, officeName: str = "", month: Optional[str] = None):
    try:
        return groups.ledger(user_id, officeName, month)
    except LookupError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- Ramp sandbox (formerly backend/server.py on :8787)

def _ramp_guard(request: Request) -> None:
    # Native clients only: no browser origins. The X-Camp-Token middleware still applies when set.
    if request.headers.get("origin") or request.headers.get("x-camp-client") != "camp-native":
        raise HTTPException(403, "This endpoint is reserved for the camp native app.")


@app.get("/v1/ramp")
def ramp_snapshot(request: Request):
    _ramp_guard(request)
    try:
        return ramp.snapshot()
    except Problem as e:
        raise HTTPException(e.status, str(e))


@app.post("/v1/ramp/allocations")
async def ramp_allocate(request: Request):
    _ramp_guard(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object.")
    try:
        return ramp.allocate(body)
    except Problem as e:
        raise HTTPException(e.status, str(e))
