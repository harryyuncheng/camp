"""Live Activity push-to-update: token registration, the write fanout, and ES256 JWT minting."""
import asyncio
import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from camp.apns import APNsClient, APNsConfig
from camp.models import ActivityPushToken
from camp.store import Store
from camp.sync import LunchSyncService


def rec(session_id="s1", revision=0, phase="choosing"):
    return {"sessionId": session_id, "revision": revision,
            "session": {"id": session_id, "phase": phase, "revision": revision}}


def _config():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    return key, APNsConfig(key_pem=pem, key_id="ABCD123456", team_id="TEAM123456",
                           bundle_id="com.harrycheng.camp", environment="sandbox")


def test_jwt_is_a_valid_es256_assertion():
    key, config = _config()
    token = APNsClient(config)._bearer()
    header, payload, signature = token.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)
    assert json.loads(base64.urlsafe_b64decode(pad(header))) == {"alg": "ES256", "kid": "ABCD123456"}
    assert json.loads(base64.urlsafe_b64decode(pad(payload)))["iss"] == "TEAM123456"
    raw = base64.urlsafe_b64decode(pad(signature))
    assert len(raw) == 64, "JWS needs fixed-width r||s, not the DER pair cryptography returns"
    key.public_key().verify(utils.encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                                       int.from_bytes(raw[32:], "big")),
                            f"{header}.{payload}".encode(), ec.ECDSA(hashes.SHA256()))


def test_jwt_is_cached_between_sends():
    _, config = _config()
    client = APNsClient(config)
    assert client._bearer() == client._bearer()


def test_topic_appends_the_live_activity_suffix():
    _, config = _config()
    assert config.topic == "com.harrycheng.camp.push-type.liveactivity"
    assert config.host.endswith("sandbox.push.apple.com")


def test_disabled_without_credentials(monkeypatch):
    for var in ("CAMP_APNS_KEY", "CAMP_APNS_KEY_ID", "CAMP_APNS_TEAM_ID", "CAMP_APNS_BUNDLE_ID"):
        monkeypatch.delenv(var, raising=False)
    assert APNsConfig.from_env() is None
    assert APNsClient(None).enabled is False


def test_write_fans_out_to_the_other_device_only(tmp_path):
    """The device that wrote must not be pushed its own echo; the other one must."""
    store = Store(str(tmp_path / "camp.db"))
    svc = LunchSyncService(store)
    store.put(ActivityPushToken(id="s1", push_token="deadbeef", device="iphone"))
    sent = []

    async def fanout(record, device):
        row = store.get(ActivityPushToken, record["sessionId"])
        if row is not None and row.device != device:
            sent.append((row.push_token, record["session"]["phase"]))

    svc.on_change = fanout

    async def go():
        await svc.publish(rec(), None, None, "mac")          # mac writes -> push to the phone
        await asyncio.sleep(0)                                # let the detached task run
        await svc.publish(rec(revision=1, phase="reviewing"), "s1", 0, "iphone")  # phone writes -> no push
        await asyncio.sleep(0)

    asyncio.run(go())
    assert sent == [("deadbeef", "choosing")]


def test_fanout_never_breaks_a_write_without_a_loop(tmp_path):
    """Synchronous callers (tests, CLI) must still be able to publish when no event loop is running."""
    store = Store(str(tmp_path / "camp.db"))
    svc = LunchSyncService(store)
    svc.on_change = lambda record, device: asyncio.sleep(0)
    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(svc.publish(rec(), None, None, "mac"))["seq"] == 1
    finally:
        loop.close()
