from copy import deepcopy
import json
from pathlib import Path
from streamlit.testing.v1 import AppTest
from fitplate.domain import fresh_draft, today
from fitplate.storage import save_meal, list_meals, delete_meal, connect
from fitplate.nutrition.service import daily_summary, snapshot
from fitplate.nutrition import DEFAULT_DB


def meal(name="Egg", quantity=100, preparation="Boiled"):
    draft = fresh_draft()
    draft["items"] = [dict(name=name, quantity=quantity, unit="g", preparation=preparation)]
    return draft


def test_snapshot_recalculates_on_edit_and_deletes_with_meal():
    draft = meal()
    save_meal(draft)
    first = list_meals()[0]
    assert snapshot(first)["totals"]["energy"] == 155
    draft["items"][0]["preparation"] = "Fried"
    draft["nutrition"] = first["nutrition"]
    save_meal(draft)
    second = list_meals()[0]
    assert len(list_meals()) == 1
    assert snapshot(second)["items"][0]["food_id"] == DEFAULT_DB.named("Fried egg").food_id
    assert daily_summary(list_meals(), draft["date"])["totals"]["energy"] == 196
    delete_meal(draft["id"])
    assert daily_summary(list_meals(), draft["date"])["totals"]["energy"] is None


def test_old_records_are_not_silently_recalculated():
    draft = meal()
    with connect() as db:
        db.execute("INSERT INTO meals VALUES (?, ?, ?)", (draft["id"], json.dumps(draft), "2026-11-14"))
    result = daily_summary(list_meals(), draft["date"])
    assert result["totals"]["energy"] is None
    assert result["incomplete_meals"] == 1
    assert "nutrition" not in list_meals()[0]


def test_partial_unknown_values_and_stale_snapshot():
    draft = meal()
    draft["items"].append(dict(name="Household cleaning spray", quantity=100, unit="g", preparation="Not specified"))
    save_meal(draft)
    saved = list_meals()[0]
    assert snapshot(saved)["items"][1]["energy"] is None
    result = daily_summary([saved], draft["date"])
    assert result["totals"]["energy"] == 155
    assert result["incomplete_meals"] == 1
    changed = deepcopy(saved)
    changed["items"][0]["quantity"] = 200
    assert snapshot(changed) is None


def test_verified_food_has_actual_reference_status():
    food = DEFAULT_DB.named("Quinoa")
    assert food.provenance["verification"].startswith("Verified")
    assert "/168917/" in food.provenance["source_ref"]
    assert DEFAULT_DB.named("Oats").provenance["source_food_id"] == "169705"
    assert DEFAULT_DB.named("Oats").per100["energy"] == 389
    assert DEFAULT_DB.named("Oats").per100["protein"] == 16.89


def test_revised_foods_preserve_official_precision_and_identity():
    expected = {
        12: ("169705", (389, 16.89, 66.27, 6.9)),
        18: ("168917", (120, 4.4, 21.3, 1.92)),
        54: ("171304", (97, 9, 3.98, 5)),
        59: ("172179", (98, 11.12, 3.38, 4.3)),
        132: ("170273", (598, 7.79, 45.9, 42.63)),
    }
    assert len(DEFAULT_DB.foods) >= 17000
    assert sum(f.verification.startswith("Verified") for f in DEFAULT_DB.foods) == len(DEFAULT_DB.foods)
    for food_id, (source_id, nutrients) in expected.items():
        food = DEFAULT_DB.by_id[1_000_000 + int(source_id)]
        assert tuple(food.per100.values()) == nutrients
        assert food.source_food_id == source_id
        assert food.source_food_description
        assert food.verification_date == "2026-11-14"


def test_official_precision_and_reference_are_stored_with_meal():
    save_meal(meal("Greek yogurt", 100, "Not specified"))
    detail = snapshot(list_meals()[0])["items"][0]
    assert detail["per100"]["carbs"] == 3.98
    assert detail["carbs"] == 3.98
    assert detail["source"]["source_food_id"] == "171304"
    assert detail["source"]["source_food_description"] == "Yogurt, Greek, plain, whole milk"


def test_interface_records_progress_and_csv_export():
    save_meal(meal())
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    next(b for b in app.button if b.label == "Meal records").click().run()
    assert not app.exception
    assert any(m.value == "155 kcal" for m in app.metric)
    assert any("Verified" in w.value for w in app.markdown)
    next(b for b in app.button if b.label == "Goals & insights").click().run()
    assert not app.exception
    assert any(m.value == "155 kcal" for m in app.metric)


def test_fixture_verification_still_passes():
    from verify_nutrition import verify
    meals = json.loads((Path(__file__).parent / "reference_meals.json").read_text())
    assert all(row["passed"] for row in verify(meals))
