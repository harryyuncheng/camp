"""FastAPI service over the core. Run: uv run uvicorn camp.api:app --reload"""
from __future__ import annotations

import os
import secrets
from datetime import date as Date
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import feedback as fb
from . import catalog, synth
from .ai.classify import default_classifier
from .ai.feedback_parse import parse_feedback
from .ai.modifications import modify
from .ai.tagging import tag_menu
from .explain import explain_llm
from .apns import APNsClient, APNsConfig
from .models import (ORDER_CATEGORIES, ActivityPushToken, ActivityStartToken, Context, EventType, FeedbackEvent, LunchGroup, MenuItem, Order,
                     Restaurant, User)
from .pipeline import plan_home, plan_office
from .providers import providers_from_env, sync_catalog
from .cli import _load_env_file
from .contracts import MealContext, MealOffer, OfficeRef, Wire
from .groups import (CreateGroupReq, GroupService, GroupsResponse, JoinGroupReq, LedgerWire, LunchGroupWire, MenuWire, RestaurantWire,
                     ScheduleReq, ScheduleWire)
from .offers import OfferService
from .ramp import Problem, RampService
from .search import CravingReq, CravingResponse, CravingService
from .store import Store
from .sync import LunchSyncService, SyncConflict

_load_env_file()
app = FastAPI(title="CAMP recommender")
store = Store.from_env()
clf = default_classifier()
offers = OfferService(store)
lunch_sync = LunchSyncService(store)
apns = APNsClient(APNsConfig.from_env())


async def _push_live_activity(record: dict, device: str) -> None:
    """Fans an accepted write out to the phone's Live Activity.

    With a per-activity token registered this is an update (or end) push — what makes a Mac-side change
    reach a *locked* phone: the long-poll in `LunchSyncCoordinator` only runs while camp is foregrounded,
    but APNs delivers to the activity without waking the app. Without one — the phone has never seen this
    session — a push-to-start on the device's registered start token raises the Live Activity even while
    camp is closed entirely (iOS 17.2+). The device that wrote is skipped either way; `started` records
    which sessions each device already renders so a later write can't spawn a duplicate activity.
    """
    if not apns.enabled:
        return
    session = record.get("session") or {}
    session_id = record.get("sessionId")
    if not isinstance(session_id, str):
        return
    finished = str(session.get("phase", "")) in ("delivered", "ended")
    row = store.get(ActivityPushToken, session_id)
    if row is not None and row.device != device:
        status, _ = await apns.send(
            row.push_token, session,
            event="end" if finished else "update",
            stale_at=session.get("closesAt"),
            dismiss_at=session.get("deliveredAt") or session.get("arrivesAt"),
        )
        # 410 Gone means the activity is over on the phone; stop pushing to a dead token.
        if status == 410 or finished:
            store.delete(ActivityPushToken, session_id)
        return
    if finished:
        return
    place = session.get("place")
    for start in store.all(ActivityStartToken):
        if start.id == device or session_id in start.started:
            continue
        status, _ = await apns.send(
            start.push_token, session, event="start",
            attributes_type="LunchAttributes",
            attributes={"sessionID": session.get("id")},
            stale_at=session.get("closesAt"),
            alert={"title": "camp", "body": f"New order · {place}" if place else "A new order is up"},
        )
        if status == 410:
            store.delete(ActivityStartToken, start.id)
        elif status == 200:
            start.started = sorted({*start.started, session_id})
            store.put(start)


async def _end_live_activities(removed: list[dict]) -> None:
    """A forgotten order ends every Live Activity still rendering it."""
    if not apns.enabled:
        return
    for record in removed:
        session_id = record.get("sessionId")
        if not isinstance(session_id, str):
            continue
        row = store.get(ActivityPushToken, session_id)
        if row is None:
            continue
        await apns.send(row.push_token, record.get("session") or {}, event="end")
        store.delete(ActivityPushToken, session_id)


lunch_sync.on_change = _push_live_activity
lunch_sync.on_remove = _end_live_activities
groups = GroupService(store)
cravings = CravingService(store)
ramp = RampService(store)


