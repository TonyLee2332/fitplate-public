"""Check 20 frozen arithmetic fixtures; no real-world accuracy claim."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from fitplate.nutrition import compute_nutrition

KEYS = ("energy", "protein", "carbs", "fat")
ABS_TOLERANCE = 0.11


def verify(meals):
    rows = []
    for meal in meals:
        draft = {"id": meal["meal_name"], "items": [
            {k: item[k] for k in ("name", "quantity", "unit", "preparation")}
            for item in meal["items"]]}
        result = compute_nutrition(draft)
        differences = {k: None if result["totals"][k] is None else
                       abs(result["totals"][k] - meal["expected"][k]) for k in KEYS}
        passed = result["completeness"] == "complete" and all(
            value is not None and value <= ABS_TOLERANCE for value in differences.values())
        rows.append({"case": meal["meal_name"], "passed": passed,
                     "differences": differences, "status": result["completeness"]})
    return rows


def main():
    meals = json.loads((ROOT / "tests" / "reference_meals.json").read_text(encoding="utf-8"))
    rows = verify(meals)
    for row in rows:
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['case']}: {row['differences']}")
    passed = sum(row["passed"] for row in rows)
    print(f"Passed {passed}/{len(rows)}. Absolute rounding tolerance: {ABS_TOLERANCE} kcal/g.")
    print("Arithmetic consistency only; food data and real-world portions are not independently validated.")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
