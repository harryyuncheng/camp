"""Synthetic users and context for the harness and tests. Restaurants and menus come from the real Ramp HQ
catalog (`catalog.py`); only users, fees/ETAs and item tags are synthesized."""
from __future__ import annotations

import random
from datetime import date

from .models import (ALLERGENS, CUISINES, DISH_TYPES, PROTEINS, Context, FeeSchedule, ItemTags, KcalBand,
                     LatLng, MenuItem, ProteinBand, Restaurant, Restriction, ScheduleEntry, User)

from .catalog import RAMP_HQ, to_models

OFFICE = RAMP_HQ            # 28 W 23rd St, New York

_ING_ALLERGEN = {"peanut": "peanut", "egg": "egg", "cheese": "dairy", "cream": "dairy", "mozzarella": "dairy",
                 "parmesan": "dairy", "mayo": "egg", "bread": "gluten", "dough": "gluten", "pasta": "gluten",
                 "pita": "gluten", "panko": "gluten", "crouton": "gluten", "soy": "soy", "tofu": "soy",
                 "salmon": "fish", "fish": "fish", "shrimp": "shellfish", "sesame": "sesame", "broth": "gluten"}
_MEAT = {"chicken", "beef", "pork", "turkey", "bacon", "salmon", "fish", "shrimp"}


_HEAVINESS = {"salad": 1, "soup": 1, "bowl": 2, "wrap": 2, "taco": 2, "sandwich": 3, "rice": 3, "noodles": 3, "curry": 3,
              "burger": 4, "pizza": 4, "other": 2}
_DAIRY_EGG = ("egg", "cheese", "cream", "mozzarella", "parmesan", "mayo", "butter", "yogurt", "feta", "paneer", "ghee", "milk")


def tags_for(ingredients: list[str], dish_type: str, spice: int, cuisine: str, rng: random.Random, protein: str | None = None,
             allergens: list[str] | None = None, vegetarian: bool | None = None, vegan: bool | None = None, kcal: int | None = None) -> ItemTags:
    """Deterministic stand-in for Jev menu tagging. Catalog facts (protein, allergens, diets, kcal) override the
    ingredient heuristics when supplied."""
    protein = protein or next((p for p in PROTEINS if p in ingredients), "none")
    if protein == "none" and "salmon" in ingredients:
        protein = "fish"
    meat = protein not in ("none", "tofu", "egg") or any(i in _MEAT for i in ingredients)
    if vegetarian:
        meat = False
    allergen_p = {a: 0.02 for a in ALLERGENS}
    for ing in ingredients:
        if ing in _ING_ALLERGEN:
            allergen_p[_ING_ALLERGEN[ing]] = 0.95
    for a in allergens or []:
        allergen_p[a] = 0.98
    heaviness = _HEAVINESS.get(dish_type, 2)
    if kcal:
        kcal_band = KcalBand.lt400 if kcal < 400 else KcalBand.b400_600 if kcal < 600 else KcalBand.b600_800 if kcal < 800 else KcalBand.gt800
    else:
        kcal_band = [KcalBand.lt400, KcalBand.b400_600, KcalBand.b600_800, KcalBand.gt800][min(heaviness, 3)]
    kcal = kcal_band
    prot = ProteinBand.gt45 if protein in ("chicken", "beef", "lamb") else (ProteinBand.b30_45 if protein != "none" else ProteinBand.lt15)
    egg_dairy = any(i in _DAIRY_EGG for i in ingredients) or any(a in ("egg", "dairy") for a in allergens or [])
    return ItemTags(cuisine=cuisine, protein=protein, dish_type=dish_type, spice=spice, heaviness=heaviness,
                    warm=1 if dish_type in ("salad", "sandwich") else 4, kcal_band=kcal, protein_band=prot,
                    vegetarian=0.05 if meat else 0.95,
                    vegan=0.95 if vegan else (0.02 if (meat or egg_dairy) else 0.9),
                    halal=0.1 if any(i in ("pork", "bacon", "ham", "prosciutto", "pancetta") for i in ingredients) or protein == "pork" else 0.6,
                    travels_well=0.9 if dish_type in ("bowl", "curry", "rice", "sandwich", "wrap") else 0.4,
                    allergen_p=allergen_p, confidence=0.9)


def make_world(n_users: int = 40, n_restaurants: int | None = None, seed: int = 0, center: LatLng | None = None):
    """Synthetic colleagues around the real Ramp HQ catalog. `n_restaurants=None` uses the whole catalog; a number takes
    the N nearest. `center` re-centres the catalog geometry on another office."""
    OFFICE = center or globals()['OFFICE']
    restaurants, items = to_models(n_restaurants, seed=seed, center=center)
    rng = random.Random(seed + 1)
    users = []
    for k in range(n_users):
        u = User(name=f"user{k}", office_id="hq", home=LatLng(lat=OFFICE.lat + rng.uniform(-0.03, 0.03), lng=OFFICE.lng + rng.uniform(-0.04, 0.04)),   # within the 6 km delivery radius
                 budget_cents={"lunch": rng.choice([1800, 2000, 2200, 2500]), "dinner": 2500})
        liked = rng.sample(CUISINES, 3)
        for c in liked:
            u.prefs.stated[f"cuisine:{c}"] = rng.uniform(0.4, 1.0)
        u.prefs.stated[f"cuisine:{rng.choice(CUISINES)}"] = -0.8
        u.traits.epsilon_a, u.traits.epsilon_b = rng.choice([(1, 4), (2, 2), (4, 1)])
        roll = rng.random()
        if roll < 0.1:
            u.restrictions.append(Restriction(kind="diet", value="vegetarian"))
        elif roll < 0.18:
            u.restrictions.append(Restriction(kind="allergen", value=rng.choice(["peanut", "shellfish", "dairy"]), severe=rng.random() < 0.4))
        u.schedule = [ScheduleEntry(weekday=d, meal="lunch", location="office" if rng.random() < 0.75 else "home") for d in range(5)]
        users.append(u)
    return users, restaurants, items


def make_context(meal: str = "lunch", d: date | None = None, **kw) -> Context:
    d = d or date(2026, 9, 21)
    return Context(date=d.isoformat(), meal=meal, weekday=d.weekday(), **kw)
