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
