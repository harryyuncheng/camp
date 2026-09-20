"""Synthetic users, restaurants, menus and context for the harness and tests."""
from __future__ import annotations

import random
from datetime import date

from .models import (ALLERGENS, CUISINES, DISH_TYPES, PROTEINS, Context, FeeSchedule, ItemTags, KcalBand,
                     LatLng, MenuItem, ProteinBand, Restaurant, Restriction, ScheduleEntry, User)

OFFICE = LatLng(lat=37.7849, lng=-122.4094)

_DISHES = {
    "thai": [("Pad Thai", ["rice noodles", "egg", "peanut", "tofu"], "noodles", 2), ("Green Curry", ["coconut", "chicken", "basil"], "curry", 3)],
    "mexican": [("Chicken Burrito", ["chicken", "rice", "beans", "cheese"], "wrap", 1), ("Fish Tacos", ["fish", "cabbage", "lime"], "taco", 2)],
    "japanese": [("Salmon Poke Bowl", ["salmon", "rice", "avocado", "soy"], "bowl", 0), ("Chicken Katsu", ["chicken", "panko", "rice"], "rice", 0)],
    "indian": [("Chicken Tikka Masala", ["chicken", "cream", "tomato"], "curry", 3), ("Chana Masala", ["chickpea", "tomato", "onion"], "curry", 2)],
    "mediterranean": [("Falafel Wrap", ["falafel", "hummus", "pita", "sesame"], "wrap", 1), ("Chicken Shawarma Plate", ["chicken", "rice", "garlic"], "rice", 1)],
    "italian": [("Margherita Pizza", ["dough", "mozzarella", "basil"], "pizza", 0), ("Penne Arrabbiata", ["pasta", "tomato", "chili"], "noodles", 2)],
    "salad": [("Kale Caesar", ["kale", "parmesan", "crouton", "egg"], "salad", 0), ("Protein Power Bowl", ["quinoa", "chicken", "egg", "avocado"], "bowl", 0)],
    "chinese": [("Kung Pao Chicken", ["chicken", "peanut", "chili"], "rice", 3), ("Mapo Tofu", ["tofu", "pork", "chili"], "rice", 4)],
    "sandwich": [("Turkey Club", ["turkey", "bacon", "bread", "mayo"], "sandwich", 0), ("Caprese Sandwich", ["mozzarella", "tomato", "bread"], "sandwich", 0)],
    "korean": [("Bibimbap", ["rice", "egg", "beef", "gochujang"], "bowl", 2), ("Tofu Soup", ["tofu", "egg", "kimchi"], "soup", 3)],
    "vietnamese": [("Pho", ["rice noodles", "beef", "broth"], "soup", 1), ("Banh Mi", ["pork", "bread", "pickles"], "sandwich", 1)],
    "american": [("Cheeseburger", ["beef", "cheese", "bread"], "sandwich", 0), ("Grilled Chicken Salad", ["chicken", "lettuce", "tomato"], "salad", 0)],
}

_ING_ALLERGEN = {"peanut": "peanut", "egg": "egg", "cheese": "dairy", "cream": "dairy", "mozzarella": "dairy",
                 "parmesan": "dairy", "mayo": "egg", "bread": "gluten", "dough": "gluten", "pasta": "gluten",
                 "pita": "gluten", "panko": "gluten", "crouton": "gluten", "soy": "soy", "tofu": "soy",
                 "salmon": "fish", "fish": "fish", "shrimp": "shellfish", "sesame": "sesame", "broth": "gluten"}
_MEAT = {"chicken", "beef", "pork", "turkey", "bacon", "salmon", "fish", "shrimp"}


