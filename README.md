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

When a generated candidate fails, the existing bounded retry repairs one concrete candidate using its full ingredients, instructions, and rejection details instead of asking for another generic batch. It preserves the request and provenance, updates affected cooking steps, and passes through the same independent verification. Invalid output is never returned just to avoid an empty result.

For “more recipes,” intent is rebuilt from prior user requests rather than the assistant's recipe descriptions or nutrition claims. Previously shown names are excluded before the CSV candidate limit and before accepting AI output, so repeated generations trigger the existing bounded retry instead of an empty response. Intent prompts specify the full JSON structure, including flavor preferences and explicit user constraints.

Conversation context belongs to the active chat. Requests carry that chat's user turns and structured recipe references; the backend does not share conversation memory between chats. Intent resolution retains earlier user requirements, applies later changes, and produces a standalone request for retrieval and verification. References such as “the second one” resolve against recipe IDs from that chat. Questions about a shown recipe are answered from its details; explicit modifications use the selected recipe as generation context and remain labeled AI Generated (`conversation_guided` for prior AI recipes). Ambiguous references request clarification. All user turns and recipe references are available to intent resolution, with assistant prose limited to the last six turns. Chat history currently lasts for the mounted application session; this does not add persistence across page reloads.

Intent processing preserves semantic search expansions (for example, “shelf-stable meals” → canned beans, dried lentils, rice) for vector retrieval and CSV candidate ranking. Pantry-based requests and strictly shelf-stable-only requests are distinguished by `constraints.ingredient_storage`. Shared prompt rules apply across intent analysis, verification, generation, and summaries; pantry ingredients do not imply room-temperature storage of the prepared meal.

Requests for little active attention use `constraints.attention_level="low"`, independently of total cooking time or ingredient storage. Search expands toward baking, roasting, assembly, and slow cooking without requiring a particular appliance. Verification assesses actual instructions, not titles alone: lengthy passive cooking can qualify, while continuous stirring does not. Pantry requests do not acquire this constraint merely because an example in a prompt mentions it.

Pantry-based recipes must be achievable without required fresh or refrigerated purchases; fresh garnishes must be explicitly optional. Pantry verification requires a structured assessment of required non-pantry ingredients, unspecified ingredient forms, and conflicting guidance. Missing or adverse assessments fail verification. Generated tips and adaptations trigger final verification; rejected generated guidance may be removed once, followed by another full check. Core ingredient failures remain rejected, and failed generation assessments are passed to the retry.

Both batch and individual verification also audit ingredient lines independently of the model. This bounded check catches known fresh/refrigerated ingredients and ambiguous forms such as unspecified corn or broth, even when the model reports an empty error list. Explicit pantry forms (for example, canned carrots or garlic powder) remain eligible. Conflicts retain exact ingredient lines for the existing correction retry; otherwise relevant recipes remain available as adaptation references, not direct matches. This is a supplemental guard, not a complete food-storage classifier: unfamiliar ingredients and narrative guidance still require semantic verification.

If final validation removes every selected recipe, unused verified database matches are tried first. If none remain, one additional generation attempt receives the final rejection feedback and relevant recipe references, then undergoes the same verification and follow-up exclusion checks. This bounded recovery does not add another round of optional tips. Initial-request failures and exhausted follow-ups have distinct messages.

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

## Chat UI

The chat page uses [assistant-ui's external-store runtime](https://www.assistant-ui.com/docs/runtimes/custom/external-store) for message rendering and scroll behavior. `NutriThriveChatbot` still owns chat state, health polling, and request handling; `BackendService` and `buildConversationHistory` remain the only recipe-request path. `AssistantChatThread` is the presentation adapter and renders the original messages, including structured recipe data and safety responses, without changing their contents.

The existing voice-enabled `ChatInput` is retained. Conversation starters only fill the draft; they do not submit requests. Source links, AI labels, ingredient groups, tips, and recipe expansion remain in `RecipeCard`. Search Analysis is available in an expandable disclosure. Styles are scoped to `.thrive-chat` and do not change the landing page.

On narrow screens, `useChatViewport` sizes the chat to the [visual viewport](https://developer.mozilla.org/en-US/docs/Web/API/VisualViewport), including changes from browser controls and the on-screen keyboard. The page-level scroll lock applies only while the mobile chat is mounted; messages keep their own scrolling area. Leaving the chat removes the lock and viewport listeners. Pinch zoom is not disabled. The mobile composer starts at 44px, grows for longer drafts, and keeps health, voice, and error messages visible while hiding the idle hint.

`@assistant-ui/react` is pinned to `0.10.30` to retain compatibility with this project's TypeScript 4.9 / Create React App toolchain. No assistant-ui cloud service, additional model provider, or persistent conversation storage is configured. Jest transforms the library's ESM dependencies so regression tests exercise the real runtime rather than mocking it.

Run the chat and recipe UI regression tests:

```bash
CI=true npm test -- --watchAll=false --runInBand --runTestsByPath src/hooks/useChatViewport.test.tsx src/components/NutriThriveChatbot.test.tsx src/components/RecipeCard.test.tsx src/utils/conversationHistory.test.ts src/utils/ingredientGroups.test.ts
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

## Local development notes

- If the backend is not fully initialized yet, `/health` may show startup in progress while the server is already reachable.
- If the OpenAI key is invalid or missing, the app starts but recipe generation endpoints will not fully initialize.
- In deployed single-service mode, do not point the frontend to `localhost:8000`; same-origin is the correct default.
