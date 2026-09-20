"""§7.3 menu tagging with cache. Allergen answers are warning-only (they can only exclude)."""
from __future__ import annotations

import asyncio
import hashlib

from ..models import ALLERGENS, ItemTags, KcalBand, MenuItem, ProteinBand
from . import schemas as S
from .classify import Classifier, HIGH, MEDIUM

_cache: dict[str, ItemTags] = {}


def _key(item: MenuItem) -> str:
    return hashlib.sha1(f"{item.name}|{item.description}|{','.join(item.ingredients)}".encode()).hexdigest()


def _state(item: MenuItem) -> str:
    return f"Menu item: {item.name}\nDescription: {item.description}\nIngredients: {', '.join(item.ingredients) or 'not listed'}"


async def tag_item(clf: Classifier, item: MenuItem) -> ItemTags:
    k = _key(item)
    if k in _cache:
        return _cache[k]
    ans = await clf.ask(_state(item), S.MenuTagQuestions)
    o = ans.output
    conf = min(ans.confidence.values()) if ans.confidence else 1.0
    probs = ans.probabilities

    def p_true(field_name: str) -> float:
        d = probs.get(field_name)
        if isinstance(d, dict) and "true" in d:
            return float(d["true"])
        return 0.9 if getattr(o, field_name) else 0.05    # no distribution → use the boolean with a margin

    tags = ItemTags(cuisine=None if o.cuisine == "other" else o.cuisine, protein=None if o.protein == "other" else o.protein,
                    dish_type=o.dish_type, spice=int(o.spice), heaviness=int(o.heaviness), warm=int(o.warm),
                    kcal_band=KcalBand(o.kcal_band), protein_band=ProteinBand(o.protein_band),
                    vegetarian=p_true("vegetarian"), vegan=p_true("vegan"), halal=p_true("halal"), travels_well=p_true("travels_well"),
                    allergen_p={a: p_true(f"contains_{a}") for a in ALLERGENS},
                    confidence=conf, needs_review=conf < MEDIUM)
    if conf >= MEDIUM:            # low confidence → human review queue, don't cache
        _cache[k] = tags
    return tags


async def tag_menu(clf: Classifier, items: list[MenuItem], concurrency: int = 16) -> list[MenuItem]:
    sem = asyncio.Semaphore(concurrency)

    async def one(i: MenuItem) -> None:
        async with sem:
            i.tags = await tag_item(clf, i)

    await asyncio.gather(*(one(i) for i in items))
    return items
