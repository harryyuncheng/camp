"""Group orders for the Today page: pending office group orders, one restaurant, category and delivery slot each.
Categories are "coffee" (morning coffee / tea / pastries) and "meal"; a person holds one order per category per day.

The database is the authority for membership. Joining upserts the member's Order (source="group") and leaving
cancels it, so the Spending page, the recommender's history and the group list all read the same rows.
A day with no groups is seeded from the real catalog with synthetic colleagues (flagged `seeded`), so the
demo never shows an empty office while still exercising the same code path as user-created groups.
"""
from __future__ import annotations

import random
from datetime import date as _date, datetime
from typing import Optional

from . import filters, scoring, synth
from .contracts import OfficeRef, Wire
from .models import (Context, GroupMember, GroupOption, LatLng, LunchGroup, MenuItem, Order, OrderLine, OrderCategory,
                     Restaurant, ScheduledOrder, User)
from .store import Store

MAX_ITEMS_PER_MEMBER = 8               # one person's group order: a main plus sides/drinks, not a catering run

_COFFEE_WORDS = ("coffee", "latte", "espresso", "cappuccino", "americano", "cortado", "macchiato", "mocha", "cold brew",
                 "matcha", "chai", "tea", "hot chocolate", "flat white", "drip", "brew")
_SYMBOL = {"salad": "leaf.fill", "bowl": "takeoutbag.and.cup.and.straw.fill", "soup": "cup.and.saucer.fill", "pizza": "circle.grid.cross.fill",
           "curry": "flame.fill", "noodles": "fork.knife", "rice": "fork.knife", "sandwich": "sun.max.fill", "wrap": "sun.max.fill",
           "taco": "flame.fill", "burger": "flame.fill"}


def cuisine_label(r: Restaurant) -> str:
    detail = (r.cuisine_detail or "").strip()
    return detail if 0 < len(detail) <= 40 else r.cuisine.replace("_", " ").title()


def is_drink(item: MenuItem) -> bool:
    name = item.name.lower()
    return any(w in name for w in _COFFEE_WORDS)


def symbol_for(item: MenuItem) -> str:
    if is_drink(item):
        return "cup.and.saucer.fill"
    return _SYMBOL.get((item.tags.dish_type if item.tags else "") or "", "fork.knife")


def shrunk_rating(r: Restaurant, prior: float = 4.2, weight: int = 40) -> float:
    """A 5.0 from six reviews should not outrank a 4.6 from three thousand: pull sparse ratings towards a 4.2 prior."""
    if r.rating is None:
        return prior - 0.3
    n = r.review_count
    return (r.rating * n + prior * weight) / (n + weight)


def category_label(category: str) -> str:
    return "Coffee & tea" if category == "coffee" else "Meal"


def time_label(minutes: int) -> str:
    h, m = divmod(minutes % (24 * 60), 60)
    suffix = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12}:{m:02d} {suffix}"


def window_label(start: int, length: int = 15) -> str:
    a, b = time_label(start), time_label(start + length)
    if a[-2:] == b[-2:]:
        a = a[:-3]
    return f"{a}–{b}"


# ---------------------------------------------------------------- wire shapes (camelCase, decoded by Swift's DemoLunchGroup)

class GroupOptionWire(Wire):
    id: str
    name: str
    detail: str
    symbol: str
    price_cents: int                       # all-in with the delivery fee shared across current participants
    baseline_cents: int                    # all-in ordering alone
    item_price_cents: int


class GroupMemberWire(Wire):
    user_id: str
    display_name: str
    option_id: str                         # the first item, for clients written before multi-item orders
    option_ids: list[str] = []


class LunchGroupWire(Wire):
    id: str
    name: str
    category: OrderCategory = "meal"
    cuisine: str
    symbol: str
    people: int                            # participants other than the requesting user (the app adds itself)
    delivery: str
    arrival_minutes: int
    options: list[GroupOptionWire]
    restaurant_id: str
    participants: int
    savings_cents: int
    delivery_fee_cents: int
    status: str
    seeded: bool
    total_cents: int                       # what the whole group costs all-in right now (sum of members' meals)
    members: list[GroupMemberWire]
    my_option_id: Optional[str] = None     # the first of `my_option_ids`
    my_option_ids: list[str] = []          # everything the requesting user ordered here
    budget_cents: int = 0                  # the requesting user's per-order cap, so the menu can grey out what no longer fits
    user_id: Optional[str] = None          # the requesting user as the backend resolved (or created) it


class RestaurantWire(Wire):
    id: str
    name: str
    cuisine: str
    symbol: str
    rating: Optional[float] = None
    review_count: int = 0
    categories: list[str] = ["meal"]
    options: list[GroupOptionWire]


