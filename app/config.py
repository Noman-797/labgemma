from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    secret_key: str = "dev-secret-change-me"
    database_url: str = "sqlite:///./labgemma.db"
    gemma_api_key: str = ""
    gemma_api_base_url: str = "https://ollama.com/v1"
    gemma_model: str = "gemma4:31b-cloud"
    mock_gemma: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
