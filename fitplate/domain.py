"""Deterministic preview adapter. Replace with the team's AI service."""

import re
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

FOODS = {
    "Chicken breast": r"chicken(?:\s+breast)?",
    "Rice": r"(?:white\s+|brown\s+)?rice",
    "Broccoli": r"broccoli",
    "Egg": r"eggs?",
    "Oats": r"oat(?:meal|s)?",
    "Greek yogurt": r"(?:greek\s+)?yogurt",
    "Banana": r"bananas?",
    "Salmon": r"salmon",
    "Tofu": r"tofu",
    "Milk": r"milk",
    "Bread": r"(?:whole.?grain\s+)?bread",
    "Olive oil": r"olive\s+oil",
}
UNITS = ("g", "ml", "piece", "serving")
PREPARATIONS = ("Not specified", "Raw", "Cooked", "Boiled", "Steamed", "Grilled", "Baked", "Fried")


def today():
    return datetime.now(ZoneInfo("Asia/Hong_Kong")).date()


def fresh_draft():
    return {
        "id": uuid4().hex,
        "date": today().isoformat(),
        "meal_type": "Lunch",
        "items": [],
        "note": "",
        "input_source": "Text",
    }


def extract_items(text):
    items = []
    for name, pattern in FOODS.items():
        match = re.search(rf"\b(?:{pattern})\b", text, re.I)
        if not match:
            continue
        before = text[max(0, match.start() - 25):match.start()]
        after = text[match.end():match.end() + 30]
        prefix = re.search(r"(?<![-\d.])(\d+(?:\.\d+)?)\s*(g|grams?|ml|pieces?|servings?)?\s*(?:of\s+)?(?:(?:raw|cooked|boiled|steamed|grilled|baked|fried)\s+)?$", before, re.I)
        suffix = re.match(r"\s*(?:[:=]|was|is)?\s*(\d+(?:\.\d+)?)\s*(g|grams?|ml|pieces?|servings?)\b", after, re.I)
        portion = prefix or suffix
        quantity, unit = None, "g"
        if portion:
            quantity = float(portion.group(1))
            if quantity > 100000:
                quantity = None
            raw_unit = (portion.group(2) or ("piece" if name in ("Egg", "Banana") else "g")).lower()
            unit = "g" if raw_unit.startswith("g") else "piece" if raw_unit.startswith("piece") else "serving" if raw_unit.startswith("serving") else "ml"
        context = text[max(0, match.start() - 12):match.end()]
        preparation = next((p for p in PREPARATIONS[1:] if re.search(rf"\b{p}\b", context, re.I)), "Not specified")
        items.append({"name": name, "quantity": quantity, "unit": unit, "preparation": preparation})
    return items


def update_draft(draft, text):
    result = {**draft, "items": [dict(item) for item in draft["items"]]}
    for meal_type in ("Breakfast", "Lunch", "Dinner", "Snack"):
        if re.search(rf"\b{meal_type}\b", text, re.I):
            result["meal_type"] = meal_type
            break
    if re.search(r"\byesterday\b", text, re.I):
        result["date"] = (today() - timedelta(days=1)).isoformat()
    explicit_date = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if explicit_date:
        try:
            result["date"] = date.fromisoformat(explicit_date.group()).isoformat()
        except ValueError:
            pass
    parsed = extract_items(text)
    for item in parsed:
        existing = next((old for old in result["items"] if old["name"] == item["name"]), None)
        if existing:
            if item["quantity"] is not None:
                existing["quantity"], existing["unit"] = item["quantity"], item["unit"]
            if item["preparation"] != "Not specified":
                existing["preparation"] = item["preparation"]
        else:
            result["items"].append(item)
    return result, parsed


def validate_draft(draft):
    if not draft.get("items"):
        return "Add at least one food before saving."
    if date.fromisoformat(draft["date"]) > today():
        return "A meal log cannot be dated in the future."
    for item in draft["items"]:
        if not item["name"].strip():
            return "Every food needs a name."
        if item["quantity"] is None:
            from fitplate.meal_estimation import plan_item
            try:
                unresolved = plan_item(item)[2] == 'Unresolved'
            except ValueError as error:
                return str(error)
            if not draft.get("estimate_reviewed") or unresolved:
                return f"Add a positive portion for {item['name']} or review its estimated portion."
        elif item["quantity"] <= 0:
            return f"Add a positive portion for {item['name']}."
        if item["unit"] not in UNITS:
            return "Choose a supported portion unit."
    return None

