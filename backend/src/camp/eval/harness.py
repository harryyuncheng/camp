"""§8 evaluation harness. Deliverable 6.

Runs a classifier over labelled sets and reports:
  - recall on constraints / allergens (GATING)
  - per-event-type precision/recall (pass 1), scope accuracy
  - top-1 / top-3 accuracy for modification target-item resolution
  - menu tag accuracy on a tagged sample
Run Jev and the LLM on the same sets: `compare(...)`.
Labelled sets: synthetic templates here + `labels/*.csv` templates for human labels.
"""
from __future__ import annotations

import asyncio
import csv
import random
from dataclasses import dataclass, field
from pathlib import Path

from ..models import ALLERGENS, CUISINES, MenuItem
from . import synthetic_labels as SL
from ..ai import schemas as S
from ..ai.classify import Classifier
from ..ai.feedback_parse import parse_feedback
from ..ai.modifications import _shortlist

LABELS_DIR = Path(__file__).parent / "labels"
EVENT_TYPES = ["rating", "preference", "context", "constraint", "logistics", "meta", "change_item"]


@dataclass
class Report:
    backend: str
    n_feedback: int = 0
    constraint_recall: float = 0.0
    allergen_recall: float = 0.0
    per_type: dict[str, dict[str, float]] = field(default_factory=dict)
    scope_accuracy: float = 0.0
    n_mods: int = 0
    mod_top1: float = 0.0
    mod_top3: float = 0.0
    n_tags: int = 0
    tag_accuracy: dict[str, float] = field(default_factory=dict)

    def gate_passed(self, threshold: float = 0.95) -> bool:
        return self.constraint_recall >= threshold and self.allergen_recall >= threshold

    def pretty(self) -> str:
        lines = [f"== {self.backend} ==",
                 f"feedback msgs={self.n_feedback}  constraint recall={self.constraint_recall:.2f}  allergen recall={self.allergen_recall:.2f}  "
                 f"scope acc={self.scope_accuracy:.2f}  GATE={'PASS' if self.gate_passed() else 'FAIL'}"]
        for t, m in self.per_type.items():
            lines.append(f"  {t:<12} P={m['precision']:.2f} R={m['recall']:.2f} n={int(m['n'])}")
        lines.append(f"modifications={self.n_mods}  top1={self.mod_top1:.2f}  top3={self.mod_top3:.2f}")
        lines.append(f"menu tags={self.n_tags}  " + "  ".join(f"{k}={v:.2f}" for k, v in self.tag_accuracy.items()))
        return "\n".join(lines)


def load_csv(name: str) -> list[dict]:
    p = LABELS_DIR / name
    if not p.exists():
        return []
    with p.open() as f:
        return [r for r in csv.DictReader(f) if r.get("text") or r.get("name")]


async def eval_feedback(clf: Classifier, rows: list[dict]) -> dict:
    tp = {t: 0 for t in EVENT_TYPES}; fp = dict(tp); fn = dict(tp)
    c_tp = c_fn = a_tp = a_fn = 0
    scope_ok = scope_n = 0
    for r in rows:
        want = set(r["types"].split("|")) if r["types"] else set()
        res = await parse_feedback(clf, r["text"], "eval")
        got = {e.type for e in res.events}
        for t in EVENT_TYPES:
            if t in want and t in got: tp[t] += 1
            elif t in got: fp[t] += 1
            elif t in want: fn[t] += 1
        if "constraint" in want:
            ev = next((e for e in res.events if e.type == "constraint"), None)
            hit = ev is not None and ev.payload.get("which") == r.get("constraint")
            c_tp += hit; c_fn += (not hit)
            if r.get("constraint", "").startswith("allergen:"):
                a_tp += hit; a_fn += (not hit)
        if r.get("scope"):
            scope_n += 1
            scope_ok += any(e.scope == r["scope"] for e in res.events)
    per = {t: dict(precision=tp[t] / max(1, tp[t] + fp[t]), recall=tp[t] / max(1, tp[t] + fn[t]), n=tp[t] + fn[t]) for t in EVENT_TYPES}
    return dict(n=len(rows), per_type=per, constraint_recall=c_tp / max(1, c_tp + c_fn), allergen_recall=a_tp / max(1, a_tp + a_fn),
                scope_accuracy=scope_ok / max(1, scope_n))


