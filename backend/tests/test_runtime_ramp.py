import copy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from camp.models import RampAttempt, RampOverageRequest
from camp.ramp import Problem, RampService
from camp.store import Store

USER = "df2430bc-daaa-4b0b-8d1b-c9c78142b95f"
LIMIT = "6504db8c-3be2-45f4-ae78-f775430beeea"


class FakeRamp:
    def __init__(self, total=5000, transaction=None):
        self.limit = {"id": LIMIT, "display_name": "Meals", "state": "ACTIVE",
                      "restrictions": {"interval": "DAILY", "limit": {"amount": total, "currency_code": "USD"}},
                      "balance": {"total": {"amount": 0, "currency_code": "USD"}}}
        if transaction is not None:
            self.limit["restrictions"]["transaction_amount_limit"] = {"amount": transaction, "currency_code": "USD"}
        self.funds = []
        self.writes = []
        self.lose_response = False
        self.fail_before_write = False
        self.user_lookup_started = threading.Event()
        self.second_user_lookup = threading.Event()
        self.allow_user_lookup = threading.Event()
        self.allow_user_lookup.set()

    def token(self, scopes):
        return "fake-token"

    def list(self, path, scopes):
        return copy.deepcopy(self.funds if path == "/funds" else [self.limit])

    def request(self, method, path, scopes, payload=None, key=None):
        if method == "GET":
            if path.startswith("/users/"):
                if self.user_lookup_started.is_set():
                    self.second_user_lookup.set()
                self.user_lookup_started.set()
                assert self.allow_user_lookup.wait(5)
                return {"id": USER, "status": "USER_ACTIVE"}
            return copy.deepcopy(self.limit)
        self.writes.append((method, path, copy.deepcopy(payload)))
        if self.fail_before_write:
            raise Problem("connection failed")
        if method == "POST":
            result = {"id": str(uuid.uuid4()), **payload}
            self.funds.append(result)
        else:
            self.limit["restrictions"].update(copy.deepcopy(payload["spending_restrictions"]))
            result = self.limit
        if self.lose_response:
            raise Problem("lost response")
        return copy.deepcopy(result)


def service(store=None, remote=None):
    svc = RampService(store if store is not None else Store())
    svc.ramp = remote if remote is not None else FakeRamp()
    return svc


def allocation_body():
    return {"requestID": str(uuid.uuid4()), "userID": USER, "amountCents": 6000}


def overage_body():
    return {"requestID": str(uuid.uuid4()), "userID": USER, "requestedCents": 7500}


def test_concurrent_allocation_retry_issues_only_one_fund():
    remote = FakeRamp()
    remote.allow_user_lookup.clear()
    svc, body = service(remote=remote), allocation_body()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(svc.allocate, body)
        assert remote.user_lookup_started.wait(2)
        second = pool.submit(svc.allocate, body)
        try:
            remote.second_user_lookup.wait(0.1)
            assert not second.done()
        finally:
            remote.allow_user_lookup.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert len(remote.writes) == 1


def test_lost_allocation_response_reconciles_after_restart_without_second_post(tmp_path):
    path = str(tmp_path / "camp.db")
    store, remote = Store(path), FakeRamp()
    svc, body = service(store, remote), allocation_body()
    remote.lose_response = True
    with pytest.raises(Problem) as error:
        svc.allocate(body)
    assert error.value.status == 409
    store.close()
    reopened = Store(path)
    again = service(reopened, remote)
    result = again.allocate(body)
    assert result["fund"]["amountCents"] == 6000
    assert len(remote.writes) == 1
    assert reopened.get(RampAttempt, body["requestID"]).state == "ready"
    reopened.close()


def test_allocation_failure_to_store_result_still_reconciles(monkeypatch):
    store, remote = Store(), FakeRamp()
    svc, body = service(store, remote), allocation_body()
    original = store.put

    def fail_result(row):
        if isinstance(row, RampAttempt) and row.state == "ready":
            raise OSError("disk full")
        original(row)

    monkeypatch.setattr(store, "put", fail_result)
    with pytest.raises(OSError, match="disk full"):
        svc.allocate(body)
    monkeypatch.setattr(store, "put", original)
    assert service(store, remote).allocate(body)["fund"]["amountCents"] == 6000
    assert len(remote.writes) == 1


def test_overage_id_cannot_be_reused_with_different_employee_or_amount():
    svc, body = service(), overage_body()
    svc.request_overage(body)
    for change in ({"userID": str(uuid.uuid4())}, {"requestedCents": 8000}, {"reason": "different"}):
        with pytest.raises(Problem) as error:
            svc.request_overage({**body, **change})
        assert error.value.status == 409
    assert svc.store.count(RampOverageRequest) == 1
    assert svc.ramp.writes == []


