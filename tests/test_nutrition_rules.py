"""Regression cases for food state, cooking, units, provenance and invalid input."""
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from fitplate.nutrition import DEFAULT_DB, FoodDatabase, compute_nutrition, parse_count
from fitplate.nutrition.calculator import KEYS


def calculate(name="Egg", quantity=100, unit="g", preparation="Boiled", **extra):
    return compute_nutrition({"items": [dict(name=name, quantity=quantity, unit=unit,
                                          preparation=preparation, **extra)]})


class TestFoodRules(unittest.TestCase):
    def test_rice_state_selects_actual_entry(self):
        for name, state, food_id, energy in [("Rice", "Raw", 3, 346),
                                              ("Rice", "Cooked", 1, 116),
                                              ("Brown rice", "Raw", 4, 362),
                                              ("Salmon", "Raw", 73, 142)]:
            with self.subTest(name=name, state=state):
                result = calculate(name, preparation=state)
                item = result["items"][0]
                self.assertEqual(item["food_id"], food_id)
                self.assertEqual(item["calculation_grams"], 100)
                self.assertEqual(result["totals"]["energy"], energy)

    def test_missing_paired_state_requires_confirmation(self):
        result = calculate("Rice", preparation="Not specified")
        self.assertEqual(result["completeness"], "pending_confirmation")
        self.assertIsNone(result["totals"]["energy"])

    def test_fried_egg_uses_specific_entry(self):
        boiled = calculate()
        fried = calculate(preparation="Fried")
        self.assertEqual(fried["items"][0]["food_id"], 50)
        self.assertEqual(fried["totals"]["energy"], 196)
        self.assertNotEqual(boiled["totals"], fried["totals"])

    def test_frying_never_guesses_oil(self):
        result = calculate("Chicken breast", preparation="Fried")
        self.assertEqual(result["completeness"], "pending_confirmation")
        self.assertIsNone(result["totals"]["energy"])

    def test_named_state_and_preparation_are_retained(self):
        a = calculate("Raw chicken breast", 150, preparation="Not specified")
        b = calculate("Chicken breast", 150, preparation="Raw")
        self.assertEqual(a["totals"], b["totals"])
        item = a["items"][0]
        self.assertEqual(item["preparation"], "Raw")
        self.assertEqual(item["quantity"], 150)
        self.assertEqual(item["calculation_grams"], 112.5)
        self.assertTrue(item["estimated"])

    def test_conflicting_name_and_preparation(self):
        for name, prep in [("Raw chicken breast", "Boiled"), ("Fried egg", "Boiled"),
                           ("French fries", "Boiled"), ("Roast chicken", "Boiled"),
                           ("Raw chicken breast", "Cooked"), ("Raw cooked chicken breast", "Not specified")]:
            with self.subTest(name=name):
                self.assertEqual(calculate(name, preparation=prep)["completeness"], "pending_confirmation")

    def test_plural_and_longer_names(self):
        for name, fid, prep in [("Bananas", 109, "Raw"), ("Chicken breasts", 24, "Cooked"),
                                ("Brown rice cooked", 2, "Not specified")]:
            with self.subTest(name=name):
                result = calculate(name, preparation=prep)
                self.assertEqual(result["items"][0]["food_id"], fid)
                self.assertEqual(result["completeness"], "complete")

    def test_compound_names_do_not_become_ingredients(self):
        for name in ["Chicken breast fried rice", "鸡胸肉炒饭", "Unsweetened almond milk"]:
            with self.subTest(name=name):
                self.assertIsNone(calculate(name)["totals"]["energy"])

    def test_id_selection_is_authoritative(self):
        result = calculate("Rice", preparation="Cooked", food_id=2)
        self.assertEqual(result["items"][0]["name"], "Brown rice")
        self.assertEqual(result["totals"]["energy"], 112)

    def test_id_selection_does_not_bypass_state(self):
        result = calculate("Rice", preparation="Raw", food_id=1)
        self.assertEqual(result["items"][0]["food_id"], 1)
        self.assertEqual(result["completeness"], "pending_confirmation")

    def test_bad_ids_require_confirmation(self):
        for fid in [True, "47", -1, 9999, None]:
            with self.subTest(fid=fid):
                self.assertEqual(calculate(food_id=fid)["completeness"], "pending_confirmation")

    def test_chinese_ingredient_is_not_a_raw_modifier(self):
        result = calculate("花生", preparation="Cooked")
        self.assertEqual(result["items"][0]["food_id"], 121)
        self.assertEqual(result["completeness"], "complete")