def tags_for(ingredients: list[str], dish_type: str, spice: int, cuisine: str, rng: random.Random) -> ItemTags:
    """Deterministic stand-in for Jev menu tagging."""
    protein = next((p for p in PROTEINS if p in ingredients), "none")
    if "salmon" in ingredients:
        protein = "fish"
    meat = any(i in _MEAT for i in ingredients)
    allergen_p = {a: 0.02 for a in ALLERGENS}
    for ing in ingredients:
        if ing in _ING_ALLERGEN:
            allergen_p[_ING_ALLERGEN[ing]] = 0.95
    heaviness = {"salad": 1, "soup": 1, "bowl": 2, "wrap": 2, "taco": 2, "sandwich": 3, "rice": 3, "noodles": 3, "curry": 3, "pizza": 4}[dish_type]
    kcal = [KcalBand.lt400, KcalBand.b400_600, KcalBand.b600_800, KcalBand.gt800][min(heaviness, 3)]
    prot = ProteinBand.gt45 if protein in ("chicken", "beef") else (ProteinBand.b30_45 if protein != "none" else ProteinBand.lt15)
    return ItemTags(cuisine=cuisine, protein=protein, dish_type=dish_type, spice=spice, heaviness=heaviness,
                    warm=1 if dish_type in ("salad", "sandwich") else 4, kcal_band=kcal, protein_band=prot,
                    vegetarian=0.05 if meat else 0.95, vegan=0.02 if (meat or any(i in ("egg", "cheese", "cream", "mozzarella", "parmesan", "mayo") for i in ingredients)) else 0.9,
                    halal=0.1 if any(i in ("pork", "bacon") for i in ingredients) else 0.6,
                    travels_well=0.9 if dish_type in ("bowl", "curry", "rice", "sandwich", "wrap") else 0.4,
                    allergen_p=allergen_p, confidence=0.9)


def make_world(n_users: int = 40, n_restaurants: int = 12, seed: int = 0, center: LatLng | None = None):
    rng = random.Random(seed)
    OFFICE = center or globals()['OFFICE']
    restaurants, items = [], []
    for k in range(n_restaurants):
        cuisine = CUISINES[k % len(CUISINES)]
        r = Restaurant(name=f"{cuisine.title()} Place {k}", cuisine=cuisine,
                       location=LatLng(lat=OFFICE.lat + rng.uniform(-0.03, 0.03), lng=OFFICE.lng + rng.uniform(-0.03, 0.03)),
                       fees=FeeSchedule(delivery_fee_cents=rng.choice([399, 499, 699, 899]), min_order_cents=rng.choice([1500, 2500, 4000])),
                       eta_mean_minutes=rng.randint(15, 40), eta_std_minutes=rng.randint(3, 12),
                       max_meals_per_slot=rng.choice([15, 30, 60]), reliability=round(rng.uniform(0.7, 0.98), 2),
                       verified_allergen_data=rng.random() < 0.3)
        restaurants.append(r)
        for name, ings, dish, spice in _DISHES[cuisine]:
            price = rng.randint(1100, 1900)
            verified = {_ING_ALLERGEN[i] for i in ings if i in _ING_ALLERGEN} if r.verified_allergen_data else None
            items.append(MenuItem(restaurant_id=r.id, name=name, description=f"{name} with {', '.join(ings)}", ingredients=ings,
                                  price_cents=price, modifiers=["no onions", "extra sauce", "add coke", "add side salad"],
                                  verified_allergens=verified, tags=tags_for(ings, dish, spice, cuisine, rng)))
        # one premium item that only fits under budget when the fee is shared
        items.append(MenuItem(restaurant_id=r.id, name=f"{cuisine.title()} Feast", description="large premium plate",
                              ingredients=["chicken", "rice"], price_cents=1750, modifiers=["add coke"],
                              verified_allergens=set() if r.verified_allergen_data else None,
                              tags=tags_for(["chicken", "rice"], "rice", 1, cuisine, rng)))

    users = []
    for k in range(n_users):
        u = User(name=f"user{k}", office_id="hq", home=LatLng(lat=OFFICE.lat + rng.uniform(-0.05, 0.05), lng=OFFICE.lng + rng.uniform(-0.05, 0.05)),
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
