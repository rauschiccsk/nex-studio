from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str = "postgresql+pg8000://nexstudio:nexstudio@localhost:9178/nexstudio"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 480
    backend_port: int = 9176
    frontend_port: int = 9177

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
