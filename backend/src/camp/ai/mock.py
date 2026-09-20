"""Keyword rules for the offline MockClassifier. Good enough to exercise the pipelines and eval harness."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from ..models import ALLERGENS, CUISINES
from . import schemas as S

_NEG = ["bad", "awful", "terrible", "meh", "disappoint", "soggy", "bland", "salty", "greasy", "hated", "gross", "too "]
_POS = ["great", "amazing", "loved", "delicious", "perfect", "good", "tasty", "excellent", "solid", "nice"]
_ALLERGEN_WORDS = {"peanut": ["peanut"], "tree_nut": ["tree nut", "almond", "cashew", "walnut", "pecan"], "shellfish": ["shellfish", "shrimp", "crab", "prawn"],
                   "fish": ["fish allergy", "allergic to fish", "to fish"], "dairy": ["dairy", "lactose", "milk"], "egg": ["egg"], "gluten": ["gluten", "celiac", "coeliac"],
                   "soy": ["soy"], "sesame": ["sesame"]}
_DIET_WORDS = {"vegetarian": ["vegetarian"], "vegan": ["vegan"], "halal": ["halal"], "kosher": ["kosher"], "gluten_free": ["gluten free", "gluten-free"], "dairy_free": ["dairy free", "dairy-free"]}


def default_rules(state: str, schema: type[BaseModel]) -> dict[str, Any]:
    t = state.lower()
    has = lambda *ws: any(w in t for w in ws)  # noqa: E731

    if schema is S.FeedbackPass1:
        constraint = has("allerg", "intoleran", "celiac", "coeliac") or any(w in t for ws in _DIET_WORDS.values() for w in ws)
        return {
            "is_rating": (has(*_NEG) or has(*_POS)) and not has("swap", "change", "instead", "add a", "cancel") ,
            "is_modification": has("swap", "change to", "instead", "add a", "add an", "no onion", "without", "cancel", "make it", "remove"),
            "is_lasting_preference": (has("not into", "don't like", "dont like", "hate", "love", "prefer", "never", "more ", "less ", "no more")
                                      and not has("today", "this time")) and not constraint,
            "is_temporary_context": has("today", "this time", "right now", "tonight"),
            "is_constraint": constraint,
            "is_logistics": has("late", "cold", "wrong order", "missing", "damaged", "never arrived", "arrived"),
            "is_meta": has("pick myself", "choose myself", "let me pick", "more options", "stop ordering", "stop auto"),
        }
    if schema is S.RatingDetail:
        neg, pos = has(*_NEG), has(*_POS)
        overall = S.Sentiment5.very_positive if (pos and not neg and has("loved", "amazing", "perfect")) else \
            S.Sentiment5.positive if pos and not neg else S.Sentiment5.very_negative if (neg and has("awful", "terrible", "gross")) else \
            S.Sentiment5.negative if neg else S.Sentiment5.neutral
        asp = lambda ws: S.Aspect3.negative if (has(*ws) and (neg or has("too "))) else (S.Aspect3.positive if has(*ws) else S.Aspect3.not_mentioned)  # noqa: E731
        return {"overall": overall, "taste": asp(["salty", "bland", "flavor", "flavour", "taste", "delicious", "spicy"]),
                "portion": asp(["portion", "small", "huge", "tiny", "big"]), "temperature": asp(["cold", "lukewarm", "hot"]),
                "value": asp(["value", "pricey", "expensive", "worth"]), "too_heavy": has("too heavy", "too much", "too big", "not healthy", "greasy")}
    if schema is S.PreferenceDetail:
        attr = "other"
        for c in CUISINES:
            if c in t:
                attr = f"cuisine:{c}"
        for p in ["chicken", "beef", "pork", "fish", "shrimp", "tofu"]:
            if p in t:
                attr = f"protein:{p}"
        for ing in ["onion", "cilantro", "mushroom", "cheese", "mayo", "egg"]:
            if ing in t:
                attr = f"ingredient:{ing}"
        for d in ["salad", "soup", "sandwich", "bowl"]:
            if d in t:
                attr = f"dish:{d}"
        if has("spicy", "spice"):
            attr = "spice"
        if has("heavy", "light"):
            attr = "heaviness"
        direction = "never" if has("never", "hate", "can't stand", "no more") else "less" if has("less", "not into", "don't like", "dont like", "too ") else "more"
        return {"attribute": attr, "direction": direction, "scope": "today" if has("today", "tonight") else "ongoing"}
    if schema is S.ContextDetail:
        return {"lighter": has("light", "small", "salad"), "heavier": has("hearty", "filling", "big", "indulg"),
                "spicier": has("spicy", "spicier"), "milder": has("mild"), "warm": has("warm", "soup", "comfort")}
    if schema is S.ConstraintDetail:
        which = "other"
        for a, ws in _ALLERGEN_WORDS.items():
            if has(*ws) and not (a == "fish" and "shellfish" in t):
                which = f"allergen:{a}"
        for d, ws in _DIET_WORDS.items():
            if has(*ws):
                which = f"diet:{d}"
        return {"which": which, "action": "remove" if has("no longer", "not anymore", "anymore", "turns out i'm not", "not actually") else "add",
                "severe": has("severe", "anaphyla", "epipen", "serious", "hospital")}
    if schema is S.LogisticsDetail:
        issue = "late" if has("late") else "cold" if has("cold") else "wrong" if has("wrong") else "missing" if has("missing", "never arrived") else "damaged" if has("damaged", "spilled") else "other"
        return {"issue": issue, "repeated": has("again", "every time", "always")}
    if schema is S.MetaDetail:
        return {"wants": "pick_myself" if has("myself", "let me pick") else "more_options" if has("more options") else "stop_auto_order" if has("stop") else "other"}
    if schema is S.ModIntent:
        return {"intent": "cancel" if has("cancel") else "go_manual" if has("myself", "manual") else "change_restaurant" if has("restaurant", "somewhere else", "different place")
                else "remove_ingredient" if has("no ", "without", "remove") and not has("swap", "instead") else "add_extras" if has("add ", "extra", "plus a") else
                "swap_item_same_restaurant" if has("swap", "instead", "change to", "make it") else "other"}
    if schema.__name__ == "TargetItem":
        opts = list(schema.model_fields["item"].annotation.__args__)
        best, best_n = "none of these", 0
        for o in opts[:-1]:
            n = sum(1 for w in re.findall(r"[a-z]+", o.lower()) if len(w) > 2 and w in t)
            if n > best_n:
                best, best_n = o, n
        return {"item": best}
    if schema.__name__ == "Customizations":
        mods = schema.__modifiers__  # type: ignore[attr-defined]
        return {f"m{i}": all(w in t for w in m.lower().split()[-1:]) for i, m in enumerate(mods)}
    if schema is S.MenuTagQuestions:
        return {}
    return {}
