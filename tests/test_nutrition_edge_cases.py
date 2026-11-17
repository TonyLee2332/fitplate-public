"""Member 3 v1.2 regression tests: interface-format items, serving confirmation,
quantities, composite dish names, unknown-vs-zero, English-first data layer.

Run: python tests/test_edge_cases.py (or unittest discover)
Set FITPLATE_FOODS_CSV to test against an alternative foods.csv.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from fitplate.nutrition import compute_nutrition, parse_count  # noqa: E402


def run(items, **extra):
    """Run compute_nutrition with an interface meal draft."""
    meal = {"id": "test-meal", "date": "2026-11-12", "meal_type": "Lunch",
            "note": "", "input_source": "Text", "items": items}
    meal.update(extra)
    return compute_nutrition(meal)


def item(name, quantity=None, unit="g", preparation="Cooked"):
    """Interface draft item (fitplate/domain.py format)."""
    return {"name": name, "quantity": quantity, "unit": unit,
            "preparation": preparation}


class TestQuantityConfirmation(unittest.TestCase):
    """Missing amount requires confirmation; never auto-fill 100g."""

    def test_missing_quantity_no_auto_100g(self):
        r = run([item("Broccoli", quantity=None, unit="g")])
        d = r["items"][0]
        self.assertIsNone(d["quantity"])
        self.assertIsNone(d["energy"])        # unknown is null, not 0
        self.assertTrue(d["needs_confirmation"])
        self.assertEqual(r["completeness"], "pending_confirmation")
        self.assertEqual(len(r["pending_items"]), 1)

    def test_gram_quantity_ok(self):
        r = run([item("Broccoli", quantity=150)])
        self.assertEqual(r["items"][0]["quantity"], 150)
        self.assertEqual(r["completeness"], "complete")

    def test_ml_treated_as_grams(self):
        r = run([item("Milk", quantity=250, unit="ml", preparation="Not specified")])
        self.assertEqual(r["items"][0]["quantity"], 250)
        self.assertEqual(r["completeness"], "complete")

    def test_unknown_unit_requires_confirmation(self):
        r = run([item("Yogurt", quantity=1, unit="plate")])
        self.assertTrue(r["items"][0]["needs_confirmation"])
        self.assertEqual(r["completeness"], "pending_confirmation")

    def test_mixed_meal_pending(self):
        r = run([item("Chicken breast", quantity=100), item("White rice", quantity=None)])
        self.assertEqual(r["completeness"], "pending_confirmation")
        self.assertEqual(r["computed_count"], 1)
        self.assertEqual(r["total_count"], 2)


class TestQuantityUnits(unittest.TestCase):
    """Quantities like "2 pieces" / "2 servings" are computed correctly."""

    def test_two_pieces_of_egg(self):
        r = run([item("Egg", quantity=2, unit="piece", preparation="Boiled")])
        self.assertEqual(r["items"][0]["quantity"], 100)  # 50g x 2

    def test_two_servings_of_rice(self):
        r = run([item("White rice", quantity=2, unit="serving")])
        self.assertEqual(r["items"][0]["quantity"], 300)  # bowl 150g x 2
        self.assertTrue(r["warnings"])

    def test_half_serving(self):
        r = run([item("White rice", quantity=0.5, unit="serving")])
        self.assertEqual(r["items"][0]["quantity"], 75)

    def test_default_one_unit(self):
        r = run([item("Egg", quantity=1, unit="piece")])
        self.assertEqual(r["items"][0]["quantity"], 50)

    def test_piece_weight_unknown_requires_confirmation(self):
        # Oats default unit is "serving"; "piece" is not meaningful -> pending
        r = run([item("Oats", quantity=1, unit="piece")])
        self.assertTrue(r["items"][0]["needs_confirmation"])

    def test_parse_count_variants(self):
        for v, exp in [("2", 2.0), (2.5, 2.5), ("两", 2.0), ("俩", 2.0), ("十", 10.0)]:
            got, ok = parse_count(v)
            self.assertTrue(ok)
            self.assertEqual(got, exp)
        for v in [0, -3, "abc", "", None, True]:
            _, ok = parse_count(v)
            self.assertFalse(ok, f"quantity={v!r} should be invalid")

    def test_invalid_quantity_rejected(self):
        r = run([item("Egg", quantity="abc", unit="piece")])
        d = r["items"][0]
        self.assertTrue(d["needs_confirmation"])
        self.assertIsNone(d["energy"])
        self.assertEqual(r["completeness"], "pending_confirmation")


class TestInvalidValues(unittest.TestCase):
    """Invalid values (0 / negative / non-numeric) are rejected, never zero-filled."""

    def test_zero_quantity_rejected(self):
        r = run([item("Chicken breast", quantity=0)])
        self.assertTrue(r["items"][0]["needs_confirmation"])

    def test_negative_quantity_rejected(self):
        r = run([item("Chicken breast", quantity=-50)])
        self.assertTrue(r["items"][0]["needs_confirmation"])

    def test_non_numeric_quantity_rejected(self):
        r = run([item("Chicken breast", quantity="one big piece")])
        self.assertTrue(r["items"][0]["needs_confirmation"])
        self.assertIsNone(r["items"][0]["energy"])


class TestFoodMatching(unittest.TestCase):
    """Composite dish names must not match single ingredients; candidates when unsure."""

    def test_composite_dish_not_matched_to_ingredient(self):
        r = run([item("Chicken breast fried rice", quantity=1, unit="serving",
                      preparation="Fried")])
        d = r["items"][0]
        self.assertNotEqual(d["name"], "Chicken breast")
        self.assertEqual(d["match_type"], "composite")
        self.assertIsNone(d["energy"])         # not force-computed as chicken breast
        self.assertTrue(d["needs_confirmation"])
        self.assertTrue(d["candidates"])       # candidates offered for confirmation
        self.assertEqual(r["completeness"], "pending_confirmation")

    def test_chinese_composite_dish_still_guarded(self):
        r = run([item("鸡胸肉炒饭", quantity=200)])
        d = r["items"][0]
        self.assertEqual(d["match_type"], "composite")
        self.assertIsNone(d["energy"])

    def test_prep_modifier_in_name_still_matches(self):
        r = run([item("Boiled chicken breast", quantity=150)])
        d = r["items"][0]
        self.assertEqual(d["name"], "Chicken breast")
        self.assertFalse(d["needs_confirmation"])
        self.assertTrue(d["estimated"])

    def test_dish_exact_match_unaffected(self):
        r = run([item("Scrambled eggs with tomato", quantity=200)])
        self.assertEqual(r["items"][0]["name"], "Scrambled eggs with tomato")
        self.assertEqual(r["completeness"], "complete")

    def test_ambiguous_gives_candidates(self):
        r = run([item("Chicken soup", quantity=100)])
        d = r["items"][0]
        self.assertTrue(d["needs_confirmation"])
        self.assertTrue(d["candidates"])

    def test_unmatched_partial(self):
        r = run([item("Chicken breast", quantity=100),
                 item("Household cleaning spray", quantity=100)])
        self.assertEqual(r["completeness"], "partial")
        self.assertEqual(r["nutrition_status"], "Partial")
        d = r["items"][1]
        self.assertIsNone(d["energy"])         # unknown, not 0
        self.assertIn("Household cleaning spray", r["unmatched"])
        self.assertGreater(r["totals"]["energy"], 0)  # matched items still counted

    def test_all_unknown_totals_null(self):
        r = run([item("Household cleaning spray", quantity=100)])
        self.assertIsNone(r["totals"]["energy"])
        self.assertIsNone(r["totals"]["protein"])
        self.assertEqual(r["nutrition_status"], "Partial")

    def test_unmatchable_but_fuzzy_similar_goes_pending(self):
        # "Mystery dish" is fuzzy-similar to "Oyster" (0.588) -> candidates,
        # so the meal is pending_confirmation, not partial
        r = run([item("Mystery dish", quantity=100)])
        d = r["items"][0]
        self.assertEqual(d["match_type"], "ambiguous")
        self.assertTrue(d["candidates"])
        self.assertEqual(r["completeness"], "pending_confirmation")

    def test_interface_canonical_names(self):
        cases = {"Chicken breast": 24, "Rice": 1, "Broccoli": 84, "Egg": 47,
                 "Oats": 12, "Greek yogurt": 54, "Banana": 109, "Salmon": 72,
                 "Tofu": 60, "Milk": 51, "Bread": 11, "Olive oil": 128}
        for name, fid in cases.items():
            r = run([item(name, quantity=100)])
            self.assertEqual(r["items"][0]["food_id"], fid, f"{name} -> {fid}")

    def test_chinese_names_still_match(self):
        r = run([item("鸡胸肉", quantity=100)])
        self.assertEqual(r["items"][0]["food_id"], 24)
        r = run([item("奇异果", quantity=100)])
        self.assertEqual(r["items"][0]["food_id"], 115)

    def test_raw_preparation_triggers_yield_conversion(self):
        r = run([item("Chicken breast", quantity=150, preparation="Raw")])
        d = r["items"][0]
        self.assertEqual(d["quantity"], 150.0)
        self.assertEqual(d["calculation_grams"], 112.5)
        self.assertTrue(r["warnings"])

    def test_dry_to_cooked_restoration(self):
        r = run([item("Oats", quantity=60, preparation="Cooked")])
        d = r["items"][0]
        self.assertEqual(d["quantity"], 60.0)
        self.assertEqual(d["calculation_grams"], 20.0)


class TestContractAndSources(unittest.TestCase):
    """Contract fields and data sources (v1.2, interface-aligned)."""

    def test_food_id_name_zh_and_preparation(self):
        r = run([item("Egg", quantity=1, unit="piece", preparation="Boiled")])
        d = r["items"][0]
        self.assertEqual(d["food_id"], 47)
        self.assertEqual(d["name_zh"], "鸡蛋")
        self.assertEqual(d["preparation"], "Boiled")
        self.assertEqual(d["input_name"], "Egg")

    def test_draft_fields_passthrough(self):
        r = run([item("Egg", quantity=1, unit="piece")], id="abc-123",
                meal_type="Dinner", date="2026-11-11")
        self.assertEqual(r["meal_id"], "abc-123")
        self.assertEqual(r["meal_type"], "Dinner")
        self.assertEqual(r["date"], "2026-11-11")

    def test_data_sources_present_and_english(self):
        r = run([item("White rice", quantity=1, unit="serving"),
                 item("Chicken breast", quantity=100, preparation="Raw")])
        fields = {d["field"] for d in r["data_sources"]}
        self.assertIn("food_nutrition", fields)
        self.assertIn("unit_conversion", fields)
        self.assertIn("state_conversion", fields)
        food_src = next(d for d in r["data_sources"] if d["field"] == "food_nutrition")
        self.assertTrue(food_src["entries"])
        for e in food_src["entries"]:
            self.assertTrue(e["source"] and e["source_version"])
            self.assertFalse(any("\u4e00" <= ch <= "\u9fff" for ch in e["source"]),
                             "source strings must be English")

    def test_nutrition_status_complete(self):
        r = run([item("Egg", quantity=1, unit="piece")])
        self.assertEqual(r["completeness"], "complete")
        self.assertEqual(r["nutrition_status"], "Complete")

    def test_json_serializable(self):
        r = run([item("Egg", quantity=1, unit="piece"),
                 item("White rice", quantity=1, unit="serving")])
        json.dumps(r, ensure_ascii=False)      # contract must be JSON-serializable


if __name__ == "__main__":
    unittest.main(verbosity=2)
