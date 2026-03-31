"""Configurações centralizadas do CRM QS Backend."""

from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    # ── App ──
    app_name: str = "CRM QS Backend"
    app_version: str = "1.0.0"
    debug: bool = False
    secret_key: str = "crm-qs-secret-change-me"
    cors_origins: str = "*"

    # ── Evolution API ──
    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = "crm-qs-evolution-key-2026"
    evolution_instance_name: str = "crm-qs-main"

    # ── Database ──
    database_path: str = "/data/crm_qs.db"

    # ── WhatsApp Owner (quem é "eu" nas conversas) ──
    owner_name: str = "Felipe Torres"
    owner_phone: str = "5531999999999"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
