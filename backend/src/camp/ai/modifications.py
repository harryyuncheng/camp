"""§7.2 order modifications: intent → target item → customizations → deterministic validation → template."""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import filters
from ..models import Batch, MenuItem, Order, OrderLine, Restaurant, User
from ..store import Store
from . import schemas as S
from .classify import Classifier, HIGH, MEDIUM


@dataclass
class ModResult:
    intent: str
    ok: bool
    message: str
    new_line: OrderLine | None = None
    options: list[str] = field(default_factory=list)      # top-3 buttons on medium confidence
    total_cents: int | None = None
    events: list[dict] = field(default_factory=list)


def _shortlist(items: list[MenuItem], text: str, k: int = 50) -> list[MenuItem]:
    """Stand-in for embedding pre-filter: word overlap. Keeps within Jev's 255-option limit."""
    words = {w for w in text.lower().split() if len(w) > 2}
    scored = sorted(items, key=lambda i: -len(words & set((i.name + " " + i.description).lower().split())))
    return scored[:k]


async def modify(clf: Classifier, store: Store, order: Order, text: str, now_minutes: int) -> ModResult:
    u = store.get(User, order.user_id)
    items = {i.id: i for i in store.all(MenuItem)}
    rests = {r.id: r for r in store.all(Restaurant)}
    batch = store.get(Batch, order.batch_id) if order.batch_id else None
    cur = items[order.line.item_id]

    intent = (await clf.ask(text, S.ModIntent)).output.intent
    if batch and now_minutes > batch.cutoff_minutes:
        return ModResult(intent, False, "Sorry, changes for this order closed at the cutoff.")
    if intent == "cancel":
        order.status = "cancelled"
        store.put(order)
        return ModResult(intent, True, "Cancelled. You won't be charged.")
    if intent == "go_manual":
        order.status = "manual"
        store.put(order)
        return ModResult(intent, True, "Okay, you're ordering yourself today. Your budget still applies.",
                         events=[dict(type="go_manual", shown_item_ids=order.shown_item_ids)])

    # candidate pool: same restaurant, or the batch's restaurants (§6.2 rule 2), or anything at home
    if intent in ("swap_item_same_restaurant", "add_extras", "remove_ingredient", "other"):
        pool = [i for i in items.values() if i.restaurant_id == cur.restaurant_id]
    elif order.location == "home":
        pool = list(items.values())
    else:
        pool = [i for i in items.values() if batch and i.restaurant_id in {b.restaurant_id for b in batch.restaurants}]

    new_item, removed, addons = cur, list(order.line.removed_ingredients), list(order.line.addons)
    if intent in ("swap_item_same_restaurant", "change_restaurant", "other"):
        short = _shortlist(pool, text)
        schema = S.target_item_schema([i.name for i in short])
        ans = await clf.ask(text, schema)
        conf = ans.conf("item")
        name = ans.output.item
        if name == "none of these" or conf < MEDIUM:
            return ModResult(intent, False, "I couldn't tell which dish you meant. Could you say the name?")
        if conf < HIGH:
            probs = ans.probabilities.get("item", {})
            top3 = [k for k, _ in sorted(probs.items(), key=lambda kv: -kv[1])[:3]] or [name] + [i.name for i in short[:2] if i.name != name]
            return ModResult(intent, False, "Did you mean one of these?", options=top3[:3])
        new_item = next(i for i in short if i.name == name)
    if intent in ("add_extras", "remove_ingredient", "swap_item_same_restaurant", "other") and new_item.modifiers:
        cs = S.customizations_schema(new_item.modifiers)
        ans = await clf.ask(text, cs)
        for i, m in enumerate(new_item.modifiers):
            if getattr(ans.output, f"m{i}"):
                (removed if m.lower().startswith(("no ", "without")) else addons).append(m)

    # deterministic validation (§7.2 step 4)
    r = rests[new_item.restaurant_id]
    share = order.fee_share_cents if new_item.restaurant_id == cur.restaurant_id else \
        next((b.fee_share_cents for b in (batch.restaurants if batch else []) if b.restaurant_id == r.id), r.fees.delivery_fee_cents)
    addon_cost = sum(new_item.modifier_prices.get(a, 0) for a in addons)
    total = filters.total_cost_cents(new_item, r, share) + addon_cost
    if total > u.budget(order.meal):
        return ModResult(intent, False, f"{new_item.name} would come to ${total/100:.2f}, over your ${u.budget(order.meal)/100:.0f} budget.")
    if batch and new_item.restaurant_id != cur.restaurant_id:
        old_br = next(b for b in batch.restaurants if b.restaurant_id == cur.restaurant_id)
        # §6.2: leaving is allowed only if the remaining batch still fits; fee split is frozen so it does. Track it.
        u.traits.batch_breaks += 1
        old_br.company_absorbed_cents += old_br.fee_share_cents
        store.put(batch); store.put(u)
    ok_dietary, why = filters.passes_dietary(u, new_item)
    if not ok_dietary:
        return ModResult(intent, False, f"{new_item.name} conflicts with your dietary settings ({why}).")

    line = OrderLine(item_id=new_item.id, restaurant_id=r.id, price_cents=new_item.price_cents, removed_ingredients=removed, addons=addons)
    order.line, order.total_cents = line, total
    store.put(order)
    mods = ", ".join(removed + addons)
    where = "still in your group order" if batch and r.id in {b.restaurant_id for b in batch.restaurants} else "delivered to you"
    msg = f"{new_item.name}{' (' + mods + ')' if mods else ''} — ${total/100:.2f}, {where}."
    ev_type = "add_extras" if new_item.id == cur.id and addons else "change_item" if r.id == cur.restaurant_id else "change_restaurant"
    return ModResult(intent, True, msg, new_line=line, total_cents=total,
                     events=[dict(type=ev_type, item_id=new_item.id, from_item_id=cur.id, addons=addons, old_was_novel=order.novel)])
