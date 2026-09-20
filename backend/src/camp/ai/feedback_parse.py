"""§7.1 NL feedback → structured FeedbackEvents. Two passes, questions in parallel.
Raw text is NOT stored on the events (decision 2026-09-19)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..models import FeedbackEvent
from . import schemas as S
from .classify import CONSTRAINT_HIGH, Answer, Classifier


@dataclass
class ParseResult:
    events: list[FeedbackEvent]
    clarify: str | None = None                 # one clarifying question, if ambiguous
    other_cases: list[str] = field(default_factory=list)   # for the LLM 'other' extraction + taxonomy log
    temporary_context: dict[str, float] = field(default_factory=dict)


async def parse_feedback(clf: Classifier, text: str, user_id: str, order_id: str | None = None,
                         item_id: str | None = None, restaurant_id: str | None = None) -> ParseResult:
    p1: Answer[S.FeedbackPass1] = await clf.ask(text, S.FeedbackPass1)
    flags = p1.output
    wanted: list[tuple[str, type]] = []
    if flags.is_rating:
        wanted.append(("rating", S.RatingDetail))
    if flags.is_lasting_preference:
        wanted.append(("preference", S.PreferenceDetail))
    if flags.is_temporary_context:
        wanted.append(("context", S.ContextDetail))
    if flags.is_constraint:
        wanted.append(("constraint", S.ConstraintDetail))
    if flags.is_logistics:
        wanted.append(("logistics", S.LogisticsDetail))
    if flags.is_meta:
        wanted.append(("meta", S.MetaDetail))
    answers = await asyncio.gather(*(clf.ask(text, sch) for _, sch in wanted))

    res = ParseResult(events=[])
    base = dict(user_id=user_id, order_id=order_id, item_id=item_id, restaurant_id=restaurant_id, source="nl")
    for (kind, _), ans in zip(wanted, answers):
        o = ans.output
        conf = ans.conf("response") if ans.backend != "jev" else min(ans.confidence.values() or [1.0])
        if kind == "rating":
            res.events.append(FeedbackEvent(type="rating", scope="meal", confidence=conf, payload=dict(
                overall=int(o.overall), taste=int(o.taste), portion=int(o.portion), temperature=int(o.temperature),
                value=int(o.value), too_heavy=o.too_heavy), **base))
        elif kind == "preference":
            if o.attribute == "other":
                res.other_cases.append("preference")
            res.events.append(FeedbackEvent(type="preference", scope="ongoing" if o.scope == "ongoing" else "today",
                                            confidence=conf, payload=dict(attribute=o.attribute, direction=o.direction), **base))
        elif kind == "context":
            tp: dict[str, float] = {}
            if o.lighter:
                tp["heaviness"] = -0.8
            if o.heavier:
                tp["heaviness"] = 0.6
            if o.spicier:
                tp["spice"] = 0.6
            if o.milder:
                tp["spice"] = -0.8
            res.temporary_context = tp
            res.events.append(FeedbackEvent(type="context", scope="today", confidence=conf, payload=tp, **base))
        elif kind == "constraint":
            if o.which == "other":
                res.other_cases.append("constraint")
                res.clarify = "Which allergy or restriction should I note down?"
                continue
            ev = FeedbackEvent(type="constraint", scope="ongoing", confidence=conf,
                               payload=dict(which=o.which, action=o.action, severe=o.severe, confirmed=False), **base)
            # guardrails (§6.3): add → provisional + confirm; remove → never without explicit confirmation
            ev.needs_confirmation = True
            if conf < CONSTRAINT_HIGH and o.action == "add":
                res.clarify = f"Just to confirm: should I avoid {o.which.split(':', 1)[1].replace('_', ' ')} for you from now on?"
            if o.action == "remove":
                res.clarify = f"You'd like me to stop avoiding {o.which.split(':', 1)[1].replace('_', ' ')}. Please confirm."
            res.events.append(ev)
        elif kind == "logistics":
            res.events.append(FeedbackEvent(type="logistics", scope="restaurant", confidence=conf,
                                            payload=dict(issue=o.issue, repeated=o.repeated), **base))
        elif kind == "meta":
            res.events.append(FeedbackEvent(type="meta", scope="ongoing", confidence=conf, payload=dict(wants=o.wants), **base))
    if flags.is_modification:
        res.events.append(FeedbackEvent(type="change_item", scope="meal", confidence=p1.conf("is_modification"),
                                        payload=dict(needs_modification_pipeline=True), **base))
    if not wanted and not flags.is_modification and res.clarify is None:
        res.clarify = "Got it. Was that about today's meal, a delivery issue, or something you'd like changed going forward?"
    return res
