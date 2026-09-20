"""`classify(state, schema) → typed answer + probabilities`, behind one interface (§7).

JevClassifier   — TypeSafe Jev via pydantic-ai. Primary.
LLMClassifier   — OpenAI with structured output, same schemas. Fallback + 'other' extraction.
MockClassifier  — keyword rules, offline. Used in tests and the synthetic eval.
RoutedClassifier— Jev first, LLM on error/timeout.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# confidence routing (§7.4); constraints need ≥ 0.95 and always confirm
HIGH, MEDIUM = 0.85, 0.60
CONSTRAINT_HIGH = 0.95
LLM_FIXED_CONFIDENCE = 0.70   # LLMs are not calibrated → lands in "medium"


@dataclass
class Answer(Generic[T]):
    output: T
    confidence: dict[str, float] = field(default_factory=dict)          # per field
    probabilities: dict[str, dict[str, float]] = field(default_factory=dict)  # per pick-one field
    backend: str = "mock"

    def conf(self, field_name: str) -> float:
        if field_name in self.confidence:
            return self.confidence[field_name]
        return self.confidence.get("response", 1.0)

    def level(self, field_name: str) -> str:
        c = self.conf(field_name)
        return "high" if c >= HIGH else ("medium" if c >= MEDIUM else "low")


class Classifier(Protocol):
    async def ask(self, state: str, schema: type[T]) -> Answer[T]: ...


async def ask_many(clf: Classifier, state: str, schemas: list[type[BaseModel]]) -> list[Answer]:
    """Many small questions in parallel (§7 rules)."""
    return list(await asyncio.gather(*(clf.ask(state, s) for s in schemas)))


def ask_sync(clf: Classifier, state: str, schema: type[T]) -> Answer[T]:
    return asyncio.run(clf.ask(state, schema))


# ------------------------------------------------------------ Jev

class JevClassifier:
    def __init__(self, model_name: str = "jev-latest", boolean_threshold: float = 0.5, timeout: float = 5.0):
        from pydantic_ai.models.typesafe import TypeSafeModel, TypeSafeModelSettings
        self.model = TypeSafeModel(model_name)
        self.settings = TypeSafeModelSettings(typesafe_boolean_threshold=boolean_threshold, timeout=timeout)

    async def ask(self, state: str, schema: type[T]) -> Answer[T]:
        from pydantic_ai import Agent
        agent = Agent(self.model, output_type=schema, model_settings=self.settings)
        res = await agent.run(state)
        pd = res.response.provider_details or {}
        conf = pd.get("confidence", {})
        if not isinstance(conf, dict):
            conf = {"response": float(conf)}
        return Answer(output=res.output, confidence={k: float(v) for k, v in conf.items()},
                      probabilities=pd.get("probabilities", {}) or {}, backend="jev")


# ------------------------------------------------------------ LLM fallback

class LLMClassifier:
    def __init__(self, model_name: str = "openai:gpt-4.1-mini"):
        self.model_name = model_name

    async def ask(self, state: str, schema: type[T]) -> Answer[T]:
        from pydantic_ai import Agent
        agent = Agent(self.model_name, output_type=schema,
                      instructions="Answer each field strictly from the text. If unsure, choose the conservative or 'other' option.")
        res = await agent.run(state)
        return Answer(output=res.output, confidence={"response": LLM_FIXED_CONFIDENCE}, backend="llm")


# ------------------------------------------------------------ mock

class MockClassifier:
    """rules(state, schema) → partial dict of field values; missing fields get schema defaults / first option."""

    def __init__(self, rules: Callable[[str, type[BaseModel]], dict[str, Any]] | None = None, confidence: float = 0.9):
        from .mock import default_rules
        self.rules = rules or default_rules
        self.confidence = confidence

    async def ask(self, state: str, schema: type[T]) -> Answer[T]:
        values = dict(self.rules(state, schema))
        for name, f in schema.model_fields.items():
            if name in values:
                continue
            values[name] = _default_for(f.annotation)
        return Answer(output=schema.model_validate(values), confidence={"response": self.confidence}, backend="mock")


def _default_for(ann: Any) -> Any:
    from enum import IntEnum
    from typing import get_args, get_origin
    if ann is bool:
        return False
    if isinstance(ann, type) and issubclass(ann, IntEnum):
        members = list(ann)
        return members[len(members) // 2]
    if get_origin(ann) is not None:
        args = get_args(ann)
        return "other" if "other" in args else args[0]
    return None


# ------------------------------------------------------------ routing

class RoutedClassifier:
    def __init__(self, primary: Classifier, fallback: Classifier):
        self.primary, self.fallback = primary, fallback

    async def ask(self, state: str, schema: type[T]) -> Answer[T]:
        try:
            return await self.primary.ask(state, schema)
        except Exception:
            return await self.fallback.ask(state, schema)


def default_classifier() -> Classifier:
    """Jev if TYPESAFE_API_KEY is set (LLM fallback if OPENAI_API_KEY too), else mock."""
    if os.getenv("TYPESAFE_API_KEY"):
        jev = JevClassifier()
        return RoutedClassifier(jev, LLMClassifier()) if os.getenv("OPENAI_API_KEY") else jev
    if os.getenv("OPENAI_API_KEY"):
        return LLMClassifier()
    return MockClassifier()
