"""CLI harness: synthetic world → run a batch → print what happened."""
from __future__ import annotations

import statistics
from collections import Counter

import typer

from . import synth
from .models import MenuItem, Restaurant, User
from .pipeline import plan_home, plan_office
from .store import Store

app = typer.Typer(no_args_is_help=True)


def _load(db: str, users: int, restaurants: int | None, seed: int) -> Store:
    store = Store(db)
    if not store.all(User):
        u, r, i = synth.make_world(users, restaurants, seed)
        store.put_many(u); store.put_many(r); store.put_many(i)
    return store


@app.command()
def run_batch(db: str = ":memory:", users: int = 40, restaurants: int | None = None, seed: int = 0, days: int = 1,
              temp_c: float = 18.0, raining: bool = False):
    """Run the office lunch batch for N consecutive days on synthetic data."""
    from datetime import date, timedelta
    store = _load(db, users, restaurants, seed)
    rests = {r.id: r for r in store.all(Restaurant)}
    items = {i.id: i for i in store.all(MenuItem)}
    for d in range(days):
        ctx = synth.make_context("lunch", date(2026, 9, 21) + timedelta(days=d), temp_c=temp_c, raining=raining)
        plan = plan_office(store, "hq", synth.OFFICE, ctx)
        b = plan.batch
        typer.echo(f"\n=== {ctx.date} lunch  solver={plan.solver}  objective={b.objective:.2f}  company cost=${b.total_cost_cents/100:.2f}")
        for br in b.restaurants:
            typer.echo(f"  {rests[br.restaurant_id].name:<24} n={len(br.user_ids):<3} fee share=${br.fee_share_cents/100:.2f}")
        regs = [v for v in b.regret.values() if v >= 0]
        typer.echo(f"  users in batch={len(plan.orders)}  suggest-only={len(plan.suggest_only)}  unassigned={len(plan.unassigned)}")
        if regs:
            typer.echo(f"  regret mean={statistics.mean(regs):.2f}  max={max(regs):.2f}  >0.5: {sum(r > 0.5 for r in regs)}")
        over = [o for o in plan.orders if o.total_cents > store.get(User, o.user_id).budget('lunch')]
        typer.echo(f"  budget overruns={len(over)}  novel picks={sum(o.novel for o in plan.orders)}")
        if d == 0:
            for o in plan.orders[:5]:
                u = store.get(User, o.user_id)
                recs = plan.recommendations[u.id]
                alts = ", ".join(items[r.item_id].name for r in recs[1:])
                typer.echo(f"    {u.name:<8} -> {items[o.line.item_id].name:<24} ${o.total_cents/100:.2f}/{u.budget('lunch')/100:.0f}  alts: {alts}")


@app.command()
def run_home(db: str = ":memory:", seed: int = 0):
    store = _load(db, 40, None, seed)
    items = {i.id: i for i in store.all(MenuItem)}
    u = store.all(User)[0]
    plan = plan_home(store, u, synth.OFFICE, synth.make_context("dinner"))
    for r in plan.recommendations[u.id]:
        typer.echo(f"{items[r.item_id].name:<24} score={r.score:.2f} {r.breakdown}")


if __name__ == "__main__":
    app()


@app.command()
def eval(n: int = 200, backends: str = "mock"):
    """Run the §8 evaluation harness. backends: comma list of mock,jev,llm (jev/llm need API keys)."""
    import asyncio
    from .ai.classify import JevClassifier, LLMClassifier, MockClassifier
    from .eval import harness
    harness.write_templates()
    clfs = {}
    for b in backends.split(","):
        clfs[b] = {"mock": MockClassifier, "jev": JevClassifier, "llm": LLMClassifier}[b]()
    for rep in asyncio.run(harness.compare(clfs, n_synth=n)):
        typer.echo(rep.pretty())


@app.command()
def feedback_demo(seed: int = 0):
    """Show NL feedback → events → profile updates on a synthetic user."""
    import asyncio
    from . import feedback as fb
    from .ai.classify import default_classifier
    from .ai.feedback_parse import parse_feedback
    store = _load(":memory:", 10, 12, seed)
    u = store.all(User)[0]
    clf = default_classifier()
    for text in ["Great, but too salty", "Not into spicy food", "I'm allergic to shellfish", "Arrived cold again", "Let me pick myself"]:
        res = asyncio.run(parse_feedback(clf, text, u.id))
        typer.echo(f"\n> {text}")
        for e in res.events:
            typer.echo(f"  event {e.type}/{e.scope} conf={e.confidence:.2f} {e.payload}")
            for line in fb.apply_event(store, e):
                typer.echo(f"    → {line}")
        if res.clarify:
            typer.echo(f"  ask: {res.clarify}")
    typer.echo(f"\nlearned: {fb.learned_view(store.get(User, u.id))}")


@app.command()
def migrate(source: str = "camp.db", target: str | None = None):
    """Copy every table from a SQLite file (or any store URL) into the target database (default: CAMP_DATABASE_URL)."""
    import os
    dst_url = target or os.getenv("CAMP_DATABASE_URL")
    if not dst_url:
        raise typer.BadParameter("set CAMP_DATABASE_URL or pass --target postgresql://...")
    src, dst = Store(source), Store(dst_url)
    for table, n in dst.copy_from(src).items():
        typer.echo(f"  {table:<12} {n} rows")
    typer.echo(f"copied {source} → {dst_url}")


@app.command()
def sync(db: str = "camp.db", radius_km: float = 6.0, tag: bool = True, fixtures: bool = False):
    """Pull restaurants + menus from Uber/DoorDash (mocks unless env keys are set), de-dupe, tag, store."""
    import asyncio
    from .ai.classify import default_classifier
    from .ai.tagging import tag_menu
    from .providers import MockProvider, providers_from_env, sync_catalog
    store = Store(db)
    provs = providers_from_env()
    if fixtures:
        for p in provs:
            if isinstance(p, MockProvider):
                p.dump_fixtures()
    clf = default_classifier()
    tagger = (lambda items: tag_menu(clf, items)) if tag else None
    rep = asyncio.run(sync_catalog(store, provs, synth.OFFICE, radius_km, tagger=tagger))
    typer.echo(f"providers: {[p.name for p in provs]}  stores seen: {rep.stores_seen}  merged: {rep.merged}")
    typer.echo(f"restaurants: {rep.restaurants}  items: {rep.items}  skipped: {rep.skipped_providers}  errors: {len(rep.errors)}")
    for r in store.all(Restaurant)[:6]:
        typer.echo(f"  {r.name:<24} via {r.platform:<8} ids={list(r.platform_ids)} fee=${r.fees.delivery_fee_cents/100:.2f} eta={r.eta_mean_minutes}m verified_allergens={r.verified_allergen_data}")
