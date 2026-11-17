import json
from copy import deepcopy
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
from pathlib import Path

from fitplate import agent
from fitplate.domain import fresh_draft, today
from fitplate.meal_estimation import (RECIPES, INGREDIENTS, DEFAULT_DB, assess_meal, questions_for,
                                     validate_details, clean_notes, current_notes)
from fitplate.storage import save_meal, list_meals, delete_meal
from fitplate.nutrition.service import daily_summary


def food(name, quantity=250, unit="g", preparation="Cooked", **details):
    return dict(name=name, quantity=quantity, unit=unit, preparation=preparation, details=details)


def dinner():
    return {**fresh_draft(), "items": [food("Stir-fried pork with chili peppers", 250, preparation="Fried"),
             food("Boiled spinach", 80, preparation="Boiled"), food("Regular rice", 1.5, "serving", "Not specified")]}


def lunch():
    return {**fresh_draft(), "items": [food("Lamb skewers", 3, "piece", "Grilled"),
             food("Mixed noodles", 1, "serving"), food("Lamb soup", 200, "ml", "Boiled")]}


@pytest.mark.parametrize("factory", [dinner, lunch])
def test_screenshot_meals_calculate_all_foods_and_trace_sources(factory):
    meal = factory()
    original = deepcopy(meal)
    result = assess_meal(meal)
    assert meal == original
    assert result["computed_count"] == result["total_count"] == 3
    assert result["requires_estimate_review"]
    assert result["nutrition_status"] == "Estimated"
    for key, value in result["totals"].items():
        assert value is not None
        low, high = result["scenario_range"][key]
        assert low <= value <= high
    for item in result["items"]:
        for component in item["components"]:
            assert component["food_id"] in DEFAULT_DB.by_id
            assert component["source"]["verification"].startswith("Verified")
    assert all("input_index" in row for rows in result["scenario_inputs"].values() for row in rows)


def test_all_76_templates_resolve_without_invented_nutrients():
    assert len(RECIPES) >= 76
    for recipe in RECIPES.values():
        result = assess_meal({"items": [food(recipe["name"], preparation="Not specified")]})
        assert result["computed_count"] == 1, recipe["key"]
        assert not result["estimation_errors"]
        assert result["totals"]["energy"] is not None


def test_known_dish_mass_is_preserved_when_oil_changes():
    results = []
    for oil in ("None", "Generous"):
        result = assess_meal({"items": [food("Stir-fried pork with chili peppers", oil=oil, meat_fat="Lean")]})
        assert sum(c["quantity"] for c in result["items"][0]["components"]) == pytest.approx(250, abs=.001)
        results.append(result["totals"])
    assert results[1]["energy"] > results[0]["energy"]
    assert results[1]["fat"] > results[0]["fat"]


def test_user_cooked_ingredient_weights_override_recipe_ratios():
    result = assess_meal({"items": [food("Stir-fried pork with chili peppers", oil="None", meat_fat="Lean",
                ingredient_weight_state="Cooked", ingredient_grams={"pork": 150, "pepper": 90, "oil": 10})]})
    parts = {p["food_id"]: p["quantity"] for p in result["items"][0]["components"]}
    assert parts[INGREDIENTS["pork"]] == 150
    assert parts[INGREDIENTS["pepper"]] == 90
    assert parts[INGREDIENTS["oil"]] == 10
    assert sum(parts.values()) == 250


def test_raw_ingredient_weights_are_not_applied_to_cooked_dish():
    result = assess_meal({"items": [food("Stir-fried pork with chili peppers", ingredient_weight_state="Raw", ingredient_grams={"pork": 150})]})
    assert result["estimation_errors"]
    assert result["totals"]["energy"] is None


def test_drainage_changes_solids_without_changing_dish_mass():
    drained = assess_meal({"items": [food("Boiled spinach", 80, preparation="Boiled", drained="Drained", oil="None")]})
    wet = assess_meal({"items": [food("Boiled spinach", 80, preparation="Boiled", drained="With liquid", oil="None")]})
    assert wet["totals"]["energy"] < drained["totals"]["energy"]
    assert sum(p["quantity"] for p in wet["items"][0]["components"]) == pytest.approx(80)


