#!/usr/bin/env python3
"""Local-only camp → Ramp sandbox bridge. Python standard library; no production mode."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import UUID

RAMP = "https://demo-api.ramp.com/developer/v1"


class Problem(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RampClient:
    def __init__(self):
        self.client_id = os.environ.get("RAMP_CLIENT_ID", "")
        self.secret = os.environ.get("RAMP_CLIENT_SECRET", "")
        self.tokens = {}
        self.http = build_opener(NoRedirect())

    def wire(self, method, path, body=None, headers=None):
        request = Request(RAMP + path, data=body, method=method, headers={
            "User-Agent": "camp-sandbox/0.1", "Accept": "application/json", **(headers or {})})
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

    def token(self, scopes):
        if not self.client_id or not self.secret:
            raise Problem("Set RAMP_CLIENT_ID and RAMP_CLIENT_SECRET on the camp backend.", 503)
        cached = self.tokens.get(scopes)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        auth = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
        result = self.wire("POST", "/token", urlencode({"grant_type": "client_credentials", "scope": scopes}).encode(), {
            "Authorization": "Basic " + auth, "Content-Type": "application/x-www-form-urlencoded"})
        self.tokens[scopes] = (result["access_token"], time.time() + int(result.get("expires_in", 3600)))
        return result["access_token"]

    def request(self, method, path, scopes, payload=None, key=None):
        token = self.token(scopes)
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if key:
            headers["X-Idempotency-Key"] = key
        return self.wire(method, path, json.dumps(payload).encode() if payload is not None else None, headers)

    def list(self, path, scopes):
        rows = []
        next_path = path + ("&" if "?" in path else "?") + "page_size=100"
        seen = set()
        for _ in range(20):
            result = self.request("GET", next_path, scopes)
            rows.extend(result.get("data", []))
            link = (result.get("page") or {}).get("next")
            if not link:
                return rows
            # Read cursor only; never send bearer credentials to a returned URL.
            cursor = parse_qs(urlsplit(link).query).get("start", [None])[0]
            if not cursor or cursor in seen:
                raise Problem("Ramp pagination could not be completed.")
            seen.add(cursor)
            next_path = path + ("&" if "?" in path else "?") + urlencode({"page_size": 100, "start": cursor})
        raise Problem("This sandbox has too many records for the local prototype.")


def fund_summary(fund):
    restrictions = fund.get("spending_restrictions") or {}
    limit = restrictions.get("limit") or {}
    return {"id": fund["id"], "name": fund.get("display_name") or "Unnamed fund",
            "state": fund.get("state", "UNKNOWN"), "amountCents": limit.get("amount", 0),
            "currency": limit.get("currency_code", "USD"),
            "cards": [{"id": c["card_id"], "lastFour": c.get("last_four", "")} for c in fund.get("cards", [])]}


class CampService:
    def __init__(self, state):
        self.ramp = RampClient()
        self.cap = int(os.environ.get("CAMP_SANDBOX_GROUP_CAP_CENTS", "15000"))
        if not 100 <= self.cap <= 15000:
            raise SystemExit("Local sandbox cap must be between $1 and $150.")
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(state / "attempts.sqlite3")
        self.db.execute("CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, result TEXT)")
        # A process interrupted during issuance must not silently issue again.
        self.db.execute("UPDATE attempts SET state='unknown' WHERE state='submitting'")
        self.db.commit()

    def snapshot(self):
        business = self.ramp.request("GET", "/business", "business:read")
        users = self.ramp.list("/users?status=USER_ACTIVE", "users:read")
        funds = self.ramp.list("/funds", "funds:read")
        return {"environment": "sandbox", "company": business.get("business_name_legal") or "Ramp sandbox",
                "companyID": business.get("id", ""), "groupCapCents": self.cap,
                "users": [{"id": u["id"], "name": " ".join(filter(None, [u.get("first_name"), u.get("last_name")])) or u.get("email", "Sandbox user")} for u in users],
                "funds": [fund_summary(f) for f in funds if (f.get("display_name") or "").startswith("camp · ")]}

    def allocate(self, body):
        try:
            attempt_id = str(UUID(body["requestID"]))
            user_id = str(UUID(body["userID"]))
            amount = body["amountCents"]
        except (KeyError, ValueError, TypeError, AttributeError):
            raise Problem("A valid request ID, sandbox owner and amount are required.", 400)
        if type(amount) is not int or not 100 <= amount <= self.cap:
            raise Problem(f"The sandbox allocation must be between 100 and {self.cap} cents.", 400)
        fingerprint = hashlib.sha256(f"{user_id}:{amount}".encode()).hexdigest()
        row = self.db.execute("SELECT fingerprint,payload,state,result FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if row:
            if row[0] != fingerprint:
                raise Problem("This attempt already has a different owner or amount. Resolve it before starting another.", 409)
            if row[2] == "ready":
                return json.loads(row[3])
            # Reconcile by the unique full attempt ID in the fund display name.
            funds = self.ramp.list("/funds", "funds:read")
            matches = [f for f in funds if f.get("display_name") == "camp · " + attempt_id]
            if len(matches) == 1:
                return self.finish(attempt_id, matches[0])
            raise Problem("Allocation status is unknown. No second fund was created. Check Ramp and retry reconciliation with this same attempt.", 409)
        user = self.ramp.request("GET", "/users/" + user_id, "users:read")
        if user.get("status") != "USER_ACTIVE":
            raise Problem("Choose an active sandbox employee.", 400)
        # Obtain permission before recording a possible remote write.
        self.ramp.token("funds:write")
        payload = {"user_id": user_id, "display_name": "camp · " + attempt_id, "is_shareable": False,
                   "permitted_spend_types": {"physical_card": False, "reimbursements": False, "virtual_card": True},
                   "spending_restrictions": {"interval": "TOTAL", "limit": {"amount": amount, "currency_code": "USD"},
                       "transaction_amount_limit": {"amount": amount, "currency_code": "USD"},
                       "allowed_category_codes": [19],
                       "lock_date": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)).isoformat()}}
        self.db.execute("INSERT INTO attempts VALUES (?,?,?,'submitting',NULL)", (attempt_id, fingerprint, json.dumps(payload)))
        self.db.commit()
        try:
            fund = self.ramp.request("POST", "/funds", "funds:write", payload, "camp-" + attempt_id)
            return self.finish(attempt_id, fund)
        except Exception:
            self.db.execute("UPDATE attempts SET state='unknown' WHERE id=?", (attempt_id,))
            self.db.commit()
            raise Problem("Ramp allocation could not be confirmed. Keep this attempt and use Reconcile; do not create a replacement.", 409) from None

    def finish(self, attempt_id, fund):
        result = {"requestID": attempt_id, "fund": fund_summary(fund)}
        self.db.execute("UPDATE attempts SET state='ready',result=? WHERE id=?", (json.dumps(result), attempt_id))
        self.db.commit()
        return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # No request headers, credentials, employee data or upstream bodies in logs.

    def reply(self, status, body):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def dispatch(self):
        # Loopback-only native demo service. Reject browser origins and DNS rebinding.
        if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            raise Problem("Use the local camp service address.", 403)
        if self.headers.get("Origin") or self.headers.get("X-Camp-Client") != "camp-native":
            raise Problem("This local endpoint is reserved for the camp native app.", 403)
        if self.command == "GET" and self.path == "/v1/ramp":
            return self.server.service.snapshot()
        if self.command == "POST" and self.path == "/v1/ramp/allocations":
            if self.headers.get("Content-Type") != "application/json":
                raise Problem("JSON is required.", 415)
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise Problem("Invalid request size.", 400)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise Problem("Expected a JSON object.", 400)
            return self.server.service.allocate(body)
        raise Problem("Unknown endpoint.", 404)

    def handle_request(self):
        try:
            self.reply(200, self.dispatch())
        except Problem as error:
            self.reply(error.status, {"error": str(error)})
        except (ValueError, TypeError):
            self.reply(400, {"error": "Invalid request."})
        except Exception:
            self.reply(500, {"error": "camp could not complete the request. Existing allocation attempts are retained."})

    do_GET = handle_request
    do_POST = handle_request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(__file__).with_name(".env"))
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if args.env_file.exists():
        for line in args.env_file.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    os.umask(0o077)
    state = Path(os.environ.get("CAMP_STATE_DIR", str(Path(__file__).with_name(".state"))))
    service = CampService(state)
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    server.service = service
    print(f"camp sandbox backend listening on http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
