# Recipe latency: implemented path and next architecture

## Bounded final-review window

The ordinary model deadline is 45 seconds by default, with a 30-second cap per model call.
Once fallback generation has produced candidates, final verification may use a window of up to
`RECIPE_FINAL_REVIEW_SECONDS` (default 20), bounded by the original deadline plus that setting.
The absolute model-work deadline is therefore 65 seconds
by default, not an end-to-end SLA. Repeated reviews cannot keep extending this limit. No extra window
is granted outside the request lifecycle, and ordinary generation/retrieval deadlines are unchanged.
Set the value to zero to disable the extension. This trades a bounded longer wait for fewer discarded
generated candidates; it is not a latency reduction or a reason to serve unverified output.

## Compact semantic interpretation

`RECIPE_COMPACT_INTENT=true` separates request extraction from recipe validation for all model-interpreted
requests. The baseline standalone prompt shrank from 31,856 to approximately 6,200 characters (about 80%).
It still describes every supported requirement and preserves unsupported concepts in residual criteria.
Detailed cooking, symptom, food-safety and nutrition rules remain in generation and verification.
Context-dependent requests still include scoped conversation/reference data and context-resolution rules.
The legacy prompt is available through `RECIPE_COMPACT_INTENT=false`.

Model-call telemetry records stage, elapsed time and input/output character counts, not prompt or response
text. Character reduction is not a latency SLA, and mocked regression tests cannot establish live semantic
accuracy. Validate unfamiliar paraphrases, combined restrictions and follow-ups with live provider calls
before claiming a production speedup.

Design reference: [OpenAI latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization).

Small live synthetic audit: three legacy intent calls took 6.54, 6.10 and 3.44 seconds; the initial compact
version took 2.60, 3.25 and 2.47 seconds. Inspection found a missing regional preference, so the compact
schema was clarified. Two final compact checks took 3.75 and 3.58 seconds: one retained meat-free,
peanut exclusion and a 20-minute limit; the other retained Chicago-inspired cuisine and supper.
Diet/meal vocabulary is not always canonical (e.g. meat-free and supper), so unsupported local values
still require semantic review. These are a small intent-only sample, not end-to-end or p95 results.

## Shared semantic candidate-fit round

Complete structured recipe-search intents now use one bounded review round over the top four
retrieved candidates. The existing requirement-evidence contract handles both hard constraints
and relevance; this is not a vector-similarity percentage. Every required check must pass.
Missing, unknown, malformed, or conflicting assessments are not accepted.

The shared round uses `RECIPE_CATALOG_REVIEW_SECONDS` (default 12 seconds), capped by the remaining request deadline.
It does not repair missing assessments through extra model calls, retry malformed output per
candidate, or scan another database batch after failure. The outer request deadline is restored
before bounded generation, whose safety checks remain in place. Partial accepted results can
be supplemented once; completion failure retains already accepted recipes.

This replaces the cuisine-substring absence shortcut: cuisine, ingredients, and other semantic
requirements use the same assessment contract. Existing budget/adaptation and explicit-generation
paths are preserved; incomplete intent stays on the defensive legacy path. This is not a promise
that generation will finish within the remaining deadline. Live latency and output-quality
evaluation are still required.

## Runtime evidence matching (no new precomputed catalog)

`RECIPE_RUNTIME_EVIDENCE=true` enables runtime matching against the current CSV records.
Intent output is compact JSON; omitted fields are restored locally. The interpretation includes
`requirement_coverage` to state whether all requirements are represented and whether they belong to
the latest independent request or the active conversation. A complete new-request interpretation
does not need a second intent call; incomplete context resolution retains the defensive fallback.

Only fully supported structured requests can pass locally: source-listed total time, source meal/diet
categories with ingredient screening, and required ingredients. Additional semantic requirements,
symptoms, allergies, cuisine, requested yield, budgets, or adaptation needs retain review. Missing
evidence is unknown, never pass. This is bounded evidence support, not a universal clinical validator.
All accepted source recipes still run final deterministic and configured guideline checks.

For supported requests the current records are inspected in memory; no embeddings or snapshot build
is needed. If no recipe has complete matching evidence, routing goes directly to bounded verified
generation rather than remote reviews of speculative catalog candidates. Existing source and AI
labels remain unchanged. Partial source matches remain usable without mandatory generation latency.

