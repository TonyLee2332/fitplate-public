# Advanced estimation methods

## Cooking

Enable Calculate from weighed ingredients under Preparation & options. Enter the complete batch including oil, ingredient weights in the exact state named by each selected source, edible fractions and finished cooked batch weight. The main Portion field is the cooked amount eaten in grams. Nutrients are summed over edible ingredients and multiplied by eaten weight / finished batch weight. Ingredient-equivalent grams are accounting inputs, not physical cooked ingredient weights.

Optional nutrient-specific retention factors require an HTTPS evidence reference. References are recorded but not independently verified. Factors are rejected for already-cooked source entries to prevent double application. Unspecified retention remains 1 as an accounting assumption; this does not prove no loss. USDA Release 6 primarily covers vitamins, minerals and alcohol, and is not used to invent factors for the four tracked energy/macronutrient values. Discarded fat/liquid and hidden ingredients require appropriate additional data.

- FAO: https://www.fao.org/4/y4705e/y4705e23.htm
- Retention scope: https://www.ars.usda.gov/ARSUserFiles/80400525/Data/retn/retn06.pdf

## Sampling

Run sampling analysis generates 256, 512 or 1024 reproducible scenarios. Unweighed portions use Latin-hypercube uniform multipliers 0.65–1.40; unknown retained oil uses 0.4–1.8. Unweighed recipe shares use Dirichlet draws with concentration 100, preserving whole-dish mass. Fully weighed recipes are not randomly changed.

Per-nutrient p05/median/p95 are simulated scenario percentiles, not calibrated confidence intervals. Squared-correlation screening ranks input variables against nutrient outputs; scores are not causal effects or additive variance contributions. Distributions are engineering assumptions. Food identity errors and unknown ingredients are not fully represented.

Seed, source-table hash, input fingerprint, assumptions, summaries and screening scores are stored only with Save meal. Editing inputs invalidates the displayed sampled result. Sampling and reruns make no API calls.

## Images and depth

After sending a photo, open Photo regions & depth. Decompose photo returns visible food names, normalised bounding boxes and uncertain preparation notes, without nutrients or measured grams. It makes one multimodal request with at most one correction; users review the overlay.

The local Depth Anything V2 Small model outputs relative inverse depth, not metric distance. Its pinned revision is 5426e4f0f36572d16453bbda7a8389317b1bef99, under Apache-2.0. First setup downloads approximately 100 MB of model weights; later CPU inference is local and offline.

Volume requires a reviewed food rectangle inside a flat reference rectangle, known reference width, supplied peak food height, supplied bulk density and a near-overhead view. Relative depth above the median exposed reference surface is mapped linearly to the supplied height, clipped, integrated using planar pixel scale, then multiplied by supplied density. This is a height-anchored relative-depth proxy, not calibrated metric depth. Boxes can include other foods/background. Occlusion, nonuniform density and slanted planes cause errors. Geometry weight cannot override supplied gram weights. Calibration changes require recalculation.

Explicit buttons trigger image analysis and depth inference. Reviewed geometry provenance is saved with the chosen draft item; session images and depth arrays are not saved as meal records. Manual model setup: `python -m fitplate.install_depth`.

- Model: https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf
- Smoke-test image: https://github.com/google-research-datasets/Nutrition5k (CC BY 4.0), cropped overhead panel from res/plate_1.jpg, excluding the annotated nutrient and supplied depth panels. This test demonstrates execution, not food-mass accuracy.
