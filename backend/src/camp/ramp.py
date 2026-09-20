"""Ramp sandbox bridge, served by the same FastAPI app and database as the recommender.

Ported from the former stand-alone `backend/server.py`. Fund issuance is idempotent: every attempt is written to the
`ramp_attempts` table (state submitting → ready | unknown) before the remote POST, so a retry after a crash reconciles
against Ramp by the unique fund name instead of issuing twice. Credentials never leave the server; the app receives
company/user/fund projections only.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from .models import RampAttempt, RampOverageRequest
from .store import Store

RAMP = "https://demo-api.ramp.com/developer/v1"


class Problem(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RampClient:
    def __init__(self):
        self.client_id = os.environ.get("RAMP_CLIENT_ID", "")
        self.secret = os.environ.get("RAMP_CLIENT_SECRET", "")
        self.tokens: dict[str, tuple[str, float]] = {}
        self.http = build_opener(_NoRedirect())

    def wire(self, method, path, body=None, headers=None):
        request = Request(RAMP + path, data=body, method=method, headers={
            "User-Agent": "camp-sandbox/0.2", "Accept": "application/json", **(headers or {})})
        try:
            with self.http.open(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            # Never relay upstream payloads, which could contain credentials or PII.
            hints = {400: "Check the requested scopes and sandbox fund configuration.",
                     401: "Check sandbox credentials and the client-credentials grant.",
                     403: "Enable the required scopes in the Ramp sandbox developer dashboard.",
                     429: "Ramp rate limited the request. Wait before trying again."}
            raise Problem(f"Ramp returned HTTP {error.code}. " + hints.get(error.code, "Ramp is unavailable; try again later.")) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise Problem("Ramp could not be reached or returned an unreadable response.") from None

    def token(self, scopes: str) -> str:
        if not self.client_id or not self.secret:
            raise Problem("Set RAMP_CLIENT_ID and RAMP_CLIENT_SECRET in backend/.env.", 503)
        cached = self.tokens.get(scopes)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        auth = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
        result = self.wire("POST", "/token", urlencode({"grant_type": "client_credentials", "scope": scopes}).encode(), {
            "Authorization": "Basic " + auth, "Content-Type": "application/x-www-form-urlencoded"})
        self.tokens[scopes] = (result["access_token"], time.time() + int(result.get("expires_in", 3600)))
        return result["access_token"]

    def request(self, method, path, scopes, payload=None, key=None):
        headers = {"Authorization": "Bearer " + self.token(scopes), "Content-Type": "application/json"}
        if key:
            headers["X-Idempotency-Key"] = key
        return self.wire(method, path, json.dumps(payload).encode() if payload is not None else None, headers)

    def list(self, path, scopes):
        rows, seen = [], set()
        next_path = path + ("&" if "?" in path else "?") + "page_size=100"
        for _ in range(20):
            result = self.request("GET", next_path, scopes)
            rows.extend(result.get("data", []))
            link = (result.get("page") or {}).get("next")
            if not link:
                return rows
            cursor = parse_qs(urlsplit(link).query).get("start", [None])[0]   # cursor only; never call a returned URL with our bearer
            if not cursor or cursor in seen:
                raise Problem("Ramp pagination could not be completed.")
            seen.add(cursor)
            next_path = path + ("&" if "?" in path else "?") + urlencode({"page_size": 100, "start": cursor})
        raise Problem("This sandbox has too many records for the local prototype.")


CAMP_FUND_PREFIX = "camp \u00b7 "     # "camp · ": the one-off allocations this app issues, not a standing spend limit


def _cents(money: dict | None) -> int:
    return int((money or {}).get("amount") or 0)


def limit_summary(limit: dict) -> dict:
    """One row of GET /limits (note: `restrictions`, where GET /funds says `spending_restrictions`).

    `remainingCents` is what is left in the current interval; `perOrderCents` is what a single order may cost, which
    is the smaller of that and any per-transaction ceiling Ramp holds on the limit."""
    r = limit.get("restrictions") or {}
    total = _cents((r.get("limit") or {}))
    spent = _cents(((limit.get("balance") or {}).get("total")))
    remaining = max(0, total - spent)
    txn = _cents(r.get("transaction_amount_limit")) if r.get("transaction_amount_limit") else 0
    return {"id": limit["id"], "name": limit.get("display_name") or "Unnamed limit",
            "state": limit.get("state", "UNKNOWN"), "interval": r.get("interval", "TOTAL"),
            "limitCents": total, "spentCents": spent, "remainingCents": remaining,
            "perOrderCents": min(remaining, txn) if txn else remaining,
            "transactionLimitCents": txn, "resetsAt": r.get("next_interval_reset") or "",
            "currency": (r.get("limit") or {}).get("currency_code", "USD")}


def overage_wire(row: RampOverageRequest) -> dict:
    return {"id": row.id, "userID": row.ramp_user_id, "limitID": row.limit_id, "limitName": row.limit_name,
            "requester": row.requester, "baselineCents": row.baseline_cents, "requestedCents": row.requested_cents,
            "reason": row.reason, "state": row.state, "decidedBy": row.decided_by,
            "createdAt": row.created_at.isoformat(), "decidedAt": row.decided_at.isoformat() if row.decided_at else None}


def fund_summary(fund: dict) -> dict:
    restrictions = fund.get("spending_restrictions") or {}
    limit = restrictions.get("limit") or {}
    return {"id": fund["id"], "name": fund.get("display_name") or "Unnamed fund",
            "state": fund.get("state", "UNKNOWN"), "amountCents": limit.get("amount", 0),
            "currency": limit.get("currency_code", "USD"),
            "cards": [{"id": c["card_id"], "lastFour": c.get("last_four", "")} for c in fund.get("cards", [])]}


class RampService:
    def __init__(self, store: Store):
        self.store = store
        self.ramp = RampClient()
        self._mutations = threading.RLock()
        self.cap = int(os.environ.get("CAMP_SANDBOX_GROUP_CAP_CENTS", "15000"))
        if not 100 <= self.cap <= 15000:
            raise SystemExit("CAMP_SANDBOX_GROUP_CAP_CENTS must be between 100 and 15000 ($1–$150).")
        # A process interrupted during issuance must not silently issue again.
        for a in self.store.all(RampAttempt):
            if a.state == "submitting":
                a.state = "unknown"
                self.store.put(a)

    @property
    def configured(self) -> bool:
        return bool(self.ramp.client_id and self.ramp.secret)

    def snapshot(self) -> dict:
        business = self.ramp.request("GET", "/business", "business:read")
        users = self.ramp.list("/users?status=USER_ACTIVE", "users:read")
        funds = self.ramp.list("/funds", "funds:read")
        return {"environment": "sandbox", "company": business.get("business_name_legal") or "Ramp sandbox",
                "companyID": business.get("id", ""), "groupCapCents": self.cap,
                "attempts": self.store.count(RampAttempt),
                "users": [{"id": u["id"], "name": " ".join(filter(None, [u.get("first_name"), u.get("last_name")])) or u.get("email", "Sandbox user")} for u in users],
                "funds": [fund_summary(f) for f in funds if (f.get("display_name") or "").startswith("camp · ")]}

    def allocate(self, body: dict) -> dict:
        with self._mutations:
            return self._allocate(body)

    def _allocate(self, body: dict) -> dict:
        try:
            attempt_id = str(UUID(body["requestID"]))
            user_id = str(UUID(body["userID"]))
            amount = body["amountCents"]
        except (KeyError, ValueError, TypeError, AttributeError):
            raise Problem("A valid request ID, sandbox owner and amount are required.", 400)
        if type(amount) is not int or not 100 <= amount <= self.cap:
            raise Problem(f"The sandbox allocation must be between 100 and {self.cap} cents.", 400)
        fingerprint = hashlib.sha256(f"{user_id}:{amount}".encode()).hexdigest()
        row = self.store.get(RampAttempt, attempt_id)
        if row:
            if row.fingerprint != fingerprint:
                raise Problem("This attempt already has a different owner or amount. Resolve it before starting another.", 409)
            if row.state == "ready" and row.result:
                return row.result
            # Reconcile by the unique full attempt ID in the fund display name.
            funds = self.ramp.list("/funds", "funds:read")
            matches = [f for f in funds if f.get("display_name") == "camp · " + attempt_id]
            if len(matches) == 1:
                return self.finish(row, matches[0])
            raise Problem("Allocation status is unknown. No second fund was created. Check Ramp and retry reconciliation with this same attempt.", 409)
        user = self.ramp.request("GET", "/users/" + user_id, "users:read")
        if user.get("status") != "USER_ACTIVE":
            raise Problem("Choose an active sandbox employee.", 400)
        self.ramp.token("funds:write")     # obtain permission before recording a possible remote write
        payload = {"user_id": user_id, "display_name": "camp · " + attempt_id, "is_shareable": False,
                   "permitted_spend_types": {"physical_card": False, "reimbursements": False, "virtual_card": True},
                   "spending_restrictions": {"interval": "TOTAL", "limit": {"amount": amount, "currency_code": "USD"},
                       "transaction_amount_limit": {"amount": amount, "currency_code": "USD"},
                       "allowed_category_codes": [19],
                       "lock_date": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)).isoformat()}}
        row = RampAttempt(id=attempt_id, fingerprint=fingerprint, payload=payload, state="submitting")
        self.store.put(row)
        try:
            fund = self.ramp.request("POST", "/funds", "funds:write", payload, "camp-" + attempt_id)
        except Problem:
            row.state = "unknown"
            self.store.put(row)
            raise Problem("Ramp allocation could not be confirmed. Keep this attempt and use Reconcile; do not create a replacement.", 409) from None
        return self.finish(row, fund)

    def finish(self, row: RampAttempt, fund: dict) -> dict:
        row.result = {"requestID": row.id, "fund": fund_summary(fund)}
        row.state = "ready"
        self.store.put(row)
        return row.result

    # ------------------------------------------------------------ spending limits and overage requests

    def spend_limits(self, user_id: str) -> dict:
        """What this employee may actually spend, read from Ramp rather than from the local demo budget.

        `perOrderCents` is the binding one — the smallest per-order ceiling across their active limits — and is what
        the app shows and enforces. The one-off allocations this app issues (`camp · …`) are left out: they are lunch
        money for a single group order, not a standing limit. None means Ramp holds no limit and the local cap stands.
        """
        user_id = self._employee(user_id)
        rows = self.ramp.list(f"/limits?user_id={user_id}", "limits:read")
        limits = [limit_summary(x) for x in rows
                  if x.get("state") == "ACTIVE" and not (x.get("display_name") or "").startswith(CAMP_FUND_PREFIX)]
        if any(limit["currency"] != "USD" for limit in limits):
            raise Problem("This local sandbox demo supports USD spending limits only.", 409)
        binding = min(limits, key=lambda x: x["perOrderCents"], default=None)
        requests = self.store.overages_for(user_id)
        return {"userID": user_id, "limits": limits, "limit": binding,
                "perOrderCents": binding["perOrderCents"] if binding else None,
                "overages": [overage_wire(r) for r in requests[:20]],
                "pendingOverages": sum(1 for r in requests if r.state == "pending")}

    def _employee(self, user_id: str) -> str:
        try:
            return str(UUID(user_id))
        except (ValueError, AttributeError, TypeError):
            raise Problem("A valid Ramp employee ID is required.", 400) from None

    def request_overage(self, body: dict) -> dict:
        """Ask for a higher ceiling on the employee's binding Ramp limit. Idempotent on `requestID`, so a retry after
        a dropped response returns the same request instead of filing a second one. Nothing changes in Ramp until
        someone approves it."""
        with self._mutations:
            return self._request_overage(body)

    def _request_overage(self, body: dict) -> dict:
        try:
            request_id = str(UUID(body["requestID"]))
            user_id = self._employee(body["userID"])
            amount = body["requestedCents"]
            reason = str(body.get("reason") or "").strip()[:280]
            requester = str(body.get("requester") or "").strip()[:80]
        except (KeyError, ValueError, TypeError, AttributeError):
            raise Problem("A valid request ID, Ramp employee and requested amount are required.", 400) from None
        if type(amount) is not int or not 100 <= amount <= 100_000:
            raise Problem("The requested ceiling must be between 100 and 100000 cents ($1–$1,000).", 400)
        existing = self.store.get(RampOverageRequest, request_id)
        if existing:
            if (existing.ramp_user_id, existing.requested_cents, existing.reason, existing.requester) != (
                user_id, amount, reason, requester
            ):
                raise Problem("This request already has a different employee, amount or explanation.", 409)
            return overage_wire(existing)
        snapshot = self.spend_limits(user_id)
        binding = snapshot["limit"]
        if not binding:
            raise Problem("Ramp holds no active spending limit for this employee, so there is nothing to raise.", 409)
        if amount <= binding["perOrderCents"]:
            raise Problem("That is not above the current Ramp limit; no overage is needed.", 400)
        if any(r.state == "pending" for r in self.store.overages_for(user_id)):
            raise Problem("An overage request for this employee is already waiting for a decision.", 409)
        row = RampOverageRequest(id=request_id, ramp_user_id=user_id, limit_id=binding["id"], limit_name=binding["name"],
                                 requester=requester, baseline_cents=binding["perOrderCents"], requested_cents=amount,
                                 reason=reason)
        self.store.put(row)
        return overage_wire(row)

    def decide_overage(self, request_id: str, body: dict) -> dict:
        """Approve or deny a pending request. Approving raises the limit in Ramp; `baseline_cents` on the row keeps
        the ceiling it had beforehand. Who may approve is the app's call — this endpoint trusts its caller."""
        with self._mutations:
            return self._decide_overage(request_id, body)

    def _decide_overage(self, request_id: str, body: dict) -> dict:
        try:
            request_id = str(UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            raise Problem("A valid request ID is required.", 400) from None
        row = self.store.get(RampOverageRequest, request_id)
        if not row:
            raise Problem("No such overage request.", 404)
        if row.state != "pending":
            return overage_wire(row)              # already decided; the decision stands
        approve = body.get("approve")
        if type(approve) is not bool:
            raise Problem("Send approve: true or approve: false.", 400)
        attempt_id = "overage:" + request_id
        attempt = self.store.get(RampAttempt, attempt_id)
        if attempt:
            if not approve:
                raise Problem("Approval may already have reached Ramp. Reconcile it before making another decision.", 409)
            current = self.ramp.request("GET", "/limits/" + row.limit_id, "limits:read")
            restrictions = current.get("restrictions") or {}
            expected = attempt.payload["spending_restrictions"]
            fields = ("limit", "transaction_amount_limit")
            if (current.get("state") != "ACTIVE"
                    or restrictions.get("interval", "TOTAL") != expected["interval"] or any(
                field in expected and (
                    _cents(restrictions.get(field)) != expected[field]["amount"]
                    or (restrictions.get(field) or {}).get("currency_code", "USD") != expected[field]["currency_code"]
                ) for field in fields
            )):
                raise Problem("Approval status is unknown. No second increase was sent. Check Ramp and retry this same decision.", 409)
            return self._finish_overage(row, attempt)
        if approve:
            current = self.ramp.request("GET", "/limits/" + row.limit_id, "limits:read")
            restrictions = current.get("restrictions") or {}
            if current.get("state") != "ACTIVE":
                raise Problem("The requested spending limit is no longer active.", 409)
            if any((restrictions.get(field) or {}).get("currency_code", "USD") != "USD"
                   for field in ("limit", "transaction_amount_limit")):
                raise Problem("This local sandbox demo supports USD spending limits only.", 409)
            spending: dict = {"interval": restrictions.get("interval", "TOTAL"),
                              "limit": {"amount": max(_cents(restrictions.get("limit")),
                                                     row.requested_cents + _cents((current.get("balance") or {}).get("total"))),
                                        "currency_code": "USD"}}
            if restrictions.get("transaction_amount_limit"):
                spending["transaction_amount_limit"] = {"amount": max(row.requested_cents, _cents(restrictions["transaction_amount_limit"])),
                                                       "currency_code": "USD"}
            attempt = RampAttempt(
                id=attempt_id,
                fingerprint=hashlib.sha256(f"{row.ramp_user_id}:{row.limit_id}:{row.requested_cents}".encode()).hexdigest(),
                payload={"spending_restrictions": spending, "approver": str(body.get("approver") or "").strip()[:80]},
            )
            self.store.put(attempt)
            try:
                self.ramp.request("PATCH", "/funds/" + row.limit_id, "funds:write", {"spending_restrictions": spending})
            except Problem:
                attempt.state = "unknown"
                self.store.put(attempt)
                raise Problem("Ramp approval could not be confirmed. Retry this same decision to reconcile; no second increase will be sent.", 409) from None
            return self._finish_overage(row, attempt)
        row.state = "denied"
        row.decided_by = str(body.get("approver") or "").strip()[:80]
        row.decided_at = dt.datetime.now(dt.timezone.utc)
        self.store.put(row)
        return overage_wire(row)

    def _finish_overage(self, row: RampOverageRequest, attempt: RampAttempt) -> dict:
        row.state = "approved"
        row.decided_by = attempt.payload["approver"]
        row.decided_at = dt.datetime.now(dt.timezone.utc)
        attempt.state = "ready"
        attempt.result = overage_wire(row)
        with self.store.transaction():
            self.store.put(row)
            self.store.put(attempt)
        return attempt.result
