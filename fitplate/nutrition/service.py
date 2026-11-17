"""Nutrition snapshots and partial-intake aggregation; no database writes."""
from hashlib import sha256
import json
from .calculator import KEYS


def fingerprint(meal):
    fields = {key: meal.get(key) for key in ("id", "date", "meal_type", "items")}
    if "estimate_reviewed" in meal:
        fields["estimate_reviewed"] = meal["estimate_reviewed"]
    return sha256(json.dumps(fields, sort_keys=True, allow_nan=False).encode()).hexdigest()


def enrich_meal(meal):
    from fitplate.meal_estimation import assess_meal
    result = assess_meal(meal)
    if result["estimation_errors"]:
        raise ValueError(result["estimation_errors"][0])
    if result['computed_count'] == 0 and meal.get('estimation_notice'):
        raise ValueError('AI matching is incomplete. Resolve food matches and portions before saving this meal.')
    if result["requires_estimate_review"] and not meal.get("estimate_reviewed"):
        raise ValueError("Review and accept the recipe/portion estimates before saving.")
    result["input_fingerprint"] = fingerprint(meal)
    if result['computed_count'] == result['total_count'] and result['computed_count']:
        meal = {k:v for k,v in meal.items() if k != 'estimation_notice'}
    return {**meal, "nutrition": result}


def snapshot(meal):
    result = meal.get("nutrition")
    try:
        current = fingerprint(meal)
    except (ValueError, TypeError):
        return None
    if not isinstance(result, dict) or result.get("input_fingerprint") != current:
        return None
    return result


def daily_summary(meals, date):
    selected = [meal for meal in meals if meal.get("date") == date]
    totals = dict.fromkeys(KEYS, 0.0)
    computed = 0
    incomplete = 0
    unavailable = set()
    carb_definitions = set()
    estimated_meals = 0
    energy_low = energy_high = 0.0
    for meal in selected:
        result = snapshot(meal)
        if not result or result["completeness"] != "complete":
            incomplete += 1
        if result and result["computed_count"]:
            estimated_meals += bool(result.get("requires_estimate_review"))
            energy_range = result.get("scenario_range", {}).get("energy")
            if result["totals"].get("energy") is not None:
                energy_low += energy_range[0] if energy_range else result["totals"]["energy"]
                energy_high += energy_range[1] if energy_range else result["totals"]["energy"]
            computed += result["computed_count"]
            for key in KEYS:
                if result["totals"][key] is None:
                    unavailable.add(key)
                else:
                    totals[key] += result["totals"][key]
            carb_definitions.update((item.get("source") or {}).get("carb_definition", "Unknown") or "Unknown"
                                    for item in result["items"] if not item["needs_confirmation"])
    if len(carb_definitions) > 1:
        unavailable.add("carbs")
    return {"totals": {k: round(v, 1) if computed and k not in unavailable else None for k, v in totals.items()},
            "carb_definitions": sorted(carb_definitions),
            "estimated_meals": estimated_meals,
            "energy_scenario_range": [round(energy_low, 1), round(energy_high, 1)] if computed else None,
            "meal_count": len(selected), "incomplete_meals": incomplete,
            "computed_items": computed}