Per-recipe model assessments now survive batch regrouping. Keys include recipe content, requirements,
model settings, verification/guideline contracts, policy data, and service-code fingerprint. Retrieval
phrasing and scheduling metadata do not invalidate the same assessment. Complete negative assessments
can also be reused; errors and unknown checks are not cached as definitive assessments. Cached passes
are rechecked locally against current policy. The TTL/capacity-limited cache remains process-local;
it does not persist participant data to disk. Set `RECIPE_RUNTIME_EVIDENCE=false` to disable new local
acceptance/routing while retaining model-based verification.

Regression tests cover live CSV lunch/time matching, unresolved requirements, changed policies and
recipe content, batch regrouping, context isolation, and early verified-generation routing. These are
offline tests, not an Azure or live-provider latency benchmark. Remote generation and unresolved
semantic review remain provider-dependent; no millisecond end-to-end promise is made.

## Implemented

Retrieval still uses semantic embeddings. Local ranking replaces the optional LLM reranking call by default. Dinner/lunch requests prioritize main-dish categories over explicitly labeled snacks and sides. Unknown categories remain available, and ties retain retrieval order. Time filtering rejects established conflicts without treating unknown timings as passes. All returned candidates still pass the existing verification pipeline.

Verification assessment cache keys ignore scheduling and retrieval-only metadata. Recipe content, actual request context, model configuration, and prompt rules still affect cache identity. Deterministic and guideline checks execute again on cache hits. This is a process-local exact assessment cache, not a persistent prevalidated catalog.

## Implemented catalog fast path

A separate, read-only catalog now supports an intentionally narrow full-match grammar: `Show recipes that take 30 minutes or less for dinner`, with numeric minute limits, inclusive/exclusive boundaries, and optional lunch/breakfast/dinner. `Give me`, `please`, and `meals` variants are also supported. Additional words, allergies, symptoms, ingredients, budgets, or follow-up references do not enter this path. Conversation scoping runs first; only independent requests use local intent parsing.

For a matching generic profile, the runtime reconstructs recipes from the current database, checks content hashes, expiry and validation/model versions, and reruns the existing deterministic verification finalizer and guideline checks. At least three distinct passing recipes are required to bypass retrieval and live verification. The existing timed-response formatter needs no summary-model call. Optional enhancement must remain disabled for this route.

Missing, malformed, changed, expired, or insufficient profiles fall back to the existing pipeline. Timed cold requests use one bounded verification queue rather than waiting for the first three to finish before scheduling the remaining five. If an exact simple timed request yields one or two matches, one bounded generation attempt can fill the remaining slots; generated additions still require verification. This cold top-up can take additional time and does not guarantee three passes.

Build a catalog deliberately, outside user requests, from the backend directory:

```sh
.venv/bin/python -m app.build_verified_catalog \
  --query 'Show recipes that take 30 minutes or less for dinner' \
  --target 6 --max-candidates 36 --allow-model-calls
```

This uses the configured API key and incurs model charges. Candidate assessments may require provider retries. The builder does not create embeddings and does not read participant chats. Repeat `--query` to publish multiple profiles together. A build replaces the previous snapshot atomically only if every requested profile has at least three verified matches. The catalog stores public recipe evidence and hashes, not participant prompts.

`RECIPE_VERIFIED_CATALOG_PATH` defaults to `app/data/verified_catalog.json` under the backend directory. `RECIPE_VERIFIED_CATALOG_TTL_SECONDS` defaults to seven days. The generated artifact is gitignored: a remote Git-based deployment will NOT receive a locally generated snapshot automatically. Build or deliver it in the deployment pipeline for the exact deployed service code and model settings; local Docker builds include it when present in the build context. Rebuild after service-code, model, or relevant recipe changes, and before expiry. Treat the snapshot as a trusted deployment artifact with operator-only write access, not as a user-uploadable file.

## Next phase: broader evidence coverage

### Composed-dinner generation route

**Current default:** Eligible composed-dinner and new budget-generation paths request recipes without model self-assessments. The generation prompt retains nutrition guidance and request constraints. Local checks reject concrete violations, and budget recipes still require ingredient-level pricing within the ceiling. These checks are not independent AI review or proof of semantic or clinical compliance. Catalog and repair paths retain their existing review behavior. Set `RECIPE_SINGLE_PASS_DINNER=false` to restore separate model review for composed dinners.