def test_drinking_less_broth_reduces_soup_intake():
    all_broth = assess_meal({"items": [food("Lamb soup", 200, "ml", "Boiled", broth_consumed="All")]})
    no_broth = assess_meal({"items": [food("Lamb soup", 200, "ml", "Boiled", broth_consumed="None")]})
    assert no_broth["totals"]["energy"] < all_broth["totals"]["energy"]


def test_fried_egg_source_is_not_given_oil_twice():
    result = assess_meal({"items": [food("Egg", 100, preparation="Fried")]})
    assert result["totals"]["energy"] == 196
    assert len(result["items"][0]["components"]) == 1


def test_manual_source_choice_is_respected():
    item = food("Regular rice", 100)
    item["food_id"] = DEFAULT_DB.named("Brown rice").food_id
    result = assess_meal({"items": [item]})
    assert result["items"][0]["food_id"] == item["food_id"]


def test_questions_are_targeted_and_stop_repeating_answered_details():
    meal = {"items": [food("Boiled spinach", 80, preparation="Boiled")]}
    assert any("drain" in q.lower() for q in questions_for(meal))
    meal["items"][0]["details"].update(drained="Drained", oil="None")
    assert questions_for(meal) == []
    meal = dinner()
    assert 0 < len(questions_for(meal)) <= 2
    for item in meal["items"]:
        item["details"]["use_defaults"] = True
    assert questions_for(meal) == []


def test_estimates_require_review_and_survive_edit_delete():
    meal = dinner()
    with pytest.raises(ValueError, match="Review"):
        save_meal(meal)
    assert not list_meals()
    meal["estimate_reviewed"] = True
    save_meal(meal)
    first = list_meals()[0]
    assert first["nutrition"]["scenario_inputs"]
    summary = daily_summary(list_meals(), meal["date"])
    assert summary["estimated_meals"] == 1
    assert summary["energy_scenario_range"][0] <= summary["totals"]["energy"]
    meal["items"][0]["details"].update(oil="None", meat_fat="Lean")
    save_meal(meal)
    assert len(list_meals()) == 1
    assert list_meals()[0]["nutrition"]["totals"]["fat"] < first["nutrition"]["totals"]["fat"]
    delete_meal(meal["id"])
    assert daily_summary(list_meals(), meal["date"])["totals"]["energy"] is None


def test_stale_missing_quantity_notes_are_removed():
    note = "Rice recorded as 1.5 servings based on user description (bowls). Pork and spinach quantities are missing. No onions."
    assert clean_notes(note) == "No onions."
    assert "not provided" not in current_notes(dinner()).lower()


def test_model_proposal_cannot_masquerade_as_user_weight():
    draft = {"items": [food("Chicken breast", 150)]}
    agent._guard_quantities(draft, "I ate chicken breast", None)
    assert draft["items"][0]["quantity"] is None
    assert draft["items"][0]["details"]["estimated_grams"] == 150


def test_explicit_bowl_count_is_not_lost_or_converted_to_measured_grams():
    draft = {"items": [food("Cooked white rice", 300, preparation="Not specified", recipe_key="rice", estimated_grams=300)]}
    agent._restore_portion_evidence(draft, "我吃了1.5碗普通米饭")
    assert draft["items"][0]["quantity"] == 1.5
    assert draft["items"][0]["unit"] == "serving"
    assert "estimated_grams" not in draft["items"][0]["details"]


def test_oil_weight_does_not_overwrite_whole_food_portion():
    draft = {"items": [food("Rice", 150)]}
    agent._restore_portion_evidence(draft, "米饭加5克油")
    assert draft["items"][0]["quantity"] == 150


