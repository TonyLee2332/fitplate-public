# Meal estimation

The official food table remains unchanged. Recipes are a separate estimation layer: 76 editable Chinese meal/single-food templates refer to 45 actual ingredient records. Their ratios, portions and cooking outcomes have not been weighed or validated. They are not official nutrient entries or authentic standard recipes.

## Conversation

The model extracts supplied foods, counts, weights and details, then asks up to two targeted questions. Oil, drainage, portion size, meat fat, noodle type and broth consumption are retained across follow-ups. Measured amounts remain in `quantity`; visual/AI gram proposals stay in `details.estimated_grams`. Deterministic evidence guards preserve explicit bowl/skewer counts, reject unsupported factual details, and prevent a nearby oil weight from replacing the whole-food portion.

Unknown dishes may use a separate source planner. It receives retrieved USDA choices and the bounded ingredient list. It may choose an actual ID or propose fractions summing to one, never nutrient values or executable actions. Invalid plans receive at most one correction attempt; unresolved items remain editable. Only explicit chat/media submissions call the model; previews, saving and page reruns do not.

Existing meals can be processed with **Reanalyse with AI**; drafts use **Estimate with AI**. Planning covers every unresolved food in batches of at most six, not just the first two. Explicit reanalysis is transactional: a failed request leaves the original draft and saved record unchanged. Whole-food references must come from that food's retrieved candidates; component plans use a bounded set of source IDs. Source retrieval tolerates plurals, cuts and preparation words without treating avocado oil as avocado fruit.

Count interpretation is separate from nutrition composition. A small set of editable app portion assumptions covers whole/sliced avocado, orange segments, pickled ginger slices and fried wonton strips. In a multi-food salad, several avocado pieces default to slices; segment/strip names retain those interpretations. These are unconfirmed defaults, not facts about a photograph or official portion standards. The original count/unit stays intact. Users can choose a different **Portion interpretation**, edit **Estimated total weight (g)**, or enter **Confirmed weight (g)**. Confirmed grams and supplied gram amounts take precedence. Estimated grams always mean the entire item and are never multiplied by the count again. Potential whole-dish/component duplication is flagged for review.

## Calculation

Ingredient nutrition equals source value per 100 g multiplied by the ingredient-equivalent grams divided by 100, summed by the calculator. Direct source selection overrides recipe matching. Single raw/cooked foods use actual variants where available. Mixed recipes require cooked whole-dish weight; explicit raw ingredient weights are not silently combined with cooked totals. Known cooked ingredient weights override template ratios and are checked against dish mass.

Oil is allocated within dish weight unless Main ingredient is selected. A complete fried-egg reference already includes cooking fat; it is never given oil twice. Meat fat uses clearly labelled leaner/fattier cooked-reference proxies. Drained/liquid ratios, bowl/skewer weights and watery-soup density are editable assumptions. Broth consumption changes only the consumed liquid components. Source profiles for flour, tofu, broth and fish may be ingredient-equivalent/proxy approximations, explicitly noted rather than claimed as measured cooking yields. Instant noodles require an appropriate source/brand and weight basis rather than automatic substitution with ordinary noodles.

This approach is informed by [FAO recipe-calculation guidance](https://www.fao.org/4/y4705e/y4705e23.htm) and [FAO/INFOODS recipe resources](https://www.fao.org/infoods/infoods/recipes/en/). Those sources describe methodology; they do not validate FitPlate's recipe ratios, portion defaults or proxies. All original nutrient provenance remains available in the ingredient breakdown.

## Uncertainty and review

Low/point/high scenarios vary uncertain portions, ingredient proportions, meat references, drainage and oil. Per-nutrient envelopes include the nominal result, but are not statistical confidence intervals or guaranteed error bounds. They do not cover every unknown ingredient, reference mismatch or cooking loss. Better supplied details can narrow selected assumptions; they cannot establish laboratory accuracy.

Estimates are visibly approximate and require a review checkbox before Save meal. Save stores the original input, details, nominal ingredient breakdown, source IDs/per-100g snapshots, scenario inputs, assumptions, recipe-catalog hash and review state. Editing recalculates; deletion removes the snapshot. Historical records are not silently migrated. Incomplete saved records may show a new preview; daily totals continue to use saved snapshots until review and save.

## Validation

Tests cover the two reported meals, all templates, real source IDs, mass balance, oil/drainage sensitivity, known ingredient weights, raw/cooked safeguards, bounded AI plans, review-before-write, edit/delete, source precision and no model calls on rerun. A real Chinese two-turn dialogue was also tested without writing personal records. Food identification, recipe accuracy and visual portion error have not undergone independent user or weighed-meal validation.