async def eval_modifications(clf: Classifier, rows: list[dict], menu: list[MenuItem]) -> dict:
    top1 = top3 = 0
    for r in rows:
        short = _shortlist(menu, r["text"])
        ans = await clf.ask(r["text"], S.target_item_schema([i.name for i in short]))
        probs = ans.probabilities.get("item") or {}
        ranked = [k for k, _ in sorted(probs.items(), key=lambda kv: -kv[1])] or [ans.output.item]
        top1 += ranked[0] == r["target"]
        top3 += r["target"] in ranked[:3]
    return dict(n=len(rows), top1=top1 / max(1, len(rows)), top3=top3 / max(1, len(rows)))


async def eval_tags(clf: Classifier, rows: list[dict]) -> dict:
    from ..ai.tagging import tag_item
    fields = ["cuisine", "protein", "dish_type", "kcal_band"]
    ok = {f: 0 for f in fields}; allergen_ok = 0; allergen_n = 0
    for r in rows:
        item = MenuItem(restaurant_id="eval", name=r["name"], description=r.get("description", ""),
                        ingredients=[x for x in r.get("ingredients", "").split("|") if x], price_cents=1000)
        t = await tag_item(clf, item)
        for f in fields:
            v = getattr(t, f)
            v = v.value if hasattr(v, "value") else v
            ok[f] += (str(v) == r.get(f))
        want = set(x for x in r.get("allergens", "").split("|") if x)
        for a in ALLERGENS:
            allergen_n += 1
            allergen_ok += ((t.allergen_p.get(a, 0) > 0.1) == (a in want))
    out = {f: ok[f] / max(1, len(rows)) for f in fields}
    out["allergen_flag_acc"] = allergen_ok / max(1, allergen_n)
    return dict(n=len(rows), acc=out)


async def run(clf: Classifier, backend: str, n_synth: int = 200, seed: int = 0, menu: list[MenuItem] | None = None) -> Report:
    rng = random.Random(seed)
    fb = load_csv("feedback.csv") or SL.feedback_set(n_synth, rng)
    menu = menu or SL.menu()
    mods = load_csv("modifications.csv") or SL.modification_set(n_synth // 2, menu, rng)
    tags = load_csv("menu_tags.csv") or SL.tag_set(menu)
    f, m, t = await eval_feedback(clf, fb), await eval_modifications(clf, mods, menu), await eval_tags(clf, tags)
    return Report(backend=backend, n_feedback=f["n"], constraint_recall=f["constraint_recall"], allergen_recall=f["allergen_recall"],
                  per_type=f["per_type"], scope_accuracy=f["scope_accuracy"], n_mods=m["n"], mod_top1=m["top1"], mod_top3=m["top3"],
                  n_tags=t["n"], tag_accuracy=t["acc"])


async def compare(clfs: dict[str, Classifier], **kw) -> list[Report]:
    """Run every backend on the SAME sets (§8)."""
    return [await run(c, name, **kw) for name, c in clfs.items()]


def write_templates() -> None:
    """CSV templates for human labelling."""
    LABELS_DIR.mkdir(exist_ok=True)
    (LABELS_DIR / "feedback.template.csv").write_text("text,types,constraint,scope\n\"Great but too salty\",rating,,meal\n\"Allergic to shellfish\",constraint,allergen:shellfish,ongoing\n")
    (LABELS_DIR / "modifications.template.csv").write_text("text,target\n\"swap to the chicken bowl\",Chicken Bowl\n")
    (LABELS_DIR / "menu_tags.template.csv").write_text("name,description,ingredients,cuisine,protein,dish_type,kcal_band,allergens\nPad Thai,,rice noodles|egg|peanut,thai,tofu,noodles,600-800,egg|peanut|soy\n")