def test_unsupplied_drainage_and_default_acceptance_are_not_facts():
    draft = {"items": [food("Boiled spinach", 80, drained="Drained", use_defaults=True,
                           ingredient_grams={"spinach": 70, "oil": 10}, ingredient_weight_state="Cooked")]}
    agent._guard_detail_evidence(draft, "80克水煮菠菜", None)
    details = draft["items"][0]["details"]
    assert details["drained"] == "Unknown"
    assert not details["use_defaults"]
    assert "ingredient_grams" not in details


def test_explicit_cooked_follow_up_is_applied_without_reasking():
    draft = {"items": [food("Regular rice", 1.5, "serving", "Not specified", portion_size="Small")]}
    agent._guard_detail_evidence(draft, "1.5碗是小碗，之前的重量都是熟食重量", None)
    assert draft["items"][0]["preparation"] == "Cooked"
    assert questions_for(draft) == []


def test_follow_up_preserves_details_and_explicit_no_oil_clears_old_amount():
    previous = {**fresh_draft(), "items": [food("Boiled spinach", 80, preparation="Boiled", oil="Regular", oil_grams=5)]}
    output = {"intent": "meal", "reply": "Updated", "meal": {"date": today().isoformat(), "meal_type": "Lunch",
              "items": [food("Boiled spinach", 80, preparation="Boiled", oil="None", drained="Drained")], "note": ""}}
    result = agent.decode_result(json.dumps(output), previous, "Text")
    assert result["draft"]["items"][0]["details"]["oil_grams"] == 0
    assert result["draft"]["items"][0]["details"]["drained"] == "Drained"


def test_unchanged_manual_source_and_weight_survive_follow_up():
    previous = {**fresh_draft(), "items": [food("Rice", 1, "serving")]}
    previous["items"][0].update(food_id=DEFAULT_DB.named("Brown rice").food_id, confirmed_grams=160)
    output = {"intent": "meal", "reply": "Updated", "meal": {"date": today().isoformat(), "meal_type": "Lunch",
               "items": [food("Rice", 1, "serving")], "note": "No onions"}}
    result = agent.decode_result(json.dumps(output), previous, "Text")
    assert result["draft"]["items"][0]["food_id"] == previous["items"][0]["food_id"]
    assert result["draft"]["items"][0]["confirmed_grams"] == 160


def test_material_detail_changes_invalidate_an_old_ai_reference():
    previous = {**fresh_draft(), "items": [food("Unfamiliar chicken dish", reference_food_id=INGREDIENTS["chicken"], oil="Regular")]}
    output = {"intent": "meal", "reply": "Updated", "meal": {"date": today().isoformat(), "meal_type": "Lunch",
               "items": [food("Unfamiliar chicken dish", oil="None")], "note": ""}}
    result = agent.decode_result(json.dumps(output), previous, "Text")
    assert "reference_food_id" not in result["draft"]["items"][0]["details"]


def test_bounded_ai_recipe_cannot_introduce_unknown_source_ids():
    draft = {"items": [food("An unfamiliar stir-fry", 200)]}
    invalid = {"plans": [{"index": 0, "reference_food_id": None, "components": [{"food_id": 999999999, "fraction": 1}], "estimated_grams": None, "basis": "Unverified"}]}
    client = Mock()
    client.chat.return_value = json.dumps(invalid)
    agent._plan_unmatched(draft, client)
    assert client.chat.call_count == 2
    assert "ai_components" not in draft["items"][0]["details"]


def test_bounded_ai_can_propose_a_source_backed_ingredient_plan():
    draft = {"items": [food("An unfamiliar stir-fry", 200)]}
    plan = {"plans": [{"index": 0, "reference_food_id": None,
        "components": [{"food_id": INGREDIENTS["chicken"], "fraction": .6}, {"food_id": INGREDIENTS["pepper"], "fraction": .4}],
        "estimated_grams": None, "basis": "Illustrative cooked chicken/pepper mixture; ratio and oil are uncertain."}]}
    client = Mock()
    client.chat.return_value = json.dumps(plan)
    agent._plan_unmatched(draft, client)
    result = assess_meal(draft)
    assert result["computed_count"] == 1
    assert result["requires_estimate_review"]
    assert result["items"][0]["match_type"] == "recipe"


