# Automatic estimation

## Entry points

- `assess_meal(meal)` applies calculation first and the local fallback only to unresolved items.
- `assess_meal(meal, automatic=False)` preserves strict validation for explicit AI reference-planner requests.
- `prepare_auto_estimates(meal, indices=None)` returns a separate projected meal plus assumption provenance. It never writes records or calls a model.

## Selection and portions

Compatible whole-food identities are preferred. Curated source choices cover fresh blueberries, whole-wheat bread, scrambled eggs, white mushrooms, generic cow milk and generic high-protein powder. General candidates normalize plurals and reject unrequested desserts, sauces, extracts, plant parts, smoked/fried preparations and related processed products. Exact primary food names take priority over related foods. This is a bounded proxy-selection method, not a guarantee of a brand/variety match.

Confirmed grams and supplied grams take priority. Documented household measures are next: examples include USDA 172688 slice (32 g), 171711 berries (68 g per 50 berries), 169252 mushroom (12 g), and 174181 powder serving (20 g). These are reference averages, not measurements of the user's food. Previously reviewed gram proposals are retained. Explicit size choices use a matching publisher size where available; otherwise the existing 0.7/1/1.4 size factors are labelled assumptions.

Unweighed liquids use publisher density when available, otherwise an explicit 1 g/ml approximation. Prepared protein drinks without powder grams assume one source powder serving per 250 ml water; milk and other additions need separate entries. When neither a compatible source measure nor a prior estimate exists, 30 g per piece or 100 g per serving is a visible editable fallback, not a measured standard.

Existing sourced dish templates remain preferred. Identifiable combinations can use nutrient-source ingredient equivalents with normalized composition assumptions (base weights 0.45 starch, 0.35 protein ingredient, 0.20 vegetable; normalize across detected ingredients). Fried composition scenarios include oil once. These ratios are engineering assumptions, not authentic recipes, measured cooking yields or medical recommendations.

## Output and limitations

Results mark automatic estimates, preserve original input quantities, carry database/source identities and household-measure provenance, and expose source/portion/recipe assumptions. Existing estimation ranges and sampled sensitivity tools remain applicable; ranges are not calibrated confidence intervals. No additional activation is required to display calculated estimates. Saving remains an explicit action with the existing review workflow.

An unknown identity, invalid quantity, incompatible explicit cooking state, or unsupported composition is not assigned a fabricated number. The existing bounded AI planner can still supply source-backed alternatives during an AI workflow. Calculation itself is offline. Historical saved snapshots remain unchanged until explicitly recalculated and saved; this prevents silent history changes. Carbohydrate definitions retain existing compatibility rules.