@app.middleware("http")
async def require_camp_token(request: Request, call_next):
    """Set CAMP_TOKEN when binding beyond loopback (`--host 0.0.0.0` for the phone): every request must carry
    it as X-Camp-Token. Unset, the service stays open, which is only acceptable on 127.0.0.1."""
    token = os.getenv("CAMP_TOKEN", "")
    if token and not secrets.compare_digest(request.headers.get("x-camp-token", "").encode(), token.encode()):
        return JSONResponse({"detail": "X-Camp-Token header missing or wrong"}, status_code=401)
    if not token and (request.headers.get("origin") or request.headers.get("sec-fetch-site") == "cross-site"):
        return JSONResponse({"detail": "Browser requests require CAMP_TOKEN."}, status_code=403)
    return await call_next(request)
if not store.all(User):
    u, r, i = synth.make_world(int(os.getenv("CAMP_USERS", "40")), None, 0)
    with store.transaction():
        store.put_many(u); store.put_many(r); store.put_many(i)
elif catalog.ensure_current(store):
    print("camp: replaced the stored restaurant catalog with the Ramp HQ dataset")


class RecommendReq(BaseModel):
    office_id: str = "hq"
    meal: Literal["lunch", "dinner"] = "lunch"
    date: Date | None = None
    temp_c: float = Field(default=18.0, allow_inf_nan=False)
    raining: bool = False


class FeedbackReq(BaseModel):
    user_id: str
    text: str | None = None
    order_id: str | None = None
    tap: dict | None = None            # {"type": "accept"|"change_item"|..., ...payload}
    confirm_constraint: bool = False

    @field_validator("tap")
    @classmethod
    def validate_tap(cls, tap: dict | None) -> dict | None:
        if tap is None:
            return tap
        FeedbackEvent(user_id="validation", type=tap.get("type"), item_id=tap.get("item_id"))
        kind: EventType = tap["type"]
        if kind == "preference":
            if not isinstance(tap.get("attribute"), str) or not tap["attribute"].strip():
                raise ValueError("preference needs an attribute")
            if tap.get("direction") not in ("more", "less", "never"):
                raise ValueError("preference needs direction more, less or never")
        if kind == "constraint":
            which = tap.get("which")
            if not isinstance(which, str) or ":" not in which:
                raise ValueError("constraint needs which as allergen:name or diet:name")
            prefix, value = which.split(":", 1)
            if prefix not in ("allergen", "diet") or not value or tap.get("action") not in ("add", "remove"):
                raise ValueError("invalid constraint or action")
        for field in ("overall", "portion", "temperature"):
            if field in tap and (type(tap[field]) is not int or not 0 <= tap[field] <= 4):
                raise ValueError(f"{field} must be an integer from 0 to 4")
        for field in ("addons", "shown_item_ids"):
            if field in tap and (not isinstance(tap[field], list) or not all(isinstance(x, str) for x in tap[field])):
                raise ValueError(f"{field} must be a list of strings")
        if tap.get("from_item_id") is not None and not isinstance(tap["from_item_id"], str):
            raise ValueError("from_item_id must be a string")
        for field in ("severe", "confirmed", "too_heavy", "repeated", "old_was_novel", "novel"):
            if field in tap and type(tap[field]) is not bool:
                raise ValueError(f"{field} must be a boolean")
        return tap


class ModifyReq(BaseModel):
    order_id: str
    text: str
    now_minutes: int = Field(default=10 * 60, ge=0, lt=1440)


@app.post("/batch/run")
async def batch_run(req: RecommendReq):
    d = req.date or Date.today()
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
    d = req.date or Date.today()
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
    if store.get(User, req.user_id) is None:
        raise HTTPException(404, "unknown user")
    o = store.get(Order, req.order_id) if req.order_id else None
    if req.order_id and (o is None or o.user_id != req.user_id):
        raise HTTPException(404, "unknown order for this user")
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
    with store.transaction():
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
async def catalog_sync(radius_km: float = Query(6.0, gt=0, le=50, allow_inf_nan=False), tag: bool = False):
    provs = providers_from_env()
    tagger = (lambda items: tag_menu(clf, items)) if tag else None
    rep = await sync_catalog(store, provs, synth.OFFICE, radius_km, tagger=tagger)
    return dict(providers=[p.name for p in provs], stores_seen=rep.stores_seen, merged=rep.merged, restaurants=rep.restaurants,
                items=rep.items, skipped=rep.skipped_providers, errors=rep.errors[:10])