class TestPortionsAndValidation(unittest.TestCase):
    def test_units_are_not_interchangeable(self):
        for name, unit, prep in [("Egg", "slice", "Boiled"), ("White bread", "piece", "Cooked"),
                                  ("Rice", "cup", "Cooked"), ("Olive oil", "ml", "Raw"),
                                  ("Oats", "piece", "Raw"), ("Rice", "plate", "Cooked")]:
            with self.subTest(name=name, unit=unit):
                self.assertEqual(calculate(name, 1, unit, prep)["completeness"], "pending_confirmation")

    def test_average_serving_is_explicitly_estimated(self):
        result = calculate("Rice", 2, "serving", "Cooked")
        item = result["items"][0]
        self.assertEqual(item["quantity"], 300)
        self.assertTrue(item["estimated"])
        self.assertTrue(item["conversions"])
        self.assertTrue(result["warnings"])

    def test_confirmed_weight_overrides_unit_estimate(self):
        result = calculate("Olive oil", 15, "ml", "Raw", confirmed_grams=13.5)
        item = result["items"][0]
        self.assertEqual(item["quantity"], 13.5)
        self.assertEqual(item["input_quantity"], 15)
        self.assertEqual(item["input_unit"], "ml")
        self.assertEqual(item["conversions"], [])
        self.assertTrue(item["estimated"])

    def test_liquid_approximation_is_not_hidden(self):
        result = calculate("Milk", 250, "ml", "Not specified")
        self.assertEqual(result["items"][0]["quantity"], 250)
        self.assertTrue(result["items"][0]["estimated"])
        self.assertIn("Approximate liquid density: 1 g/ml", result["warnings"])

    def test_invalid_quantities_stay_strict_json(self):
        for value in [float("inf"), float("nan"), -float("inf"), "Infinity", 1e308, 0, -1, True, {}, []]:
            with self.subTest(value=repr(value)):
                result = calculate(quantity=value)
                self.assertEqual(result["completeness"], "pending_confirmation")
                self.assertIsNone(result["totals"]["energy"])
                json.dumps(result, allow_nan=False)

    def test_converted_weights_are_bounded(self):
        self.assertEqual(calculate(quantity=100_000, unit="piece")["completeness"], "pending_confirmation")

    def test_invalid_names_preparations_and_flags(self):
        for extra in [{"name": 12}, {"name": None}, {"name": []}, {"preparation": []},
                      {"preparation": "Invalid"}, {"estimated": "false"}]:
            with self.subTest(extra=extra):
                result = calculate(**extra)
                self.assertEqual(result["completeness"], "pending_confirmation")
                json.dumps(result, allow_nan=False)

    def test_empty_and_malformed_meals(self):
        self.assertEqual(compute_nutrition({"items": []})["completeness"], "pending_confirmation")
        for meal in [None, [], {"items": None}, {"items": {}}]:
            with self.subTest(meal=meal), self.assertRaises(ValueError):
                compute_nutrition(meal)
        result = compute_nutrition({"items": [None, 42]})
        self.assertEqual(result["completeness"], "pending_confirmation")

    def test_legacy_input_is_supported(self):
        result = compute_nutrition({"items": [{"food_name": "鸡蛋", "quantity": None,
                                             "grams": 100, "state": "cooked"}]})
        self.assertEqual(result["totals"]["energy"], 144)
        result = compute_nutrition({"items": [{"food_name": "鸡蛋", "count": "两",
                                             "unit": "个", "state": "cooked"}]})
        self.assertEqual(result["totals"]["energy"], 144)

    def test_extended_counts(self):
        for value, expected in [("二十三", 23), ("一个半", 1.5), ("半个", 0.5), ("1e2", 100)]:
            self.assertEqual(parse_count(value), (expected, True))
        for value in ["二三", "NaN", "inf", "-5"]:
            self.assertEqual(parse_count(value), (None, False))


