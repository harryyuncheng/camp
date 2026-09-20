"""Template-generated labelled sets. Real labels belong in eval/labels/*.csv (see write_templates)."""
from __future__ import annotations

import random

from ..models import ALLERGENS, CUISINES, MenuItem
from ..synth import make_world

_RATING = [("Great, loved it", "meal"), ("Meh, pretty bland", "meal"), ("Delicious but the portion was tiny", "meal"),
           ("Too salty and too greasy", "meal"), ("Perfect, would reorder", "meal"), ("Awful, gross", "meal")]
_PREF = [("Not into spicy food", "ongoing"), ("I love thai", "ongoing"), ("Never give me cilantro", "ongoing"),
         ("Less beef please", "ongoing"), ("More salad options", "ongoing"), ("I don't like mushroom", "ongoing")]
_CTX = [("Something light today", "today"), ("Feeling like soup today", "today"), ("Spicy tonight please", "today")]
_CON = [("I'm allergic to {a}", "add", False), ("Severe {a} allergy, please be careful", "add", True),
        ("Turns out I'm not allergic to {a} anymore", "remove", False), ("I'm vegetarian", "add", False), ("Gluten free please", "add", False)]
_LOG = [("Arrived cold again", "cold"), ("It was 40 minutes late", "late"), ("Wrong order", "wrong"), ("My drink was missing", "missing")]
_META = [("Let me pick myself from now on", "pick_myself"), ("Give me more options", "more_options"), ("Stop auto ordering", "stop_auto_order")]
_MOD = ["Swap to {item}", "Can I get the {item} instead", "Change to {item}, no onions", "{item} please, add a coke"]


def feedback_set(n: int, rng: random.Random) -> list[dict]:
    rows = []
    for _ in range(n):
        kind = rng.choice(["rating", "preference", "context", "constraint", "constraint", "logistics", "meta", "combo"])
        if kind == "rating":
            t, s = rng.choice(_RATING); rows.append(dict(text=t, types="rating", constraint="", scope=s))
        elif kind == "preference":
            t, s = rng.choice(_PREF); rows.append(dict(text=t, types="preference", constraint="", scope=s))
        elif kind == "context":
            t, s = rng.choice(_CTX); rows.append(dict(text=t, types="context", constraint="", scope=s))
        elif kind == "constraint":
            tpl, action, severe = rng.choice(_CON)
            if "{a}" in tpl:
                a = rng.choice(["peanut", "shellfish", "dairy", "egg", "sesame", "soy"])
                rows.append(dict(text=tpl.format(a=a), types="constraint", constraint=f"allergen:{a}", scope="ongoing"))
            else:
                rows.append(dict(text=tpl, types="constraint", constraint="diet:vegetarian" if "vegetarian" in tpl else "diet:gluten_free", scope="ongoing"))
        elif kind == "logistics":
            t, _ = rng.choice(_LOG); rows.append(dict(text=t, types="logistics", constraint="", scope="restaurant"))
        elif kind == "meta":
            t, _ = rng.choice(_META); rows.append(dict(text=t, types="meta", constraint="", scope="ongoing"))
        else:
            (r, _), (l, _) = rng.choice(_RATING), rng.choice(_LOG)
            rows.append(dict(text=f"{r}, but {l.lower()}", types="rating|logistics", constraint="", scope="meal"))
    return rows


def menu() -> list[MenuItem]:
    _, _, items = make_world(1, None, 0)
    return items


def modification_set(n: int, items: list[MenuItem], rng: random.Random) -> list[dict]:
    return [dict(text=rng.choice(_MOD).format(item=(it := rng.choice(items)).name.lower()), target=it.name) for _ in range(n)]


def tag_set(items: list[MenuItem]) -> list[dict]:
    rows = []
    for it in items:
        t = it.tags
        rows.append(dict(name=it.name, description=it.description, ingredients="|".join(it.ingredients), cuisine=t.cuisine, protein=t.protein,
                         dish_type=t.dish_type, kcal_band=t.kcal_band.value, allergens="|".join(a for a, p in t.allergen_p.items() if p > 0.5)))
    return rows
