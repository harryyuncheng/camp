"""Jev question schemas (§7). Each class = one request; each field = one typed question.
Questions live in field descriptions. Every Choice has an 'other' escape hatch (§7.1 taxonomy gaps)."""
from __future__ import annotations

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field

from ..models import ALLERGENS, CUISINES, DIETS


# ------------------------------------------------------------ §7.1 feedback pass 1

class FeedbackPass1(BaseModel):
    """Six Nouls in parallel: which event types does this message contain?"""
    is_rating: bool = Field(description="Does the message rate or react to a meal they already ate (taste, portion, enjoyment)?")
    is_modification: bool = Field(description="Does the message ask to change an upcoming order (swap item, add/remove something, change restaurant, cancel)?")
    is_lasting_preference: bool = Field(description="Does the message state an ongoing food preference (likes/dislikes a cuisine, ingredient, spice level) that should apply from now on?")
    is_temporary_context: bool = Field(description="Does the message state a wish for just today or this meal (e.g. 'something light today')?")
    is_constraint: bool = Field(description="Does the message mention an allergy, intolerance or dietary restriction (religious, vegetarian, vegan, gluten-free)?")
    is_logistics: bool = Field(description="Does the message report a delivery problem (late, cold, wrong, missing, damaged)?")
    is_meta: bool = Field(description="Does the message ask to change how the service works for them (pick myself, more options, stop auto-ordering)?")


# ------------------------------------------------------------ §7.1 feedback pass 2

class Sentiment5(IntEnum):
    """Five-level sentiment rubric."""
    very_negative = 0
    """Strongly disliked, would not eat again."""
    negative = 1
    """Mildly disappointed."""
    neutral = 2
    """Fine, no strong feeling."""
    positive = 3
    """Liked it."""
    very_positive = 4
    """Loved it, would reorder."""


class Aspect3(IntEnum):
    """Per-aspect sentiment; 1 = not mentioned."""
    negative = 0
    """Complained about this aspect."""
    not_mentioned = 1
    """Aspect not mentioned."""
    positive = 2
    """Praised this aspect."""


class RatingDetail(BaseModel):
    overall: Sentiment5 = Field(description="Overall sentiment about the meal.")
    taste: Aspect3 = Field(description="Sentiment about taste or flavour, if mentioned.")
    portion: Aspect3 = Field(description="Sentiment about portion size, if mentioned.")
    temperature: Aspect3 = Field(description="Sentiment about the food's temperature on arrival, if mentioned.")
    value: Aspect3 = Field(description="Sentiment about value or price, if mentioned.")
    too_heavy: bool = Field(description="Did they say the meal was too heavy, too big, or not healthy enough?")


PrefAttribute = Literal[tuple(f"cuisine:{c}" for c in CUISINES) + (
    "protein:chicken", "protein:beef", "protein:pork", "protein:fish", "protein:shrimp", "protein:tofu",
    "spice", "heaviness", "ingredient:onion", "ingredient:cilantro", "ingredient:mushroom", "ingredient:cheese",
    "ingredient:mayo", "ingredient:egg", "dish:salad", "dish:soup", "dish:sandwich", "dish:bowl", "other")]


class PreferenceDetail(BaseModel):
    attribute: PrefAttribute = Field(description="Which food attribute the preference is about. Pick 'other' if none fits.")
    direction: Literal["more", "less", "never"] = Field(description="Do they want more of it, less of it, or never?")
    scope: Literal["today", "ongoing"] = Field(description="Is this for today only, or from now on?")


class ContextDetail(BaseModel):
    lighter: bool = Field(description="Do they want something lighter or smaller than usual today?")
    heavier: bool = Field(description="Do they want something more filling or indulgent today?")
    spicier: bool = Field(description="Do they want something spicier than usual today?")
    milder: bool = Field(description="Do they want something milder than usual today?")
    warm: bool = Field(description="Do they want something warm or comforting today?")


ConstraintName = Literal[tuple(f"allergen:{a}" for a in ALLERGENS) + tuple(f"diet:{d}" for d in DIETS) + ("other",)]


class ConstraintDetail(BaseModel):
    which: ConstraintName = Field(description="Which allergy or dietary restriction is mentioned. 'other' if none fits.")
    action: Literal["add", "remove"] = Field(description="Are they telling us they HAVE this restriction (add), or that it no longer applies (remove)?")
    severe: bool = Field(description="Is it described as severe, serious, anaphylactic, or a medical allergy rather than a preference?")