# ---------------------------------------------------------------- native app contract (docs/INTEGRATION-PLAN.md §4)

@app.get("/v1/health")
def health():
    return dict(service="camp-recommender", version="0.2.0", classifier=type(clf).__name__,
                database="postgres" if store.pg else "sqlite",
                providers=[p.name for p in providers_from_env()], users=len(store.all(User)), restaurants=len(store.all(Restaurant)),
                items=len(store.all(MenuItem)), orders=store.count(Order), groups=store.count(LunchGroup), ramp=ramp.configured)


@app.post("/v1/meal-offers", response_model=MealOffer)
def meal_offers(ctx: MealContext, force: bool = False):
    try:
        return offers.offer(ctx, force=force)
    except ValueError as e:
        raise HTTPException(422, str(e))


class LunchEventReq(Wire):
    offer_id: str
    option_id: Optional[str] = None
    event: Literal["confirmed", "delivered", "ended"]
    rating: Optional[int] = Field(default=None, ge=0, le=4, strict=True)


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
    expected_revision: Optional[int] = Field(default=None, ge=0, strict=True)
    device: str = Field(default="unknown", min_length=1, max_length=128)


@app.get("/v1/lunch-session")
async def lunch_session(since: Optional[int] = Query(None, ge=0), wait: float = Query(0, allow_inf_nan=False)):
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


class ActivityTokenReq(Wire):
    session_id: str = Field(min_length=1, max_length=128)
    push_token: str = Field(min_length=1, max_length=512)
    device: str = Field(default="iphone", min_length=1, max_length=128)
    environment: str = Field(default="sandbox", pattern="^(sandbox|production)$")


@app.post("/v1/lunch-session/push-token")
def lunch_session_push_token(req: ActivityTokenReq):
    """The phone registers its Live Activity's APNs token here, and again whenever iOS rotates it."""
    if not all(c in "0123456789abcdefABCDEF" for c in req.push_token):
        raise HTTPException(422, "push_token must be hex")
    store.put(ActivityPushToken(id=req.session_id, push_token=req.push_token.lower(),
                                device=req.device, environment=req.environment))
    # A device already rendering the session must never get a push-to-start for it, so remember it.
    start = store.get(ActivityStartToken, req.device)
    if start is not None and req.session_id not in start.started:
        start.started = sorted([*start.started, req.session_id])
        store.put(start)
    return {"registered": req.session_id, "pushEnabled": apns.enabled}


class ActivityStartTokenReq(Wire):
    push_token: str = Field(min_length=1, max_length=512)
    device: str = Field(default="iphone", min_length=1, max_length=128)
    environment: str = Field(default="sandbox", pattern="^(sandbox|production)$")


@app.post("/v1/lunch-session/push-start-token")
def lunch_session_push_start_token(req: ActivityStartTokenReq):
    """The phone's ActivityKit push-to-start token lets a new order from another device raise a Live
    Activity while camp is closed (iOS 17.2+). Re-registered whenever iOS rotates the token; `started`
    carries over so re-registration doesn't forget which sessions this device already renders."""
    if not all(c in "0123456789abcdefABCDEF" for c in req.push_token):
        raise HTTPException(422, "push_token must be hex")
    existing = store.get(ActivityStartToken, req.device)
    store.put(ActivityStartToken(id=req.device, push_token=req.push_token.lower(),
                                 environment=req.environment,
                                 started=existing.started if existing else []))
    return {"registered": req.device, "pushEnabled": apns.enabled}


@app.delete("/v1/lunch-session/push-token")
def lunch_session_drop_push_token(sessionId: str):
    """Called when the activity ends on the phone."""
    store.delete(ActivityPushToken, sessionId)
    return {"dropped": sessionId}


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
def debug_events(limit: int = Query(50, ge=1, le=500)):
    evs = sorted(store.all(FeedbackEvent), key=lambda e: e.created_at)[-limit:]
    return [e.model_dump() for e in evs]


