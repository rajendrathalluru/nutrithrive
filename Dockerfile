FROM node:20-alpine AS frontend-build

WORKDIR /frontend

COPY package*.json ./
RUN npm ci

COPY . .

RUN npm run build

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV API_HOST=0.0.0.0
ENV PORT=8000
ENV DATA_FILE_PATH=app/data/Recipe.csv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY recipe_rag_backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY recipe_rag_backend/app ./app
COPY --from=frontend-build /frontend/build ./frontend-build

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host ${API_HOST} --port ${PORT}"]
