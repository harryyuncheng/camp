"""Onboarding is stored once, in the database, and read back by the other device."""
from camp.contracts import MealContext, OfficeRef
from camp.models import OnboardingProfile, User
from camp.offers import OfferService
from camp.onboarding import OnboardingReq, OnboardingService
from camp.store import Store

OFFICE = OfficeRef(id="hq", name="HQ", latitude=40.7424, longitude=-73.9913)


def service(tmp_path=None):
    store = Store(str(tmp_path / "camp.db") if tmp_path else ":memory:")
    return store, OnboardingService(store, OfferService(store))


def context(name="Harry", **kwargs):
    return MealContext(display_name=name, office=OFFICE, **kwargs)


def settings(name="Harry"):
    return {"personal": {"displayName": name, "dietaryStyle": "Vegetarian", "allergies": "peanuts", "lunchStart": 720},
            "office": {"name": "HQ"}, "connections": {"recommendationURL": "http://192.168.1.4:8788"}}


def test_setup_applies_to_the_profile_and_is_read_back_by_the_other_device(tmp_path):
    store, svc = service(tmp_path)
    saved = svc.save(OnboardingReq(context=context(dietary_style="Vegetarian", allergies=["peanuts"], lunch_start=720,
                                                   budget_cents=2500), settings=settings(), device="mac"))
    assert saved.completed and saved.completed_at is not None and saved.device == "mac"

    user = store.get(User, saved.user_id)
    assert {"vegetarian", "peanut"} <= {r.value for r in user.restrictions}
    assert user.budget_cents["lunch"] == 2500
    assert user.windows["lunch"].start == max(720, OFFICE.delivery_start) and user.windows["lunch"].end == 870

    # the phone knows neither its user id nor the name yet: it adopts the finished setup for the office
    phone = svc.find(None, None, OFFICE.id)
    assert phone is not None and phone.user_id == saved.user_id
    assert phone.settings["connections"]["recommendationURL"] == "http://192.168.1.4:8788"

    # …and writing from the phone updates that same row rather than creating a second person
    again = svc.save(OnboardingReq(context=context(user_id=phone.user_id, lunch_start=690), settings=settings(), device="iphone"))
    assert again.user_id == saved.user_id and again.device == "iphone"
    assert again.completed_at == saved.completed_at          # finishing once keeps the original completion time
    assert store.count(OnboardingProfile) == 1

    # survives a restart: the row is in the database, not in the process
    assert OnboardingService(Store(str(tmp_path / "camp.db")), OfferService(Store(str(tmp_path / "camp.db")))) \
        .find(saved.user_id).settings == settings()


def test_find_prefers_the_named_person_and_reset_replays_the_flow():
    store, svc = service()
    mine = svc.save(OnboardingReq(context=context("Harry"), settings=settings(), device="mac"))
    theirs = svc.save(OnboardingReq(context=context("Ada"), settings=settings("Ada"), device="mac"))
    assert svc.find(None, "Harry", OFFICE.id).user_id == mine.user_id
    assert svc.find(None, None, OFFICE.id).user_id == theirs.user_id      # most recently completed
    assert svc.find(None, None, "other-office") is None

    reset = svc.reset(mine.user_id)
    assert not reset.completed and reset.completed_at is None
    assert reset.settings == settings()                                   # the answers stay; only the flag is cleared
    assert svc.save(OnboardingReq(context=context("Harry", user_id=mine.user_id))).settings == settings()


def test_http_contract(monkeypatch):
    monkeypatch.setenv("CAMP_DB", ":memory:")
    monkeypatch.setenv("CAMP_DATABASE_URL", "")
    monkeypatch.setenv("CAMP_TOKEN", "")
    from fastapi.testclient import TestClient
    import importlib, camp.api
    api = importlib.reload(camp.api)
    c = TestClient(api.app)
    assert c.get("/v1/onboarding").status_code == 404
    body = {"context": {"displayName": "Harry", "office": OFFICE.model_dump(by_alias=True), "dietaryStyle": "Vegan"},
            "settings": settings(), "device": "iphone"}
    put = c.put("/v1/onboarding", json=body)
    assert put.status_code == 200 and put.json()["completed"] is True
    user_id = put.json()["userId"]
    assert c.get("/v1/onboarding", params={"userId": user_id}).json()["settings"] == settings()
    assert c.delete(f"/v1/onboarding/{user_id}").json()["completed"] is False
    assert c.delete("/v1/onboarding/u_nobody").status_code == 404