class MenuItemWire(Wire):
    id: str
    name: str
    detail: str
    symbol: str
    price_cents: int                       # all-in with the delivery share (same basis as GroupOptionWire.price_cents)
    item_price_cents: int
    popular: bool = False
    drink: bool = False
    score: Optional[float] = None          # recommender score for this user (None when there is no user yet)
    reason: str = ""


class MenuWire(Wire):
    """Everything the group-order sheet shows: the place's public rating, the user's top picks, then the whole menu."""
    restaurant_id: str
    name: str
    cuisine: str
    category: OrderCategory = "meal"
    rating: Optional[float] = None
    review_count: int = 0
    ratings: dict[str, float] = {}
    recommendations: list[str] = []
    address: str = ""
    top: list[MenuItemWire]
    items: list[MenuItemWire]


class ScheduleWire(Wire):
    id: str
    category: OrderCategory
    label: str
    restaurant_id: Optional[str] = None
    restaurant_name: str = ""
    option_id: Optional[str] = None
    time_minutes: int
    weekdays: list[int]
    active: bool
    calendar_event_id: Optional[str] = None


class ScheduleReq(Wire):
    office: OfficeRef
    user_id: Optional[str] = None
    display_name: str = "You"
    category: OrderCategory = "meal"
    label: str = ""
    restaurant_id: Optional[str] = None
    option_id: Optional[str] = None
    time_minutes: int
    weekdays: list[int] = [0, 1, 2, 3, 4]
    calendar_event_id: Optional[str] = None


class GroupsResponse(Wire):
    date: str
    office_id: str
    user_id: Optional[str] = None
    groups: list[LunchGroupWire]
    people_ordering: int
    total_savings_cents: int


class CreateGroupReq(Wire):
    office: OfficeRef
    restaurant_id: str
    delivery_minutes: int
    option_id: Optional[str] = None         # one item; `option_ids` orders several at once
    option_ids: list[str] = []
    category: Optional[OrderCategory] = None    # default: the restaurant's primary category
    user_id: Optional[str] = None
    display_name: str = "You"


class JoinGroupReq(Wire):
    office: OfficeRef
    option_id: Optional[str] = None         # any item on the restaurant's menu; the group's options grow to include it
    option_ids: list[str] = []              # several items at once; the whole selection replaces the member's last one
    user_id: Optional[str] = None
    display_name: str = "You"


class LedgerEntryWire(Wire):
    id: str
    date: str                              # ISO datetime
    office: str
    restaurant: str
    item: str
    symbol: str
    amount_cents: int
    baseline_cents: int
    status: str
    source: str


class LedgerWire(Wire):
    user_id: str
    entries: list[LedgerEntryWire]
    spent_month_cents: int
    saved_month_cents: int
    monthly_budget_cents: int
    month: str


# ---------------------------------------------------------------- service

