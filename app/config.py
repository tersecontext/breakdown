from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    redis_url: str = "redis://localhost:6379"
    tersecontext_url: str = "http://localhost:8090"
    source_dirs: str
    anthropic_api_key: str
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_channel: str = "tc-tasks"
    default_model: str = "claude-sonnet-4-20250514"
    port: int = 8000


settings = Settings()
