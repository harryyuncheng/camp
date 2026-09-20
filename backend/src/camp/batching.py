"""Batch optimizer (§4), office only. Deliverable 3.

    max_{R,a}  Σ_u s(u,a(u)) − λ·total_cost − μ|R| − Σ_u debt_u·max(0, regret_u − δ) − U·|unassigned|
    s.t.       p_a(u) + overhead + f_r / n_r ≤ B_u,  min_order_r ≤ Σ prices,  n_r ≤ capacity_r

Greedy facility location: add the restaurant with the best marginal objective, re-run the
assignment (which recomputes fee shares, so budget feasibility is re-checked), stop when nothing
improves. Regret is soft; per-user sacrifice debt makes the optimizer rotate who yields.
Exact CP-SAT solve is used when the problem is small enough.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .filters import total_cost_cents
from .models import Batch, BatchRestaurant, MenuItem, Restaurant, User

LAMBDA_COST = 0.00004     # utility per cent: $10 of company cost ≈ 0.4 utility
MU_RESTAURANT = 0.15      # operational tie-breaker per restaurant opened
DELTA_REGRET = 0.5        # regret above this is penalised
U_UNASSIGNED = 5.0        # big penalty so the greedy keeps opening restaurants for stranded users
EXACT_MAX_CELLS = 2000    # |users| × |restaurants| threshold for CP-SAT


@dataclass
class Candidate:
    """Scores for one office group. scores[u][item_id] = s(u,i) for pairs that passed non-budget filters."""
    users: dict[str, User]
    restaurants: dict[str, Restaurant]
    items: dict[str, MenuItem]
    scores: dict[str, dict[str, float]]
    meal: str

    def best_global(self, uid: str) -> float:
        sc = self.scores[uid]
        return max(sc.values()) if sc else 0.0


@dataclass
class Assignment:
    assign: dict[str, tuple[str, str]] = field(default_factory=dict)   # uid -> (restaurant_id, item_id)
    n: dict[str, int] = field(default_factory=dict)                     # restaurant_id -> headcount
    objective: float = float("-inf")
    total_cost: int = 0
    regret: dict[str, float] = field(default_factory=dict)


def fee_share(r: Restaurant, n: int) -> int:
    return round(r.fees.delivery_fee_cents / max(n, 1))


def _assign(c: Candidate, R: list[str], n_seed: dict[str, int] | None = None, iters: int = 6) -> Assignment:
    """Assign each user their best budget-feasible option in R, iterating because fee shares depend on headcount."""
    n = {r: (n_seed or {}).get(r, len(c.users)) for r in R}   # optimistic seed: assume everyone shares
    a = Assignment()
    for _ in range(iters):
        assign: dict[str, tuple[str, str]] = {}
        picks_by_r: dict[str, list[tuple[float, str, str]]] = {r: [] for r in R}
        for uid, u in c.users.items():
            best, best_pair = None, None
            for rid in R:
                rest = c.restaurants[rid]
                share = fee_share(rest, n[rid])
                for iid, s in c.scores[uid].items():
                    if c.items[iid].restaurant_id != rid:
                        continue
                    if total_cost_cents(c.items[iid], rest, share) > u.budget(c.meal):
                        continue
                    if best is None or s > best:
                        best, best_pair = s, (rid, iid)
            if best_pair:
                assign[uid] = best_pair
                picks_by_r[best_pair[0]].append((best, uid, best_pair[1]))
        # capacity: keep the highest-scoring users, bump the rest to their next best (simple: drop them this round)
        for rid, picks in picks_by_r.items():
            cap = c.restaurants[rid].max_meals_per_slot
            if len(picks) > cap:
                picks.sort(reverse=True)
                for _, uid, _ in picks[cap:]:
                    del assign[uid]
        new_n = {r: sum(1 for v in assign.values() if v[0] == r) for r in R}
        if new_n == n:
            break
        n = new_n
    # min order: drop restaurants that don't reach it (their users become unassigned this round)
    for rid in R:
        subtotal = sum(c.items[iid].price_cents for (r2, iid) in assign.values() if r2 == rid)
        if 0 < subtotal < c.restaurants[rid].fees.min_order_cents:
            for uid in [u for u, v in assign.items() if v[0] == rid]:
                del assign[uid]
            n[rid] = 0
    a.assign, a.n = assign, n
    a.total_cost = sum(total_cost_cents(c.items[iid], c.restaurants[rid], 0) for rid, iid in assign.values()) \
        + sum(c.restaurants[r].fees.delivery_fee_cents for r in R if n[r] > 0)
    util = 0.0
    fair_pen = 0.0
    for uid in c.users:
        if uid in assign:
            s = c.scores[uid][assign[uid][1]]
            util += s
            reg = c.best_global(uid) - s
            a.regret[uid] = reg
            fair_pen += (1.0 + c.users[uid].traits.sacrifice_debt) * max(0.0, reg - DELTA_REGRET)
        else:
            a.regret[uid] = float("inf")
    unassigned = sum(1 for uid in c.users if uid not in assign)
    opened = sum(1 for r in R if n[r] > 0)
    a.objective = util - LAMBDA_COST * a.total_cost - MU_RESTAURANT * opened - fair_pen - U_UNASSIGNED * unassigned
    return a


def solve_greedy(c: Candidate) -> tuple[list[str], Assignment]:
    R: list[str] = []
    best = _assign(c, R)
    candidates = list(c.restaurants)
    while True:
        improved = None
        for rid in candidates:
            if rid in R:
                continue
            trial = _assign(c, R + [rid], n_seed=best.n)
            if trial.objective > best.objective + 1e-9 and (improved is None or trial.objective > improved[1].objective):
                improved = (rid, trial)
        if improved is None:
            break
        R.append(improved[0])
        best = improved[1]
    R = [r for r in R if best.n.get(r, 0) > 0]
    return R, best


def solve_exact(c: Candidate, time_limit_s: float = 10.0) -> tuple[list[str], Assignment] | None:
    """CP-SAT. Fee-share budget constraint linearised: x[u,r,i] ⇒ fee_r ≤ slack[u,i]·n_r."""
    from ortools.sat.python import cp_model

    SCALE = 1000
    m = cp_model.CpModel()
    users, rests = list(c.users), list(c.restaurants)
    y = {r: m.NewBoolVar(f"y_{r}") for r in rests}
    n = {r: m.NewIntVar(0, len(users), f"n_{r}") for r in rests}
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    for uid, u in c.users.items():
        for iid, s in c.scores[uid].items():
            it = c.items[iid]
            rest = c.restaurants[it.restaurant_id]
            slack = u.budget(c.meal) - total_cost_cents(it, rest, 0)
            if slack < 0:
                continue
            v = m.NewBoolVar(f"x_{uid}_{iid}")
            x[(uid, iid)] = v
            m.Add(v <= y[rest.id])
            # fee ≤ slack·n_r when v; big-M otherwise
            m.Add(rest.fees.delivery_fee_cents <= slack * n[rest.id] + (rest.fees.delivery_fee_cents) * (1 - v))
    for uid in users:
        m.Add(sum(v for (u2, _), v in x.items() if u2 == uid) <= 1)
    for r in rests:
        vs = [v for (_, iid), v in x.items() if c.items[iid].restaurant_id == r]
        m.Add(n[r] == sum(vs))
        m.Add(n[r] <= c.restaurants[r].max_meals_per_slot)
        m.Add(sum(c.items[iid].price_cents * v for (_, iid), v in x.items() if c.items[iid].restaurant_id == r)
              >= c.restaurants[r].fees.min_order_cents * y[r])
        m.Add(n[r] >= y[r])
    # objective (regret penalty approximated linearly with debt weight; δ handled by the greedy only)
    obj = []
    for (uid, iid), v in x.items():
        it = c.items[iid]
        rest = c.restaurants[it.restaurant_id]
        s = c.scores[uid][iid]
        debt = 1.0 + c.users[uid].traits.sacrifice_debt
        reg_pen = debt * max(0.0, c.best_global(uid) - s - DELTA_REGRET)
        gain = s - reg_pen - LAMBDA_COST * total_cost_cents(it, rest, 0) + U_UNASSIGNED
        obj.append(int(gain * SCALE) * v)
    for r in rests:
        obj.append(-int((MU_RESTAURANT + LAMBDA_COST * c.restaurants[r].fees.delivery_fee_cents) * SCALE) * y[r])
    m.Maximize(sum(obj))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    R = [r for r in rests if solver.Value(y[r])]
    a = _assign(c, R, n_seed={r: solver.Value(n[r]) for r in R})
    # trust the solver's assignment where it differs
    for (uid, iid), v in x.items():
        if solver.Value(v):
            a.assign[uid] = (c.items[iid].restaurant_id, iid)
    return R, _assign(c, R, n_seed={r: sum(1 for v in a.assign.values() if v[0] == r) for r in R})


def solve(c: Candidate) -> tuple[list[str], Assignment, str]:
    R, a = solve_greedy(c)
    if len(c.users) * len(c.restaurants) <= EXACT_MAX_CELLS:
        ex = solve_exact(c)
        if ex and ex[1].objective > a.objective + 1e-6:
            return ex[0], ex[1], "exact"
    return R, a, "greedy"


def to_batch(c: Candidate, R: list[str], a: Assignment, office_id: str, date: str) -> Batch:
    brs = []
    for rid in R:
        uids = [u for u, v in a.assign.items() if v[0] == rid]
        if uids:
            brs.append(BatchRestaurant(restaurant_id=rid, user_ids=uids, fee_share_cents=fee_share(c.restaurants[rid], len(uids))))
    return Batch(office_id=office_id, date=date, meal=c.meal, restaurants=brs, objective=a.objective,
                 total_cost_cents=a.total_cost, regret={k: (v if v != float("inf") else -1) for k, v in a.regret.items()})


def update_fairness(c: Candidate, a: Assignment) -> None:
    """Rotate who yields: debt grows with regret above δ, decays otherwise. Caller persists users."""
    for uid, u in c.users.items():
        reg = a.regret.get(uid, 0.0)
        if reg != float("inf") and reg > DELTA_REGRET:
            u.traits.sacrifice_debt += reg - DELTA_REGRET
        else:
            u.traits.sacrifice_debt *= 0.5
