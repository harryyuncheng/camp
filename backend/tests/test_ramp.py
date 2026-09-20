"""Ramp spending limits and overage requests, against a stubbed Ramp API (no network, no sandbox writes)."""
import uuid

import pytest

from camp.models import RampOverageRequest
from camp.ramp import Problem, RampService
from camp.store import Store

USER = "df2430bc-daaa-4b0b-8d1b-c9c78142b95f"
LIMIT = "6504db8c-3be2-45f4-ae78-f775430beeea"


def limit_row(amount=5000, spent=0, name="Everyday Expenses", state="ACTIVE", txn=None):
    return {"id": LIMIT, "display_name": name, "state": state,
            "restrictions": {"interval": "DAILY", "limit": {"amount": amount, "currency_code": "USD"},
                             "transaction_amount_limit": {"amount": txn, "currency_code": "USD"} if txn else None,
                             "next_interval_reset": "2026-09-21T00:00:00+00:00"},
            "balance": {"total": {"amount": spent, "currency_code": "USD"}},
            "users": [{"user_id": USER}]}


class FakeRamp:
    """Stands in for RampClient: records writes, serves the limits the tests set up."""
    def __init__(self, rows):
        self.rows = rows
        self.writes = []

    def list(self, path, scopes):
        return list(self.rows)

    def request(self, method, path, scopes, payload=None, key=None):
        if method == "GET" and path.startswith("/limits/"):
            return self.rows[0]
        self.writes.append((method, path, payload))
        return self.rows[0]


def service(rows=None):
    svc = RampService(Store())
    svc.ramp = FakeRamp(rows if rows is not None else [limit_row()])
    return svc


def test_spend_limits_reports_the_binding_ramp_limit_not_a_local_budget():
    svc = service([limit_row(amount=5000, spent=1200), limit_row(amount=100_000, name="camp · old-allocation")])
    snap = svc.spend_limits(USER)
    # the camp allocation is lunch money for one order, not a standing limit, so it is left out
    assert [x["name"] for x in snap["limits"]] == ["Everyday Expenses"]
    assert snap["perOrderCents"] == 3800 and snap["limit"]["spentCents"] == 1200
    assert snap["overages"] == [] and snap["pendingOverages"] == 0


def test_per_order_ceiling_is_the_smaller_of_remaining_and_the_transaction_limit():
    svc = service([limit_row(amount=5000, txn=2500)])
    assert svc.spend_limits(USER)["perOrderCents"] == 2500


def test_no_active_ramp_limit_leaves_the_local_cap_in_charge():
    svc = service([limit_row(state="TERMINATED")])
    snap = svc.spend_limits(USER)
    assert snap["limit"] is None and snap["perOrderCents"] is None


def test_overage_request_is_idempotent_and_one_at_a_time():
    svc = service()
    rid = str(uuid.uuid4())
    body = {"requestID": rid, "userID": USER, "requestedCents": 7500, "reason": "Team lunch", "requester": "Harry"}
    first = svc.request_overage(body)
    assert first["state"] == "pending" and first["baselineCents"] == 5000 and first["limitID"] == LIMIT
    assert svc.request_overage(body)["id"] == first["id"]          # a retry files nothing new
    assert svc.store.count(RampOverageRequest) == 1
    with pytest.raises(Problem):                                    # a second pending ask waits its turn
        svc.request_overage({"requestID": str(uuid.uuid4()), "userID": USER, "requestedCents": 9000})
    with pytest.raises(Problem):                                    # nothing to raise: it is under the limit
        svc.request_overage({"requestID": str(uuid.uuid4()), "userID": USER, "requestedCents": 1000})


def test_approval_raises_the_limit_in_ramp_and_keeps_the_baseline():
    svc = service([limit_row(amount=5000, spent=1000)])
    rid = str(uuid.uuid4())
    svc.request_overage({"requestID": rid, "userID": USER, "requestedCents": 6000})
    decided = svc.decide_overage(rid, {"approve": True, "approver": "Demo admin"})
    assert decided["state"] == "approved" and decided["baselineCents"] == 4000 and decided["decidedBy"] == "Demo admin"
    method, path, payload = svc.ramp.writes[-1]
    # the new ceiling is what was asked for on top of what is already spent, so 6000 is left to spend
    assert (method, path) == ("PATCH", "/funds/" + LIMIT)
    assert payload["spending_restrictions"]["limit"]["amount"] == 7000
    assert payload["spending_restrictions"]["interval"] == "DAILY"
    assert svc.decide_overage(rid, {"approve": False})["state"] == "approved"     # a decision is final


def test_denial_changes_nothing_in_ramp():
    svc = service()
    rid = str(uuid.uuid4())
    svc.request_overage({"requestID": rid, "userID": USER, "requestedCents": 6000})
    assert svc.decide_overage(rid, {"approve": False, "approver": "Demo admin"})["state"] == "denied"
    assert svc.ramp.writes == []
    # denied is not pending, so the next ask goes through
    assert svc.request_overage({"requestID": str(uuid.uuid4()), "userID": USER, "requestedCents": 6500})["state"] == "pending"


def test_a_bad_employee_or_amount_is_refused():
    svc = service()
    with pytest.raises(Problem):
        svc.spend_limits("not-a-uuid")
    with pytest.raises(Problem):
        svc.request_overage({"requestID": str(uuid.uuid4()), "userID": USER, "requestedCents": 5_000_000})
