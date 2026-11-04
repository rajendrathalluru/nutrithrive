# Dynamic ingredient pricing

Recipes are selected for the request, not restricted to the local price catalog. The pipeline remains database → database-guided generation → AI-only generation. Prepared candidates receive missing-price lookup before existing independent verification and deterministic budget arithmetic. All dietary, allergy, symptom, time, equipment, required-food, portion and food-safety checks still apply. A price match is not nutritional approval.

## Web search: specific product listings, not averages

The default provider is now `web_search`. It uses the existing server-side `OPENAI_API_KEY` with a separately configurable search model; the recipe-generation model stays unchanged:

```dotenv
BUDGET_PRICE_PROVIDER=web_search
BUDGET_WEB_SEARCH_MODEL=gpt-5.4-mini
```

This uses [OpenAI Responses web search](https://developers.openai.com/api/docs/guides/tools-web-search), not direct Walmart scraping or model memory. Search is required and limited to Walmart, Target and Kroger, with Walmart preferred in the instructions. Only ingredient names/forms/units are sent, not chat history, diagnoses or patient profiles. `store` is false; that is not a blanket zero-retention guarantee. API/model/search access and billing must be available for the configured OpenAI project. An explicit existing provider setting overrides the default; change it to `web_search` to use this path.

For each ingredient, the model must extract **one specific retailer-sold product's unconditional package price**, package size, and short supporting listing excerpt. No averaging, invented prices, unit-price/package-price confusion, conditional discounts or third-party marketplace sellers are allowed. The backend requires a completed search, an allowed retailer evidence URL present in the tool's returned source list, matching name/unit, explicit form confirmation and internally consistent size/price evidence. Product-detail URLs are preferred. A Walmart food browse listing is also supported when the excerpt contains the complete specific product name, package size and price together; category-wide ranges and generic search URLs are not accepted, and a product-detail URL must never be invented. Backend Decimal arithmetic performs unit conversions and cost calculation; the model does not calculate the total. Variant query parameters are retained when matching sources.

These are **web-listed reference estimates**, not authenticated live checkout quotes. A retrieved source URL and consistent model-extracted excerpt do not independently prove the price is current or the extraction is correct. The application does not bypass CAPTCHA or blocked pages. Missing or ambiguous evidence remains unknown. Cards link the product and label the date as **Retrieved**, not a verified price-update date. Citation text is treated as untrusted data.

At most two additional Responses calls per budget request, each with up to six ingredient lookups and three hosted search tool calls; connect/read timeouts are 3/25 seconds and there is no automatic HTTP retry. Database retrieval can use at most one call, reserving capacity for generation or repair. Cache-only passes do not spend this allowance, and cached/negative-cache keys do not occupy batch slots. Missing ingredients are searched without also refreshing known prices; a second call is never used solely for reference refresh. Cache entries expire after 24 hours (missing results after 60 seconds). Cold web lookups add cost and latency; these limits are not an end-to-end SLA. Successful lookup replaces the corresponding cached reference for calculations; unavailable lookup can fall back to a still-valid, clearly dated local reference. Nothing is permanently written to the CSV/catalog, and non-budget requests do not use web pricing.

Each generation/repair attempt receives updated cached price references, not only the initial seed catalog. Hints are capped at 64 items (baseline references plus recently added items) to bound prompt growth; the full catalog and dynamic lookup still price foods outside those hints. Failure details survive the structured fallback and the transition from database-guided to AI-only generation. The generation contract requires explicit weights for solids and volumes for liquids, with quantified seasonings; cup-to-weight guesses and unmeasured extras remain unpriceable. Independent recipe verification reviews ingredients, instructions, portions, cuisine and patient requirements, plus available priced-product descriptions for food-form conflicts. It does not receive monetary failure details that could be mistaken for missing recipe ingredients. The backend still recalculates every ingredient cost and rejects unknown/over-budget totals after semantic verification. Price-only changes do not require repeating an unchanged semantic review.

Development checks on November 4, 2026: a direct Walmart request redirected to `/blocked` and was not bypassed. Two synthetic OpenAI web searches completed in approximately five seconds each. The inspected response returned a Target dry-lentil product; the parser's spacing fix (`1LB` versus `1 lb`) was checked by replaying that captured response. This is not a production latency benchmark, coverage guarantee, or deployed end-to-end validation. Unit tests exercise URL/citation rejection, forms, package sizes, no averaging, caching, arithmetic, and UI labels.

## Optional direct retailer API

The optional direct API adapter supports **Kroger**, separately from the default web-search provider. It uses the retailer's [Products API](https://developer.kroger.com/documentation/api-products/public/products/product-search) and [service-to-service OAuth](https://developer.kroger.com/documentation/public/security/service-to-service). Register an application with product read access in [Kroger Developers](https://developer.kroger.com/), review the applicable terms, and configure backend-only settings in Azure or the backend `.env`:

```dotenv
BUDGET_PRICE_PROVIDER=kroger
KROGER_CLIENT_ID=
KROGER_CLIENT_SECRET=
KROGER_LOCATION_ID=
```

Fill the values privately; never commit credentials, put them in frontend variables, or paste them into chat. Use a real eight-digit reference-store ID from Kroger's Locations API; do not invent one. Restart/redeploy after configuration changes. An unconfigured adapter makes no external requests. Reference-store pricing is not the participant's local quote. Product availability is not guaranteed by the API search response.

The adapter reads regular prices, not conditional promotion/loyalty discounts. It accepts exact normalized product descriptions after removing the supplied brand prefix, explicit package sizes and `soldBy: Unit`. Weight-priced items, ambiguous multipacks, missing prices, unmatched descriptions and mass/volume conversions are rejected. Generic names and qualified product descriptions may not match: **this is intentionally conservative and does not promise coverage of every ingredient**. It does not infer low sodium, pasteurization, gluten-free status or raw/cooked equivalence. The candidate recipe itself must still pass patient-specific checks.

No retailer credentials were supplied during development. HTTP behavior is covered with synthetic fixtures; a credentialed smoke test in the target environment is required before enabling this for participants. Do not describe mock tests as live retailer validation.

## Other retailers or approved price feeds

A vetted backend price service can integrate Walmart, Target or other authorized retailer feeds. This optional adapter expects the following contract; **an ordinary retailer web URL is not this API**. Supply real sourced product data, not LLM estimates or search-result snippets.

```dotenv
BUDGET_PRICE_PROVIDER=quotes
BUDGET_PRICE_API_URL=https://YOUR-TRUSTED-SERVICE/ingredient-quotes
BUDGET_PRICE_API_TOKEN=
BUDGET_PRICE_SOURCE_HOSTS=www.walmart.com,www.target.com
```

The endpoint is administrator-configured HTTPS. Optional bearer authentication stays server-side. Redirects are disabled. The request contains only ingredient names/forms and units—not prompts, chat history, patient requirements or identities:

```json
{"currency":"USD","ingredients":[{"name":"raw salmon","unit":"g"}]}
```

Example **synthetic response**, not a real retail quote:

```json
{"quotes":[{
  "name":"raw salmon","unit":"g","currency":"USD",
  "exact_form_match":true,
  "package_quantity":"500","package_price":"8.00",
  "product":"Example raw salmon, 500 g",
  "source_url":"https://www.walmart.com/ip/REPLACE-WITH-REAL-PRODUCT-ID",
  "observed_on":"2026-11-04",
  "region":"Actual reference store or retail region"
}]}
```

Names and units must match a requested key exactly. The service is responsible for verifying food identity/form and returning a regular purchasable package price, source product, observation date and region. Unknown/ambiguous matches should be omitted. The backend rejects absent form confirmation, unrequested keys, duplicate valid quotes, invalid numbers, unsupported currencies, non-allowlisted source hosts, future dates and quotes older than seven days. It never fetches the returned product URL. Metadata checks cannot independently prove that a provider's reported price or form assertion is truthful: configure only a reviewed provider.

## Direct API/quote-service limits

- Lookup occurs only for missing prices on prepared budget candidates, not during full-database scans or non-budget requests.
- At most two lookup batches per application request. Kroger searches up to six missing ingredients per batch with three workers; the quote service accepts up to 24. No model-based price estimation or extra mandatory model call is added.
- Connection/read timeouts are 2/4 seconds, response bodies are bounded, and there are no automatic HTTP retries. These are I/O limits, not a hard end-to-end SLA; cold lookups add latency.
- Process-local quote cache: at most 512 entries, positive quotes up to 24 hours, failed/missing lookups 60 seconds. Quotes remain subject to observation-date validation. Restart clears this cache. Cached prices must not be labeled live.
- Local reviewed references are used first. Their refresh policy remains separate from the API cache; a provider does not refresh all catalog prices on every request.
- Prices and final totals are recalculated after changes. Source product, date and region appear in cost details. Missing evidence remains uncertain; it is never silently treated as free or replaced with a different required food.
- Explicitly owned quantities can cover an additional-shopping requirement even without a purchase price. The card shows unknown consumed value, zero additional purchase, and no fabricated source. Whole-recipe/per-serving valuation still requires prices for owned food. Insufficient or unquantified pantry supply does not get this credit.

## Nutrition policy

Budget generation and verification share contextual application guidance informed by [AICR during-treatment guidance](https://www.aicr.org/cancer-survival/treatment-tips/during-treatment/) and the [ACS survivor guideline](https://www.cancer.org/cancer/supportive-care/nutrition-activity-with-cancer/acs-nutrition-and-physical-activity-guideline-for-survivors.html). Application summary reviewed November 4, 2026. Individual needs and care-team restrictions take precedence over generic dietary-pattern goals. This is not a complete machine-readable clinical guideline or AICR/ACS endorsement; research-team clinical review is required before participant deployment.

## Validation

`recipe_rag_backend/tests/test_dynamic_budget_prices.py` exercises off-catalog foods, missing catalogs, whole-recipe versus pantry-shopping accounting, provider failures, cache expiry, source/form validation, bounded lookups and the Kroger adapter without real credentials. `test_web_search_prices.py` exercises the evidence contract, two-call bound, reserved generation capacity, corrected-unit repairs and cache-aware scheduling. Existing budget and general recipe tests remain in place. Frontend tests verify unknown owned-food value and product-specific source metadata.
