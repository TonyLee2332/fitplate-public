# Retrieval, source portions and clarification

Retrieval combines BM25 (k1=1.2, b=0.75), IDF-weighted recipe GloVe cosine similarity, reciprocal-rank fusion (k=60), and explicit food identity / preparation reranking. GloVe vectors are loaded offline from ingredient-parser-nlp 2.10.0. This is a FitPlate implementation of weighted embeddings, not the package's complete uSIF algorithm or a trained cross-encoder. Rankings are not calibrated probabilities. Unknown identity words are not silently discarded to force a match.

Ingredient Parser: https://github.com/strangetom/ingredient-parser (MIT). The installed package supplies its 35-dimensional recipe embeddings; package/model notices apply. The runtime does not download NLTK language resources or call an embedding API.

Source portions are transcribed from USDA SR Legacy 2018 food_portion.csv, limited to retained production food IDs and positive amounts/weights. source_portions.json preserves original portion ID, FDC ID, row, description, amount, gram weight, source URL and file/archive hashes. Selecting a source measure means the count is a count of that selected measure. Average portion weights are estimates. Cups are not silently reinterpreted as bowls, and no slice weights are inferred from cup weights. Source measures take precedence over app/AI count estimates; confirmed grams take precedence over source measures.

Questions are ordered by counterfactual scenario impact: the maximum of energy spread, 4 times protein/carbohydrate spread and 9 times fat spread. Explicit whole/slice alternatives are included. Unresolved questions use labelled fallback priorities. This is a deterministic sensitivity heuristic, not a learned information-gain policy or statistical confidence score. At most two questions are shown; known details and explicit typical-estimate choices are respected.

Method references:
- https://ingredient-parser.readthedocs.io/en/stable/explanation/foundation.html
- https://fdc.nal.usda.gov/docs/Download_Field_Descriptions_Oct2020.pdf
- https://sls.csail.mit.edu/archives/root/publications/2019/Korpusik_IEEE_August2019.pdf