class TestDatabaseAndProvenance(unittest.TestCase):
    def test_all_foods_and_aliases(self):
        self.assertEqual(len(DEFAULT_DB.foods), 152)
        for food in DEFAULT_DB.foods:
            with self.subTest(food=food.name):
                result = calculate(food.name, preparation="Raw" if food.state == "raw" else "Cooked")
                self.assertEqual(result["completeness"], "complete")
                self.assertEqual(result["totals"], {k: round(v, 1) for k, v in food.per100.items()})
                for alias in food.all_keys():
                    self.assertEqual(DEFAULT_DB.match(alias).food.food_id, food.food_id)

    def test_each_item_retains_audit_fields(self):
        item = calculate("Chicken breast", 150, preparation="Raw", id="row-1")["items"][0]
        self.assertEqual(item["input_item_id"], "row-1")
        self.assertEqual(item["input_index"], 0)
        self.assertEqual(item["input_preparation"], "Raw")
        self.assertEqual(item["source"]["database_version"], DEFAULT_DB.version)
        self.assertEqual(item["per100"]["energy"], 165)
        self.assertEqual(item["source"]["verification"], "Unverified")

    def test_totals_round_after_summing(self):
        result = compute_nutrition({"items": [dict(name="Egg", quantity=0.1, unit="g",
                                                   preparation="Boiled") for _ in range(10)]})
        self.assertEqual(result["totals"]["energy"], 1.4)
        self.assertEqual(result["totals"]["protein"], 0.1)

    def test_source_food_list_is_not_truncated(self):
        foods = [food for food in DEFAULT_DB.foods if food.source == DEFAULT_DB.foods[0].source][:15]
        result = compute_nutrition({"items": [dict(name=f.name, quantity=100, unit="g",
                                                   preparation="Raw" if f.state == "raw" else "Cooked") for f in foods]})
        self.assertEqual(len(result["data_sources"][0]["entries"][0]["foods"]), 15)

    def test_bad_csvs_fail_clearly(self):
        with (ROOT / "fitplate" / "data" / "foods.csv").open(encoding="utf-8-sig") as handle:
            original = list(csv.DictReader(handle))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "foods.csv"
            for change in [{"per100_kcal": "nan"}, {"default_unit_grams": "0"},
                           {"per100_protein": "-1"}, {"per100_fat": "101"}, {"state": "invalid"}]:
                with self.subTest(change=change):
                    row = {**original[0], **change}
                    with path.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=row.keys())
                        writer.writeheader()
                        writer.writerow(row)
                    with self.assertRaisesRegex(ValueError, "row 2"):
                        FoodDatabase(path)
            for rows in [[original[0], original[0]], [{**original[0], "aliases": "Shared alias"}, {**original[1], "aliases": "Shared alias"}]]:
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=original[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                with self.assertRaises(ValueError):
                    FoodDatabase(path)
            path.write_text("food_id,name\n1,Old schema\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Incompatible"):
                FoodDatabase(path)

    def test_verifier_reports_unresolved_without_crashing(self):
        import runpy
        verify = runpy.run_path(str(ROOT / "tests" / "verify_nutrition.py"))["verify"]
        fixture = [{"meal_name": "Unknown food", "items": [{"name": "Household cleaning spray",
                    "quantity": 100, "unit": "g", "preparation": "Not specified"}],
                    "expected": dict.fromkeys(KEYS, 0)}]
        self.assertFalse(verify(fixture)[0]["passed"])

    def test_search_is_bilingual(self):
        self.assertEqual(DEFAULT_DB.search("鸡胸肉")[0].food_id, 24)
        self.assertEqual(DEFAULT_DB.search("Chicken breast")[0].food_id, 24)
        self.assertEqual(DEFAULT_DB.search(""), [])

    def test_data_path_does_not_depend_on_working_directory(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        env.pop("FITPLATE_FOODS_CSV", None)
        code = "from fitplate.nutrition import DEFAULT_DB; assert len(DEFAULT_DB.foods)>=17000"
        with tempfile.TemporaryDirectory() as folder:
            completed = subprocess.run([sys.executable, "-c", code], cwd=folder, env=env,
                                       text=True, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
