"""Feedback event processor (§6). Deliverable 5.

Taps and parsed NL both arrive as FeedbackEvent; this module turns them into profile updates.
Weights: explicit NL statement > swap > rating tap > accepted default. Old signals decay by γ per day
(applied lazily when scoring, via the timestamp on the event; here we apply a step).
"""
from __future__ import annotations

from .models import FeedbackEvent, MenuItem, Restaurant, Restriction, User
from .scoring import item_attributes
from .store import Store

W_NL, W_SWAP, W_RATING, W_ACCEPT = 1.0, 0.6, 0.4, 0.1
DECAY_STEP = 0.97      # multiply all revealed weights by this on every new event (cheap stand-in for γ^Δt)
CLIP = 2.0


def _bump(d: dict[str, float], key: str, delta: float) -> None:
    d[key] = max(-CLIP, min(CLIP, d.get(key, 0.0) + delta))


def _bump_item(u: User, item: MenuItem, r: Restaurant, delta: float, which: str = "revealed") -> None:
    d = u.prefs.revealed if which == "revealed" else u.prefs.stated
    for k, v in item_attributes(item, r).items():
        if k.startswith(("word:",)):
            continue
        _bump(d, k, delta * v * (1.0 if k.startswith(("item:", "restaurant:", "cuisine:", "protein:", "dish:")) else 0.5))


def _decay(u: User) -> None:
    for k in list(u.prefs.revealed):
        u.prefs.revealed[k] *= DECAY_STEP