@app.post("/v1/debug/feedback")
async def debug_feedback(req: DebugFeedbackReq):
    if store.get(User, req.user_id) is None:
        raise HTTPException(404, "unknown user")
    res = await parse_feedback(clf, req.text, req.user_id)
    logs = []
    with store.transaction():
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
    try:
        with store.transaction():
            offers.ensure_world(ctx.office)
            u, created = offers.user_for(ctx)
            u.app_settings = ctx.model_dump(by_alias=True, exclude={"user_id", "now_minutes"})
            store.put(u)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return dict(userId=u.id, created=created, learned=fb.learned_view(u), restrictions=[r.model_dump() for r in u.restrictions],
                budgetCents=u.budget_cents.get(ctx.meal, 0))


@app.get("/v1/profile/{user_id}")
def profile_get(user_id: str):
    u = store.get(User, user_id)
    if not u:
        raise HTTPException(404, "unknown user")
    return dict(userId=u.id, name=u.name, officeId=u.office_id, settings=u.app_settings, learned=fb.learned_view(u),
                restrictions=[r.model_dump() for r in u.restrictions], budgetCents=u.budget_cents, orders=len(store.orders_for(u.id)))


# ---------------------------------------------------------------- lunch groups (Today page)

@app.get("/v1/groups", response_model=GroupsResponse)
def groups_today(officeId: str = "demo-office", userId: Optional[str] = None, date: Optional[Date] = None,
                 deliveryStart: int = Query(750, ge=0, lt=1440),
                 latitude: float = Query(40.7424, ge=-90, le=90), longitude: float = Query(-73.9913, ge=-180, le=180),
                 officeName: str = "Office"):
    office = OfficeRef(id=officeId, name=officeName, latitude=latitude, longitude=longitude, delivery_start=deliveryStart)
    try:
        return groups.today(office, userId, date.isoformat() if date else None)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/v1/restaurants", response_model=list[RestaurantWire])
def restaurants(limit: int = Query(12, ge=1, le=100), category: Optional[str] = None):
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
    except ValueError as e:
        raise HTTPException(422, str(e))


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
    user_id: str = Field(min_length=1)
    calendar_event_id: Optional[str] = None


@app.put("/v1/schedules/{schedule_id}/event", response_model=ScheduleWire)
def schedules_event(schedule_id: str, req: ScheduleEventReq):
    try:
        return groups.set_schedule_event(schedule_id, req.calendar_event_id, req.user_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.delete("/v1/schedules/{schedule_id}", response_model=ScheduleWire)
def schedules_remove(schedule_id: str, userId: str):
    try:
        return groups.remove_schedule(schedule_id, userId)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.post("/v1/groups", response_model=LunchGroupWire)
def groups_create(req: CreateGroupReq, date: Optional[Date] = None):
    try:
        return groups.create(req, date.isoformat() if date else None)
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
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/v1/ledger/{user_id}", response_model=LedgerWire)
def ledger(user_id: str, officeName: str = "", month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    try:
        return groups.ledger(user_id, officeName, month)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


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
def ramp_allocate(request: Request, body: dict):
    _ramp_guard(request)
    try:
        return ramp.allocate(body)
    except Problem as e:
        raise HTTPException(e.status, str(e))


@app.get("/v1/ramp/limits/{user_id}")
def ramp_limits(user_id: str, request: Request):
    """The employee's real Ramp limits, so the app stops showing a local demo budget."""
    _ramp_guard(request)
    try:
        return ramp.spend_limits(user_id)
    except Problem as e:
        raise HTTPException(e.status, str(e))


@app.post("/v1/ramp/overages")
def ramp_request_overage(request: Request, body: dict):
    _ramp_guard(request)
    try:
        return ramp.request_overage(body)
    except Problem as e:
        raise HTTPException(e.status, str(e))


@app.post("/v1/ramp/overages/{request_id}/decision")
def ramp_decide_overage(request_id: str, request: Request, body: dict):
    _ramp_guard(request)
    try:
        return ramp.decide_overage(request_id, body)
    except Problem as e:
        raise HTTPException(e.status, str(e))
