import importlib
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from camp import cli
from camp.models import FeedbackEvent, SyncState, User
from camp.store import Store


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMP_DB", ":memory:")
    monkeypatch.setenv("CAMP_DATABASE_URL", "")
    monkeypatch.setenv("CAMP_TOKEN", "")
    monkeypatch.setenv("CAMP_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    module = importlib.reload(importlib.import_module("camp.api"))
    yield module
    module.store.close()


@pytest.mark.parametrize("path", [
    "/v1/groups?date=not-a-date", "/v1/groups?deliveryStart=1440",
    "/v1/groups?latitude=91", "/v1/groups?longitude=-181",
    "/v1/restaurants?limit=-1", "/v1/debug/events?limit=0",
    "/v1/lunch-session?wait=nan", "/v1/lunch-session?wait=inf",
    "/v1/lunch-session?since=-1", "/v1/ledger/missing?month=2026-13",
])
def test_invalid_query_parameters_are_client_errors(api, path):
    assert TestClient(api.app).get(path).status_code == 422


@pytest.mark.parametrize("payload", [{"date": "yesterday"}, {"meal": "invalid"}])
def test_invalid_recommendation_parameters_do_not_reach_planner(api, payload):
    assert TestClient(api.app).post("/batch/run", json=payload).status_code == 422


@pytest.mark.parametrize("tap", [
    {}, {"type": "invalid"}, {"type": "preference"},
    {"type": "preference", "attribute": "spice", "direction": "invalid"},
    {"type": "constraint", "which": "allergen", "action": "add"},
    {"type": "constraint", "which": "invalid:x", "action": "add"},
    {"type": "rating", "overall": "great"}, {"type": "rating", "overall": 5},
    {"type": "add_extras", "addons": "cheese"},
    {"type": "change_item", "from_item_id": []},
    {"type": "constraint", "which": "allergen:shellfish", "action": "add", "severe": []},
])
def test_malformed_feedback_taps_are_validation_errors(api, tap):
    assert TestClient(api.app).post("/feedback", json={"user_id": "missing", "tap": tap}).status_code == 422


def test_unknown_feedback_users_are_not_server_errors(api):
    client = TestClient(api.app)
    assert client.post("/feedback", json={"user_id": "missing", "text": "great"}).status_code == 404
    assert client.post("/v1/debug/feedback", json={"user_id": "missing", "text": "great"}).status_code == 404


def test_feedback_event_and_profile_update_roll_back_together(api, monkeypatch):
    user = api.store.all(User)[0]
    before = api.store.count(FeedbackEvent)
    original = api.store.put

    def fail_profile(row):
        if isinstance(row, User):
            raise OSError("disk full")
        original(row)

    monkeypatch.setattr(api.store, "put", fail_profile)
    with pytest.raises(OSError, match="disk full"):
        TestClient(api.app).post("/feedback", json={
            "user_id": user.id, "tap": {"type": "preference", "attribute": "spice", "direction": "more"},
        })
    assert api.store.count(FeedbackEvent) == before
    assert api.store.get(User, user.id) == user


@pytest.mark.parametrize("path", ["/v1/ramp/allocations", "/v1/ramp/overages", "/v1/ramp/overages/missing/decision"])
@pytest.mark.parametrize("body", ["{", "[]", "null"])
def test_malformed_ramp_json_is_not_a_server_error(api, path, body):
    response = TestClient(api.app).post(path, content=body, headers={
        "Content-Type": "application/json", "X-Camp-Client": "camp-native",
    })
    assert response.status_code == 422


def test_browser_requests_cannot_mutate_an_unauthenticated_local_server(api):
    client = TestClient(api.app)
    assert client.get("/v1/health").status_code == 200
    assert client.delete("/v1/lunch-session", headers={"Origin": "https://example.org"}).status_code == 403
    assert client.get("/v1/groups", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_health_never_discloses_database_connection_strings(api):
    api.store.url = "postgresql://localhost/camp?password=private-password&sslkey=/private/key"
    response = TestClient(api.app).get("/v1/health")
    assert response.status_code == 200
    assert "private-password" not in response.text and "/private/key" not in response.text
    assert "databaseUrl" not in response.json()


def test_rating_and_expected_revision_are_strict(api):
    client = TestClient(api.app)
    assert client.post("/v1/lunch-events", json={"offerId": "a", "event": "ended", "rating": 5}).status_code == 422
    assert client.put("/v1/lunch-session", json={"record": {}, "expectedRevision": True}).status_code == 422


def test_serve_refuses_unauthenticated_remote_binding_and_keeps_loopback_default(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMP_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.delenv("CAMP_TOKEN", raising=False)
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    runner = CliRunner()
    result = runner.invoke(cli.app, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code != 0 and "CAMP_TOKEN" in result.output
    assert calls == []
    assert runner.invoke(cli.app, ["serve", "--no-reload"]).exit_code == 0
    assert calls[0][1] == {"host": "127.0.0.1", "port": 8788, "reload": False}


def test_serve_reads_token_from_env_file_before_binding(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("CAMP_TOKEN='local-demo-token'\n")
    monkeypatch.setenv("CAMP_ENV_FILE", str(env))
    monkeypatch.delenv("CAMP_TOKEN", raising=False)
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    assert CliRunner().invoke(cli.app, ["serve", "--host", "0.0.0.0"]).exit_code == 0
    assert calls[0]["host"] == "0.0.0.0"


def test_module_entrypoint_registers_all_commands():
    result = subprocess.run([sys.executable, "-m", "camp.cli", "--help"], capture_output=True, text=True, check=True)
    assert "serve" in result.stdout and "migrate" in result.stdout and "sync" in result.stdout


def test_migrate_refuses_missing_source_instead_of_creating_empty_database(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMP_ENV_FILE", str(tmp_path / "absent.env"))
    source, target = tmp_path / "missing.db", tmp_path / "target.db"
    result = CliRunner().invoke(cli.app, ["migrate", "--source", str(source), "--target", str(target)])
    assert result.exit_code != 0
    assert not source.exists() and not target.exists()


def test_migrate_loads_target_from_env_file(monkeypatch, tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    store = Store(str(source))
    store.put(SyncState(seq=12))
    store.close()
    env = tmp_path / ".env"
    env.write_text(f"CAMP_DATABASE_URL={target}\n")
    monkeypatch.setenv("CAMP_ENV_FILE", str(env))
    monkeypatch.delenv("CAMP_DATABASE_URL", raising=False)
    result = CliRunner().invoke(cli.app, ["migrate", "--source", str(source)])
    assert result.exit_code == 0
    copied = Store(str(target))
    assert copied.get(SyncState, "lunch").seq == 12
    copied.close()
