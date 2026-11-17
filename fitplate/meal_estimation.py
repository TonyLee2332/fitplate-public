"""Editable recipe/portion scenarios over source-identified nutrient records."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from fitplate.nutrition import DEFAULT_DB, compute_nutrition

CATALOG_PATH = Path(__file__).parent / "data/chinese_recipes.json"
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
VERSION = hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
RECIPES = {r["key"]: r for r in CATALOG["recipes"]}
INGREDIENTS = CATALOG["ingredients"]
KEYS = ("energy", "protein", "carbs", "fat")


def norm(text):
    return re.sub(r"[^a-z0-9\u3400-\u9fff]", "", str(text).casefold())


ALIASES = {norm(alias): r for r in RECIPES.values() for alias in r["aliases"]}
DETAIL_ENUMS = {
    "oil": ("Unknown", "None", "Light", "Regular", "Generous"),
    "drained": ("Unknown", "Drained", "With liquid"),
    "portion_size": ("Unknown", "Small", "Medium", "Large"),
    "meat_fat": ("Unknown", "Lean", "Mixed", "Fatty"),
    "broth_consumed": ("Unknown", "None", "Some", "All"),
    "soup_contents": ("Unknown", "Broth only", "Meat and broth"),
    "quantity_origin": ("User", "Estimate", "Reference"),
    "weight_basis": ("Whole dish", "Main ingredient"),
    "noodle_type": ("Unknown", "Wheat", "Rice", "Instant"),
    "ingredient_weight_state": ("Unknown", "Cooked", "Raw"),
    "portion_form": ("Unknown", "Whole", "Slice", "Segment", "Strip", "Serving"),
    "estimated_portion_form": ("Unknown", "Whole", "Slice", "Segment", "Strip", "Serving"),
}


def validate_details(details):
    if not isinstance(details, dict):
        raise ValueError("Details must be an object")
    allowed = set(DETAIL_ENUMS) | {"recipe_key", "estimated_grams", "estimate_basis", "reference_basis", "oil_grams", "use_defaults", "reference_food_id", "ai_components", "ingredient_grams", "source_portion_id", "cooking", "image_geometry"}
    if set(details) - allowed:
        raise ValueError("Unsupported detail field")
    details = {k: v for k, v in details.items() if v is not None}
    for key, value in details.items():
        if key == 'cooking':
            from fitplate.cooking import validate_cooking
            validate_cooking(value)
        if key == 'image_geometry' and (not isinstance(value,dict) or len(json.dumps(value)) > 10000):
            raise ValueError('Invalid image geometry provenance')
        if key == 'source_portion_id':
            from fitplate.source_portions import BY_ID
            if type(value) is not int or value not in BY_ID:
                raise ValueError('Unknown source portion ID')
        if key in DETAIL_ENUMS and value not in DETAIL_ENUMS[key]:
            raise ValueError("Invalid detail choice")
        if key in {"estimated_grams", "oil_grams"}:
            if type(value) not in (float, int) or not math.isfinite(value) or not (0 <= value <= 3000):
                raise ValueError("Invalid estimated weight")
            if key == "estimated_grams" and value == 0:
                raise ValueError("An estimated portion must be positive")
        if key == "recipe_key" and value not in RECIPES:
            raise ValueError("Unknown recipe key")
        if key == "use_defaults" and type(value) is not bool:
            raise ValueError("Invalid defaults choice")
        if key == "reference_food_id" and (type(value) is not int or value not in DEFAULT_DB.by_id):
            raise ValueError("Unknown reference food ID")
        if key in {"estimate_basis", "reference_basis"} and (not isinstance(value, str) or len(value) > 240 or re.search(r"[\u3400-\u9fff]", value)):
            raise ValueError("Estimate explanation must be short English text")
        if key == "ai_components":
            if not isinstance(value, list) or not 1 <= len(value) <= 8:
                raise ValueError("Invalid component plan")
            for component in value:
                if (not isinstance(component, dict) or set(component) != {"food_id", "fraction"}
                        or type(component["food_id"]) is not int or component["food_id"] not in DEFAULT_DB.by_id
                        or type(component["fraction"]) not in (float, int) or not math.isfinite(component["fraction"])
                        or not 0 < component["fraction"] <= 1):
                    raise ValueError("Invalid ingredient identity or proportion")
            if abs(sum(c["fraction"] for c in value) - 1) > .00001:
                raise ValueError("Ingredient fractions must sum to one")
        if key == "ingredient_grams":
            if not isinstance(value, dict) or not value or set(value) - set(INGREDIENTS):
                raise ValueError("Unknown ingredient weight key")
            if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 100000 for v in value.values()):
                raise ValueError("Invalid ingredient weight")
    return deepcopy(details)


def recipe_for(item):
    details = item.get("details") or {}
    if item.get("food_id") not in DEFAULT_DB.by_id and details.get("ai_components"):
        weights, sources = {}, {}
        for c in details["ai_components"]:
            key = next((k for k, fid in INGREDIENTS.items() if fid == c["food_id"]), "reference_" + str(c["food_id"]))
            weights[key] = weights.get(key, 0) + c["fraction"]
            sources[key] = c["food_id"]
        return dict(key="ai_recipe", name=item["name"], ingredients=weights, source_ids=sources,
                    default_grams=details.get("estimated_grams", 250), default_unit="serving", kind="recipe",
                    oil_sensitive="oil" in weights, drain_sensitive=False,
                    notes=details.get("reference_basis") or details.get("estimate_basis", "AI ingredient-equivalent scenario; recipe composition and yield have not been measured."))
    if item.get("food_id") in DEFAULT_DB.by_id or details.get("reference_food_id") in DEFAULT_DB.by_id:
        return None
    return RECIPES.get(details.get("recipe_key")) or ALIASES.get(norm(item.get("name")))


def _portion(item, recipe, scenario):
    details = item.get("details") or {}
    quantity, unit = item.get("quantity"), item.get("unit", "g")
    assumptions = []
    confirmed = item.get("confirmed_grams")
    if confirmed is not None and confirmed > 0:
        return confirmed, assumptions, "Confirmed grams", False
    if quantity is not None and unit == "g":
        return quantity, assumptions, "User-provided grams", details.get("quantity_origin") == "Estimate"
    from fitplate.source_portions import resolve_portion
    source_portion = resolve_portion(item)
    if source_portion:
        assumptions.append(f"USDA portion {source_portion['id']}: {source_portion['description']}; {source_portion['grams']:g} g per {source_portion['amount']:g} selected measure(s). This is a reference average, not a measured individual weight.")
        return source_portion['calculated_grams'], assumptions, 'Source portion estimate', True
    # AI proposals always describe the entire item, including its recorded count.
    # Do not multiply this total by pieces/servings a second time.
    if details.get("estimated_grams"):
        assumptions.append(details.get("estimate_basis") or "AI-proposed portion; no measured weight available.")
        return details["estimated_grams"] * {"low": .65, "point": 1, "high": 1.4}[scenario], assumptions, "AI portion estimate", True
    if quantity is not None and unit == "ml" and recipe and "soup" in recipe["key"]:
        assumptions.append("Watery soup volume approximated at 1 g/ml; not a measured density.")
        return quantity * ({"low": .98, "point": 1, "high": 1.05}[scenario]), assumptions, "Soup volume estimate", True
    if quantity is not None and recipe and unit in {"piece", "serving"}:
        size = {"Small": .7, "Medium": 1, "Large": 1.4, "Unknown": 1}[details.get("portion_size", "Unknown")]
        grams = quantity * recipe["default_grams"] * size
        assumptions.append(f"{quantity:g} {unit}(s) use {recipe['default_grams'] * size:g} g each: an editable FitPlate portion assumption, not a measured Chinese bowl/skewer weight.")
        return grams * {"low": .75, "point": 1, "high": 1.25}[scenario], assumptions, "Reference portion estimate", True
    if quantity is None and recipe:
        assumptions.append(f"One {recipe['default_unit']} assumed at {recipe['default_grams']:g} g; confirm the amount.")
        return recipe["default_grams"] * {"low": .65, "point": 1, "high": 1.4}[scenario], assumptions, "Missing portion estimate", True
    return None, assumptions, "Unresolved", False


def _components(item, recipe, grams, scenario):
    details = item.get("details") or {}
    weights = dict(recipe["ingredients"])
    assumptions = []
    known_weights = details.get("ingredient_grams", {})
    if known_weights and details.get("ingredient_weight_state") != "Cooked":
        raise ValueError("Confirm cooked/ready-to-eat ingredient weights, or log raw ingredients separately; raw weights cannot be mixed with a cooked dish total.")
    if recipe["kind"] == "recipe" and not known_weights:
        protein_keys = {"pork", "beef", "lamb", "chicken", "egg", "tofu", "shrimp", "fish"}
        factor = {"low": .85, "point": 1, "high": 1.15}[scenario]
        weights = {k: v * (factor if k in protein_keys else 1) for k, v in weights.items()}
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}
    if recipe["kind"] == "recipe":
        assumptions.append("Editable cooked-dish composition scenario; ingredient proportions and yield have not been weighed or validated.")
    if recipe.get("notes"):
        assumptions.append(recipe["notes"])
    if "tofu" in weights:
        assumptions.append("Raw firm tofu composition approximates the tofu component; cooking moisture changes are not measured.")
    if "pepper" in weights:
        assumptions.append("Cooked green sweet pepper is a composition proxy for unspecified chili/pepper varieties.")
    if details.get("noodle_type") == "Rice" and "noodles" in weights:
        weights["rice_noodles"] = weights.pop("noodles")
    if details.get("noodle_type") == "Instant":
        raise ValueError("Instant noodles need a matching brand/source entry and dry or prepared weight. Select that reference rather than treating them as ordinary cooked noodles.")
    meat_level = details.get("meat_fat", "Unknown")
    fat_mix = {"Lean": 0, "Fatty": 1, "Mixed": {"low": .25, "point": .5, "high": .75}[scenario],
               "Unknown": {"low": 0, "point": .5, "high": 1}[scenario]}[meat_level]
    if any(k in weights for k in ("pork", "beef", "lamb")):
        assumptions.append(f"Meat composition proxy: {fat_mix:.0%} higher-fat and {1-fat_mix:.0%} leaner cooked references; this is not a measured cut or mixture.")
    if recipe["oil_sensitive"] or item.get("preparation") == "Fried" or details.get("oil_grams") is not None or details.get("oil", "Unknown") != "Unknown":
        original_oil = weights.pop("oil", 0)
        if item.get("preparation") == "Fried" and not original_oil:
            original_oil = .04
        if details.get("oil_grams") is not None or "oil" in known_weights:
            oil = known_weights.get("oil", details.get("oil_grams"))
            if oil > grams and details.get("weight_basis") != "Main ingredient":
                raise ValueError("Oil weight cannot exceed the whole dish weight. Choose Main ingredient if oil is additional.")
            oil_fraction = oil / grams if grams else 0
            assumptions.append(f"Added oil: {oil:g} g explicitly specified for this dish.")
        else:
            level = details.get("oil", "Unknown")
            factor = {"None": 0, "Light": .5, "Regular": 1, "Generous": 1.8, "Unknown": 1}[level]
            oil_fraction = (original_oil or (.025 if level not in {"None", "Unknown"} else 0)) * factor
            if level == "Unknown":
                oil_fraction *= {"low": .4, "point": 1, "high": 1.8}[scenario]
            assumptions.append(f"Oil scenario: {level.lower()} ({oil_fraction * grams:.1f} g in this portion); retained oil is uncertain unless weighed.")
        if details.get("weight_basis") == "Main ingredient":
            old_total = sum(weights.values())
            weights = {k: v / old_total for k, v in weights.items()}
            weights["oil"] = oil_fraction
            assumptions.append("Portion describes the base food; oil is additional to its weight.")
        else:
            old_total = sum(weights.values())
            weights = {k: v / old_total * (1 - oil_fraction) for k, v in weights.items()}
            if oil_fraction:
                weights["oil"] = oil_fraction
    if recipe["drain_sensitive"]:
        drained = details.get("drained", "Unknown")
        fraction = 1 if drained == "Drained" else (.7 if drained == "With liquid" else {"low": .7, "point": 1, "high": 1}[scenario])
        weights = {k: v * fraction for k, v in weights.items()}
        if fraction < 1:
            weights["water"] = weights.get("water", 0) + 1 - fraction
        assumptions.append(f"Drainage: {drained.lower()}; vegetable/solid fraction modelled at {fraction:.0%}.")
    if "soup" in recipe["key"]:
        if details.get("soup_contents") == "Broth only":
            for ingredient in list(weights):
                if ingredient not in {"water", "broth", "soy", "oil"}:
                    weights["broth"] = weights.get("broth", 0) + weights.pop(ingredient)
            assumptions.append("Broth only: no meat pieces included.")
        fraction = {"None": 0, "Some": .5, "All": 1, "Unknown": 1}[details.get("broth_consumed", "Unknown")]
        for key in ("water", "broth", "soy", "oil"):
            if key in weights:
                weights[key] *= fraction
        assumptions.append(f"Consumed broth fraction: {fraction:.0%}; unknown defaults to all.")
    if known_weights:
        target = grams * sum(weights.values())
        if sum(known_weights.values()) > target + .001:
            raise ValueError("Known ingredient weights exceed the cooked dish weight. Correct the whole-dish weight or ingredient amounts.")
        remaining = {k: v for k, v in weights.items() if k not in known_weights}
        remainder = target - sum(known_weights.values())
        if remainder > .001 and not remaining:
            raise ValueError("Known ingredient weights do not account for the dish total. Confirm the remaining ingredients or total weight.")
        remaining_total = sum(remaining.values())
        weights = {k: v / grams for k, v in known_weights.items() if v > 0}
        if remaining_total and remainder > .001:
            weights.update({k: v / remaining_total * remainder / grams for k, v in remaining.items()})
        assumptions.append("User-provided cooked ingredient weights retained; any remaining mass follows the editable recipe proportions.")
    rows = []
    for key, fraction in weights.items():
        if fraction <= 0:
            continue
        food = DEFAULT_DB.by_id[recipe.get("source_ids", {}).get(key, INGREDIENTS.get(key))]
        if recipe["kind"] == "single" and key != "oil" and key != "water":
            prep = item.get("preparation")
            if prep == "Raw" and food.state != "raw":
                partner = food.counterpart or {"egg": 1171287, "spinach": 1168462, "broccoli": 1170379}.get(key)
                if not partner:
                    raise ValueError("Choose a matching raw source entry or provide cooked weight.")
                food = DEFAULT_DB.by_id[partner]
            elif key == "chicken" and prep in {"Boiled", "Steamed"}:
                food = DEFAULT_DB.by_id[INGREDIENTS["chicken_boiled"]]
        choices = [(food, 1)]
        if key in {"pork", "beef", "lamb"}:
            choices = [(food, 1-fat_mix), (DEFAULT_DB.by_id[INGREDIENTS[key + "_fatty"]], fat_mix)]
        for reference, share in choices:
            if share > 0:
                rows.append(dict(name=reference.name, food_id=reference.food_id, quantity=round(grams * fraction * share, 5), unit="g", preparation="Not specified"))
    if rows and all(r["quantity"] >= .001 for r in rows):
        total = round(sum(r["quantity"] for r in rows), 3)
        for row in rows[:-1]:
            row["quantity"] = round(row["quantity"], 3)
        rows[-1]["quantity"] = round(total - sum(r["quantity"] for r in rows[:-1]), 3)
    return rows, assumptions


def plan_item(item, scenario="point"):
    from fitplate.portion_estimation import seed_portion_estimates
    item = deepcopy(item)
    from fitplate.food_defaults import apply_family_defaults
    apply_family_defaults(item)
    # A selected form can be recalculated locally when the user changes the count.
    if item.get("details", {}).get("portion_form", "Unknown") != "Unknown":
        seed_portion_estimates({"items": [item]})
    validate_details(item.get("details") or {})
    if item.get('details', {}).get('cooking'):
        from fitplate.cooking import project_cooking
        rows, assumptions, provenance = project_cooking(item)
        return rows, assumptions, 'FAO recipe calculation', True, dict(kind='recipe',key='fao_recipe')
    recipe = recipe_for(item)
    details = item.get("details") or {}
    if (recipe and recipe["key"] == "egg" and item.get("preparation") == "Fried"
            and item.get("quantity") is not None and details.get("oil", "Unknown") == "Unknown"
            and details.get("oil_grams") is None):
        return [{**item, "food_id": 1173423}], ["Fried egg source already includes cooking fat; no oil is added twice."], "Source reference", False, None
    if recipe and recipe["kind"] == "recipe" and recipe["key"] != "ai_recipe" and item.get("preparation") == "Raw":
        raise ValueError("This recipe requires cooked whole-dish weight. Confirm the basis or enter the raw ingredients separately.")
    grams, assumptions, portion_kind, guessed = _portion(item, recipe, scenario)
    if recipe and grams is not None:
        components, extra = _components(item, recipe, grams, scenario)
        ambiguous_state = recipe["key"] in {"rice", "brown_rice"} and item.get("preparation") == "Not specified"
        if ambiguous_state:
            extra.append("Rice assumed weighed cooked as served; select Raw if this is dry weight.")
        uncertain_drainage = recipe["drain_sensitive"] and (item.get("details") or {}).get("drained", "Unknown") != "Drained"
        return components, assumptions + extra, portion_kind, guessed or recipe["kind"] == "recipe" or len(components) > 1 or ambiguous_state or uncertain_drainage, recipe
    direct = deepcopy(item)
    ref = (item.get("details") or {}).get("reference_food_id")
    if ref:
        direct["food_id"] = ref
        direct["preparation"] = "Not specified"
        direct["estimated"] = True
        assumptions.append("Selected source approximation: " + DEFAULT_DB.by_id[ref].source_food_description + ". No additional hidden oil is added to this complete source entry.")
        if details.get("estimate_basis") and details["estimate_basis"] not in assumptions:
            assumptions.append(details["estimate_basis"])
        if details.get("reference_basis") and details["reference_basis"] not in assumptions:
            assumptions.append(details["reference_basis"])
    if grams is not None and guessed:
        direct.update(quantity=grams, unit="g", estimated=True)
        direct.pop("confirmed_grams", None)
    return [direct], assumptions, "AI reference estimate" if ref else portion_kind, guessed or bool(ref), None


def assess_meal(meal,automatic=True):
    """Calculate first; automatically estimate unresolved, identifiable foods on demand."""
    result=_assess_meal(meal)
    if not automatic or not result['pending_items']:return result
    from fitplate.auto_estimation import prepare_auto_estimates
    eligible=[p['input_index'] for p in result['pending_items']]
    prepared,provenance=prepare_auto_estimates(meal,eligible)
    if not provenance:return result
    calculated=_assess_meal(prepared)
    if calculated['computed_count']<result['computed_count']:return result
    calculated['auto_estimation_version']='1.0'
    for item in calculated['items']:
        if item['input_index'] in provenance:
            original=meal['items'][item['input_index']]
            item['automatic_estimate']=True
            if item.get('estimate_kind')!='Recipe estimate':item['estimate_kind']='Automatic source estimate'
            item['input_quantity']=original.get('quantity');item['input_unit']=original.get('unit')
            item['assumptions']=provenance[item['input_index']]+item.get('assumptions',[])
    return calculated


def _assess_meal(meal):
    projected, plans = [], []
    for index, item in enumerate(meal.get("items", [])):
        try:
            rows, assumptions, kind, review, recipe = plan_item(item)
            error = None
        except ValueError as problem:
            rows, assumptions, kind, review, recipe, error = [], [], "Unresolved", False, recipe_for(item), str(problem)
        start = len(projected)
        projected.extend(rows)
        plans.append(dict(index=index, start=start, end=len(projected), assumptions=assumptions, kind=kind,
                          requires_review=review, recipe=recipe, error=error))
    core = compute_nutrition({**meal, "items": projected})
    grouped, pending = [], []
    for plan, original in zip(plans, meal.get("items", [])):
        parts = core["items"][plan["start"]:plan["end"]]
        unresolved = bool(plan["error"]) or not parts or any(p["needs_confirmation"] for p in parts)
        if len(parts) == 1 and (not plan["recipe"] or plan["recipe"]["kind"] == "single"):
            detail = deepcopy(parts[0])
        else:
            detail = dict(name=original.get("name"), food_id=None, unit="g", preparation=original.get("preparation"),
                          quantity=sum(p.get("quantity") or 0 for p in parts) or None, match_type="recipe", source={
                              "source": "FitPlate editable recipe scenario", "source_version": CATALOG["version"],
                              "source_ref": CATALOG["method_reference"], "verification": "Recipe estimate; source-identified ingredients",
                              "carb_definition": "Total carbohydrate by difference", "verification_note": CATALOG["status"]},
                          **{key: None if unresolved else round(sum(p[key] or 0 for p in parts), 3) for key in KEYS})
        detail.update(input_index=plan["index"], input_name=original.get("name"), input_quantity=original.get("quantity"),
                      input_unit=original.get("unit"), input_preparation=original.get("preparation"),
                      preparation=original.get("preparation"), components=parts, assumptions=plan["assumptions"],
                      estimate_kind="Recipe estimate" if plan["recipe"] and plan["recipe"]["kind"] == "recipe" else plan["kind"],
                      requires_estimate_review=plan["requires_review"], estimated=bool(detail.get("estimated")) or plan["requires_review"],
                      needs_confirmation=unresolved)
        from fitplate.source_portions import resolve_portion
        try:
            detail['portion_source'] = resolve_portion(original)
        except ValueError:
            detail['portion_source'] = None
        if original.get('details',{}).get('cooking') and not plan['error']:
            from fitplate.cooking import project_cooking
            detail['cooking_source'] = project_cooking(original)[2]
            detail['quantity'] = detail['cooking_source']['eaten_weight_g']
            detail['estimate_kind'] = 'FAO recipe calculation'
        if original.get('details',{}).get('image_geometry'):
            detail['image_geometry'] = original['details']['image_geometry']
        if unresolved:
            reason = plan["error"] or next((p.get("confirm_reason") for p in parts if p["needs_confirmation"]), "No compatible ingredient plan.")
            pending.append(dict(input_index=plan["index"], input_name=original.get("name"), reason=reason, candidates=detail.get("candidates", [])))
        grouped.append(detail)
    core.update(items=grouped, total_count=len(grouped), computed_count=sum(not d["needs_confirmation"] for d in grouped),
                pending_items=pending, estimation_version=VERSION, assumptions=[a for p in plans for a in p["assumptions"]],
                requires_estimate_review=any(p["requires_review"] for p in plans), estimate_reviewed=bool(meal.get("estimate_reviewed")))
    core["estimation_errors"] = [p["error"] for p in plans if p["error"]]
    if any(p["error"] for p in plans):
        core["completeness"] = "pending_confirmation"
    if core["requires_estimate_review"]:
        core["nutrition_status"] = "Estimated" if not pending else "Partial estimate"
        scenarios = []
        scenario_inputs = {}
        for scenario in ("low", "high"):
            rows = []
            origins = []
            try:
                for index, item in enumerate(meal.get("items", [])):
                    components = plan_item(item, scenario)[0]
                    rows.extend(components)
                    origins.extend([index] * len(components))
                checked = compute_nutrition({"items": rows})
                scenarios.append(checked["totals"])
                scenario_inputs[scenario] = [{"input_index": index, "food_id": d["food_id"], "grams": d.get("quantity"), "per100": d.get("per100"),
                                             "source": d.get("source")} for index, d in zip(origins, checked["items"])]
            except ValueError:
                pass
        core["scenario_range"] = {}
        core["scenario_inputs"] = scenario_inputs
        for key in KEYS:
            values = [r[key] for r in [core["totals"], *scenarios] if r.get(key) is not None]
            core["scenario_range"][key] = [min(values), max(values)] if values else None
    if meal.get('uncertainty_analysis'):
        from fitplate.uncertainty import input_hash
        if meal['uncertainty_analysis'].get('input_hash') == input_hash(meal):
            core['uncertainty_analysis'] = meal['uncertainty_analysis']
    return core


def questions_for(meal):
    questions = []
    for item in meal.get("items", []):
        d = item.get("details") or {}
        recipe = recipe_for(item)
        if d.get("use_defaults"):
            continue
        if d.get('cooking'):
            continue
        name = item["name"]
        if norm(name) == "milk":
            questions.append("Was the milk whole, low-fat or skim milk?")
        if recipe and recipe["key"] in {"rice", "brown_rice", "chicken"} and item.get("preparation") == "Not specified":
            questions.append(f"Was the portion of {name} weighed raw or cooked?")
        if item.get("quantity") is None or item.get("unit") in {"piece", "serving"} and d.get("portion_size", "Unknown") == "Unknown":
            questions.append(f"For {name}, what was the weight or portion size (small, medium or large)?")
        if recipe and (recipe["oil_sensitive"] or item.get("preparation") == "Fried") and d.get("oil", "Unknown") == "Unknown" and d.get("oil_grams") is None:
            questions.append(f"For {name}, was the oil amount none, light, regular or generous?")
        if recipe and {"pork", "beef", "lamb"} & set(recipe["ingredients"]) and d.get("meat_fat", "Unknown") == "Unknown":
            questions.append(f"Was the meat in {name} lean, mixed or fatty?")
        if recipe and recipe["drain_sensitive"] and d.get("drained", "Unknown") == "Unknown":
            questions.append(f"Was {name} weighed after draining, and was any oil or dressing added?")
        if recipe and "soup" in recipe["key"]:
            if d.get("broth_consumed", "Unknown") == "Unknown":
                questions.append(f"For {name}, did you drink all, some or none of the broth, and did you eat meat pieces?")
        if recipe and {"noodles", "rice_noodles"} & set(recipe["ingredients"]) and d.get("noodle_type", "Unknown") == "Unknown":
            questions.append(f"Were the noodles in {name} wheat, rice or instant noodles?")
        if not recipe and not item.get("food_id") and not d.get("reference_food_id") and DEFAULT_DB.match(item["name"]).food is None:
            questions.append(f"What are the main ingredients and cooking method of {name}?")
    from fitplate.question_priority import rank_questions
    return [r['question'] for r in rank_questions(meal, list(dict.fromkeys(questions)))][:2]


def guidance(meal):
    questions = questions_for(meal)
    if questions:
        return "To improve the estimate: " + " ".join(questions) + " If unsure, ask me to use typical estimates. Review the assumptions before saving."
    return "Review the meal estimate and its assumptions below. You can adjust portions, oil and preparation before saving."


def cautions_for(meal):
    """Flag plausible whole-dish/component overlap without deleting user input."""
    from fitplate.reference_search import identity_tokens
    cautions = []
    items = meal.get("items", [])
    for i, item in enumerate(items):
        words = identity_tokens(item["name"])
        dish_words = words & {"salad", "bowl", "sandwich"}
        if not dish_words:
            continue
        base = words - dish_words
        if base and any(base <= identity_tokens(other["name"]) for n, other in enumerate(items) if n != i):
            cautions.append(f"Check whether {item['name']} is a separate food or the name of a dish already listed as ingredients. This preview counts every listed item; remove overlapping entries before saving.")
    return cautions[:2]


def current_notes(meal):
    """Keep user notes; generate current missing-field labels separately from AI prose."""
    missing = [i["name"] for i in meal.get("items", []) if i.get("quantity") is None]
    return "Portion not provided: " + ", ".join(missing) if missing else "All recorded portion fields are filled; recipe/portion estimates may still apply."


def clean_notes(note):
    sentences = re.split(r"(?<=[.!?])\s+", str(note))
    return " ".join(s for s in sentences if not re.search(r"quantit(?:y|ies).*missing|recorded as.*based on user description|quantities for.*recorded as", s, re.I))


def detail_fields(item):
    recipe = recipe_for(item)
    fields = []
    if item.get("quantity") is None or item.get("unit") in {"piece", "serving"}:
        fields.append("portion_size")
    if recipe:
        if recipe["oil_sensitive"] or recipe["drain_sensitive"] or item.get("preparation") == "Fried" or recipe["key"] == "chicken":
            fields += ["oil", "weight_basis"]
        if recipe["drain_sensitive"]:
            fields.append("drained")
        if {"pork", "beef", "lamb"} & set(recipe["ingredients"]):
            fields.append("meat_fat")
        if "soup" in recipe["key"]:
            fields += ["broth_consumed", "soup_contents"]
        if {"noodles", "rice_noodles"} & set(recipe["ingredients"]):
            fields.append("noodle_type")
    return fields