class GroupService:
    def __init__(self, store: Store):
        self.store = store

    # ---- helpers
    def _catalog(self) -> tuple[dict[str, Restaurant], dict[str, MenuItem]]:
        return {r.id: r for r in self.store.all(Restaurant)}, {i.id: i for i in self.store.all(MenuItem)}

    @staticmethod
    def _options(r: Restaurant, items: list[MenuItem], n: int = 3) -> list[GroupOption]:
        picks = sorted(items, key=lambda i: (not i.popular, i.price_cents))[:n]
        return [GroupOption(id=i.id, name=i.name, detail=(i.description or ", ".join(i.ingredients[:3]))[:60], symbol=symbol_for(i),
                            item_cents=i.price_cents, subtotal_cents=i.price_cents + r.fees.per_item_overhead(i.price_cents)) for i in picks]

    def resolve_user(self, user_id: Optional[str], display_name: str, office: OfficeRef) -> User:
        u = self.store.get(User, user_id) if user_id else None
        if user_id and u is None:
            raise ValueError("unknown user")
        if u and u.office_id != office.id:
            raise ValueError("user belongs to a different office")
        if u is None:
            u = next((x for x in self.store.all(User) if x.name == display_name and x.office_id == office.id and not x.synthetic), None)
        if u is None:
            u = User(name=display_name or "You", office_id=office.id, home=LatLng(lat=office.latitude, lng=office.longitude))
            self.store.put(u)
        return u

    @staticmethod
    def _day(day: Optional[str]) -> str:
        if day is None:
            return _date.today().isoformat()
        if _date.fromisoformat(day).isoformat() != day:
            raise ValueError("date must use YYYY-MM-DD")
        return day

    @staticmethod
    def _check_dietary(u: User, option_ids: list[str], items: dict[str, MenuItem]) -> None:
        for option_id in option_ids:
            item = items[option_id]
            allowed, reason = filters.passes_dietary(u, item)
            if not allowed:
                raise ValueError(f"{item.name} does not meet your dietary restrictions ({reason})")

    @staticmethod
    def _share(g: LunchGroup, user_id: Optional[str] = None, joining: bool = False) -> int:
        index = next((k for k, m in enumerate(g.members) if m.user_id == user_id), None)
        count = max(1, g.participants + (1 if joining and index is None else 0))
        share, remainder = divmod(g.delivery_fee_cents, count)
        if index is None and joining:
            index = g.participants
        return share + int(bool(remainder) if index is None else index < remainder)

    def _sync_orders(self, g: LunchGroup, items: dict[str, MenuItem], rests: dict[str, Restaurant]) -> None:
        """One confirmed Order per item a member ordered, with the fee share (which reflects the current headcount)
        charged once per member, on their first item. Orders left over from a larger previous selection are cancelled."""
        options = {o.id: o for o in g.options}
        for m in g.members:
            if not m.items() or any(i not in options for i in m.items()):
                raise ValueError("group member has no valid menu selection")
            share = self._share(g, m.user_id)
            chosen = [options[i] for i in m.items()]
            existing = m.order_ids or ([m.order_id] if m.order_id else [])
            written: list[str] = []
            for k, option in enumerate(chosen):
                line = OrderLine(item_id=option.id, restaurant_id=g.restaurant_id, price_cents=option.item_cents)
                o = self.store.get(Order, existing[k]) if k < len(existing) else None
                if o is None:
                    o = Order(user_id=m.user_id, date=g.date, meal=g.meal, location="office", line=line, default_line=line,
                              shown_item_ids=[x.id for x in g.options], source="group", group_id=g.id)
                fee = share if k == 0 else 0          # one delivery share per person, however many items they ordered
                o.line = line
                o.fee_share_cents = fee
                o.total_cents = option.subtotal_cents + fee
                o.baseline_cents = option.subtotal_cents + (g.delivery_fee_cents if k == 0 else 0)
                o.item_name = option.name
                o.restaurant_name = g.name
                o.item_symbol = option.symbol
                o.office_id = g.office_id
                o.office_name = g.office_name
                o.status = "confirmed"
                self.store.put(o)
                written.append(o.id)
            for stale in existing[len(chosen):]:
                if (o := self.store.get(Order, stale)) is not None:
                    o.status = "cancelled"
                    self.store.put(o)
            m.order_ids = written
            m.order_id = written[0]

    def wire(self, g: LunchGroup, user_id: Optional[str]) -> LunchGroupWire:
        share, fee = self._share(g, user_id), g.delivery_fee_cents
        mine = next((m for m in g.members if m.user_id == user_id), None)
        subtotal = {o.id: o.subtotal_cents for o in g.options}
        total = sum(subtotal[i] for m in g.members for i in m.items()) + (fee if g.members else 0)
        u = self.store.get(User, user_id) if user_id else None
        items = {i.id: i for i in self.store.items_for(g.restaurant_id)}
        options = [o for o in g.options if o.id in items and (u is None or filters.passes_dietary(u, items[o.id])[0])]
        return LunchGroupWire(id=g.id, name=g.name, category=g.category, cuisine=g.cuisine, symbol=g.symbol, total_cents=total,
                              people=sum(1 for m in g.members if m.user_id != user_id),
                              delivery=window_label(g.delivery_minutes), arrival_minutes=g.delivery_minutes,
                              options=[GroupOptionWire(id=o.id, name=o.name, detail=o.detail, symbol=o.symbol, price_cents=o.subtotal_cents + share,
                                                       baseline_cents=o.subtotal_cents + fee, item_price_cents=o.item_cents) for o in options],
                              restaurant_id=g.restaurant_id, participants=g.participants, savings_cents=g.savings_cents,
                              delivery_fee_cents=fee, status=g.status, seeded=g.seeded,
                              members=[GroupMemberWire(user_id=m.user_id, display_name=m.display_name, option_id=m.option_id,
                                                       option_ids=m.items()) for m in g.members],
                              my_option_id=mine.option_id if mine else None, my_option_ids=mine.items() if mine else [],
                              budget_cents=u.budget(g.meal) if u else 0, user_id=user_id)

    # ---- queries
    def restaurants(self, limit: int = 12, category: Optional[str] = None) -> list[RestaurantWire]:
        rests, items = self._catalog()
        by_r: dict[str, list[MenuItem]] = {}
        for i in items.values():
            by_r.setdefault(i.restaurant_id, []).append(i)
        pool = (r for r in rests.values() if len(by_r.get(r.id, [])) >= 3 and (category is None or category in r.categories))
        ranked = sorted(pool, key=lambda r: (-shrunk_rating(r), -r.review_count, r.name))
        out = []
        for r in ranked[:limit]:
            opts = self._options(r, by_r[r.id])
            out.append(RestaurantWire(id=r.id, name=r.name, cuisine=cuisine_label(r), symbol=opts[0].symbol if opts else "fork.knife",
                                      rating=r.rating, review_count=r.review_count, categories=list(r.categories),
                                      options=[GroupOptionWire(id=o.id, name=o.name, detail=o.detail, symbol=o.symbol, price_cents=o.subtotal_cents + r.fees.delivery_fee_cents,
                                                               baseline_cents=o.subtotal_cents + r.fees.delivery_fee_cents, item_price_cents=o.item_cents) for o in opts]))
        return out

    def today(self, office: OfficeRef, user_id: Optional[str], day: Optional[str] = None, seed_if_empty: bool = True) -> GroupsResponse:
        day = self._day(day)
        if user_id:
            self.resolve_user(user_id, "", office)
        groups = [g for g in self.store.groups_for(office.id, day) if g.status != "cancelled"]
        if not groups and seed_if_empty:
            groups = self.seed(office, day, exclude_user=user_id)
        if user_id and self.materialize_schedules(office, user_id, day):
            groups = [g for g in self.store.groups_for(office.id, day) if g.status != "cancelled"]
        wires = [self.wire(g, user_id) for g in groups]
        return GroupsResponse(date=day, office_id=office.id, user_id=user_id, groups=wires,
                              people_ordering=sum(w.participants for w in wires), total_savings_cents=sum(w.savings_cents for w in wires))

    def seed(self, office: OfficeRef, day: str, exclude_user: Optional[str], n_groups: int = 3) -> list[LunchGroup]:
        day = self._day(day)
        rests, items = self._catalog()
        colleagues = [u for u in self.store.users_in_office(office.id) if u.synthetic and u.id != exclude_user]
        if not colleagues:
            users, _, _ = synth.make_world(16, None, seed=hash(office.id) & 0xFFFF, center=LatLng(lat=office.latitude, lng=office.longitude))
            for u in users:
                u.office_id = office.id
                u.synthetic = True
            self.store.put_many(users)
            colleagues = users
        rng = random.Random(f"{office.id}:{day}")
        rng.shuffle(colleagues)
        chosen: list[tuple[Restaurant, str, int]] = []
        seen_cuisines: set[str] = set()
        for r in self.restaurants(limit=40, category="meal"):
            if r.cuisine in seen_cuisines or "coffee" in r.categories:      # meal groups go to proper restaurants, not cafés
                continue
            seen_cuisines.add(r.cuisine)
            chosen.append((rests[r.id], "meal", office.delivery_start + 15 * len(chosen)))
            if len(chosen) == n_groups:
                break
        # one morning coffee run when the catalog has a café
        cafes = self.restaurants(limit=1, category="coffee")
        if cafes:
            chosen.append((rests[cafes[0].id], "coffee", 9 * 60 + 30))
        groups: list[LunchGroup] = []
        cursor = 0
        for k, (r, category, minutes) in enumerate(chosen):
            menu = [i for i in items.values() if i.restaurant_id == r.id]
            opts = self._options(r, menu)
            if not opts:
                continue
            g = LunchGroup(office_id=office.id, office_name=office.name, date=day, restaurant_id=r.id, name=r.name, cuisine=cuisine_label(r), category=category,
                           symbol=opts[0].symbol, delivery_minutes=minutes, delivery_fee_cents=r.fees.delivery_fee_cents,
                           options=opts, seeded=True)
            target = rng.randint(2, 4)
            while len(g.members) < target and cursor < len(colleagues):
                u = colleagues[cursor]; cursor += 1
                safe = [i for i in menu if filters.passes_dietary(u, i)[0]]
                if not safe:
                    continue
                option_id = safe[(len(g.members) + k) % len(safe)].id
                g.options = self._with_options(g.options, r, menu, [option_id])
                g.members.append(GroupMember(user_id=u.id, display_name=u.name, option_id=option_id))
            if not g.members:
                continue
            self._sync_orders(g, items, rests)
            self.store.put(g)
            groups.append(g)
        return groups

    # ---- commands
    def create(self, req: CreateGroupReq, day: Optional[str] = None) -> LunchGroupWire:
        day = self._day(day)
        rests, items = self._catalog()
        r = rests.get(req.restaurant_id)
        if not r:
            raise ValueError("unknown restaurant")
        if not 360 <= req.delivery_minutes <= 1260:
            raise ValueError("delivery time must be between 6 AM and 9 PM")
        mine = [i for i in items.values() if i.restaurant_id == r.id]
        chosen = self._requested(req.option_ids, req.option_id)
        opts = self._options(r, mine)
        opts = self._with_options(opts, r, mine, chosen)
        category = req.category or (r.categories[0] if r.categories else "meal")
        if category not in r.categories:
            raise ValueError(f"{r.name} does not take {category_label(category).lower()} orders")
        u = self.resolve_user(req.user_id, req.display_name, req.office)
        self._check_dietary(u, chosen, items)
        g = LunchGroup(office_id=req.office.id, office_name=req.office.name, date=day, restaurant_id=r.id, name=r.name, cuisine="Started by you · " + cuisine_label(r),
                       category=category, symbol=opts[0].symbol, delivery_minutes=req.delivery_minutes, delivery_fee_cents=r.fees.delivery_fee_cents,
                       options=opts, created_by=u.id)
        member = GroupMember(user_id=u.id, display_name=u.name, option_id=chosen[0])
        member.set_items(chosen)
        self._check_budget(u, g.meal, chosen, opts, r.fees.delivery_fee_cents)
        self._leave_all(u.id, req.office.id, day, items, rests, category=category)
        g.members = [member]
        self._sync_orders(g, items, rests)
        self.store.put(g)
        return self.wire(g, u.id)

    def join(self, group_id: str, req: JoinGroupReq) -> LunchGroupWire:
        g = self.store.get(LunchGroup, group_id)
        if not g or g.status == "cancelled":
            raise LookupError("group not found")
        if g.status != "collecting":
            raise ValueError("this group is no longer collecting orders")
        if req.office.id != g.office_id:
            raise ValueError("group belongs to a different office")
        rests, items = self._catalog()
        r = rests.get(g.restaurant_id)
        if not r:
            raise ValueError("this group's restaurant is no longer in the catalog")
        chosen = self._requested(req.option_ids, req.option_id)
        g.options = self._with_options(g.options, r, [i for i in items.values() if i.restaurant_id == r.id], chosen)
        u = self.resolve_user(req.user_id, req.display_name, req.office)
        self._check_dietary(u, chosen, items)
        mine = next((m for m in g.members if m.user_id == u.id), None)
        # the share this person will pay once they are in (joining adds a head, which spreads the fee further)
        share = self._share(g, u.id, joining=True)
        self._check_budget(u, g.meal, chosen, g.options, share)
        self._leave_all(u.id, g.office_id, g.date, items, rests, keep=g.id, category=g.category)
        if mine:
            mine.set_items(chosen)
        else:
            member = GroupMember(user_id=u.id, display_name=u.name, option_id=chosen[0])
            member.set_items(chosen)
            g.members.append(member)
        self._sync_orders(g, items, rests)
        self.store.put(g)
        return self.wire(g, u.id)

    def leave(self, group_id: str, user_id: str) -> LunchGroupWire:
        g = self.store.get(LunchGroup, group_id)
        if not g:
            raise LookupError("group not found")
        if g.status != "collecting" and any(m.user_id == user_id for m in g.members):
            raise ValueError("this group is no longer collecting orders")
        rests, items = self._catalog()
        self._remove(g, user_id, items, rests)
        return self.wire(g, user_id)

    def _remove(self, g: LunchGroup, user_id: str, items, rests) -> None:
        mine = next((m for m in g.members if m.user_id == user_id), None)
        if not mine:
            return
        self._skip_schedules(user_id, g.office_id, g.date, g.category)
        g.members = [m for m in g.members if m.user_id != user_id]
        for order_id in (mine.order_ids or ([mine.order_id] if mine.order_id else [])):
            if (o := self.store.get(Order, order_id)) is not None:
                o.status = "cancelled"
                self.store.put(o)
        if not g.members and not g.seeded:
            g.status = "cancelled"          # a group you started and left disappears from Today
        self._sync_orders(g, items, rests)
        self.store.put(g)

    def _leave_all(self, user_id: str, office_id: str, day: str, items, rests, keep: Optional[str] = None,
                   category: Optional[str] = None) -> None:
        """One order per person per category per day: joining a meal group leaves any other meal group that day, and
        likewise for coffee. A coffee and a meal can both be active."""
        previous = [g for g in self.store.groups_for(office_id, day)
                    if g.id != keep and g.status != "cancelled" and (category is None or g.category == category)
                    and any(m.user_id == user_id for m in g.members)]
        if any(g.status != "collecting" for g in previous):
            raise ValueError("your existing group is no longer collecting orders")
        for g in previous:
            self._remove(g, user_id, items, rests)

    @staticmethod
    def _with_options(opts: list[GroupOption], r: Restaurant, menu: list[MenuItem], option_ids: list[str]) -> list[GroupOption]:
        """The group's option list plus every requested item from the full menu, so anyone can order off-list."""
        out = list(opts)
        for option_id in option_ids:
            item = next((i for i in menu if i.id == option_id), None)
            if item is None:
                raise ValueError("choose something from this restaurant's menu")
            if any(o.id == option_id for o in out):
                continue
            out.append(GroupOption(id=item.id, name=item.name, detail=(item.description or ", ".join(item.ingredients[:3]))[:60],
                                   symbol=symbol_for(item), item_cents=item.price_cents,
                                   subtotal_cents=item.price_cents + r.fees.per_item_overhead(item.price_cents)))
        return out

    @staticmethod
    def _requested(option_ids: list[str], option_id: Optional[str]) -> list[str]:
        """What the caller asked for, de-duplicated and in order. `option_id` alone is the single-item form."""
        wanted = list(option_ids) or ([option_id] if option_id else [])
        out: list[str] = []
        for i in wanted:
            if i and i not in out:
                out.append(i)
        if not out:
            raise ValueError("choose at least one item")
        if len(out) > MAX_ITEMS_PER_MEMBER:
            raise ValueError(f"you can order at most {MAX_ITEMS_PER_MEMBER} items in one group order")
        return out

    def _check_budget(self, u: User, meal: str, option_ids: list[str], options: list[GroupOption], share: int) -> None:
        """A person's first item always goes through, however expensive; every extra has to fit the per-order cap.
        This is the same rule the menu applies when it greys options out, enforced where the data actually lives."""
        cap = u.budget_cents.get(meal, 0)
        if len(option_ids) <= 1:
            return
        by_id = {o.id: o for o in options}
        running = share
        for k, option_id in enumerate(option_ids):
            option = by_id[option_id]
            running += option.subtotal_cents
            if k and running > cap:
                raise ValueError(f"{option.name} takes this order to ${running / 100:.2f}, over your ${cap / 100:.2f} budget")

    # ---- full menu with the user's top picks
    def menu(self, restaurant_id: str, user_id: Optional[str], group_id: Optional[str] = None, top_n: int = 3) -> MenuWire:
        rests, items = self._catalog()
        r = rests.get(restaurant_id)
        if not r:
            raise LookupError("unknown restaurant")
        g = self.store.get(LunchGroup, group_id) if group_id else None
        if group_id and (g is None or g.restaurant_id != r.id or g.status == "cancelled"):
            raise LookupError("group not found for this restaurant")
        share = self._share(g, user_id) if g else r.fees.delivery_fee_cents
        options = {o.id: o for o in g.options} if g else {}
        menu = sorted((i for i in items.values() if i.restaurant_id == r.id), key=lambda i: (is_drink(i) != ("coffee" in r.categories and "meal" not in r.categories), not i.popular, i.price_cents))
        u = self.store.get(User, user_id) if user_id else None
        if user_id and u is None:
            raise ValueError("unknown user")
        if u and g and u.office_id != g.office_id:
            raise ValueError("group belongs to a different office")
        if u:
            menu = [i for i in menu if filters.passes_dietary(u, i)[0]]
        scores: dict[str, tuple[float, dict[str, float]]] = {}
        if u is not None and menu:
            today = _date.today()
            now = datetime.now()
            ctx = Context(date=today.isoformat(), meal="lunch", weekday=today.weekday(), order_time_minutes=now.hour * 60 + now.minute)
            h = scoring.History.from_orders(self.store.orders_for(u.id), items, rests, today.toordinal())
            for i, sc, comps in scoring.rank(u, menu, rests, ctx, h, "office"):
                scores[i.id] = (sc, comps)

        def wire(i: MenuItem) -> MenuItemWire:
            option = options.get(i.id)
            sc = scores.get(i.id)
            reason = ""
            if sc:
                best = max(sc[1].items(), key=lambda kv: kv[1])
                reason = {"affinity": "matches your tastes", "novelty": "something new for you", "health": "fits your goals",
                          "context": "good for today", "rating": "popular here", "reliability": "reliable place"}.get(best[0], "")
            return MenuItemWire(id=i.id, name=i.name, detail=(i.description or ", ".join(i.ingredients[:3]))[:80], symbol=symbol_for(i),
                                price_cents=(option.subtotal_cents if option else i.price_cents + r.fees.per_item_overhead(i.price_cents)) + share,
                                item_price_cents=option.item_cents if option else i.price_cents,
                                popular=i.popular, drink=is_drink(i), score=round(sc[0], 3) if sc else None, reason=reason)
        wires = [wire(i) for i in menu]
        if scores:
            top = sorted(wires, key=lambda w: -(w.score if w.score is not None else float("-inf")))[:top_n]
        else:
            top = sorted(wires, key=lambda w: (not w.popular, w.price_cents))[:top_n]
        return MenuWire(restaurant_id=r.id, name=r.name, cuisine=cuisine_label(r), category=g.category if g else (r.categories[0] if r.categories else "meal"),
                        rating=r.rating, review_count=r.review_count, ratings=dict(r.ratings), recommendations=list(r.recommendations),
                        address=r.address, top=top, items=wires)

    # ---- standing orders (the "schedule a new order" feature on You)
    def schedule_wire(self, s: ScheduledOrder) -> ScheduleWire:
        r = self.store.get(Restaurant, s.restaurant_id) if s.restaurant_id else None
        return ScheduleWire(id=s.id, category=s.category, label=s.label or category_label(s.category), restaurant_id=s.restaurant_id,
                            restaurant_name=r.name if r else "", option_id=s.option_id, time_minutes=s.time_minutes, weekdays=s.weekdays,
                            active=s.active, calendar_event_id=s.calendar_event_id)

    def schedules(self, user_id: str) -> list[ScheduleWire]:
        return [self.schedule_wire(s) for s in self.store.schedules_for(user_id)]

    def add_schedule(self, req: ScheduleReq) -> ScheduleWire:
        if not 300 <= req.time_minutes <= 1320:
            raise ValueError("pick a time between 5 AM and 10 PM")
        if not req.weekdays or any(d < 0 or d > 6 for d in req.weekdays):
            raise ValueError("choose weekdays between 0 (Monday) and 6 (Sunday)")
        days = sorted(set(req.weekdays))
        if req.option_id and not req.restaurant_id:
            raise ValueError("choose a restaurant for the scheduled item")
        if req.restaurant_id:
            r = self.store.get(Restaurant, req.restaurant_id)
            if not r:
                raise ValueError("unknown restaurant")
            if req.category not in r.categories:
                raise ValueError(f"{r.name} does not take {category_label(req.category).lower()} orders")
            if req.option_id and not any(i.id == req.option_id for i in self.store.items_for(r.id)):
                raise ValueError("choose something from this restaurant's menu")
        u = self.resolve_user(req.user_id, req.display_name, req.office)
        if req.option_id:
            self._check_dietary(u, [req.option_id], {i.id: i for i in self.store.items_for(req.restaurant_id)})
        s = ScheduledOrder(user_id=u.id, office_id=req.office.id, category=req.category, label=req.label.strip() or category_label(req.category),
                           restaurant_id=req.restaurant_id, option_id=req.option_id, time_minutes=req.time_minutes, weekdays=days,
                           calendar_event_id=req.calendar_event_id)
        self.store.put(s)
        return self.schedule_wire(s)

    def set_schedule_event(self, schedule_id: str, calendar_event_id: Optional[str]) -> ScheduleWire:
        s = self.store.get(ScheduledOrder, schedule_id)
        if not s:
            raise LookupError("unknown schedule")
        s.calendar_event_id = calendar_event_id
        self.store.put(s)
        return self.schedule_wire(s)

    def remove_schedule(self, schedule_id: str, user_id: str) -> Optional[ScheduleWire]:
        s = self.store.get(ScheduledOrder, schedule_id)
        if not s or s.user_id != user_id:
            raise LookupError("unknown schedule")
        self.store.delete(ScheduledOrder, schedule_id)
        return self.schedule_wire(s)

    def materialize_schedules(self, office: OfficeRef, user_id: str, day: str) -> bool:
        """For each active schedule that falls on `day`, make sure the user is in a group at that place and time. A group
        the user is already in for that category is left alone (they may have changed their mind). Returns True on a change."""
        day = self._day(day)
        weekday = _date.fromisoformat(day).weekday()
        u = self.resolve_user(user_id, "", office)
        if u.suggest_only or u.traits.autonomy > 0.8:
            return False
        due = [s for s in self.store.schedules_for(user_id)
               if s.active and weekday in s.weekdays and s.office_id == office.id and day not in s.materialized_dates]
        if not due:
            return False
        rests, items = self._catalog()
        groups = [g for g in self.store.groups_for(office.id, day) if g.status != "cancelled"]
        changed = False
        for s in due:
            if any(g.category == s.category and any(m.user_id == user_id for m in g.members) for g in groups):
                s.materialized_dates.append(day)
                self.store.put(s)
                continue
            r = rests.get(s.restaurant_id) if s.restaurant_id else None
            candidates = [r] if r else ([] if s.restaurant_id else
                                       [rests[w.id] for w in self.restaurants(limit=len(rests), category=s.category)])
            menu: list[MenuItem] = []
            for r in candidates:
                if s.category not in r.categories:
                    continue
                menu = [i for i in items.values() if i.restaurant_id == r.id and filters.passes_dietary(u, i)[0]]
                if menu:
                    break
            if not menu:
                continue
            opts = self._options(r, menu)
            if s.option_id and not any(i.id == s.option_id for i in menu):
                continue
            option_id = s.option_id or opts[0].id
            opts = self._with_options(opts, r, menu, [option_id])
            existing = next((g for g in groups if g.restaurant_id == r.id and g.category == s.category and g.status == "collecting"
                             and abs(g.delivery_minutes - s.time_minutes) <= 15), None)
            if existing:
                existing.options = self._with_options(existing.options, r, menu, [option_id])
                existing.members.append(GroupMember(user_id=u.id, display_name=u.name, option_id=option_id))
                self._sync_orders(existing, items, rests)
                self.store.put(existing)
            else:
                g = LunchGroup(office_id=office.id, office_name=office.name, date=day, restaurant_id=r.id, name=r.name, cuisine=f"{s.label or category_label(s.category)} · scheduled",
                               category=s.category, symbol=opts[0].symbol, delivery_minutes=s.time_minutes, delivery_fee_cents=r.fees.delivery_fee_cents,
                               options=opts, created_by=u.id, members=[GroupMember(user_id=u.id, display_name=u.name, option_id=option_id)])
                self._sync_orders(g, items, rests)
                self.store.put(g)
                groups.append(g)
            s.materialized_dates.append(day)
            self.store.put(s)
            changed = True
        return changed

    def _skip_schedules(self, user_id: str, office_id: str, day: str, category: str) -> None:
        weekday = _date.fromisoformat(day).weekday()
        for schedule in self.store.schedules_for(user_id):
            if (schedule.active and schedule.office_id == office_id and schedule.category == category
                    and weekday in schedule.weekdays and day not in schedule.materialized_dates):
                schedule.materialized_dates.append(day)
                self.store.put(schedule)

    # ---- spending
    def ledger(self, user_id: str, office_name: str = "", month: Optional[str] = None) -> LedgerWire:
        u = self.store.get(User, user_id)
        if not u:
            raise LookupError("unknown user")
        rests, items = self._catalog()
        month = month or _date.today().isoformat()[:7]
        if len(month) != 7 or _date.fromisoformat(f"{month}-01").isoformat()[:7] != month:
            raise ValueError("month must use YYYY-MM")
        entries: list[LedgerEntryWire] = []
        for o in sorted(self.store.orders_for(user_id), key=lambda o: (o.date, o.created_at), reverse=True):
            if o.status not in ("confirmed", "manual"):
                continue
            item, r = items.get(o.line.item_id), rests.get(o.line.restaurant_id)
            total = o.total_cents
            baseline = o.baseline_cents
            if baseline is None:
                subtotal = total - o.fee_share_cents if total else o.line.price_cents + (
                    r.fees.per_item_overhead(o.line.price_cents) if r else 0)
                total = subtotal + o.fee_share_cents
                delivery = r.fees.delivery_fee_cents if r else o.fee_share_cents
                if o.group_id:
                    group = self.store.get(LunchGroup, o.group_id)
                    member = next((m for m in group.members if m.user_id == user_id), None) if group else None
                    order_ids = (member.order_ids or [member.order_id]) if member else []
                    if order_ids and o.id != order_ids[0]:
                        delivery = 0
                    elif group:
                        delivery = group.delivery_fee_cents
                baseline = subtotal + delivery
            when = o.created_at.replace(microsecond=0).isoformat() if o.date == o.created_at.date().isoformat() else f"{o.date}T12:00:00+00:00"
            entries.append(LedgerEntryWire(id=o.id, date=when,
                                           office=o.office_name if o.office_name is not None else office_name,
                                           restaurant=o.restaurant_name or (r.name if r else o.line.restaurant_id),
                                           item=o.item_name or (item.name if item else o.line.item_id),
                                           symbol=o.item_symbol or (symbol_for(item) if item else "fork.knife"), amount_cents=total,
                                           baseline_cents=baseline, status=o.status, source=o.source))
        this_month = [e for e in entries if e.date.startswith(month)]
        return LedgerWire(user_id=user_id, entries=entries, month=month,
                          spent_month_cents=sum(e.amount_cents for e in this_month),
                          saved_month_cents=sum(max(0, e.baseline_cents - e.amount_cents) for e in this_month),
                          monthly_budget_cents=u.budget_cents.get("lunch", 2000) * 20)
