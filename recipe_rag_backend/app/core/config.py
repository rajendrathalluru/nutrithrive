import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

BASE_DIR = Path(__file__).resolve().parents[2]


def environment_flag(name: str, default: str) -> bool:
    value = os.getenv(name, default).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false.")
    return value == "true"


class Settings:
    APP_BUILD_REVISION: str = os.getenv("APP_BUILD_REVISION", "unknown")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    DATA_FILE_PATH: str = os.getenv("DATA_FILE_PATH", "app/data/Recipe.csv")
    BUDGET_PRICE_CATALOG: str = os.getenv("BUDGET_PRICE_CATALOG", "app/data/ingredient_prices.json")
    BUDGET_PRICE_API_URL: str = os.getenv("BUDGET_PRICE_API_URL", "").strip()
    BUDGET_PRICE_API_TOKEN: str = os.getenv("BUDGET_PRICE_API_TOKEN", "")
    BUDGET_PRICE_SOURCE_HOSTS: str = os.getenv("BUDGET_PRICE_SOURCE_HOSTS", "")
    BUDGET_PRICE_PROVIDER: str = os.getenv("BUDGET_PRICE_PROVIDER", "web_search").strip().lower()
    BUDGET_WEB_SEARCH_MODEL: str = os.getenv("BUDGET_WEB_SEARCH_MODEL", "gpt-5.4-mini").strip()
    KROGER_CLIENT_ID: str = os.getenv("KROGER_CLIENT_ID", "")
    KROGER_CLIENT_SECRET: str = os.getenv("KROGER_CLIENT_SECRET", "")
    KROGER_LOCATION_ID: str = os.getenv("KROGER_LOCATION_ID", "").strip()
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
    CORS_ORIGINS_RAW: str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    APP_ACCESS_ENABLED: bool = environment_flag("APP_ACCESS_ENABLED", "false")
    APP_ACCESS_PASSWORD: str = os.getenv("APP_ACCESS_PASSWORD", "")
    APP_SESSION_SECRET: str = os.getenv("APP_SESSION_SECRET", "")
    APP_SESSION_HOURS: int = int(os.getenv("APP_SESSION_HOURS", "8"))
    APP_COOKIE_SECURE: bool = environment_flag("APP_COOKIE_SECURE", "true")
    
    EMBEDDING_MODEL: str = "text-embedding-ada-002"
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.5
    LLM_MAX_TOKENS: int = 1500
    LLM_REQUEST_TIMEOUT_SECONDS: float = max(1.0, float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "20")))
    LLM_MAX_RETRIES: int = max(0, min(2, int(os.getenv("LLM_MAX_RETRIES", "0"))))
    RECIPE_MODEL_BUDGET_SECONDS: float = max(1.0, float(os.getenv("RECIPE_MODEL_BUDGET_SECONDS", "25")))
    RECIPE_FINAL_REVIEW_SECONDS: float = max(0.0, min(20.0, float(os.getenv("RECIPE_FINAL_REVIEW_SECONDS", "12"))))
    RECIPE_IO_WORKERS: int = max(1, min(3, int(os.getenv("RECIPE_IO_WORKERS", "3"))))
    RECIPE_OPTIONAL_ENHANCEMENT: bool = environment_flag("RECIPE_OPTIONAL_ENHANCEMENT", "false")
    RECIPE_RUNTIME_EVIDENCE: bool = environment_flag("RECIPE_RUNTIME_EVIDENCE", "true")
    RECIPE_COMPACT_INTENT: bool = environment_flag("RECIPE_COMPACT_INTENT", "true")
    RECIPE_LLM_RERANKING: bool = environment_flag("RECIPE_LLM_RERANKING", "false")
    RECIPE_SINGLE_PASS_DINNER: bool = environment_flag("RECIPE_SINGLE_PASS_DINNER", "true")
    RECIPE_AI_COST_ESTIMATES: bool = environment_flag("RECIPE_AI_COST_ESTIMATES", "true")
    RECIPE_VERIFIED_CATALOG_PATH: str = os.getenv("RECIPE_VERIFIED_CATALOG_PATH", str(BASE_DIR / "app/data/verified_catalog.json"))
    RECIPE_VERIFIED_CATALOG_TTL_SECONDS: int = max(0, int(os.getenv("RECIPE_VERIFIED_CATALOG_TTL_SECONDS", "604800")))
    RECIPE_REQUEST_WORKERS: int = max(1, min(4, int(os.getenv("RECIPE_REQUEST_WORKERS", "2"))))
    RECIPE_CACHE_TTL_SECONDS: int = max(0, int(os.getenv("RECIPE_CACHE_TTL_SECONDS", "300")))
    RECIPE_CACHE_MAX_ENTRIES: int = max(1, min(512, int(os.getenv("RECIPE_CACHE_MAX_ENTRIES", "128"))))
    
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 100
    SEARCH_K: int = 8

    @property
    def cors_origins(self) -> list[str]:
        origins = [origin.strip() for origin in self.CORS_ORIGINS_RAW.split(",") if origin.strip()]
        return origins or ["http://localhost:3000"]

    @property
    def data_file_path(self) -> Path:
        configured_path = Path(self.DATA_FILE_PATH)
        if configured_path.is_absolute():
            return configured_path
        return BASE_DIR / configured_path

settings = Settings()
