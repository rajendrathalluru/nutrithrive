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

- Frontend: React, TypeScript, Tailwind CSS
- Backend: FastAPI, Uvicorn, LangChain, OpenAI, FAISS, Pandas, Pydantic
- Deployment: Docker, Docker Compose, Render

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
