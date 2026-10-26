"""Configuration for Founder Signal, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Automatically load .env if available
try:
    from dotenv import load_dotenv
    # Look for .env in current directory and parent directory
    env_file = Path(".env")
    if not env_file.exists():
        env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
    else:
        load_dotenv()
except ImportError:
    pass


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
    hermes_skill_host: str = "127.0.0.1"
    hermes_skill_port: int = 8765
    briefing_coming_up_days: int = 7
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e2b-it-qat"
    use_llm: bool = False
    founder_name: str = "Anthony"
    founder_email: str | None = None
    inbox_folder: str = "~/Downloads/founder-signal-inbox"
    max_upload_mb: int = 25
    upload_extensions: str = "txt,md,mp3,wav,m4a,ogg,aac"
    himalaya_bin: str = "himalaya"
    heartbeat_days: int = 3

    def founder_for_account(self, account: str | None) -> tuple[str, str | None]:
        """Return (founder_name, founder_email) for a given himalaya account.

        Looks up FOUNDER_NAME_<ACCOUNT> and FOUNDER_EMAIL_<ACCOUNT> env vars,
        falling back to the global FOUNDER_NAME / FOUNDER_EMAIL.
        """
        if account:
            key = account.upper().replace("-", "_").replace(".", "_")
            name = os.environ.get(f"FOUNDER_NAME_{key}")
            email = os.environ.get(f"FOUNDER_EMAIL_{key}")
            if name or email:
                return (name or self.founder_name, email or self.founder_email)
        return (self.founder_name, self.founder_email)

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
            hermes_skill_host=_getenv("HERMES_SKILL_HOST", "127.0.0.1") or "127.0.0.1",
            hermes_skill_port=int(_getenv("HERMES_SKILL_PORT", "8765") or 8765),
            briefing_coming_up_days=int(
                _getenv("BRIEFING_COMING_UP_DAYS", "7") or 7
            ),
            ollama_host=_getenv("OLLAMA_HOST", "http://localhost:11434")
            or "http://localhost:11434",
            ollama_model=_getenv("FOUNDER_SIGNAL_MODEL", "gemma4:e2b-it-qat")
            or "gemma4:e2b-it-qat",
            use_llm=(_getenv("FOUNDER_SIGNAL_USE_LLM", "false") or "false").lower()
            == "true",
            founder_name=_getenv("FOUNDER_NAME", "Anthony") or "Anthony",
            founder_email=_getenv("FOUNDER_EMAIL"),
            inbox_folder=_getenv("FOUNDER_SIGNAL_INBOX", "~/Downloads/founder-signal-inbox")
            or "~/Downloads/founder-signal-inbox",
            max_upload_mb=int(_getenv("FOUNDER_SIGNAL_MAX_UPLOAD_MB", "25") or 25),
            upload_extensions=_getenv(
                "FOUNDER_SIGNAL_UPLOAD_EXTENSIONS", "txt,md,mp3,wav,m4a,ogg,aac"
            )
            or "txt,md,mp3,wav,m4a,ogg,aac",
            himalaya_bin=_getenv("HIMALAYA_BIN", "himalaya") or "himalaya",
            heartbeat_days=int(_getenv("FOUNDER_SIGNAL_HEARTBEAT_DAYS", "3") or 3),
        )