def test_known_food_with_unresolved_units_can_receive_a_reviewed_ai_weight():
    milk = DEFAULT_DB.named("Milk")
    draft = {"items": [food("Milk", 200, "ml", "Not specified")]}
    plan = {"plans": [{"index": 0, "reference_food_id": milk.food_id, "components": [],
                       "estimated_grams": 206, "basis": "Approximate total milk weight for the stated volume; confirm milk type."}]}
    client = Mock()
    client.chat.return_value = json.dumps(plan)
    agent._plan_unmatched(draft, client)
    assert client.chat.call_count == 1
    result = assess_meal(draft)
    assert result["computed_count"] == 1
    assert result["requires_estimate_review"]
    assert result["items"][0]["quantity"] == 206


@pytest.mark.parametrize("details", [{"oil_grams": -1}, {"estimated_grams": float("inf")},
    {"recipe_key": "invented"}, {"ai_components": [{"food_id": INGREDIENTS["pork"], "fraction": .4}]},
    {"ingredient_grams": {"invented": 100}}])
def test_invalid_estimation_metadata_is_rejected(details):
    with pytest.raises(ValueError):
        validate_details(details)


def test_ui_estimate_review_and_details_survive_save():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    app.session_state["draft"] = lunch()
    app.session_state["draft_revision"] += 1
    app.run()
    assert not app.exception
    assert any("≈" in metric.value for metric in app.metric)
    next(b for b in app.button if b.label == "Save meal").click().run()
    assert app.error
    assert not list_meals()
    next(c for c in app.checkbox if c.label == "I reviewed the estimated portions and recipe assumptions").check()
    next(b for b in app.button if b.label == "Save meal").click().run()
    assert not app.exception
    assert len(list_meals()) == 1
    assert list_meals()[0]["nutrition"]["computed_count"] == 3
    assert "details" in list_meals()[0]["items"][0]


def test_saved_incomplete_meal_gets_preview_without_silent_migration():
    from fitplate.storage import connect
    meal = dinner()
    with connect() as db:
        db.execute("INSERT INTO meals VALUES (?, ?, ?)", (meal["id"], json.dumps(meal), "2026-11-15"))
    before = list_meals()
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    next(b for b in app.button if b.label == "Meal records").click().run()
    assert not app.exception
    assert any("≈" in m.value for m in app.metric)
    assert any(b.label == "Review estimate" for b in app.button)
    assert list_meals() == before
    assert daily_summary(list_meals(), meal["date"])["totals"]["energy"] is None


def test_typical_estimates_button_does_not_call_model_or_save(monkeypatch):
    model = Mock(side_effect=AssertionError("No model call on estimation defaults"))
    monkeypatch.setattr(agent, "respond", model)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    app.session_state["draft"] = dinner()
    app.session_state["draft_revision"] += 1
    app.run()
    next(b for b in app.button if b.label == "Use typical estimates").click().run()
    assert not app.exception
    assert model.call_count == 0
    assert questions_for(app.session_state["draft"]) == []
    assert list_meals() == []


def test_reviewed_photo_proposal_can_save_without_claiming_measured_grams():
    meal = {**fresh_draft(), "input_source": "Photo", "items": [food("Chicken breast", None,
                estimated_grams=180, estimate_basis="Visual proposal without a scale reference.")], "estimate_reviewed": True}
    save_meal(meal)
    saved = list_meals()[0]
    assert saved["items"][0]["quantity"] is None
    assert saved["nutrition"]["items"][0]["estimate_kind"] == "AI portion estimate"
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    next(b for b in app.button if b.label == "Meal records").click().run()
    assert not app.exception


def test_instant_noodles_are_not_treated_as_generic_cooked_noodles():
    result = assess_meal({"items": [food("Mixed noodles", noodle_type="Instant")]})
    assert result["estimation_errors"]
