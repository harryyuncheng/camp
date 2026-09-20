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
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from .models import RampAttempt
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
            return self.finish(row, fund)
        except Exception:
            row.state = "unknown"
            self.store.put(row)
            raise Problem("Ramp allocation could not be confirmed. Keep this attempt and use Reconcile; do not create a replacement.", 409) from None

    def finish(self, row: RampAttempt, fund: dict) -> dict:
        row.result = {"requestID": row.id, "fund": fund_summary(fund)}
        row.state = "ready"
        self.store.put(row)
        return row.result