class LogisticsDetail(BaseModel):
    issue: Literal["late", "cold", "wrong", "missing", "damaged", "other"] = Field(description="What went wrong with the delivery?")
    repeated: bool = Field(description="Do they say it has happened before ('again', 'every time')?")


class MetaDetail(BaseModel):
    wants: Literal["pick_myself", "more_options", "fewer_options", "stop_auto_order", "resume_auto_order", "other"] = Field(
        description="What change to the service do they want?")


# ------------------------------------------------------------ §7.2 modifications

class ModIntent(BaseModel):
    intent: Literal["swap_item_same_restaurant", "change_restaurant", "add_extras", "remove_ingredient",
                    "go_manual", "cancel", "other"] = Field(description="What kind of change to the order is being requested?")


def target_item_schema(option_names: list[str]) -> type[BaseModel]:
    """Choice over a pre-filtered shortlist (≤ 254 + 'none of these')."""
    opts = tuple(option_names[:254]) + ("none of these",)
    return type("TargetItem", (BaseModel,), {
        "__annotations__": {"item": Literal[opts]},  # type: ignore[valid-type]
        "item": Field(description="Which menu item does the message refer to as the one they want?"),
    })


def customizations_schema(modifiers: list[str]) -> type[BaseModel]:
    """One Noul per modifier the restaurant's ordering system actually offers."""
    ann, ns = {}, {}
    for i, m in enumerate(modifiers[:60]):
        key = f"m{i}"
        ann[key] = bool
        ns[key] = Field(description=f"Does the message ask for this modification: '{m}'?")
    ns["__annotations__"] = ann
    ns["__modifiers__"] = modifiers[:60]
    return type("Customizations", (BaseModel,), ns)


# ------------------------------------------------------------ §7.3 menu tagging

class Level5(IntEnum):
    none = 0
    """None / not at all."""
    low = 1
    """Low."""
    medium = 2
    """Medium."""
    high = 3
    """High."""
    very_high = 4
    """Very high."""


class MenuTagQuestions(BaseModel):
    cuisine: Literal[tuple(CUISINES) + ("other",)] = Field(description="Which cuisine best describes this dish?")
    protein: Literal["chicken", "beef", "pork", "fish", "shrimp", "tofu", "egg", "none", "other"] = Field(description="Main protein?")
    dish_type: Literal["bowl", "sandwich", "salad", "noodles", "rice", "pizza", "taco", "curry", "soup", "wrap", "other"] = Field(description="Dish format?")
    spice: Level5 = Field(description="How spicy is the dish?")
    heaviness: Level5 = Field(description="How heavy or filling is the dish?")
    warm: Level5 = Field(description="Is the dish served hot (very_high) or cold (none)?")
    kcal_band: Literal["<400", "400-600", "600-800", "800+"] = Field(description="Estimated calories per serving.")
    protein_band: Literal["<15g", "15-30g", "30-45g", "45g+"] = Field(description="Estimated protein grams per serving.")
    vegetarian: bool = Field(description="Is the dish vegetarian (no meat or fish)?")
    vegan: bool = Field(description="Is the dish vegan (no animal products at all)?")
    halal: bool = Field(description="Is the dish likely halal (no pork, no alcohol)?")
    travels_well: bool = Field(description="Would this dish still be good after 30 minutes in a delivery bag?")
    contains_peanut: bool = Field(description="Might the dish contain peanuts?")
    contains_tree_nut: bool = Field(description="Might the dish contain tree nuts (almond, cashew, walnut, etc.)?")
    contains_shellfish: bool = Field(description="Might the dish contain shellfish (shrimp, crab, lobster)?")
    contains_fish: bool = Field(description="Might the dish contain fish?")
    contains_dairy: bool = Field(description="Might the dish contain dairy (milk, cheese, cream, butter)?")
    contains_egg: bool = Field(description="Might the dish contain egg?")
    contains_gluten: bool = Field(description="Might the dish contain gluten (wheat, bread, pasta, soy sauce)?")
    contains_soy: bool = Field(description="Might the dish contain soy?")
    contains_sesame: bool = Field(description="Might the dish contain sesame?")