Single-pass live audit of the reported Chinese Thanksgiving dinner request: three six-serving recipes returned in 21.36 seconds, with one model call and zero retrieval calls. The audit blocked a second model call and disabled transport retries. This is one local provider-backed observation, not a guarantee for other prompts or Azure; output generation still dominates latency. The earlier multi-call audit below is retained for comparison and describes the rollback mode, not the current default.

New requests to prepare/plan a dinner or menu for an explicit party size, with plural recipes or an occasion, can now select generation first. This is a request-shape routing decision, not a claim that the database contains no related recipes. The inexpensive router excludes explicit catalog/source searches, budgets, singular-recipe requests, and reference-like wording. Conversation scoping, safety/privacy handling and named-recipe resolution precede this decision. Existing discovery, budget and adaptation routes remain available.

The route combines intent interpretation and three-recipe generation in one model call, using the configured nutrition/food-safety policy and a larger output allowance to avoid truncating three complete recipes. The actual user request remains part of verification. Three independent recipe checks run with existing bounded concurrency; party-size checks require both the declared integer yield and evidence that quantities support that yield. Failed checks cannot be overridden to reach a count of three.

The system retains passing recipes and permits only one completion attempt for missing slots, rather than entering the six-attempt general fallback ladder. A local formatter then describes the checked recipes without another model call. Every generated card remains AI Generated, not source-certified. The common successful route therefore needs one generation call plus three verification calls, with no database retrieval and no summary-model call. Malformed outputs or failed checks can still take longer or produce fewer than three verified recipes. Provider latency means new generation is not a millisecond operation.

Changing these service files invalidates older prevalidated catalog snapshots by design. Rebuild those artifacts before relying on the catalog fast path after deployment.

Live audit of the reported six-person, predominantly Chinese Thanksgiving request: the final run returned three AI-generated recipes with six servings each, zero retrieval calls and six model calls in 36.82 seconds. It required one completion attempt. This is a single local provider-backed measurement, not an Azure SLA or an ultra-low-latency result. Initial combined generation consumed about 18 seconds; verification and completion consumed the remainder. The router eliminates the database rejection cascade but does not eliminate inference latency or occasional semantic-verifier overrestriction. Do not describe this route as millisecond generation or treat automated assessments as clinical/source-organization certification.

The generic timed-profile implementation is not a universal recipe router. Broader coverage still requires reusable fact-level evidence rather than building one profile for every possible combination:

1. Normalize complete source recipes and retain ingredient, direction, serving, and source evidence.
2. Produce evidence-backed assessments for total elapsed time, equipment, preparation requirements, ingredient forms, and meal role. Record unknown or conflicting facts explicitly. Do not infer total time from cooking time alone.
3. Bind every assessment to a content hash, extraction/schema version, validation-policy version, and model version. Invalidate on any relevant change. Audit assessments before promoting a catalog snapshot.
4. Publish snapshots atomically. Persist only public recipe evidence, not participant prompts or medical information. A missing, stale, or incompatible snapshot must fall back to the current checked path.

The fast request route may use catalog evidence only when every active requirement is covered by valid assessments and deterministic checks. Ambiguous conversation references, unsupported constraints, patient-specific requirements, and conflicting evidence require semantic review. Source organization and main-dish labels alone never authorize acceptance.

Changed or generated recipes require fresh verification. Budget requests also require current price coverage, quantities, and serving calculations. A recipe used as a grounding reference does not transfer its source endorsement to generated content.

## Rollout gates

Run the proposed fast route in shadow mode against the existing verifier first. Compare constraint compliance, meal relevance, provenance, fallback behavior, and follow-up isolation. Measure cold and warm p50/p95 latency, time to first verified card, model calls, cache hits, and rejection reasons across the regression prompt set. Enable only supported request classes behind a rollback flag after reviewing disagreements.

Sub-millisecond remote generation is not a realistic acceptance criterion. A sub-second supported-catalog path is a benchmark target, not an implemented or measured guarantee. New generation remains dependent on provider latency and verification. Stream progress promptly, but never present unverified cards as finished results.
