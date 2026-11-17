"""Food lookup and auditable nutrition calculations. Standard library only."""
import csv
import difflib
import hashlib
import math
import os
from pathlib import Path
import re
import unicodedata
from functools import lru_cache

from .rules import (DATA_SOURCES, PREPARATIONS, UNITS, UNIT_ALIASES,
                    STATE_PAIRS, RAW_YIELDS, DRY_FACTORS, FRIED_FOODS,
                    LIQUIDS, PREP_WORDS)

KEYS = ("energy", "protein", "carbs", "fat")
NUTRIENT_COLUMNS = ("per100_kcal", "per100_protein", "per100_carb", "per100_fat")
MAX_GRAMS = 100_000
STATUSES = {"complete": "Complete", "partial": "Partial",
            "pending_confirmation": "Pending confirmation"}


def parse_count(value):
    """Return a finite positive quantity, including simple Chinese counts."""
    if isinstance(value, bool) or value is None:
        return None, False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        text = str(value).strip().replace("个", "").replace("份", "")
        digits = dict(zip("一二两俩三四五六七八九", (1, 2, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
        half = 0.5 if text.endswith("半") else 0
        text = text[:-1] if half else text
        if not text and half:
            number = half
        elif text in digits:
            number = digits[text] + half
        elif re.fullmatch("[一二两三四五六七八九]?十[一二三四五六七八九]?", text):
            tens, units = text.split("十")
            number = digits.get(tens, 1) * 10 + digits.get(units, 0) + half
        else:
            return None, False
    return (number, True) if math.isfinite(number) and 0 < number <= MAX_GRAMS else (None, False)


def normalize(text):
    return re.sub(r"[\s,_-]+", "", unicodedata.normalize("NFKC", text).casefold())


def preparation_in_name(name):
    found = []
    stripped = name.casefold()
    for word, preparation in PREP_WORDS:
        pattern = (rf"\b{word}\b" if word.isascii() else
                   "^" + word if word in ("生", "熟") else re.escape(word))
        if re.search(pattern, stripped):
            found.append(preparation)
            stripped = re.sub(pattern, " ", stripped)
    if "Raw" in found and "Cooked" in found:
        return stripped, {"Raw", "Cooked"}
    specific = set(found) - {"Cooked"}
    return stripped, specific or set(found)


class Food:
    def __init__(self, row):
        self.food_id = int(row["food_id"])
        for key in ("name", "name_zh", "category", "state", "default_unit", "source", "source_version"):
            setattr(self, key, row[key].strip())
        self.aliases = [s.strip() for s in row["aliases"].split(";") if s.strip()]
        self.aliases_zh = [s.strip() for s in row["aliases_zh"].split(";") if s.strip()]
        self.kcal, self.protein, self.carb, self.fat = (float(row[c]) for c in NUTRIENT_COLUMNS)
        self.default_unit_grams = float(row["default_unit_grams"])
        self.source_ref = row.get("source_ref", "").strip() or None
        self.verification = row.get("verification_status", "Unverified")
        self.verification_note = row.get("verification_note", "Original record not verified.")
        self.source_food_id = row.get("source_food_id", "") or None
        self.source_food_description = row.get("source_food_description", "") or None
        self.verification_date = row.get("verification_date", "") or None
        self.official = bool(row.get("source_dataset"))
        self.reference_metadata = {k: row.get(k, "") for k in ("source_dataset", "source_file", "source_sheet", "source_row",
            "source_sha256", "nutrient_basis", "carb_definition", "data_derivation", "source_energy_value",
            "source_energy_unit", "energy_conversion", "default_portion_id", "default_unit_description", "source_nutrient_columns")}
        self.counterpart = int(row["counterpart_food_id"]) if row.get("counterpart_food_id") else None
        self.density = float(row["density_g_per_ml"]) if row.get("density_g_per_ml") else None
        values = (self.kcal, self.protein, self.carb, self.fat, self.default_unit_grams)
        if (self.food_id <= 0 or not self.name or not self.source or not self.source_version
                or self.state not in (("raw", "cooked", "unknown") if self.official else ("raw", "cooked")) or self.default_unit not in UNIT_ALIASES
                or not all(math.isfinite(v) and v >= 0 for v in values)
                or self.kcal > 1000 or self.default_unit_grams <= 0
                or self.protein + self.carb + self.fat > 100.5):
            raise ValueError(f"Invalid food entry: {self.food_id}")
        self.default_unit = UNIT_ALIASES[self.default_unit]

    def all_keys(self):
        return [s for s in [self.name, self.name_zh, *self.aliases, *self.aliases_zh] if s]

    @property
    def per100(self):
        return dict(zip(KEYS, (self.kcal, self.protein, self.carb, self.fat)))

    @property
    def provenance(self):
        return {"source": self.source, "source_version": self.source_version,
                "source_ref": self.source_ref, "verification": self.verification,
                "verification_note": self.verification_note,
                "source_food_id": self.source_food_id,
                "source_food_description": self.source_food_description,
                "verification_date": self.verification_date, **self.reference_metadata}


class MatchResult:
    def __init__(self, food=None, match_type="none", score=1.0, candidates=None,
                 needs_confirmation=False, reason=""):
        self.food, self.match_type, self.score = food, match_type, score
        self.candidates = candidates or []
        self.needs_confirmation, self.reason = needs_confirmation, reason


class FoodDatabase:
    def __init__(self, path=None):
        path = Path(path or os.environ.get("FITPLATE_FOODS_CSV")
                    or Path(__file__).resolve().parents[1] / "data" / "foods.csv")
        required = {"food_id", "name", "name_zh", "aliases", "aliases_zh", "category", "state",
                    "default_unit", "default_unit_grams", "source", "source_version", *NUTRIENT_COLUMNS}
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not required <= set(reader.fieldnames or []):
                raise ValueError("Incompatible food CSV: use the English-first foods.csv schema.")
            self.foods = []
            for line, row in enumerate(reader, 2):
                try:
                    self.foods.append(Food(row))
                except (ValueError, TypeError, AttributeError) as error:
                    raise ValueError(f"Invalid food CSV row {line}: {error}") from error
        if not self.foods:
            raise ValueError("The food database is empty.")
        self.version = hashlib.sha256(path.read_bytes()).hexdigest()
        self.by_id, self._names, self._keys, self._plurals = {}, {}, {}, {}
        for food in self.foods:
            if food.food_id in self.by_id:
                raise ValueError(f"Duplicate food ID: {food.food_id}")
            self.by_id[food.food_id] = food
            for name in (food.name, food.name_zh):
                if name:
                    self._names[normalize(name)] = food
            for key in food.all_keys():
                normalized = normalize(key)
                if normalized in self._keys and self._keys[normalized] is not food:
                    raise ValueError(f"Ambiguous food name or alias: {key}")
                self._keys[normalized] = food
                if key.isascii() and not key.lower().endswith("s"):
                    self._plurals[normalize(key + "s")] = food
        self._ordered = sorted(self._keys, key=len, reverse=True)
        self._tokens = {f.food_id: set(re.findall(r"[a-z0-9]+", " ".join(f.all_keys()).lower())) for f in self.foods}

    def named(self, name):
        return self._keys.get(normalize(name))

    @lru_cache(maxsize=256)
    def candidates(self, text, limit=5, dataset=None):
        if self is globals().get('DEFAULT_DB') and self.foods[0].official:
            from fitplate.reference_search import reference_candidates
            return reference_candidates(text, limit=limit, dataset=dataset)
        key = normalize(text)
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        foods = [f for f in self.foods if not dataset or f.reference_metadata["source_dataset"] == dataset]
        ranked = sorted(foods, key=lambda f: -len(tokens & self._tokens[f.food_id]))[:256] if len(foods) > 1000 else foods
        eligible = {f.food_id for f in ranked}
        scores = {}
        for alias, food in self._keys.items():
            if food.food_id not in eligible:
                continue
            score = difflib.SequenceMatcher(None, key, alias).ratio()
            if food.official:
                coverage = len(tokens & self._tokens[food.food_id]) / max(len(tokens), 1)
                score = max(score, 0.7 * coverage + 0.2 * score)
            if score >= 0.55:
                scores[food.food_id] = max(scores.get(food.food_id, 0), score)
        return [{"food_id": fid, "name": self.by_id[fid].name,
                 "name_zh": self.by_id[fid].name_zh, "score": round(score, 3)}
                for fid, score in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]]

    def match(self, food_name):
        if not isinstance(food_name, str) or not food_name.strip():
            return MatchResult(needs_confirmation=True, reason="Enter a food name.")
        key = normalize(food_name)
        if key in self._keys:
            return MatchResult(self._keys[key], "exact" if key in self._names else "alias")
        if key in self._plurals:
            return MatchResult(self._plurals[key], "alias")
        stripped, _ = preparation_in_name(food_name)
        base = normalize(stripped)
        food = self._keys.get(base) or self._plurals.get(base)
        if food:
            return MatchResult(food, "prep_stripped")
        candidates = self.candidates(food_name)
        if any(len(alias) >= 2 and alias in key for alias in self._ordered):
            return MatchResult(match_type="composite", candidates=candidates, needs_confirmation=True,
                               reason="Confirm the complete dish or list its ingredients separately.")
        if candidates:
            best = candidates[0]
            gap = best["score"] - (candidates[1]["score"] if len(candidates) > 1 else 0)
            if not best.get('retrieval') and best["score"] >= 0.9 and gap >= 0.08:
                return MatchResult(self.by_id[best["food_id"]], "fuzzy", best["score"])
            return MatchResult(match_type="ambiguous", candidates=candidates, needs_confirmation=True,
                               reason="Choose the matching food from the candidates.")
        return MatchResult(reason="Food not found. Select an alternative or supply a verified entry.")

    def search(self, keyword, limit=8):
        if not isinstance(keyword, str) or not keyword.strip():
            return []
        key = normalize(keyword)
        return [f for f in self.foods if any(key in normalize(k) for k in f.all_keys())][:max(0, limit)]


def conversion(kind, method, factor):
    return {"kind": kind, "method": method, "factor": factor, **DATA_SOURCES[kind]}


def resolve_food(food, preparation, db, locked=False):
    """Prefer actual database variants; do not manufacture cooking adjustments."""
    if food.official:
        state = "raw" if preparation == "Raw" else "cooked" if preparation != "Not specified" else None
        if preparation == "Fried" and not re.search(r"\bfried\b", food.source_food_description.lower()):
            if food.source_food_id == "173424" and not locked:
                return db.by_id[1_173_423], None
            return food, "Select an explicitly fried source entry or log a cooked base food and oil separately."
        methods = {label for word, label in (("boiled", "Boiled"), ("steamed", "Steamed"), ("roasted", "Baked"),
                   ("baked", "Baked"), ("grilled", "Grilled"), ("fried", "Fried"))
                   if re.search(rf"\b{word}\b", food.source_food_description.lower())}
        if methods and preparation not in {"Not specified", "Cooked", "Raw", *methods}:
            return food, "The requested cooking method differs from the source description. Select a compatible reference."
        if preparation == "Not specified" and food.counterpart and not locked:
            return food, "Confirm whether the portion was weighed raw or cooked."
        if state is not None and state != food.state:
            if food.counterpart and not locked:
                return db.by_id[food.counterpart], None
            return food, "Preparation differs from, or is not established by, the selected source. Choose the correct entry or use Not specified for food as described."
        return food, None
    if food.name in FRIED_FOODS and preparation not in {"Not specified", "Cooked", "Fried"}:
        return food, "The selected fried dish conflicts with the requested preparation."
    if preparation == "Fried":
        if food.name == "Egg" and not locked:
            variant = db.named("Fried egg")
            if variant:
                return variant, None
        if food.name not in FRIED_FOODS:
            return food, "Select the fried dish entry, or confirm the base food and record cooking oil separately."
    state = "raw" if preparation == "Raw" else "cooked" if preparation != "Not specified" else None
    for raw_name, cooked_name in STATE_PAIRS:
        if food.name not in (raw_name, cooked_name):
            continue
        if state is None:
            return food, "Confirm whether the portion was weighed raw or cooked."
        target = db.named(raw_name if state == "raw" else cooked_name)
        if target and target is not food:
            if locked:
                return food, "The selected food ID conflicts with the requested raw/cooked state."
            return target, None
    return food, None


def resolve_grams(item, food, conversions):
    confirmed = item.get("confirmed_grams")
    quantity, valid = parse_count(confirmed if confirmed is not None else item["quantity"])
    if not valid:
        return None, "Enter a finite positive portion within the 100,000 g input limit."
    if confirmed is not None:
        return quantity, None
    unit = UNIT_ALIASES.get(str(item["unit"]).strip().lower())
    if unit == "g":
        return quantity, None
    if unit == "ml" and food.official and food.density:
        factor, method = food.density, "Publisher specific gravity (approximate g/ml)"
    elif unit == "ml" and not food.official and food.name in LIQUIDS:
        factor, method = 1.0, "Approximate liquid density: 1 g/ml"
    elif unit == food.default_unit and unit not in (None, "ml"):
        factor, method = food.default_unit_grams, f"Food-specific average {unit} weight"
    elif unit == "serving" and food.default_unit in {"serving", "bowl", "cup", "box", "pack", "can", "bottle"}:
        factor, method = food.default_unit_grams, f"One serving uses the database {food.default_unit} weight"
    else:
        return None, "No food-specific conversion for this unit. Confirm the weight in grams."
    grams = quantity * factor
    if not math.isfinite(grams) or grams > MAX_GRAMS:
        return None, "Converted weight exceeds the 100,000 g input limit."
    conversions.append(conversion("unit_conversion", method, factor))
    if food.official:
        conversions[-1].update(source=food.source, source_version=food.source_version,
            source_food_id=food.source_food_id, source_portion_id=food.reference_metadata["default_portion_id"],
            portion_description=food.reference_metadata["default_unit_description"])
    return grams, None


def calculation_weight(food, grams, preparation, conversions):
    if food.official:
        return grams, None
    if preparation == "Not specified":
        conversions.append(conversion("state_conversion", f"Assumed database state: {food.state}", 1.0))
        return grams, None
    state = "raw" if preparation == "Raw" else "cooked"
    if state != food.state:
        if state == "raw" and food.name in RAW_YIELDS:
            factor = RAW_YIELDS[food.name]
        elif state == "cooked" and food.name in DRY_FACTORS:
            factor = 1 / DRY_FACTORS[food.name]
        else:
            return None, "No supported raw/cooked conversion. Select the correct entry or confirm its database-state weight."
        conversions.append(conversion("state_conversion", f"{state} weight to {food.state} database basis", factor))
        return grams * factor, None
    if preparation in {"Boiled", "Steamed", "Grilled", "Baked"} and not (food.name == "Egg" and preparation == "Boiled"):
        conversions.append(conversion("state_conversion", f"Generic cooked entry used for {preparation.lower()}; no added oil included", 1.0))
    return grams, None


def safe_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return repr(value)[:200]


def compute_nutrition(meal, db=None):
    """Return nutrition and provenance. Unresolved values stay null."""
    db = db or DEFAULT_DB
    if not isinstance(meal, dict) or not isinstance(meal.get("items", []), list):
        raise ValueError("A meal must be an object with an items list.")
    details, pending, unmatched, warnings, source_groups = [], [], [], [], {}
    totals = dict.fromkeys(KEYS, 0.0)
    computed, confirmation = 0, not meal.get("items")
    if confirmation:
        warnings.append("Add at least one food item.")
    for index, raw in enumerate(meal.get("items", [])):
        raw = raw if isinstance(raw, dict) else {"name": raw}
        name = raw.get("name", raw.get("food_name", ""))
        quantity, unit = raw.get("quantity"), raw.get("unit")
        if quantity is None:
            if raw.get("grams") is not None:
                quantity, unit = raw["grams"], "g"
            else:
                quantity = raw.get("count")
        legacy_state = raw.get("state")
        prep = raw.get("preparation", {"raw": "Raw", "cooked": "Cooked"}.get(
            legacy_state if isinstance(legacy_state, str) else "", "Not specified"))
        detail = {"input_index": index, "input_item_id": safe_value(raw.get("id")),
                  "input_name": safe_value(name), "input_quantity": safe_value(quantity),
                  "input_unit": safe_value(unit), "input_preparation": safe_value(prep),
                  "name": None, "name_zh": None, "food_id": None, "match_type": "none",
                  "quantity": None, "unit": "g", "preparation": safe_value(prep),
                  "calculation_grams": None, "database_state": None, "conversions": [],
                  "source": None, "per100": None, "estimated": True,
                  "needs_confirmation": True, "confirm_reason": None, "candidates": [],
                  **dict.fromkeys(KEYS)}
        reason, food = None, None
        valid_name = isinstance(name, str) and bool(name.strip())
        if not valid_name:
            reason = "Enter a non-empty text food name."
        elif not isinstance(prep, str) or prep not in PREPARATIONS:
            reason = "Choose a supported preparation."
        elif "estimated" in raw and type(raw["estimated"]) is not bool:
            reason = "The estimated flag must be true or false."
        else:
            known = db.named(name)
            _, inferred = preparation_in_name(name) if not (known and known.official and normalize(name) == normalize(known.name)) else (name, set())
            if (len(inferred) > 1 or ("Raw" in inferred and prep == "Cooked")
                    or (inferred and prep not in {"Not specified", "Cooked", *inferred})):
                reason = "The food name and preparation conflict. Confirm the preparation."
            elif inferred and prep in {"Not specified", "Cooked"}:
                prep = next(iter(inferred))
                detail["preparation"] = prep
            if "food_id" in raw:
                fid = raw["food_id"]
                food = db.by_id.get(fid) if type(fid) is int else None
                mr = MatchResult(food, "selected_id", reason="Select a valid integer food ID.")
            else:
                mr = db.match(name)
            detail.update(match_type=mr.match_type, candidates=mr.candidates)
            food = mr.food
            reason = reason or (mr.reason if not food else None)
        if food:
            if not reason:
                food, reason = resolve_food(food, prep, db, locked="food_id" in raw or (food.official and normalize(name) == normalize(food.name)))
            detail.update(food_id=food.food_id, name=food.name, name_zh=food.name_zh,
                          database_state=food.state, source={**food.provenance, "database_version": db.version},
                          per100=food.per100)
        grams = basis = None
        if food and not reason:
            normalized = {**raw, "quantity": quantity, "unit": unit}
            grams, reason = resolve_grams(normalized, food, detail["conversions"])
            if not reason:
                basis, reason = calculation_weight(food, grams, prep, detail["conversions"])
        if reason:
            detail["confirm_reason"] = reason
            unknown = not food and reason.startswith("Food not found.")
            confirmation |= not unknown
            if not food and valid_name:
                unmatched.append(name)
            pending.append({"input_index": index, "input_name": safe_value(name),
                            "reason": reason, "candidates": detail["candidates"]})
        else:
            retention = raw.get('recipe_retention', {})
            if retention and (not isinstance(retention,dict) or set(retention)-set(KEYS) or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in retention.values())):
                raise ValueError('Invalid recipe nutrient-retention factors.')
            exact = {key: value * basis / 100 * retention.get(key,1) for key, value in food.per100.items()}
            detail.update({key: round(value, 3) for key, value in exact.items()})
            detail.update(quantity=round(grams, 3), calculation_grams=round(basis, 3),
                          estimated=bool(raw.get("estimated")) or bool(detail["conversions"])
                          or not food.verification.startswith("Verified")
                          or detail["match_type"] in {"fuzzy", "prep_stripped"},
                          needs_confirmation=False)
            if retention:
                detail.update(recipe_retention=retention, retention_source=raw.get('retention_source'))
            for key in KEYS:
                totals[key] += exact[key]
            computed += 1
            source_groups.setdefault((food.source, food.source_version), set()).add(food.name)
        warnings.extend(c["method"] for c in detail["conversions"])
        details.append(detail)
    completeness = "pending_confirmation" if confirmation else "partial" if unmatched else "complete"
    carb_definitions = {d["source"].get("carb_definition", "Unknown") for d in details if not d["needs_confirmation"]}
    if len(carb_definitions) > 1:
        warnings.append("Carbohydrate definitions differ between selected sources. Carbohydrate totals are not combined; select compatible reference entries.")
        if completeness == "complete":
            completeness = "partial"
    sources = [{"field": "food_nutrition", "database_version": db.version,
                "entries": [{"source": s, "source_version": v, "foods": sorted(names)}
                            for (s, v), names in source_groups.items()]}]
    for kind in DATA_SOURCES:
        if any(c["kind"] == kind for d in details for c in d["conversions"]):
            sources.append({"field": kind, **DATA_SOURCES[kind]})
    return {"meal_id": safe_value(meal.get("id")), "date": safe_value(meal.get("date")),
            "meal_type": safe_value(meal.get("meal_type")),
            "totals": {k: round(v, 1) if computed and not (k == "carbs" and len(carb_definitions) > 1) else None for k, v in totals.items()},
            "completeness": completeness, "nutrition_status": STATUSES[completeness],
            "computed_count": computed, "total_count": len(details), "items": details,
            "pending_items": pending, "unmatched": list(dict.fromkeys(unmatched)),
            "warnings": list(dict.fromkeys(warnings)), "data_sources": sources}


DEFAULT_DB = FoodDatabase()
