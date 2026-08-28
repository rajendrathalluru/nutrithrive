import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parents[2]

class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    DATA_FILE_PATH: str = os.getenv("DATA_FILE_PATH", "app/data/Recipe.csv")
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
    CORS_ORIGINS_RAW: str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    
    EMBEDDING_MODEL: str = "text-embedding-ada-002"
    LLM_MODEL: str = "gpt-3.5-turbo"
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
