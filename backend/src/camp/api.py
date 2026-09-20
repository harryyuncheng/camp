"""FastAPI service over the core. Run: uv run uvicorn camp.api:app --reload"""
from __future__ import annotations

import os
from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import feedback as fb
from . import synth
from .ai.classify import default_classifier
from .ai.feedback_parse import parse_feedback
from .ai.modifications import modify
from .ai.tagging import tag_menu
from .explain import explain_llm
from .models import Context, FeedbackEvent, MenuItem, Order, Restaurant, User
from .pipeline import plan_home, plan_office
from .providers import providers_from_env, sync_catalog
from typing import Literal, Optional

from .contracts import MealContext, MealOffer, Wire
from .offers import OfferService
from .store import Store

app = FastAPI(title="CAMP recommender")
store = Store(os.getenv("CAMP_DB", "camp.db"))
clf = default_classifier()
offers = OfferService(store)
if not store.all(User):
    u, r, i = synth.make_world(int(os.getenv("CAMP_USERS", "40")), 12, 0)
    store.put_many(u); store.put_many(r); store.put_many(i)


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
    return dict(service="camp-recommender", version="0.1.0", classifier=type(clf).__name__,
                providers=[p.name for p in providers_from_env()], users=len(store.all(User)), restaurants=len(store.all(Restaurant)),
                items=len(store.all(MenuItem)))


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