def test_simultaneous_overage_requests_leave_only_one_pending():
    svc = service()

    def request(_):
        try:
            return svc.request_overage(overage_body())["state"]
        except Problem as error:
            assert error.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(request, range(8)))
    assert results.count("pending") == 1
    assert svc.store.count(RampOverageRequest) == 1


def test_lost_overage_response_reconciles_original_amount_after_more_spending(tmp_path):
    path = str(tmp_path / "camp.db")
    store, remote = Store(path), FakeRamp()
    svc, body = service(store, remote), overage_body()
    svc.request_overage(body)
    remote.lose_response = True
    with pytest.raises(Problem) as error:
        svc.decide_overage(body["requestID"], {"approve": True, "approver": "First approver"})
    assert error.value.status == 409
    assert store.get(RampOverageRequest, body["requestID"]).state == "pending"
    remote.limit["balance"]["total"]["amount"] = 1000
    store.close()
    reopened = Store(path)
    again = service(reopened, remote)
    result = again.decide_overage(body["requestID"], {"approve": True, "approver": "Retry approver"})
    assert result["state"] == "approved" and result["decidedBy"] == "First approver"
    assert remote.limit["restrictions"]["limit"]["amount"] == 7500
    assert len(remote.writes) == 1
    reopened.close()


def test_uncertain_overage_cannot_be_retried_as_another_increase_or_denied():
    svc, body = service(), overage_body()
    svc.request_overage(body)
    svc.ramp.fail_before_write = True
    with pytest.raises(Problem):
        svc.decide_overage(body["requestID"], {"approve": True})
    for approve in (True, False):
        with pytest.raises(Problem) as error:
            svc.decide_overage(body["requestID"], {"approve": approve})
        assert error.value.status == 409
    assert svc.store.get(RampOverageRequest, body["requestID"]).state == "pending"
    assert len(svc.ramp.writes) == 1


def test_overage_completion_rolls_back_both_local_rows_and_can_recover(monkeypatch):
    store, remote = Store(), FakeRamp()
    svc, body = service(store, remote), overage_body()
    svc.request_overage(body)
    original = store.put

    def fail_receipt(row):
        if isinstance(row, RampAttempt) and row.state == "ready":
            raise OSError("disk full")
        original(row)

    monkeypatch.setattr(store, "put", fail_receipt)
    with pytest.raises(OSError, match="disk full"):
        svc.decide_overage(body["requestID"], {"approve": True})
    assert store.get(RampOverageRequest, body["requestID"]).state == "pending"
    monkeypatch.setattr(store, "put", original)
    assert service(store, remote).decide_overage(body["requestID"], {"approve": True})["state"] == "approved"
    assert len(remote.writes) == 1


def test_transaction_cap_overage_never_lowers_the_larger_daily_limit():
    svc, body = service(remote=FakeRamp(total=100_000, transaction=2000)), overage_body()
    svc.request_overage(body)
    svc.decide_overage(body["requestID"], {"approve": True})
    spending = svc.ramp.writes[0][2]["spending_restrictions"]
    assert spending["limit"]["amount"] == 100_000
    assert spending["transaction_amount_limit"]["amount"] == 7500


def test_non_usd_limits_are_not_compared_to_dollar_budgets():
    svc = service()
    svc.ramp.limit["restrictions"]["limit"]["currency_code"] = "EUR"
    with pytest.raises(Problem) as error:
        svc.spend_limits(USER)
    assert error.value.status == 409
    assert svc.ramp.writes == []


def test_approval_rechecks_active_state_and_currency():
    for change in ("state", "currency"):
        svc, body = service(), overage_body()
        svc.request_overage(body)
        if change == "state":
            svc.ramp.limit["state"] = "SUSPENDED"
        else:
            svc.ramp.limit["restrictions"]["limit"]["currency_code"] = "EUR"
        with pytest.raises(Problem):
            svc.decide_overage(body["requestID"], {"approve": True})
        assert svc.ramp.writes == []


def test_reconciliation_does_not_confirm_a_changed_reset_interval():
    svc, body = service(), overage_body()
    svc.request_overage(body)
    svc.ramp.lose_response = True
    with pytest.raises(Problem):
        svc.decide_overage(body["requestID"], {"approve": True})
    svc.ramp.limit["restrictions"]["interval"] = "MONTHLY"
    with pytest.raises(Problem):
        svc.decide_overage(body["requestID"], {"approve": True})
    assert svc.store.get(RampOverageRequest, body["requestID"]).state == "pending"
    assert len(svc.ramp.writes) == 1
