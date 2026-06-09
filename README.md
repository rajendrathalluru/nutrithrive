# NutriThrive Research

NutriThrive Research is a full-stack AI nutrition assistant that helps users ask diet and recipe questions in natural language and receive recipe-oriented answers with filtering, follow-up context, and safety checks.

It includes:
- A React frontend chat interface
- A FastAPI backend
- Retrieval and reranking over a recipe dataset
- Nutrition-oriented recipe verification and enhancement
- PHI/privacy redirect logic for protected health information

## Architecture

```text
Frontend (React) -> FastAPI backend -> intent analysis -> search/rerank -> verification -> recipe enhancement -> response
```

Main directories:

```text
nutrithrive-research/
├── src/                           # Frontend source
├── public/                        # Frontend static assets
├── recipe_rag_backend/
│   ├── app/
│   │   ├── core/                  # Backend configuration
│   │   ├── data/                  # Recipe dataset
│   │   ├── models/                # Pydantic schemas
│   │   ├── services/              # Search, verification, enhancement logic
│   │   └── main.py                # FastAPI entrypoint
│   ├── Dockerfile                 # Backend container
│   ├── requirements.txt
│   └── .env.example
├── deploy/nginx/                  # Frontend nginx config and runtime env injection
├── Dockerfile                     # Frontend container
├── docker-compose.yml             # Local container orchestration
├── render.yaml                    # Render blueprint
├── .env.example                   # Frontend environment example
└── README.md
```

## Features

- Conversational recipe discovery
- Follow-up handling across the same chat
- Diet, cuisine, and ingredient-aware retrieval
- Nutrition-oriented filtering and recipe verification
- Helpful tips and generated instructions for selected recipes
- Redirects for small-talk and PHI-like prompts

## Tech Stack

### Frontend

- React 19
- TypeScript
- Tailwind CSS
- Lucide React

### Backend

- FastAPI
- Uvicorn
- LangChain
- OpenAI
- FAISS
- Pandas
- Pydantic
- Tiktoken

## Environment Variables

### Frontend

Copy the example:

```bash
cp .env.example .env
```

Available variables:

- `REACT_APP_BACKEND_URL`
  Backend base URL used by the React app

Example:

```env
REACT_APP_BACKEND_URL=http://localhost:8000
```

### Backend

Copy the example:

```bash
cp recipe_rag_backend/.env.example recipe_rag_backend/.env
```

Required:

- `OPENAI_API_KEY`

Recommended:

- `DATA_FILE_PATH`
- `API_HOST`
- `API_PORT`
- `CORS_ORIGINS`

Example:

```env
OPENAI_API_KEY=your_openai_api_key_here
DATA_FILE_PATH=app/data/Recipe.csv
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
```

## Run Locally Without Docker

### Backend

```bash
cd recipe_rag_backend
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

### Frontend

```bash
cd /Users/rajendrathalluru/Documents/nutrithrive-research
npm install
npm start
```

Open:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`

## Run With Docker

### Backend only

```bash
docker build -t nutrithrive-backend ./recipe_rag_backend
docker run --env-file ./recipe_rag_backend/.env -p 8000:8000 nutrithrive-backend
```

### Frontend only

```bash
docker build -t nutrithrive-frontend .
docker run -e REACT_APP_BACKEND_URL=http://localhost:8000 -p 8080:80 nutrithrive-frontend
```

### Full stack with Docker Compose

```bash
docker compose up --build
```

Open:

- Frontend: `http://localhost:8080`
- Backend: `http://localhost:8000`

## Deploy to Render

This repo includes [render.yaml](/Users/rajendrathalluru/Documents/nutrithrive-research/render.yaml) as a starting point.

Deploy flow:

1. Push the repo to GitHub.
2. In Render, create a Blueprint deployment from the repository.
3. Set `OPENAI_API_KEY` in Render.
4. Update the frontend/backend hostnames in `render.yaml` if you choose different service names.

Recommended Render setup:

- Backend as a Docker web service using `recipe_rag_backend/Dockerfile`
- Frontend as a Docker web service using `Dockerfile`

Backend environment variables on Render:

- `OPENAI_API_KEY`
- `DATA_FILE_PATH=app/data/Recipe.csv`
- `CORS_ORIGINS=https://your-frontend-domain.onrender.com`

Frontend environment variable on Render:

- `REACT_APP_BACKEND_URL=https://your-backend-domain.onrender.com`

## Deploy to Other Platforms

This project can also be deployed to:

- Railway
- Fly.io
- Azure App Service
- AWS ECS / App Runner
- Google Cloud Run
- DigitalOcean App Platform
- Any VM with Docker

General production pattern:

1. Deploy the backend container.
2. Set `OPENAI_API_KEY` and `CORS_ORIGINS`.
3. Deploy the frontend container with `REACT_APP_BACKEND_URL` pointed at the backend URL.
4. Expose the frontend publicly.

## API Endpoints

### `GET /`

Basic API information.

### `GET /health`

Service health and initialization status.

### `POST /ask`

Main conversational recipe endpoint.

Example:

```json
{
  "query": "I need easy high-protein dinners",
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

Simpler search endpoint without the full adaptation pipeline.

### `GET /system/info`

Detailed backend capability and initialization information.

## Production Notes

- The backend keeps running even if initialization fails; check `/health` for details.
- CORS is configurable through `CORS_ORIGINS`.
- The frontend backend URL is injected at build time.
- The backend uses a bundled CSV dataset, so no database is required for initial deployment.
- The app should not be treated as medical advice; it is a recipe and nutrition support tool.

## Privacy / PHI Behavior

The backend includes prompt-level safeguards that:

- redirect casual small-talk away from recipe generation
- redirect prompts that include PHI-like personal or identifying health information
- allow anonymous, general diet and recipe questions

## Useful Commands

### Frontend

```bash
npm start
npm run build
npx tsc --noEmit
```

### Backend

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
python -m py_compile recipe_rag_backend/app/main.py
```

### Docker

```bash
docker compose up --build
docker compose down
```

## What Still Needs Attention

- Add automated tests for PHI redirect logic
- Add automated tests for follow-up context handling
- Tune retrieval quality for stricter cuisine preservation
- Add production monitoring/logging if deploying publicly

## License

Add your preferred license before public release.
