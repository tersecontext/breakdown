from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    redis_url: str = "redis://localhost:6379"
    tersecontext_url: str = "http://localhost:8090"
    source_dirs: str
    anthropic_api_key: str = ""
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_channel: str = "tc-tasks"
    default_model: str = "claude-sonnet-4-20250514"
    port: int = 8000

    # Auth
    secret_key: str
    access_token_ttl: int = 900      # 15 minutes
    refresh_token_ttl: int = 604800  # 7 days
    cors_origins: list[str] = []

    @field_validator("secret_key")
    @classmethod
    def secret_key_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v


settings = Settings()
