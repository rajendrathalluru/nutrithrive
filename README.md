# NutriThrive Research

NutriThrive Research is a full-stack AI nutrition assistant focused on diet-based recipe discovery. Users chat in natural language, the backend interprets the request, searches a curated recipe dataset, applies nutrition and safety logic, and returns recipe-oriented responses with follow-up awareness.

## What the project does

- Accepts diet and recipe questions in a chat interface
- Handles follow-up prompts within the same conversation
- Filters or redirects small-talk and privacy-sensitive prompts
- Retrieves relevant recipes from a structured dataset
- Applies nutrition-oriented validation and response formatting
- Returns recipe suggestions, tips, and generated guidance

## Architecture

```text
React frontend -> FastAPI API -> intent and safety checks -> recipe retrieval -> nutrition filtering -> formatted response
```

Recipe selection follows three stages:

1. Return database recipes that pass semantic relevance, user constraints, and nutrition checks. Cuisine and meal type are evaluated by meaning; an entree need not literally contain the word “dinner.” If initial retrieval has no qualifying results, rank additional CSV records by query terms and verify a bounded candidate batch before generating.
2. If no database recipe qualifies but useful related recipes exist, supply their ingredients, instructions, and source references to the model as context for a new recipe.
3. If no useful database context is found, generate from the request and configured guidelines alone.

Both generation routes are labeled **AI Generated** and are verified before serving. Generated records include `generation_basis` (`database_guided` or `ai_only`) and `reference_sources` for supplied database context; reference organizations are not represented as authors of generated recipes. Failed generation attempts retain the same context. Responses contain at most three recipes, and follow-up requests exclude previously shown recipes.

Verification uses an evidence contract rather than an LLM-generated aggregate pass/fail flag. The backend enumerates active constraints, preferences, and additional match criteria; the verifier must return a `pass`, `fail`, or `unknown` assessment with evidence for every key. Missing checks, unknown results, violations, or nonmatching relevance prevent acceptance. The backend derives the final verdict and then applies independent ingredient-form and nutrition checks. Verification batches contain at most three recipes to bound response size; all candidates are still evaluated.

Each self-contained request starts independently, even within the same chat. Earlier time limits, ingredient lists, dietary preferences, and preparation restrictions are not inherited. Explicit follow-ups such as “more recipes,” “Italian instead,” and “use those ingredients” retain the active task's requirements. Request boundaries are applied before intent extraction, retrieval, exclusion of previously shown recipes, and verification—not just to the response wording. Common standalone requests are recognized locally; other new topics can be identified semantically and re-analyzed without history. The client carries `context_action` markers so later follow-ups do not revive an older task. Older clients still receive local boundary detection for common request forms.

Contextual requests retain the actual ordered user turns from the active task in `user_request_context`, separate from the model's rewritten request. Verification, generation, and summaries receive this context so earlier goals remain visible even if the rewrite omits them. Later changes take precedence within that task. A direct request “with barley, tofu and spinach” makes each named ingredient mandatory and requires an individual verification check; this differs from choosing among an explicitly offered pool of alternatives.

Required ingredient names are also checked against the actual ingredient list independently of the model's verdict. Titles, descriptions, and suggested additions cannot supply a missing ingredient. The bounded matcher handles word boundaries, common inflections and a small set of aliases; it is not a comprehensive food ontology. A partial match can guide an AI adaptation, but is not served as an exact database match. Recipe generation order and source labels are unchanged.

Appliance requests distinguish required use (`equipment_required`) from exclusive equipment (`equipment_only`). Each required appliance receives its own verification check. A bounded instruction audit for common cooking appliances also rejects title-only claims, optional tips, and preheating without actual food preparation; unfamiliar equipment still relies on semantic verification. Retrieval includes appliance terms, and CSV rescue prioritizes recipes with preparation evidence. An air-fryer side dish is not automatically a requested meal: meal suitability remains a separate check. Method conversions follow the existing database-guided/AI fallback and AI Generated labeling rather than silently changing source recipes.

