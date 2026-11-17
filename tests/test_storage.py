from fitplate.domain import fresh_draft, update_draft
from fitplate.storage import delete_meal, list_meals, read_settings, save_meal, save_settings


def test_confirm_edit_delete_and_idempotency():
    draft, _ = update_draft(fresh_draft(), "150 g chicken breast")
    save_meal(draft)
    save_meal(draft)
    assert len(list_meals()) == 1
    draft["items"][0]["quantity"] = 125
    save_meal(draft)
    assert list_meals()[0]["items"][0]["quantity"] == 125
    delete_meal(draft["id"])
    assert list_meals() == []


def test_preferences_and_optional_targets_persist():
    profile = read_settings()
    assert profile["energy"] is None
    save_settings({**profile, "name": "Test user", "protein": 120})
    assert read_settings()["protein"] == 120
    assert read_settings()["name"] == "Test user"