def apply_event(store: Store, ev: FeedbackEvent) -> list[str]:
    """Apply one event to the user's profile. Returns a human-readable log of what changed."""
    previous = store.get(FeedbackEvent, ev.id)
    if previous:
        if (previous.user_id, previous.type, previous.order_id, previous.item_id) != (ev.user_id, ev.type, ev.order_id, ev.item_id):
            raise ValueError("event ID belongs to a different feedback event")
        confirming = previous.type == "constraint" and previous.needs_confirmation and ev.payload.get("confirmed")
        if previous.applied or not confirming:
            return ["event already recorded"]
        ev = previous.model_copy(deep=True)
        ev.payload["confirmed"] = True
        ev.needs_confirmation = False
    u = store.get(User, ev.user_id)
    assert u, ev.user_id
    items = {i.id: i for i in store.all(MenuItem)}
    rests = {r.id: r for r in store.all(Restaurant)}
    log: list[str] = []
    scale = {"high": 1.0, "medium": 0.5, "low": 0.0}[
        "high" if ev.confidence >= 0.85 else "medium" if ev.confidence >= 0.60 else "low"]
    if ev.source == "nl" and scale == 0.0:
        ev.applied = False
        store.put(ev)
        return ["low confidence: not applied"]
    if ev.type not in ("skip", "constraint", "context"):
        _decay(u)
    item = items.get(ev.item_id) if ev.item_id else None
    rest = rests.get(item.restaurant_id) if item else rests.get(ev.restaurant_id) if ev.restaurant_id else None
    p = ev.payload

    if ev.type == "accept" and item:
        _bump_item(u, item, rest, W_ACCEPT)
        log.append(f"+{W_ACCEPT} {item.name} (accepted default)")
        if ev.payload.get("novel"):
            u.traits.epsilon_a += 1
            log.append("ε: kept a novel item → a+1")

    elif ev.type == "add_extras" and item:
        _bump_item(u, item, rest, W_RATING)
        for a in p.get("addons", []):
            _bump(u.prefs.addons, a, 0.5)
        log.append(f"+ item, addon habits {p.get('addons')}")

    elif ev.type == "change_item" and item:
        old = items.get(p.get("from_item_id", ""))
        if old:
            _bump_item(u, old, rests[old.restaurant_id], -W_SWAP)
            if p.get("old_was_novel"):
                u.traits.epsilon_b += 1
                log.append("ε: swapped away a novel item → b+1")
        _bump_item(u, item, rest, W_SWAP)
        _bump(u.prefs.revealed, f"restaurant:{rest.id}", 0.3)
        log.append(f"pairwise {item.name} ≻ {old.name if old else '?'}; +restaurant")
        if old and item.tags and old.tags and item.tags.heaviness < old.tags.heaviness:
            u.traits.w_health = min(2.0, u.traits.w_health + 0.1)
            log.append("swapped lighter → w_health +0.1")

    elif ev.type == "change_restaurant" and item:
        old = items.get(p.get("from_item_id", ""))
        if old:
            _bump(u.prefs.revealed, f"restaurant:{old.restaurant_id}", -W_SWAP)
            _bump_item(u, old, rests[old.restaurant_id], -0.3)
        _bump_item(u, item, rest, W_SWAP)
        log.append("restaurant miss; pairwise")

    elif ev.type == "go_manual":
        u.traits.autonomy = min(1.0, u.traits.autonomy + 0.15)
        if item:
            _bump_item(u, item, rest, W_NL)      # a free choice is the cleanest data
        for iid in p.get("shown_item_ids", []):
            if iid in items:
                _bump_item(u, items[iid], rests[items[iid].restaurant_id], -0.3)
        log.append(f"went manual: autonomy={u.traits.autonomy:.2f}")
        if u.traits.autonomy > 0.8:
            u.suggest_only = True
            log.append("autonomy high → suggest-only mode")

    elif ev.type == "skip":
        log.append("skip ignored (no reason)")

    elif ev.type == "rating" and item:
        overall = p.get("overall", 2)            # 0..4
        delta = (overall - 2) / 2 * W_RATING * scale
        _bump_item(u, item, rest, delta)
        log.append(f"rating {overall}/4 → {delta:+.2f} on item attrs")
        if p.get("temperature") == 0 or p.get("logistics"):
            pass  # attribution: temperature goes to reliability, handled by logistics events
        if p.get("too_heavy"):
            u.health.kcal_per_meal = max(400, u.health.kcal_per_meal - 50)
            u.traits.w_health = min(2.0, u.traits.w_health + 0.1)
            log.append("too heavy → kcal target −50, w_health +0.1")
        if p.get("portion") == 0 and overall <= 1:
            _bump(u.prefs.revealed, f"restaurant:{rest.id}", -0.2)

    elif ev.type == "preference":
        attr, direction = p["attribute"], p["direction"]
        if attr == "other":
            log.append("preference attribute 'other' → logged for taxonomy growth")
        else:
            delta = {"more": 0.6, "less": -0.6, "never": -1.5}[direction] * W_NL * scale
            _bump(u.prefs.stated, attr, delta)
            log.append(f"stated {attr} {delta:+.2f}")

    elif ev.type == "context":
        log.append("temporary context stored on today's Context, not the profile")

    elif ev.type == "constraint":
        which, action = p["which"], p["action"]
        kind, value = which.split(":", 1)
        if action == "add":
            ev.needs_confirmation = not p.get("confirmed", False)
            existing = next((r for r in u.restrictions if r.kind == kind and r.value == value), None)
            if existing:
                existing.severe = existing.severe or p.get("severe", False)
                if p.get("confirmed"):
                    existing.source = "nl_confirmed"
            else:
                u.restrictions.append(Restriction(kind=kind, value=value, severe=p.get("severe", False),
                                                  source="nl_confirmed" if p.get("confirmed") else "nl_provisional"))
                log.append(f"constraint {which} added ({'confirmed' if p.get('confirmed') else 'PROVISIONAL, awaiting confirmation'})")
            if p.get("severe") and not p.get("confirmed"):
                u.suggest_only = True
        else:
            if p.get("confirmed"):
                u.restrictions = [r for r in u.restrictions if (r.kind, r.value) != (kind, value)]
                log.append(f"constraint {which} removed (confirmed)")
            else:
                log.append(f"constraint {which} removal needs explicit confirmation → not applied")
                ev.needs_confirmation = True

    elif ev.type == "logistics" and rest:
        rest.reliability = max(0.3, rest.reliability - (0.05 if not p.get("repeated") else 0.1))
        log.append(f"{rest.name} reliability → {rest.reliability:.2f} ({p.get('issue')})")

    elif ev.type == "meta":
        w = p.get("wants")
        if w in ("pick_myself", "stop_auto_order"):
            u.traits.autonomy = 1.0
            u.suggest_only = True
        elif w == "resume_auto_order":
            u.traits.autonomy = 0.0
            u.suggest_only = False
        elif w == "more_options":
            u.traits.autonomy = min(1.0, u.traits.autonomy + 0.3)
        log.append(f"meta {w}: autonomy={u.traits.autonomy:.2f} suggest_only={u.suggest_only}")

    ev.applied = not ev.needs_confirmation
    store.put_many([ev, u, *([rest] if ev.type == "logistics" and rest else [])])
    return log


def learned_view(u: User) -> dict[str, list[str]]:
    """User-editable 'what we learned' (§6.3)."""
    avoid = sorted(k for k, v in {**u.prefs.revealed, **u.prefs.stated}.items() if v <= -0.5 and not k.startswith(("item:", "restaurant:")))
    like = sorted(k for k, v in {**u.prefs.revealed, **u.prefs.stated}.items() if v >= 0.5 and not k.startswith(("item:", "restaurant:")))
    return {"avoiding": avoid, "liking": like,
            "constraints": [f"{r.value}{' (severe)' if r.severe else ''}{' [unconfirmed]' if r.source == 'nl_provisional' else ''}" for r in u.restrictions],
            "goals": [f"{u.health.kcal_per_meal} kcal/meal", f"{u.health.protein_g_per_meal}g protein/meal"],
            "style": [f"explorer {u.traits.epsilon:.0%}", f"autonomy {u.traits.autonomy:.0%}"]}