Upset-stomach/nausea food requests activate `digestive_comfort="gentle"`, grounded in actual user turns rather than assistant descriptions. This is a conservative food-selection preference, not a diagnosis or medical clearance. Shared generation/verification rules assess seasoning, preparation and individual-tolerance uncertainty; a bounded independent audit catches common hot seasonings and deep-frying even when the model falsely approves them. Among otherwise verified matches, selection prefers the fewest known higher-fiber/gas-forming ingredient cautions rather than padding to three. This relative preference is not an absolute ban or proof of tolerance; it does not universally prohibit tomatoes, dairy, legumes or all spices. Source recipes requiring changes remain adaptation references. Summaries acknowledge variable tolerance and advise contacting the care team for severe/persistent symptoms or inability to keep fluids down. The rule basis is [MedlinePlus nausea/vomiting guidance](https://medlineplus.gov/nauseaandvomiting.html) and [NCI easy-to-digest food guidance](https://www.cancer.gov/about-cancer/treatment/side-effects/nutrition/easy-to-digest); clinical review remains necessary for research deployment.

For digestive-comfort and low-exertion searches, verified recipes bypass optional generic enhancement so later protein/fiber tips cannot dilute the request. Missing core recipes and requested adaptations still use the existing generation/verification pipeline. Fallback generation produces one complete candidate at a time for these requests, within the existing retry limits; it does not weaken acceptance checks or manufacture three matches.

Cooking with body weakness/fatigue activates `preparation_effort="low"`, distinct from low hand strength, seated preparation, short total time and no heat. Verification includes preparation hidden in ingredient lines, sustained manual work and heavy cookware transfers. The bounded audit identifies three or more unaccounted ingredient-preparation tasks; it is a conservative workload heuristic, not a clinical accessibility threshold. Purchased pre-cut forms, brief heating and passive waiting are not automatically rejected. General “easy recipes” requests do not acquire this restriction. Both preferences persist through explicit follow-ups and clear for independent requests or explicit withdrawals. The skillet, soup and salad examples are regression fixtures; recipe discovery and database → database-guided AI → AI-only ordering remain unchanged. See [Macmillan's practical eating guidance](https://www.macmillan.org.uk/cancer-information-and-support/impacts-of-cancer/eating-problems/tips-for-managing-eating-problems) for prepared-food options when too tired to cook; the application does not infer cancer or a cause of weakness.

When a generated candidate fails, the existing bounded retry repairs one concrete candidate using its full ingredients, instructions, and rejection details instead of asking for another generic batch. It preserves the request and provenance, updates affected cooking steps, and passes through the same independent verification. Invalid output is never returned just to avoid an empty result.

For “more recipes,” intent is rebuilt from user requests within the active task rather than the assistant's recipe descriptions or nutrition claims. Names already shown in that task are excluded before the CSV candidate limit and before accepting AI output, so repeated generations trigger the existing bounded retry instead of an empty response. Intent prompts specify the full JSON structure, including flavor preferences and explicit user constraints.

Conversation context belongs to the active chat. Requests carry that chat's user turns and structured recipe references; the backend does not share conversation memory between chats. Within the active task, intent resolution retains earlier user requirements, applies later changes, and produces a standalone request for retrieval and verification. References such as “the second one” resolve against recipe IDs from that task. Questions about a shown recipe are answered from its details; explicit modifications use the selected recipe as generation context and remain labeled AI Generated (`conversation_guided` for prior AI recipes). Ambiguous references request clarification. Recipe references include ingredient lists, and assistant food lists remain available for follow-ups within their task. Assistant suggestions are reference data, not requirements, unless the user explicitly selects them. Selecting from a list of alternatives uses an ingredient pool (`ingredients_available`), while explicitly required items use `ingredients_must_use`. Selected ingredients and active preparation criteria are included in the resolved search/generation request. Chat history currently lasts for the mounted application session; this does not add persistence across page reloads. Reference extraction remains model-dependent; this is not a guarantee of perfect conversational recall.

Intent processing preserves semantic search expansions (for example, “shelf-stable meals” → canned beans, dried lentils, rice) for vector retrieval and CSV candidate ranking. Pantry-based requests and strictly shelf-stable-only requests are distinguished by `constraints.ingredient_storage`. Shared prompt rules apply across intent analysis, verification, generation, and summaries; pantry ingredients do not imply room-temperature storage of the prepared meal.

Requests for little active attention use `constraints.attention_level="low"`, independently of total cooking time or ingredient storage. Search expands toward baking, roasting, assembly, and slow cooking without requiring a particular appliance. Verification assesses actual instructions, not titles alone: lengthy passive cooking can qualify, while continuous stirring does not. Pantry requests do not acquire this constraint merely because an example in a prompt mentions it.

Pantry-based recipes must be achievable without required fresh or refrigerated purchases; fresh garnishes must be explicitly optional. Pantry verification requires a structured assessment of required non-pantry ingredients, unspecified ingredient forms, and conflicting guidance. Missing or adverse assessments fail verification. Generated tips and adaptations trigger final verification; rejected generated guidance may be removed once, followed by another full check. Core ingredient failures remain rejected, and failed generation assessments are passed to the retry.

Both batch and individual verification also audit ingredient lines independently of the model. This bounded check catches known fresh/refrigerated ingredients and ambiguous forms such as unspecified corn or broth, even when the model reports an empty error list. Explicit pantry forms (for example, canned carrots or garlic powder) remain eligible. Conflicts retain exact ingredient lines for the existing correction retry; otherwise relevant recipes remain available as adaptation references, not direct matches. This is a supplemental guard, not a complete food-storage classifier: unfamiliar ingredients and narrative guidance still require semantic verification.

If final validation removes every selected recipe, unused verified database matches are tried first. If none remain, one additional generation attempt receives the final rejection feedback and relevant recipe references, then undergoes the same verification and follow-up exclusion checks. This bounded recovery does not add another round of optional tips. Initial-request failures and exhausted follow-ups have distinct messages.

Low-chewing requests use `constraints.chewing_effort="low"`, separate from preparation effort, digestion, and swallowing conditions. Explicit wording is retained even when the intent model omits it, and search expands toward soft, moist, mashed, and pureed preparations. Conversation resolution preserves the requirement for follow-ups and allows the user to withdraw it.

Both database and generated recipes must supply a `chewing_check` covering every ingredient with pass/fail/unknown judgments and exact citations to ingredient or instruction entries. The backend checks coverage, citation validity, finished-preparation evidence, and conflicting guidance. Supplemental deterministic checks reject common unsupported firm components; they are bounded checks, not a complete texture classifier. Descriptions and titles alone cannot establish softness. Texture assessments use one-recipe batches, with at most three in flight and input order preserved, to limit structured output under the existing model token budget; ordinary verification batching is unchanged.

Database recipes needing texture changes remain adaptation references rather than direct matches. The existing database-first, database-guided generation, and AI-only fallback order remains unchanged, as do source labels, the three-recipe cap, and final verification of generated tips. Low-chewing summaries quote verified preparation evidence rather than asking a second model to invent texture claims; requested storage guidance is retained. Offline regressions include the reported muesli, shrimp stir-fry, and roasted-vegetable CSV records, plus suitable soft preparations and both retrieval/generation paths. These tests do not certify medical suitability or prove live-model accuracy.

Chewing preferences are not a swallowing-safety assessment. No IDDSI level or liquid thickness is inferred: [ASHA describes individualized assessment before recommending dysphagia texture modifications](https://www.asha.org/slp/healthcare/dysphagia-diets/). General soft-food context is also available in the [American Cancer Society's eating-problems guidance](https://www.cancer.org/cancer/side-effects/eating-problems/swallowing-problems.html); it is not a substitute for a participant's care-team instructions.

Leftover summaries preserve storage sentence boundaries and remove neighboring non-storage tips. Original source guidance is preferred for unchanged database recipes and supplied to verification before selection; generated recipes retain their own storage instructions. Summaries do not invent durations or cut instructions in the middle of a sentence. Valid one- and two-step database recipes are preserved rather than marked incomplete solely for having fewer than three steps.

“Multiple small servings” and “divide into smaller portions” activate `portion_size="small"` and the existing leftover requirement. Explicit meal requests also carry `meal_suitability="meal"`; the semantic verifier must assess the complete dish rather than count a condiment, snack, or accompaniment as a standalone meal. No arbitrary calorie threshold is added, and broad requests for recipes still allow snacks and sides. Shared rules apply in intent analysis, verification, generation, and repair.

Run offline backend regression tests from the repository root:

```bash
PYTHONPATH=recipe_rag_backend recipe_rag_backend/.venv/bin/python -m unittest discover -s recipe_rag_backend/tests -v
```

## Repository structure

```text
nutrithrive-research/
├── public/                       # Frontend static files
├── src/                          # Frontend application
├── recipe_rag_backend/
│   ├── app/
│   │   ├── core/                 # Environment and config handling
│   │   ├── data/                 # Recipe CSV dataset
│   │   ├── models/               # API schemas
│   │   ├── services/             # Retrieval, filtering, adaptation, scoring
│   │   └── main.py               # FastAPI app and API routes
│   ├── requirements.txt
│   └── .env.example
├── Dockerfile                    # Single-service production container
├── docker-compose.yml            # Single-service local container run
├── render.yaml                   # Single Render web service blueprint
├── .env.example                  # Frontend example env file
└── README.md
```

## Tech stack

- Frontend: React, TypeScript, Tailwind CSS, assistant-ui chat primitives
- Backend: FastAPI, Uvicorn, LangChain, OpenAI, FAISS, Pandas, Pydantic
- Deployment: Docker, Docker Compose, Render

## Homepage UI

The homepage uses a scoped warm-neutral and sage design in `LandingPage.tsx` and `LandingPage.css`, with responsive navigation, keyboard-accessible controls, recipe prompt examples, source-label explanations, and native FAQ disclosures. Every start-chat button uses the existing `onGetStarted` callback; the examples do not send requests or change conversation state. This presentation-only redesign does not modify recipe retrieval, chat, voice input, health polling, or routing.

The decorative meal image is bundled locally rather than fetched from an external image host, and is clearly labeled AI-created rather than represented as a database recipe. Its generation prompt and provenance are documented in `src/assets/images/home-meal.README.md`. The homepage no longer imports the old WebGL background or GSAP navigation. Unsubstantiated ratings, patient testimonials, verification claims, and placeholder links are not displayed.

## Chat UI

Browser tabs and home-screen shortcuts use the Thrivewell leaf from `public/thrivewell-icon.svg`, matching the homepage's leaf symbol. `favicon.ico`, `logo192.png`, and `logo512.png` are raster exports of this SVG; regenerate those together when changing the symbol. The manifest uses the Thrivewell name and sage/ivory colors. Versioned icon URLs replace previously cached React icons.

The landing page lives at `/` and the chat at `/chat`. Navigation updates browser history, so opening or refreshing `/chat` stays on the chat page, and browser Back/Forward follows the current URL. FastAPI's existing frontend fallback serves the React app for this route. This preserves the page, not the conversation: messages remain in memory and are reset by a full reload; no browser or server-side conversation storage is added.

The chat page uses [assistant-ui's external-store runtime](https://www.assistant-ui.com/docs/runtimes/custom/external-store) for message rendering and scroll behavior. `NutriThriveChatbot` still owns chat state, health polling, and request handling; `BackendService` and `buildConversationHistory` remain the only recipe-request path. `AssistantChatThread` is the presentation adapter and renders the original messages, including structured recipe data and safety responses, without changing their contents.

The existing voice-enabled `ChatInput` is retained. Conversation starters only fill the draft; they do not submit requests. Source links, AI labels, ingredient groups, tips, and recipe expansion remain in `RecipeCard`. Search Analysis is available in an expandable disclosure. Styles are scoped to `.thrive-chat` and do not change the landing page.

On narrow screens, `useChatViewport` sizes the chat to the [visual viewport](https://developer.mozilla.org/en-US/docs/Web/API/VisualViewport), including changes from browser controls and the on-screen keyboard. The page-level scroll lock applies only while the mobile chat is mounted; messages keep their own scrolling area. Leaving the chat removes the lock and viewport listeners. Pinch zoom is not disabled. The mobile composer starts at 44px, grows for longer drafts, and keeps health, voice, and error messages visible while hiding the idle hint.

`@assistant-ui/react` is pinned to `0.10.30` to retain compatibility with this project's TypeScript 4.9 / Create React App toolchain. No assistant-ui cloud service, additional model provider, or persistent conversation storage is configured. Jest transforms the library's ESM dependencies so regression tests exercise the real runtime rather than mocking it.

Run the navigation, chat, and recipe UI regression tests:

```bash
CI=true npm test -- --watchAll=false --runInBand
```

## Environment variables

### Backend

Copy the backend example file:

```bash
cp recipe_rag_backend/.env.example recipe_rag_backend/.env
```

Required:

- `OPENAI_API_KEY`

Recommended:

- `DATA_FILE_PATH`
- `API_HOST`
- `API_PORT`
- `PORT`
- `CORS_ORIGINS`

Example:

```env
OPENAI_API_KEY=your_openai_api_key_here
DATA_FILE_PATH=app/data/Recipe.csv
API_HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:3000,http://localhost:8000
```

### Frontend

Frontend can still use `REACT_APP_BACKEND_URL`, but it is optional now.

- Local split frontend/backend mode: set `REACT_APP_BACKEND_URL=http://localhost:8000`
- Single-service deployed mode: leave it unset and the frontend will call the same origin automatically

## Run locally without Docker

### Backend

```bash
cd /Users/rajendrathalluru/Documents/nutrithrive-research/recipe_rag_backend
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

In a second terminal:

```bash
cd /Users/rajendrathalluru/Documents/nutrithrive-research
npm install
npm start
```

Open:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`

## Run locally with Docker

This now runs as one container and serves both frontend and backend from the same service.

```bash
cd /Users/rajendrathalluru/Documents/nutrithrive-research
docker compose up --build
```

Open:

- App and API: `http://localhost:8000`
- Health check: `http://localhost:8000/health`

## Deploy to Render

This repo is now set up for a true single-service Render deployment.

### Render setup

1. Push the repository to GitHub.
2. In Render, create a new Blueprint or Web Service from the repo.
3. Make sure the root `Dockerfile` is used.
4. Set the required environment variable:
   - `OPENAI_API_KEY`
5. Keep or set the recommended variables:
   - `DATA_FILE_PATH=app/data/Recipe.csv`
   - `API_HOST=0.0.0.0`
   - `PORT=8000`
   - `CORS_ORIGINS=https://your-service-name.onrender.com`

### Why this works

- The Docker build compiles the React frontend
- The same container installs and runs the FastAPI backend
- FastAPI serves the built frontend files
- Browser requests and API requests use the same domain

That means you only need one Render web service.

## Deploy to other platforms

The same root `Dockerfile` can be used on:

- Railway
- Fly.io
- Azure App Service
- AWS App Runner or ECS
- Google Cloud Run
- DigitalOcean App Platform
- Any VM or container host with Docker

For any platform, expose port `8000` and set `OPENAI_API_KEY`.

## Deploy to Azure with GitHub Actions

This repo now includes a GitHub Actions workflow at [.github/workflows/azure-deploy.yml](/Users/rajendrathalluru/Documents/nutrithrive-research/.github/workflows/azure-deploy.yml).

Recommended Azure architecture:

- GitHub repository as source
- GitHub Container Registry to store the built image
- Azure App Service to run the single container
- GitHub Actions to build from the root `Dockerfile`, push to GHCR, and deploy to App Service using a publish profile

### Azure resources you need

- An Azure App Service Web App for Linux using Docker
- A resource group containing those resources

### GitHub repository secrets to add

In GitHub:

1. Open your repository
2. Go to `Settings`
3. Go to `Secrets and variables` -> `Actions`
4. Add these repository secrets:

- `AZURE_WEBAPP_NAME`
- `AZURE_WEBAPP_PUBLISH_PROFILE`

### Secret meanings

- `AZURE_WEBAPP_NAME`: the Azure App Service name
- `AZURE_WEBAPP_PUBLISH_PROFILE`: the downloaded App Service publish profile XML

### Azure Portal settings to configure once

In the Azure Web App:

1. Open `Settings` -> `Environment variables`
2. Add:

- `OPENAI_API_KEY`
- `DATA_FILE_PATH=app/data/Recipe.csv`
- `API_HOST=0.0.0.0`
- `PORT=8000`
- `WEBSITES_PORT=8000`
- `CORS_ORIGINS=https://your-app-name.azurewebsites.net`

3. In the container configuration for the Web App, switch to `Other container registries` and use GHCR:

- registry server URL: `https://ghcr.io`
- image and tag: `ghcr.io/<github-owner>/thrivewell:latest`
- registry username: your GitHub username
- registry password: a GitHub personal access token with `read:packages`

### App Service configuration

Your Azure Web App should be:

- `Publish`: Docker Container
- `Operating System`: Linux
- configured to pull from your Azure Container Registry

### How deployment works

The workflow embeds the Git commit SHA in the container. Check `/health` → `build_revision` against the successful workflow's commit to confirm which backend is running. Missing revision metadata means the image predates this diagnostic; `unknown` means the image was built without `APP_BUILD_REVISION`. The frontend normally calls the same origin, but a configured `REACT_APP_BACKEND_URL` can point it elsewhere, so confirm the browser's actual `/ask` URL when diagnosing stale responses.

On every push to `main`, the workflow:

1. Logs into GitHub Container Registry
2. Builds the root `Dockerfile`
3. Pushes the image with both commit SHA and `latest` tags to `ghcr.io`
4. Deploys the commit-specific image to Azure App Service using the publish profile

You can also run it manually from the GitHub Actions tab with `workflow_dispatch`.

## API endpoints

### `GET /health`

Returns service health and initialization status.

### `POST /ask`

Primary conversational recipe endpoint.

Example:

```json
{
  "query": "Give me easy high-protein dinner recipes",
  "mode": "auto",
  "conversation_history": [
    {
      "role": "user",
      "content": "Show me nutritious lunch ideas"
    }
  ]
}
```

### `POST /search`

Simpler recipe search endpoint without the full conversational adaptation pipeline.

### `GET /system/info`

Returns detailed backend capability and startup information.

## Recipe retesting regressions

Serving temperature uses `constraints.serving_temperature`, independently of no-heat preparation, spice intensity, and medical symptoms. Warm-but-not-hot recipe requests require citations to actual final-serving instructions. The two reported chilled/room-temperature bean salads are rejected as unchanged warm matches; useful recipes can still supply context for a clearly labeled AI adaptation. Missing evidence, fabricated citations, and conflicting serving guidance fail verification. Ordinary warm salads are eligible when their instructions actually support warm serving. These are bounded evidence checks, not a complete culinary or food-safety classifier.

Culinary category questions such as “Show foods that taste good warm but not hot” use `query_type=food_guidance`, returning a conversational answer and optional recipe offer without cards, a fabricated search result, or Search Analysis. Explicit recipe follow-ups return to the existing database-first pipeline. The current chat's explicit user temperature preference survives follow-ups and can be changed or cleared; assistant examples do not establish restrictions unless selected by the user. The privacy and crisis gates run before this route.

Guidance does not present a universal preferred temperature or confuse eating temperature with safe storage. Its prompt references [NIDCD's explanation of flavor](https://www.nidcd.nih.gov/health/taste-disorders) and [FDA's food-holding guidance](https://www.fda.gov/food/buy-store-serve-safe-food/serving-safe-buffets). Offline serving-temperature and routing regressions are in `test_serving_temperature.py`; these tests do not establish live-model accuracy.

The reported Prompt 54/55/63/64/69/73 examples have offline regression coverage in `test_source_annotations.py` and `test_preparation_validation.py`.

- Database `Notes` now reach expanded cards and same-chat recipe references without losing footnote markers. Referenced ingredient recipes resolve to existing CSV names and source URLs. Missing footnotes are explicitly flagged, never guessed; the imported sheet-pan za'atar note is missing, and the source page also has no separate footnote legend.
- `preparation_mode` distinguishes no-heat and assembly-only preparation from cold serving. Shared rules apply to intent, generation, repair, and verification. Stove/oven/microwave/kettle steps, hidden cooking dependencies, and incompatible tips cannot qualify merely because a recipe ends with assembly or cooling.
- Strict frozen-only requests are distinct from including some frozen ingredients. `avoid_steam` and `avoid_splatter` remain separate requirements. No ingredient exceptions or appliance substitutions are silently assumed.
- Time limits mean total elapsed preparation, including waiting. “Under 5 minutes” excludes exactly 5 minutes; “5 minutes or less” includes it. Verification requires numeric timing with recipe citations and independently checks stated step durations and source total times. These detailed preparation checks use one recipe per assessment, with at most three concurrent calls under the existing output-token limit.

Time-limited generation requests one complete candidate per call (existing reference-adaptation behavior is retained), with an explicit elapsed-time budget repeated in both generation and repair prompts. The backend constructs exact citations from unambiguous `total_time` or source `Total Time` declarations when the model omits `time_check` or agrees with the declared total; formatting differences in model quotes do not discard valid metadata. Partial cooking steps and untimed recipes do not acquire invented totals. Explicit model failures, unknown assessments, other constraints, and contradictory instructions still reject the recipe. Timed summaries use the accepted duration and describe it as approximate, not a cooking-time guarantee. If every attempt fails, the response acknowledges the clear time requirement instead of asking the user to rephrase. Regression coverage is in `test_time_limited_recipes.py`.

These checks supplement semantic verification; they are not a complete parser of every cooking instruction or a guarantee that cooking cannot splatter. Ambiguous preparation dependencies and unknown timing fail verification. Tests use mocked model assessments, including deliberately incorrect positive verdicts, and real CSV records; they do not establish live-model accuracy or deploy changes to Azure. Existing database-first retrieval, bounded generation retries, provenance labels, per-chat context, and the three-recipe limit remain in place.

## Recipe fallback order

Recipe discovery returns verified database matches first, including the existing additional CSV-candidate search when retrieval has no qualifying matches. If none qualify, relevant database recipes guide AI generation. If that reference-guided stage fails verification, a separate AI-only stage starts without the rejected reference recipes or hybrid repair targets. All user constraints, nutrition guidance, and same-chat exclusions remain active. Without useful references, generation goes directly to AI-only. A request to adapt a specific previous recipe stays tied to that recipe rather than silently returning a different dish.

Each generation stage allows two JSON attempts and one structured-text fallback, stopping immediately on verified matches. Optional enhancement works on copies of accepted recipes and cannot erase those originals: changed candidates must pass verification before replacing the same recipe. Rejected tips, malformed enhancements, and optional enhancement errors retain the already-verified original under the same request, rather than launching another generation loop. Initial verification and all active constraints still apply; an unverified candidate is never eligible for this fallback. Generated and hybrid dishes retain AI provenance, and responses remain capped at three recipes. `test_recipe_routing.py` covers stage order, bounded failures, repair feedback, follow-up exclusions, explicit adaptations, enhancement isolation, and the reported frozen-meals routing case using mocked model responses; this is not a live-model success guarantee.

CSV fallback ranking weights ingredient matches separately from incidental mentions in descriptions or directions, and uses meal-type metadata even when query keywords exist. Conversational words such as “best” and “generate” do not outrank actual meal categories. Ranking selects candidates for verification; it does not certify that their preparation satisfies the request. Automated tests run separately from request handling and are not shipped in the runtime Docker image.

Verification receives the resolved recipe request and active requirements, without unused intent defaults or retrieval keywords. Its batch example includes recipe IDs and the expected array shape, avoiding contradictory object-only formatting instructions. Suggested substitutions in source descriptions/notes are adaptation opportunities, not proof that the unchanged recipe satisfies the request. These prompts still depend on model assessment; passing offline tests does not certify dietary or relevance judgments.

The existing verification contract also requires an explicit `recipe_request` assessment whenever the pipeline supplies the original/resolved request. Empty named constraints no longer mean that the request's actual property can go unchecked. A missing, failed, or unknown request assessment cannot qualify as a match, even with a positive overall relevance label. This uses the existing verification call and does not add another retry/validation loop; it still depends on the model judging evidence correctly.

Generation, enhancement, repair, and verification select rule families from the active parsed constraints rather than including every unrelated preparation/storage rule. Intent analysis still receives the complete rule catalog. Frozen-only generation requests one complete recipe using realistic purchased frozen components, with no silent oil, spice, milk, or non-frozen grain additions. Cooking remains allowed unless independently prohibited, and instructions must prepare every component rather than serving still-frozen rice or protein. Pantry substitution examples appear only for pantry constraints. These changes keep the same verification gates and fallback order; `test_frozen_recipe_generation.py` covers the observed model failures, combined constraints, relevant prompt rules, and fresh-chat versus same-chat breakfast behavior. A broad breakfast follow-up preserves an active frozen-only requirement; a new chat or explicit reset clears it.

Frozen-only validation also independently checks common non-frozen additions in directions and optional guidance, so generated seed/nut toppings cannot pass merely because the model says all ingredients are frozen. Conflicting generated tips can be removed and the unchanged core reverified under the existing final-validation path. These are bounded checks, not a complete culinary parser. An assessment with an omitted ID is associated automatically only when exactly one recipe and one assessment are present; explicit wrong IDs and ambiguous multi-recipe responses are not reassigned, and all semantic and deterministic checks still run.

## Preparation accessibility and strict ingredient forms

Meal-discovery requests (including “Show meals I can prepare sitting down,” “What recipes require minimal hand strength to prepare?”, “Help me to prepare … recipes,” and “What meals use frozen ingredients from start to finish?”) route to recipe results rather than general food-category advice. Explicit requests for tips/explanations and questions about existing recipes retain their separate routes.

Food-selection requests such as “What foods …?”, “Which foods …?”, “What are some foods …?”, and “Suggest foods …” use recipe discovery when asking for options that meet a need, even without a cooking verb. The exact reheating-texture prompt follows the database → database-guided generation → AI-only pipeline rather than returning generic food categories. Explicit explanations, tips, category-only requests, and questions/adaptations about shown recipes retain their separate routes. The established culinary-category question “Show foods that taste good warm but not hot” still uses food guidance. Regression coverage checks paraphrases, fresh/repeated chat routing, both database and generated results, and explicit requests not to provide recipes.

Timing flexibility means forgiving preparation, not low hand strength, seated preparation, no-heat cooking, a short time limit, or low monitoring. Texture retention after reheating does not imply low chewing effort, and unchanged texture must not be guaranteed. General recipe summaries receive preparation steps and the verification rationale so they can explain the requested fit rather than repeating generic nutrition claims. The original request remains available to verification and generation; required doneness and food-safety checks are not waived. Prompt guidance does not guarantee live-model accuracy.

Positive reheating requests also use the existing leftovers-evidence path: unsupported model claims cannot qualify a recipe without storage/reheating guidance. For example, the imported Vegetable Stone Soup includes explicit reheating and separate-crouton guidance; the air-fryer plantain recipe does not. Reheating summaries quote available guidance and acknowledge possible texture changes rather than promising identical results. Requests without reheating are not converted to this requirement. Forgiving preparation must not be presented as permission to undercook food.

Physical-preparation constraints are grounded against actual user messages in the current chat, not assistant suggestions or an unsupported model rewrite. Unsupported hand/seated fields and matching criteria are removed, and their search expansions are rebuilt from user requests. Explicit user restrictions still persist through follow-ups; withdrawals and resets override them. These bounded grounding checks do not replace semantic recipe assessment. The exact timing prompt, repeated-chat contamination, real prior hand restrictions, and route preservation have regression coverage in `test_preparation_accessibility.py`.

`preparation_position="seated"` and `hand_effort="low"` are independent constraints, not diagnoses, low-attention cooking, or short preparation times. Verification requires cited evidence for every instruction and checks unresolved ingredient/setup dependencies and conflicting guidance. Bounded deterministic checks reject common heating/hot-transfer assumptions for seated requests and common forceful actions for low-hand-effort requests. Tabletop assembly does not need the literal word “seated” to qualify. These checks cannot certify an individual's kitchen accessibility or ability to open a package; uncertain preparation remains an adaptation candidate. User-stated restrictions persist within the chat, explicit withdrawals/reset override them, and assistant suggestions do not establish restrictions.

`ingredient_storage="canned_only"` is distinct from pantry-based, shelf-stable-only, and frozen-only requests. All food ingredients and optional suggestions must have canned forms; dry grains, fresh garnishes, oils, seasonings, or cooking-water exceptions are not silently introduced. Rinsing/washing water is not treated as an added food ingredient. Semantic checks cover all fields, with bounded independent checks for ingredient forms and common hidden additions. Canned-only does not itself prohibit heating. Requests restricting only vegetable forms are not promoted to an all-ingredients restriction.

Generated text fallback must provide an actual dish name and category, not a title-cased user prompt or `CUSTOM` card. The same ingredient/preparation verification still runs afterward. Offline regressions in `test_preparation_accessibility.py` and `test_canned_only_recipes.py` cover the reported database dishes and generated quinoa example, positive assembly/canned alternatives, routing, follow-ups, provenance, and final tips. These tests do not establish universal accessibility or live-model reliability; deployment is separate.

Missing canned-only/accessibility assessment fields receive at most one focused completion call per verification. This fills absent fields only, does not overwrite existing failures, and does not accept a recipe without the same semantic and independent checks afterward. Invalid or still-incomplete assessments fail closed. Canned-only generation requests one complete candidate at a time; its existing bounded repair uses the rejected candidate's canned components without silently removing ingredients from a source recipe.

### Following up on a shown recipe

A standalone title matching the loaded recipe catalog or a previously shown card starts an independent recipe task. The intent for a literal title is built without model-inferred requirements, so an earlier time limit (such as 35 minutes) cannot be inherited. The same title boundary is honored when scoping subsequent follow-ups, even if older client history lacks boundary metadata. Actual named modifications/questions and title replies to a pending “Which recipe?” clarification retain context. Explicit time limits in the current request still apply. Unknown titles and more complex requests continue through semantic intent analysis.

Exact catalog-title requests load that database record before semantic retrieval and return at most one recipe, rather than padding the answer with related dishes. The record still undergoes the existing preparation, verification, and safety checks. If it cannot pass, the normal bounded generation path remains available; broad requests retain their existing database-first retrieval and fallback order.

Explicit follow-ups such as “Can you simplify this recipe even more?” bind to the latest single recipe card, or an unambiguous name/ordinal in the active chat task. Multiple possible targets prompt clarification instead of searching for alternatives. New self-contained requests still start independent tasks. Intent context includes the shown instructions as well as ingredients; user restrictions remain distinct from the recipe's optional components.

Explicit recipe adaptations generate from the selected reference rather than verifying and returning the unchanged original. Simplification uses a focused editing prompt within the existing bounded generation/repair pipeline, with no unrelated search or AI-only fallback. Verification compares the proposed ingredients and preparation against the original; unchanged content is rejected independently, and the semantic comparison must support a real reduction in work or nonessential ingredients, not merely shorter wording. Optional enhancement is skipped so it cannot add complexity back. Cards retain AI Generated provenance and reference metadata. Regression tests cover exact wording, selected and ambiguous references, repeat simplification, scope isolation, unchanged candidates, comparison evidence, and routing; semantic judgments still depend on the configured model.

Recipe follow-ups share a target/action resolver for questions, comparisons, texture edits, ingredient substitutions, scaling, equipment changes and simplification. A versioned `recipe_context` travels with assistant messages through the frontend and `/ask` history schema. It stores selected recipe IDs and pending clarification, never a global conversation. IDs must refer to cards in the scoped chat task. Naming or selecting a recipe overrides an earlier selection; a successful edit selects the newly generated version for later questions. Descriptive references can use semantic resolution, but unknown IDs are rejected. “More recipes” remains discovery with active requirements and exclusion of already shown recipes, not an edit of the selected card.

“Can you change the texture of this recipe?” asks for the desired texture before generating. If several recipes are possible, it first asks which one. A short reply such as “softer and creamier” resumes the pending edit; short messages with recipe context are not automatically discarded as small talk. The focused editing prompt and verification compare the actual ingredients and directions, including crunchy seeds or toppings. An independent bounded check rejects unchanged recipes and unprocessed nuts/seeds in explicit soft/smooth edits; other culinary judgments remain semantic. Culinary texture preferences do not by themselves create a low-chewing requirement. Optional generic enhancements are skipped for edits so they cannot undo the requested change. Backend routing, multi-turn regressions and frontend history serialization are covered in `test_recipe_follow_up.py` and the conversation-history tests. Rebuild both frontend and backend to transport clarification state; arbitrary semantic references and generated content still depend on the configured model and are not a guarantee of perfect conversational recall.

## Local development notes

- If the backend is not fully initialized yet, `/health` may show startup in progress while the server is already reachable.
- If the OpenAI key is invalid or missing, the app starts but recipe generation endpoints will not fully initialize.
- In deployed single-service mode, do not point the frontend to `localhost:8000`; same-origin is the correct default.
