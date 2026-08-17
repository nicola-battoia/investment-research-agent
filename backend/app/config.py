"""Validated application settings."""

from pathlib import Path
from typing import Annotated

from pydantic import AnyHttpUrl, PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    supabase_url: AnyHttpUrl
    supabase_anon_key: SecretStr
    supabase_service_role_key: SecretStr
    database_url: SecretStr
    openai_api_key: SecretStr
    openai_embedding_model: str
    openai_embedding_dimensions: PositiveInt
    allowed_origins: Annotated[tuple[AnyHttpUrl, ...], NoDecode]

    @field_validator("database_url")
    @classmethod
    def require_psycopg_3(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError(
                "DATABASE_URL must use postgresql+psycopg:// for Psycopg 3"
            )
        return value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_allowed_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(
                origin.strip() for origin in value.split(",") if origin.strip()
            )
        return value


settings = Settings()
