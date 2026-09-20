"""MealContext → durable MealOffer bridge, plus in-memory debug state."""
from __future__ import annotations

import statistics
import re
import hashlib
from datetime import date, datetime, timedelta
from typing import Any

from . import batching, catalog, explain, feedback as fb, filters, scoring, synth
from .contracts import MealContext, MealOffer, MealOfferOption, OfficeRef
from .filters import haversine_km
from .models import Batch, Context, FeedbackEvent, LatLng, MealWindow, MenuItem, OfferRecord, Order, OrderLine, Restaurant, Restriction, User, new_id, utcnow
from .pipeline import MealPlan, plan_home, plan_office
from .store import Store

_ALLERGY_WORDS = {"peanut": "peanut", "peanuts": "peanut", "nut": "tree_nut", "nuts": "tree_nut", "tree nut": "tree_nut", "almond": "tree_nut",
                  "shellfish": "shellfish", "shrimp": "shellfish", "fish": "fish", "dairy": "dairy", "milk": "dairy", "lactose": "dairy",
                  "egg": "egg", "eggs": "egg", "gluten": "gluten", "wheat": "gluten", "soy": "soy", "sesame": "sesame"}
_DIET_STYLE = {"Vegetarian": "vegetarian", "Vegan": "vegan", "Halal": "halal", "Gluten-free": "gluten_free"}
_SYMBOL = {"salad": "leaf.fill", "bowl": "takeoutbag.and.cup.and.straw.fill", "soup": "cup.and.saucer.fill", "pizza": "circle.grid.cross.fill",
           "curry": "flame.fill", "noodles": "fork.knife", "rice": "fork.knife", "sandwich": "sun.max.fill", "wrap": "sun.max.fill", "taco": "flame.fill"}


EXPLORATION = 0.25    # score jitter per request; affinity is ~[-1, 1], so this reshuffles near-ties, not clear favourites


