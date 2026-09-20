"""Live Activity push-to-update: token registration, the write fanout, and ES256 JWT minting."""
import asyncio
import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from camp.apns import APNsClient, APNsConfig
from camp.models import ActivityPushToken, ActivityStartToken
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


# ------------------------------------------------------------ api fanout (update vs push-to-start)

class _FakeAPNs:
    enabled = True

    def __init__(self):
        self.sent = []

    async def send(self, push_token, content_state, **kwargs):
        self.sent.append((push_token, kwargs.get("event", "update"), kwargs.get("attributes")))
        return (200, "apns-id")


def _api(monkeypatch, tmp_path):
    """The api module with its store/APNs swapped for a temp DB and a recording fake."""
    monkeypatch.setenv("CAMP_DB", ":memory:")
    monkeypatch.setenv("CAMP_DATABASE_URL", "")
    import camp.api as api
    store = Store(str(tmp_path / "camp.db"))
    fake = _FakeAPNs()
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "apns", fake)
    return api, store, fake


def test_write_push_starts_a_session_the_phone_never_saw(monkeypatch, tmp_path):
    api, store, fake = _api(monkeypatch, tmp_path)
    store.put(ActivityStartToken(id="iphone", push_token="beefface"))

    asyncio.run(api._push_live_activity(rec("s1"), "mac"))
    assert fake.sent == [("beefface", "start", {"sessionID": "s1"})]
    assert store.get(ActivityStartToken, "iphone").started == ["s1"]

    # A later write for the same session can't raise a duplicate Live Activity.
    asyncio.run(api._push_live_activity(rec("s1", revision=1, phase="reviewing"), "mac"))
    assert len(fake.sent) == 1
    # The device that wrote is never pushed, and finished sessions never start an activity.
    asyncio.run(api._push_live_activity(rec("s2"), "iphone"))
    asyncio.run(api._push_live_activity(rec("s3", phase="delivered"), "mac"))
    assert len(fake.sent) == 1


def test_registered_update_token_wins_over_push_to_start(monkeypatch, tmp_path):
    api, store, fake = _api(monkeypatch, tmp_path)
    store.put(ActivityPushToken(id="s1", push_token="deadbeef", device="iphone"))
    store.put(ActivityStartToken(id="iphone", push_token="beefface"))

    asyncio.run(api._push_live_activity(rec("s1"), "mac"))
    assert fake.sent == [("deadbeef", "update", None)]
    assert store.get(ActivityStartToken, "iphone").started == []


def test_update_token_registration_marks_the_session_started(monkeypatch, tmp_path):
    """Once the phone has registered an activity token, dropping it (activity ended) must not let a
    later write push-start a duplicate for the same session."""
    api, store, fake = _api(monkeypatch, tmp_path)
    store.put(ActivityStartToken(id="iphone", push_token="beefface"))
    api.lunch_session_push_token(api.ActivityTokenReq(session_id="s1", push_token="deadbeef", device="iphone"))
    assert store.get(ActivityStartToken, "iphone").started == ["s1"]

    store.delete(ActivityPushToken, "s1")  # as happens when the activity ends (410/finished)
    asyncio.run(api._push_live_activity(rec("s1", revision=2, phase="choosing"), "mac"))
    assert fake.sent == []


def test_forgetting_an_order_ends_its_pushed_activity(monkeypatch, tmp_path):
    api, store, fake = _api(monkeypatch, tmp_path)
    store.put(ActivityPushToken(id="s1", push_token="deadbeef", device="iphone"))
    store.put(ActivityPushToken(id="s2", push_token="cafef00d", device="iphone"))

    asyncio.run(api._end_live_activities([rec("s1")]))
    assert fake.sent == [("deadbeef", "end", None)]
    assert store.get(ActivityPushToken, "s1") is None
    assert store.get(ActivityPushToken, "s2") is not None


def test_push_start_token_registration_round_trip(monkeypatch, tmp_path):
    api, store, _ = _api(monkeypatch, tmp_path)
    api.lunch_session_push_start_token(api.ActivityStartTokenReq(push_token="BEEF", device="iphone"))
    assert store.get(ActivityStartToken, "iphone").push_token == "beef"
    # Re-registering a rotated token keeps the sessions this device already renders.
    store.put(ActivityStartToken(id="iphone", push_token="beef", started=["s1"]))
    api.lunch_session_push_start_token(api.ActivityStartTokenReq(push_token="cafe", device="iphone"))
    row = store.get(ActivityStartToken, "iphone")
    assert row.push_token == "cafe" and row.started == ["s1"]
