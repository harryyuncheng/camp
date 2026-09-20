"""Free-text craving ("I want tacos") → typed search terms over the catalog.

`CravingQuery` is one OpenAI structured-output request: the same schema-per-question style as the other
`ai` modules, but answered in a single call because the fields describe one search. With no `OPENAI_API_KEY`
the keyword reader below produces the same shape offline, so the demo and the tests never need a key.
"""
from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, Field

from ..models import CUISINES, DISH_TYPES

CravingCuisine = Literal[tuple(CUISINES) + ("any",)]
CravingDish = Literal[tuple(DISH_TYPES) + ("any",)]

INSTRUCTIONS = (
    "You turn one sentence about what someone feels like eating into search terms for a restaurant menu "
    "database. Only use what the sentence says: pick 'any' when they did not name a cuisine or a dish "
    "format, and leave lists empty rather than inventing terms."
)


class CravingQuery(BaseModel):
    cuisine: CravingCuisine = Field(description="Which cuisine are they asking for? 'any' if they did not name one.")
    dish_type: CravingDish = Field(description="Which dish format are they asking for? 'any' if they did not name one.")
    keywords: list[str] = Field(default_factory=list,
                                description="Up to five lowercase dish or ingredient words to look for on menus, e.g. ['taco', 'al pastor'].")
    avoid: list[str] = Field(default_factory=list, description="Lowercase words for anything they said they do not want.")
    vegetarian: bool = Field(default=False, description="Did they ask for vegetarian food?")
    vegan: bool = Field(default=False, description="Did they ask for vegan food?")
    gluten_free: bool = Field(default=False, description="Did they ask for gluten-free food?")
    spicy: bool = Field(default=False, description="Did they ask for something spicy?")
    max_price_cents: int = Field(default=0, description="Spending limit in cents if they gave one ('under $15' → 1500), otherwise 0.")
    summary: str = Field(default="", description="Their craving in three words or fewer, e.g. 'tacos'.")

    @property
    def is_empty(self) -> bool:
        return self.cuisine == "any" and self.dish_type == "any" and not self.keywords


# ---------------------------------------------------------------- offline reader

_CUISINE_WORDS: dict[str, tuple[str, ...]] = {
    "mexican": ("mexican", "taco", "tacos", "burrito", "quesadilla", "al pastor", "carnitas", "tex-mex", "nachos"),
    "thai": ("thai", "pad thai", "green curry", "tom yum", "drunken noodle"),
    "japanese": ("japanese", "sushi", "ramen", "udon", "donburi", "katsu", "poke", "teriyaki"),
    "chinese": ("chinese", "dumpling", "dumplings", "lo mein", "kung pao", "dim sum", "szechuan", "sichuan"),
    "korean": ("korean", "bibimbap", "bulgogi", "kimchi", "gochujang"),
    "vietnamese": ("vietnamese", "pho", "banh mi", "vermicelli"),
    "indian": ("indian", "tikka", "masala", "biryani", "naan", "korma", "vindaloo", "samosa"),
    "italian": ("italian", "pasta", "spaghetti", "lasagna", "risotto", "carbonara", "penne"),
    "mediterranean": ("mediterranean", "greek", "falafel", "hummus", "shawarma", "gyro", "kebab", "halal cart"),
    "pizza": ("pizza", "slice", "margherita", "pepperoni"),
    "burger": ("burger", "cheeseburger", "smash burger", "patty"),
    "sandwich": ("sandwich", "sub", "hoagie", "panini", "bagel", "deli"),
    "salad": ("salad", "greens", "caesar"),
    "american": ("american", "bbq", "barbecue", "wings", "fried chicken", "mac and cheese"),
    "bakery": ("bakery", "pastry", "croissant", "danish", "cookie"),
}
_DISH_WORDS: dict[str, tuple[str, ...]] = {
    "taco": ("taco", "tacos"),
    "burger": ("burger", "burgers", "cheeseburger"),
    "pizza": ("pizza", "slice"),
    "salad": ("salad", "salads"),
    "soup": ("soup", "broth", "pho", "ramen"),
    "noodles": ("noodle", "noodles", "pasta", "ramen", "pad thai", "lo mein", "udon"),
    "rice": ("rice", "biryani", "fried rice", "donburi"),
    "curry": ("curry", "masala", "tikka"),
    "sandwich": ("sandwich", "sub", "panini", "banh mi", "bagel", "hoagie"),
    "wrap": ("wrap", "burrito", "gyro", "shawarma"),
    "bowl": ("bowl", "poke", "bibimbap", "grain bowl"),
}
_DIET_WORDS = {"vegetarian": ("vegetarian", "veggie", "no meat"), "vegan": ("vegan", "plant based", "plant-based"),
               "gluten_free": ("gluten free", "gluten-free", "no gluten", "celiac")}
_SPICE_WORDS = ("spicy", "hot ", "fiery", "extra heat")
_STOP = {"i", "want", "a", "an", "the", "some", "something", "im", "i'm", "feel", "feeling", "like", "craving",
         "crave", "really", "today", "for", "lunch", "dinner", "please", "would", "love", "to", "eat", "get",
         "me", "of", "instead", "rather", "with", "and", "or", "in", "mood", "hungry", "up", "is", "it"}


def keyword_query(text: str) -> CravingQuery:
    """Offline stand-in for the LLM: enough to demo 'I want tacos' with no API key configured."""
    low = f" {text.lower().strip()} "
    cuisine = next((c for c, words in _CUISINE_WORDS.items() if any(w in low for w in words)), "any")
    dish = next((d for d, words in _DISH_WORDS.items() if any(w in low for w in words)), "any")
    avoid = [w for w in re.findall(r"(?:no|without|hate|dislike|not)\s+([a-z]{3,})", low) if w not in _STOP]
    tokens = [t for t in re.findall(r"[a-z][a-z'-]{2,}", low) if t not in _STOP and t not in avoid]
    price = re.search(r"(?:under|below|less than|max)\s*\$?\s*(\d{1,3})", low)
    return CravingQuery(cuisine=cuisine, dish_type=dish, keywords=tokens[:5], avoid=avoid[:5],
                        vegetarian=any(w in low for w in _DIET_WORDS["vegetarian"]),
                        vegan=any(w in low for w in _DIET_WORDS["vegan"]),
                        gluten_free=any(w in low for w in _DIET_WORDS["gluten_free"]),
                        spicy=any(w in low for w in _SPICE_WORDS),
                        max_price_cents=int(price.group(1)) * 100 if price else 0,
                        summary=" ".join(tokens[:3]) or text.strip()[:40])


# ---------------------------------------------------------------- OpenAI

async def parse_craving(text: str, model_name: str = "openai:gpt-4.1-mini") -> tuple[CravingQuery, str]:
    """(query, backend). OpenAI structured output when `OPENAI_API_KEY` is set, keywords otherwise or on error."""
    if not os.getenv("OPENAI_API_KEY"):
        return keyword_query(text), "keywords"
    try:
        from pydantic_ai import Agent
        agent = Agent(model_name, output_type=CravingQuery, instructions=INSTRUCTIONS)
        res = await agent.run(text)
    except Exception:
        return keyword_query(text), "keywords"
    query = res.output
    if query.is_empty:                       # the model found nothing; the reader still catches plain dish words
        fallback = keyword_query(text)
        query = query.model_copy(update=dict(cuisine=fallback.cuisine, dish_type=fallback.dish_type, keywords=fallback.keywords))
    if not query.summary:
        query.summary = text.strip()[:40]
    return query, "llm"
