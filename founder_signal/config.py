"""Configuration for Founder Signal, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _getenv(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


@dataclass(frozen=True)
class Config:
    ledger_backend: str = "sqlite"
    ledger_sqlite_path: str = "data/founder_signal.db"
    mongodb_uri: str | None = None
    mongodb_database: str = "founder_signal"
    hermes_skill_endpoint: str | None = None
    web_host: str = "127.0.0.1"
    web_port: int = 5000
    briefing_coming_up_days: int = 7
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e2b-it-qat"
    use_llm: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            ledger_backend=_getenv("LEDGER_BACKEND", "sqlite") or "sqlite",
            ledger_sqlite_path=_getenv("LEDGER_SQLITE_PATH", "data/founder_signal.db")
            or "data/founder_signal.db",
            mongodb_uri=_getenv("MONGODB_URI"),
            mongodb_database=_getenv("MONGODB_DATABASE", "founder_signal") or "founder_signal",
            hermes_skill_endpoint=_getenv("HERMES_SKILL_ENDPOINT"),
            web_host=_getenv("WEB_HOST", "127.0.0.1") or "127.0.0.1",
            web_port=int(_getenv("WEB_PORT", "5000") or 5000),
            briefing_coming_up_days=int(
                _getenv("BRIEFING_COMING_UP_DAYS", "7") or 7
            ),
            ollama_host=_getenv("OLLAMA_HOST", "http://localhost:11434")
            or "http://localhost:11434",
            ollama_model=_getenv("FOUNDER_SIGNAL_MODEL", "gemma4:e2b-it-qat")
            or "gemma4:e2b-it-qat",
            use_llm=(_getenv("FOUNDER_SIGNAL_USE_LLM", "false") or "false").lower()
            == "true",
        )
