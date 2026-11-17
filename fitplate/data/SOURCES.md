# Food sources

The production table contains **17,382 records**, all transcribed from identified official files. It replaces the earlier 152-row table; unsupported source attributions were removed, not relabelled. Reference values describe the publisher's food, not the exact composition of an individual meal.

| Publisher | Dataset / pinned edition | Included records |
|---|---|---:|
| USDA | FoodData Central SR Legacy, April 2018; published in FDC April 2019 | 7,793 |
| Public Health England | CoFID 2021 | 2,311 |
| Food Standards Australia New Zealand | AFCD Release 3, December 2025 | 1,588 |
| Health Canada | Canadian Nutrient File 2015, archived edition | 5,690 |

These are four publishing organisations, not four independent laboratory programmes. Records can incorporate analysis, borrowed values, imputation or recipe calculations performed by the publisher. `data_derivation` preserves available reference/method information. No unsupported old values or AI-generated nutrients remain in the production table. Historical JSON fixtures under `tests/fixtures` are isolated compatibility tests, not production nutrition references.

## Primary references

- [USDA downloads](https://fdc.nal.usda.gov/download-datasets/) and [SR Legacy documentation](https://www.ars.usda.gov/ARSUserFiles/80400535/DATA/SR-Legacy/SR-Legacy_Doc.pdf). Each USDA row links directly to its FDC food ID. Join `food.csv` to `food_nutrient.csv` on `fdc_id`; energy/protein/carbohydrate/fat IDs are 1008/1003/1005/1004.
- [CoFID official dataset](https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid) and [2021 user guide](https://assets.publishing.service.gov.uk/media/60538e66d3bf7f03249bac58/McCance_and_Widdowsons_Composition_of_Foods_integrated_dataset_2021.pdf). Read the `1.3 Proximates` worksheet: energy M, protein J, carbohydrate L, fat K. Includes public sector information licensed under the Open Government Licence v3.0.
- [AFCD official files](https://www.foodstandards.gov.au/science-data/food-nutrient-databases/afcd/data-files). Read `All solids & liquids per 100 g`, columns E/H/AN/J. Join `Food details` on Public Food Key for derivation and specific gravity. The separate per-100 mL worksheet is not imported.
- [CNF 2015 official download](https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/nutrient-data/canadian-nutrient-file-2015-download-files.html) and [user guide](https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/nutrient-data/canadian-nutrient-file-compilation-canadian-food-composition-data-users-guide.html). Source: Canadian Nutrient File, Health Canada, 2015. Join FOOD NAME and NUTRIENT AMOUNT on FoodID; use nutrient IDs 208/203/205/204. FoodCode is retained as the public identifier. The 2015 edition is deliberately labelled archived, not current.

## Identity and units

Every row retains publisher, original code and description, source version, file, worksheet/table, row number, nutrient column/ID mapping and raw-file SHA-256. `sources.json` pins the downloads. Internal numeric IDs use separate publisher namespaces. Display names carry the dataset/code; similar foods from different sources are never averaged or silently merged. A small reviewed bilingual alias list supplies default references for common foods; users can select another exact entry using the source filter.

All four exported nutrients use a **100 g basis**. Energy is kcal; protein, carbohydrate and fat are grams. AFCD energy is converted from the publisher's energy-with-fibre kJ using division by 4.184; the original value and unit remain in the row. Other published precision is retained, with Excel binary representation noise removed at 15 significant digits.

Carbohydrate definitions remain explicit: USDA/CNF total by difference; UK available carbohydrate in monosaccharide equivalents; AFCD available carbohydrate including sugar alcohols. Incompatible carbohydrate totals are not added together. This does not prevent energy, protein or fat totals from being shown.

`unknown` state means no unambiguous raw/cooked keyword was available; it is not a guess. Select `Not specified` to use the selected food exactly as described, or choose another matching state/method. Direct source lookup does not use assumed cooking yields or generic 1 g/mL conversions. The separate, opt-in meal estimator uses explicitly labelled recipe/portion assumptions and approximate watery-soup density; see `ESTIMATION.md`. Documented USDA egg/banana/rice portion IDs and AFCD specific gravity may support unit conversion, clearly marked as estimates.

## Exclusions and validation

576 raw records were excluded. Missing values and `Tr`/`N` markers were not replaced with zero. UK beverage groups and positive-alcohol entries were conservatively excluded because the workbook gives alcoholic beverages per 100 mL. Both occurrences of duplicate UK code 13-669, associated with different foods, were excluded rather than guessed. Implausible or incomplete required nutrient profiles are listed in `exclusions.json`.

The independent source checker reconciled all **17,382 identities and 69,528 nutrient values** against the archived raw files. This proves transcription consistency, not independent chemical measurement or real-world portion accuracy. Existing saved snapshots remain historical; editing and saving recalculates against the new table.

## Rebuild

```powershell
python tools/download_official_foods.py
python tools/build_official_foods.py
python tools/verify_official_foods.py
```

Raw files and generated evidence are under `artifacts/official_foods_2026-11-14`. The builder stages a new CSV there. Replace `fitplate/data/foods.csv` and `sources.json` only after verification passes and source hashes are reviewed. Rebuilding does not touch personal meal records or API credentials.
