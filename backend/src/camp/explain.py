"""'Why this pick' text (§ core principle: a small LLM writes user-facing text, never decides)."""
from __future__ import annotations

import os

from .models import MenuItem, Recommendation, User


def explain_template(u: User, item: MenuItem, rec: Recommendation) -> str:
    top = sorted(rec.breakdown.items(), key=lambda kv: -kv[1])[:2]
    reasons = {"affinity": "it's close to things you've liked", "novelty": "you like trying new things",
               "health": "it fits your protein and calorie goals", "context": "it suits today's weather",
               "reliability": "this restaurant is reliable", "repetition": "", "learned": ""}
    why = " and ".join(r for k, _ in top if (r := reasons.get(k)))
    return f"{item.name}: {why or 'a solid pick'}."


async def explain_llm(u: User, item: MenuItem, rec: Recommendation, model: str = "anthropic:claude-haiku-4-5-20251001") -> str:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return explain_template(u, item, rec)
    from pydantic_ai import Agent
    agent = Agent(model, instructions="Write one friendly sentence (max 18 words) telling the user why this lunch was picked for them. "
                                      "Use only the given reasons. No health claims beyond the listed ones.")
    facts = f"Item: {item.name}. Score components: {rec.breakdown}. Novel for user: {rec.novel}."
    res = await agent.run(facts)
    return res.output.strip()
