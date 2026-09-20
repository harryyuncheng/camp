"""APNs push-to-update for Live Activities.

The phone can only long-poll while camp is foregrounded (`LunchSyncCoordinator` is stopped in
`scenePhase != .active`), so a Mac-side change never reaches a locked phone. This module closes that
gap: when `LunchSyncService` accepts a write, the new session is pushed straight to the Live Activity's
push token, which iOS delivers without waking the app.

Configuration comes from the environment; absent a key the client is disabled and the long-poll path
is unchanged, so the app still works on a machine with no Apple credentials:

    CAMP_APNS_KEY        path to the .p8 from Keys -> Apple Push Notifications service
    CAMP_APNS_KEY_ID     the key's 10-character identifier
    CAMP_APNS_TEAM_ID    the Apple Developer team (DC92972HRX for camp)
    CAMP_APNS_BUNDLE_ID  the *app* bundle id; the topic appends .push-type.liveactivity
    CAMP_APNS_ENV        "sandbox" (default, for development builds) or "production"

Apple requires HTTP/2 and an ES256-signed JWT, hence the httpx[http2] and cryptography dependencies.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

log = logging.getLogger("camp.apns")

HOSTS = {"sandbox": "https://api.sandbox.push.apple.com", "production": "https://api.push.apple.com"}
# Apple rejects a token older than an hour; refresh well before that.
TOKEN_TTL = 45 * 60


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@dataclass
class APNsConfig:
    key_pem: bytes
    key_id: str
    team_id: str
    bundle_id: str
    environment: str = "sandbox"

    @property
    def host(self) -> str:
        return HOSTS.get(self.environment, HOSTS["sandbox"])

    @property
    def topic(self) -> str:
        return f"{self.bundle_id}.push-type.liveactivity"

    @classmethod
    def from_env(cls) -> Optional["APNsConfig"]:
        path, key_id = os.getenv("CAMP_APNS_KEY"), os.getenv("CAMP_APNS_KEY_ID")
        team_id, bundle_id = os.getenv("CAMP_APNS_TEAM_ID"), os.getenv("CAMP_APNS_BUNDLE_ID")
        if not (path and key_id and team_id and bundle_id):
            return None
        try:
            key_pem = open(path, "rb").read()
        except OSError as e:
            log.warning("APNs key %s unreadable (%s); push-to-update disabled", path, e)
            return None
        env = (os.getenv("CAMP_APNS_ENV") or "sandbox").lower()
        return cls(key_pem=key_pem, key_id=key_id, team_id=team_id, bundle_id=bundle_id, environment=env)


class APNsClient:
    """Sends Live Activity updates. `enabled` is False when the environment has no key, which keeps the
    rest of the backend free of Apple-credential branching."""

    def __init__(self, config: Optional[APNsConfig] = None):
        self.config = config
        self._jwt: Optional[str] = None
        self._jwt_at = 0.0
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def enabled(self) -> bool:
        return self.config is not None

    def _bearer(self) -> str:
        assert self.config is not None
        now = time.time()
        if self._jwt and now - self._jwt_at < TOKEN_TTL:
            return self._jwt
        # Hand-rolled ES256 rather than a PyJWT dependency: the signature is a DER-encoded (r, s) pair
        # that JWS requires as a fixed-width 64-byte concatenation.
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        key = serialization.load_pem_private_key(self.config.key_pem, password=None)
        header = _b64(json.dumps({"alg": "ES256", "kid": self.config.key_id}, separators=(",", ":")).encode())
        payload = _b64(json.dumps({"iss": self.config.team_id, "iat": int(now)}, separators=(",", ":")).encode())
        signing_input = f"{header}.{payload}".encode()
        der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = utils.decode_dss_signature(der)
        signature = _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        self._jwt, self._jwt_at = f"{header}.{payload}.{signature}", now
        return self._jwt

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(http2=True, timeout=10.0)
        return self._client

    async def send(self, push_token: str, content_state: dict[str, Any], *, event: str = "update",
                   stale_at: Optional[float] = None, dismiss_at: Optional[float] = None) -> tuple[int, str]:
        """Pushes one content-state. Returns (status, apns-id or reason); 410 means the token is dead."""
        if self.config is None:
            return (0, "apns disabled")
        aps: dict[str, Any] = {"timestamp": int(time.time()), "event": event, "content-state": content_state}
        if stale_at is not None:
            aps["stale-date"] = int(stale_at)
        if event == "end" and dismiss_at is not None:
            aps["dismissal-date"] = int(dismiss_at)
        headers = {
            "authorization": f"bearer {self._bearer()}",
            "apns-topic": self.config.topic,
            "apns-push-type": "liveactivity",
            "apns-priority": "10",
            "apns-expiration": "0",
        }
        client = await self._http()
        try:
            r = await client.post(f"{self.config.host}/3/device/{push_token}", headers=headers,
                                  content=json.dumps({"aps": aps}).encode())
        except httpx.HTTPError as e:
            log.warning("APNs post failed: %s", e)
            return (0, str(e))
        if r.status_code == 200:
            return (200, r.headers.get("apns-id", ""))
        reason = ""
        try:
            reason = (r.json() or {}).get("reason", "")
        except ValueError:
            reason = r.text[:200]
        log.warning("APNs %s for token %s...: %s", r.status_code, push_token[:8], reason)
        return (r.status_code, reason)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