class OfferService:
    def __init__(self, store: Store):
        self.store = store
        self.plans: dict[tuple[str, str, str], MealPlan] = {}
        self.last: dict[str, Any] = {"context": None, "offer": None, "seeded": []}
        self.offers: dict[str, dict] = {}     # legacy caller-supplied mappings, promoted on the first event

    # ------------------------------------------------------------ world + user sync
    def ensure_world(self, office: OfficeRef) -> None:
        loc = LatLng(lat=office.latitude, lng=office.longitude)
        seed = int.from_bytes(hashlib.sha256(office.id.encode()).digest()[:2], "big")
        if catalog.ensure_current(self.store, center=loc, seed=seed):     # legacy/synthetic or mis-centred catalog → replace
            self.last["seeded"].append(f"loaded the Ramp HQ catalog ({len(self.store.all(Restaurant))} restaurants) around {office.name}")
            self.plans.clear()
        if not self.store.users_in_office(office.id):
            users, _, _ = synth.make_world(16, None, seed=seed, center=loc)
            for u in users:
                u.office_id = office.id
                u.synthetic = True
            self.store.put_many(users)
            self.last["seeded"].append(f"seeded {len(users)} colleagues at {office.name}")
            self.plans.clear()

    def user_for(self, ctx: MealContext) -> tuple[User, bool]:
        with self.store.transaction():
            return self._user_for(ctx)

    def _user_for(self, ctx: MealContext) -> tuple[User, bool]:
        u = self.store.get(User, ctx.user_id) if ctx.user_id else None
        if ctx.user_id and (u is None or u.synthetic or u.office_id != ctx.office.id):
            raise ValueError("unknown user for this office")
        created = False
        if u is None:
            u = next((x for x in self.store.all(User) if not x.synthetic and x.name == ctx.display_name and x.office_id == ctx.office.id), None)
        if u is None:
            u = User(name=ctx.display_name, office_id=ctx.office.id, home=LatLng(lat=ctx.office.latitude, lng=ctx.office.longitude))
            created = True
        u.budget_cents[ctx.meal] = ctx.budget_cents
        u.windows[ctx.meal] = MealWindow(start=max(ctx.lunch_start, ctx.office.delivery_start), end=ctx.lunch_end, min_eat_minutes=ctx.lunch_duration)
        # restrictions from the app are authoritative for onboarding-sourced ones; NL-confirmed ones are kept
        keep = [r for r in u.restrictions if r.source != "onboarding"]
        new: list[Restriction] = []
        for raw in ctx.allergies:
            matched = False
            for word, a in _ALLERGY_WORDS.items():
                if re.search(rf"\b{re.escape(word)}\b", raw.lower()):
                    matched = True
                    existing = next((r for r in new if r.value == a), None)
                    if existing:
                        existing.severe = existing.severe or "severe" in raw.lower()
                        continue
                    new.append(Restriction(kind="allergen", value=a, severe="severe" in raw.lower()))
            if not matched and raw.strip():
                new.append(Restriction(kind="allergen", value=raw.strip().lower(), severe=True))
        if ctx.dietary_style in _DIET_STYLE:
            new.append(Restriction(kind="diet", value=_DIET_STYLE[ctx.dietary_style]))
        for kept in keep:
            match = next((n for n in new if (n.kind, n.value) == (kept.kind, kept.value)), None)
            if match:
                match.severe = match.severe or kept.severe
                match.source = kept.source
            else:
                new.append(kept)
        u.restrictions = new
        for raw in ctx.dislikes:
            d = raw.strip().lower()
            if d:
                u.prefs.stated[f"ingredient:{d}"] = -0.8
        self.store.put(u)
        if created:
            self.plans.clear()      # a new colleague changes the batch
        return u, created

    # ------------------------------------------------------------ offer
    def _context(self, ctx: MealContext) -> Context:
        d = date.today()
        clock = datetime.now()
        now = ctx.now_minutes if ctx.now_minutes is not None else clock.hour * 60 + clock.minute
        return Context(date=d.isoformat(), meal=ctx.meal, weekday=d.weekday(), temp_c=ctx.temp_c, raining=ctx.raining,
                       order_time_minutes=now, exploration=EXPLORATION, nonce=new_id("n"))

    def offer(self, ctx: MealContext, force: bool = False) -> MealOffer:   # force kept for API compatibility
        with self.store.transaction():
            return self._offer(ctx)

    def _offer(self, ctx: MealContext) -> MealOffer:
        self.ensure_world(ctx.office)
        u, _ = self.user_for(ctx)
        c = self._context(ctx)
        office_loc = LatLng(lat=ctx.office.latitude, lng=ctx.office.longitude)
        location = "home" if ctx.presence == "outside" else "office"
        key = (ctx.office.id, c.date, c.meal)
        if location == "office":
            # every explicit request re-plans with a fresh nonce, so a refreshed offer explores different options;
            # the cached plan is still used by lunch_event / snapshot between requests
            live = {u.id: "office"}
            plan = plan_office(self.store, ctx.office.id, office_loc, c, live_location=live)
            self.plans[key] = plan
        else:
            plan = plan_home(self.store, u, office_loc, c)
        rests = {r.id: r for r in self.store.all(Restaurant)}
        items = {i.id: i for i in self.store.all(MenuItem)}
        share = {br.restaurant_id: br.fee_share_cents for br in plan.batch.restaurants} if plan.batch else {}
        heads = {br.restaurant_id: len(br.user_ids) for br in plan.batch.restaurants} if plan.batch else {}
        options = []
        for k, rec in enumerate(plan.recommendations.get(u.id, [])[:3]):
            it, r = items[rec.item_id], rests[rec.restaurant_id]
            fee_share = share.get(r.id, r.fees.delivery_fee_cents)
            total = filters.total_cost_cents(it, r, fee_share)
            baseline = filters.total_cost_cents(it, r, r.fees.delivery_fee_cents)
            detail = explain.explain_template(u, it, rec).split(": ", 1)[-1]
            options.append(MealOfferOption(id=it.id, name=it.name, detail=detail, symbol=_SYMBOL.get((it.tags.dish_type if it.tags else "") or "", "fork.knife"),
                                           price_cents=total, baseline_cents=baseline, item_price_cents=it.price_cents, restaurant=r.name,
                                           restaurant_id=r.id, item_id=it.id, score=round(rec.score, 4), novel=rec.novel,
                                           breakdown={a: round(b, 4) for a, b in rec.breakdown.items()}))
        default_rid = options[0].restaurant_id if options else None
        today = datetime.combine(date.today(), datetime.min.time()).astimezone()
        offer = MealOffer(offer_id=new_id("offer"), user_id=u.id, office_id=ctx.office.id, group_id=plan.batch.id if plan.batch and u.id in {o.user_id for o in plan.orders} else None,
                          location=location, closes_at=(today + timedelta(minutes=ctx.office.cutoff)).isoformat(),
                          arrives_at=(today + timedelta(minutes=ctx.office.delivery_start)).isoformat(), options=options,
                          participants=heads.get(default_rid, 1) if location == "office" else 1,
                          shared_delivery_cents=share.get(default_rid, 0) if default_rid else 0,
                          separate_delivery_cents=rests[default_rid].fees.delivery_fee_cents if default_rid else 0,
                          suggest_only=u.id in plan.suggest_only,
                          note="" if options else "No feasible meals: " + self._why_empty(u, plan))
        my_order = next((o for o in plan.orders if o.user_id == u.id), None)
        self.store.put(OfferRecord(id=offer.offer_id, wire=offer,
                                           user_id=u.id, order_id=my_order.id if my_order else None, default_item_id=options[0].item_id if options else None,
                                           shown=[o.item_id for o in options], novel=options[0].novel if options else False, meal=ctx.meal, date=c.date,
                                           location=location, fee_share=share, plan_key=key, office=ctx.office.model_dump(),
                                           context=c.model_dump(), now_minutes=ctx.now_minutes))
        self.last["context"], self.last["offer"], self.last["plan_key"] = ctx.model_dump(by_alias=True), offer.model_dump(by_alias=True), key
        return offer

    # ------------------------------------------------------------ lunch lifecycle from the card
    def lunch_event(self, offer_id: str, option_id: str | None, event: str, rating: int | None = None) -> dict:
        with self.store.transaction():
            return self._lunch_event(offer_id, option_id, event, rating)

    def _lunch_event(self, offer_id: str, option_id: str | None, event: str, rating: int | None = None) -> dict:
        """confirmed → the pick becomes the order + accept/change events. delivered → order delivered (+ optional rating).
        ended (before confirm) → skip event, ignored per §6.1."""
        record = self.store.get(OfferRecord, offer_id)
        if record is None and offer_id in self.offers:
            record = OfferRecord(id=offer_id, **self.offers[offer_id])
        if record is None:
            return {"error": "unknown offer; request a new lunch offer"}
        meta = record.model_dump()
        if event not in ("confirmed", "delivered", "ended"):
            return {"error": "unknown event"}
        if rating is not None and (event != "delivered" or rating not in range(5)):
            return {"error": "rating must be between 0 and 4 on delivery"}
        u = self.store.get(User, meta["user_id"])
        if u is None:
            return {"error": "unknown user"}
        items = {i.id: i for i in self.store.all(MenuItem)}
        rests = {r.id: r for r in self.store.all(Restaurant)}
        order = self.store.get(Order, meta["order_id"]) if meta["order_id"] else None
        logs: list[str] = []
        events: list[FeedbackEvent] = []
        if event == "confirmed":
            if option_id not in meta["shown"]:
                return {"error": "option was not shown in this offer"}
            if meta.get("ended") or (order and order.status == "cancelled"):
                return {"error": "offer has ended"}
            if order and order.status == "confirmed":
                if order.line.item_id != option_id:
                    return {"error": "offer is already confirmed with another option"}
                return dict(orderId=order.id, status=order.status, events=[], profileUpdates=["already confirmed"],
                            learned=fb.learned_view(u), epsilon=round(u.traits.epsilon, 3), autonomy=u.traits.autonomy)
            if record.wire and record.now_minutes is None and utcnow() >= datetime.fromisoformat(record.wire.closes_at):
                return {"error": "offer has expired; request a new offer"}
            item = items.get(option_id or "")
            if not item or item.restaurant_id not in rests:
                return {"error": "unknown option"}
            r = rests[item.restaurant_id]
            fee = meta["fee_share"].get(r.id, r.fees.delivery_fee_cents)
            if not filters.passes_dietary(u, item)[0] or not filters.passes_budget(u, item, r, meta["meal"], fee)[0]:
                return {"error": "option no longer fits your dietary settings or budget; request a new offer"}
            office = OfficeRef.model_validate(meta["office"])
            c = Context.model_validate(meta["context"])
            clock = datetime.now()
            c.order_time_minutes = meta["now_minutes"] if meta["now_minutes"] is not None else clock.hour * 60 + clock.minute
            if meta["date"] != date.today().isoformat() or (meta["location"] == "office" and c.order_time_minutes > office.cutoff):
                return {"error": "offer has expired; request a new offer"}
            if not filters.passes_location(u, r, meta["location"], LatLng(lat=office.latitude, lng=office.longitude))[0]:
                return {"error": "option no longer delivers to your location"}
            batch = self.store.get(Batch, order.batch_id) if order and order.batch_id else None
            headcount = next((len(br.user_ids) + (u.id not in br.user_ids) for br in batch.restaurants if br.restaurant_id == r.id), 1) if batch else 1
            if headcount > r.max_meals_per_slot or not filters.passes_time(u, r, c, headcount)[0]:
                return {"error": "option no longer fits the delivery window or restaurant capacity"}
            line = OrderLine(item_id=item.id, restaurant_id=r.id, price_cents=item.price_cents)
            if order is None:   # suggest-only / home users had no order yet
                default = items.get(meta["default_item_id"] or item.id, item)
                order = Order(user_id=u.id, date=meta["date"], meal=meta["meal"], location=meta["location"], line=line,
                              default_line=OrderLine(item_id=default.id, restaurant_id=default.restaurant_id, price_cents=default.price_cents),
                              shown_item_ids=meta["shown"], fee_share_cents=fee, novel=meta["novel"])
                meta["order_id"] = order.id
            order.line, order.fee_share_cents = line, fee
            order.total_cents = filters.total_cost_cents(item, r, fee)
            order.baseline_cents = filters.total_cost_cents(item, r, r.fees.delivery_fee_cents)
            order.item_name, order.restaurant_name = item.name, r.name
            order.item_symbol = _SYMBOL.get((item.tags.dish_type if item.tags else "") or "", "fork.knife")
            order.office_id, order.office_name = office.id, office.name
            order.status = "confirmed"
            meta["selected_option_id"] = item.id
            if batch:
                regret = batch.regret.get(u.id, -1)
                if regret > batching.DELTA_REGRET:
                    u.traits.sacrifice_debt += regret - batching.DELTA_REGRET
                elif regret >= 0:
                    u.traits.sacrifice_debt *= 0.5
            self.store.put_many([order, u])
            default_id = meta["default_item_id"]
            if item.id == default_id:
                events.append(FeedbackEvent(id=f"{offer_id}:confirmed", user_id=u.id, type="accept", order_id=order.id, item_id=item.id, payload=dict(novel=meta["novel"]), source="tap"))
            else:
                same_r = items[default_id].restaurant_id == r.id if default_id in items else True
                events.append(FeedbackEvent(id=f"{offer_id}:confirmed", user_id=u.id, type="change_item" if same_r else "change_restaurant", order_id=order.id, item_id=item.id,
                                            payload=dict(from_item_id=default_id, old_was_novel=meta["novel"], shown_item_ids=meta["shown"]), source="tap"))
        elif event == "delivered":
            if meta["ended"]:
                return {"error": "offer has ended"}
            if not order or order.status != "confirmed":
                return {"error": "confirm the offer before marking it delivered"}
            if rating is not None:
                events.append(FeedbackEvent(id=f"{offer_id}:rating", user_id=u.id, type="rating", order_id=order.id, item_id=order.line.item_id, payload=dict(overall=rating), source="tap"))
            else:
                logs.append("delivered without a rating: enjoyment unknown (not neutral); the order itself now counts in history")
        elif event == "ended":
            meta["ended"] = True
            if order and order.status == "proposed":
                order.status = "cancelled"
                self.store.put(order)
                events.append(FeedbackEvent(id=f"{offer_id}:ended", user_id=u.id, type="skip", order_id=order.id, source="tap"))
        for ev in events:
            logs += fb.apply_event(self.store, ev)
        meta["state"], meta["updated_at"] = event, utcnow()
        self.store.put(OfferRecord.model_validate(meta))
        # the profile and history changed: the next offer must re-plan instead of reusing today's cached batch
        self.plans.pop(meta.get("plan_key"), None)
        u = self.store.get(User, u.id)
        return dict(orderId=order.id if order else None, status=order.status if order else None,
                    events=[dict(type=e.type, payload=e.payload) for e in events], profileUpdates=logs, learned=fb.learned_view(u),
                    epsilon=round(u.traits.epsilon, 3), autonomy=u.traits.autonomy)

    def _why_empty(self, u: User, plan: MealPlan) -> str:
        if u.id in plan.unassigned:
            return "nothing fit budget/time; try a higher budget or wider window"
        return "no items passed the hard filters (check allergies and diet)"

    # ------------------------------------------------------------ debug
    def snapshot(self) -> dict:
        key = self.last.get("plan_key")
        plan = self.plans.get(key) if key else None
        rests = {r.id: r for r in self.store.all(Restaurant)}
        users = {x.id: x for x in self.store.all(User)}
        batch = None
        if plan and plan.batch:
            regs = [v for v in plan.batch.regret.values() if v >= 0]
            batch = dict(id=plan.batch.id, solver=plan.solver, objective=round(plan.batch.objective, 3), totalCostCents=plan.batch.total_cost_cents,
                         restaurants=[dict(name=rests[b.restaurant_id].name, headcount=len(b.user_ids), feeShareCents=b.fee_share_cents,
                                           deliveryFeeCents=rests[b.restaurant_id].fees.delivery_fee_cents,
                                           users=[users[x].name for x in b.user_ids if x in users]) for b in plan.batch.restaurants],
                         regret=dict(mean=round(statistics.mean(regs), 3) if regs else 0, max=round(max(regs), 3) if regs else 0, above_delta=sum(r > 0.5 for r in regs)),
                         suggestOnly=[users[x].name for x in plan.suggest_only if x in users], unassigned=[users[x].name for x in plan.unassigned if x in users],
                         orders=len(plan.orders))
        return dict(lastContext=self.last.get("context"), lastOffer=self.last.get("offer"), batch=batch, seeded=self.last["seeded"],
                    counts=dict(users=len(users), restaurants=len(rests), items=len(self.store.all(MenuItem))))

    def user_debug(self, user_id: str) -> dict:
        u = self.store.get(User, user_id)
        if not u:
            return {"error": "unknown user"}
        rests = {r.id: r for r in self.store.all(Restaurant)}
        items = self.store.all(MenuItem)
        ctx = self.last.get("context")
        office = OfficeRef(**{k: v for k, v in (ctx or {}).get("office", {}).items()}) if ctx and ctx.get("office") else None
        loc = LatLng(lat=office.latitude, lng=office.longitude) if office else u.home
        c = Context(date=date.today().isoformat(), meal="lunch", weekday=date.today().weekday())
        feas = filters.feasible([u], rests, items, c, loc, lambda _: "office", lambda _, r: 0)
        reasons: dict[str, int] = {}
        for why in feas.reasons[u.id].values():
            k = why.split(":")[0] if why.startswith(("distance", "cost", "arrival")) else ":".join(why.split(":")[:2]); reasons[k] = reasons.get(k, 0) + 1
        h = scoring.History.from_orders(self.store.orders_for(u.id), {i.id: i for i in items}, rests, date.today().toordinal())
        ranked = scoring.rank(u, feas.items_for(u.id), rests, c, h, "office")[:12]
        return dict(user=u.model_dump(), learned=fb.learned_view(u), filterRejections=reasons, feasibleCount=len(feas.items_for(u.id)),
                    topCandidates=[dict(item=i.name, restaurant=rests[i.restaurant_id].name, score=round(s, 3), breakdown={a: round(b, 3) for a, b in br.items()}) for i, s, br in ranked],
                    events=[e.model_dump() for e in self.store.events_for(u.id)[-20:]], orders=[o.model_dump() for o in self.store.orders_for(u.id)[-10:]])
