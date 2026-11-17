"""Production-table tests, independent of the historical compatibility fixture."""
import csv
import math
from pathlib import Path
from fitplate.nutrition import DEFAULT_DB, compute_nutrition
from fitplate.nutrition.service import daily_summary, enrich_meal


def item(food, quantity=100, **extra):
    return dict(name=food.name, food_id=food.food_id, quantity=quantity, unit="g",
                preparation="Not specified", **extra)


def test_every_production_record_has_primary_source_identity():
    rows = list(csv.DictReader((Path(__file__).resolve().parents[1] / "fitplate/data/foods.csv").open(encoding="utf-8-sig")))
    assert len(rows) == len(DEFAULT_DB.foods) == 17382
    assert {r["source_dataset"] for r in rows} == {"USDA", "UK", "AU", "CA"}
    assert len({r["food_id"] for r in rows}) == len(rows)
    for row in rows:
        for key in ["source_food_id", "source_food_description", "source_file", "source_sheet", "source_row",
                    "source_sha256", "source_ref", "source_version", "nutrient_basis", "carb_definition", "source_nutrient_columns"]:
            assert row[key], (row["food_id"], key)
        assert row["verification_status"] == "Verified official-source transcription"
        assert len(row["source_sha256"]) == 64
        assert row["source_ref"].startswith("https://")
        assert all(math.isfinite(float(row[k])) and float(row[k]) >= 0 for k in
                   ["per100_kcal", "per100_protein", "per100_carb", "per100_fat"])


def test_each_publisher_calculates_as_described_without_state_guesses():
    for dataset in ["USDA", "UK", "AU", "CA"]:
        foods = [f for f in DEFAULT_DB.foods if f.reference_metadata["source_dataset"] == dataset][:10]
        for food in foods:
            result = compute_nutrition({"items": [item(food)]})
            assert result["completeness"] == "complete", food.name
            assert result["items"][0]["per100"] == food.per100
            assert result["totals"] == {k: round(v, 1) for k, v in food.per100.items()}


def test_cross_definition_carbohydrates_are_not_blended():
    us = DEFAULT_DB.named("Egg")
    uk = next(f for f in DEFAULT_DB.foods if f.reference_metadata["source_dataset"] == "UK")
    mixed = {"date": "2026-11-14", "items": [item(us), item(uk)]}
    result = compute_nutrition(mixed)
    assert result["totals"]["carbs"] is None
    assert result["totals"]["energy"] is not None
    assert result["completeness"] == "partial"
    separate = [enrich_meal({"id": str(i), "date": "2026-11-14", "items": [item(f)]}) for i, f in enumerate([us, uk])]
    assert daily_summary(separate, "2026-11-14")["totals"]["carbs"] is None


def test_no_generic_density_or_cooking_yield_is_applied():
    oil = DEFAULT_DB.named("Olive oil")
    request = item(oil)
    request["unit"] = "ml"
    assert compute_nutrition({"items": [request]})["totals"]["energy"] is None
    chicken = DEFAULT_DB.named("Chicken breast")
    request = item(chicken)
    request["preparation"] = "Raw"
    assert compute_nutrition({"items": [request]})["totals"]["energy"] is None


def test_curated_alias_uses_actual_raw_variant_not_a_yield_guess():
    result = compute_nutrition({"items": [dict(name="Rice", quantity=100, unit="g", preparation="Raw")]})
    assert result["items"][0]["source"]["source_food_id"] == "169756"
    assert result["totals"]["energy"] == 365
    assert result["items"][0]["conversions"] == []


def test_piece_weight_has_official_portion_identity():
    result = compute_nutrition({"items": [dict(name="Egg", quantity=2, unit="piece", preparation="Boiled")]})
    detail = result["items"][0]
    assert detail["quantity"] == 100
    assert detail["conversions"][0]["source_portion_id"] == "92500"
    assert detail["conversions"][0]["portion_description"] == "large"


def test_same_name_search_does_not_collapse_distinct_sources():
    choices = DEFAULT_DB.candidates("chicken breast")
    assert choices
    assert len({r["food_id"] for r in choices}) == len(choices)
    assert all("[" in r["name"] for r in choices)


def test_publisher_filter_can_reach_all_four_databases():
    for dataset in ["USDA", "UK", "AU", "CA"]:
        choices = DEFAULT_DB.candidates("chicken", dataset=dataset)
        assert choices
        assert all(DEFAULT_DB.by_id[c["food_id"]].reference_metadata["source_dataset"] == dataset for c in choices)


def test_publisher_density_is_used_only_when_available():
    food = next(f for f in DEFAULT_DB.foods if f.density)
    request = item(food, quantity=100)
    request["unit"] = "ml"
    result = compute_nutrition({"items": [request]})
    assert result["items"][0]["quantity"] == round(100 * food.density, 3)
    assert result["items"][0]["estimated"]
