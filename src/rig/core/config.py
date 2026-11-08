"""Configuração do RIG via pydantic-settings (sem hardcode de chave)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Configuração lida de ambiente / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=(str(_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    deepseek_api_key: SecretStr = Field(..., alias="DEEPSEEK_API_KEY")
    llm_provider: str = Field("deepseek", alias="LLM_PROVIDER")
    llm_base_url: str = Field("https://api.deepseek.com", alias="LLM_BASE_URL")
    model_triage: str = Field("deepseek-flash", alias="MODEL_TRIAGE")
    model_audit: str = Field("deepseek-flash", alias="MODEL_AUDIT")
    model_draft: str = Field("deepseek-flash", alias="MODEL_DRAFT")
    model_embedding: str = Field("BAAI/bge-m3", alias="MODEL_EMBEDDING")
    embedding_dim: int = Field(1024, alias="EMBEDDING_DIM")
    database_url: str = Field("postgresql://rig:***@localhost:5432/rig", alias="DATABASE_URL")
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    max_cost_usd_per_run: float = Field(0.20, alias="MAX_COST_USD_PER_RUN")
    max_deadline_s: int = Field(90, alias="MAX_DEADLINE_S")

    @property
    def api_key(self) -> SecretStr:
        return self.deepseek_api_key

    @property
    def base_url(self) -> str:
        return self.llm_base_url

    @property
    def provider(self) -> str:
        return self.llm_provider

    @property
    def triage_model(self) -> str:
        return self.model_triage

    @property
    def audit_model(self) -> str:
        return self.model_audit

    @property
    def draft_model(self) -> str:
        return self.model_draft


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(**{})


__all__ = ["Settings", "get_settings"]
