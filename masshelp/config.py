"""App settings, loaded from env (and .env) with pydantic-settings."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Claude
    anthropic_api_key: str | None = None
    masshelp_model: str = "claude-haiku-5-5"
    masshelp_heavy_model: str | None = None

    # Twilio
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_phone_number: str | None = None
    twilio_validate: bool = True
    twilio_send_pdf_media: bool = False

    # Vapi
    vapi_secret: str | None = None
    vapi_default_phone: str | None = None

    # App
    public_base_url: str = "http://localhost:8000"
    database_url: str | None = None
    data_dir: Path = ROOT / "data"
    rules_path: Path = PACKAGE_DIR / "rules" / "masshealth_rules.yaml"
    seed_path: Path = ROOT / "seed" / "members.yaml"

    # Agent behavior
    max_tool_rounds: int = 6
    max_tokens_voice: int = 1024
    max_tokens_sms: int = 2048
    identity_ttl_hours: int = 24
    max_identity_attempts: int = 3
    file_link_days: int = 7
    sms_split_chars: int = 600
    # A "conversation" on SMS restarts (and repeats the disclosure) after this much silence
    sms_conversation_gap_hours: int = 12

    # Demo controls
    demo_today: date | None = None
    demo_fixed_pdf: Path | None = None
    # Appends agent/prompts/demo_script.md to the system prompt (2-minute voice demo)
    demo_script: bool = False
    demo_phone_maria: str = "+16175550101"
    demo_phone_carlos: str = "+16175550102"
    demo_phone_ana: str = "+16175550103"
    demo_phone_jamal: str = "+16175550104"
    demo_phone_linh: str = "+16175550105"
    demo_phone_david: str = "+16175550106"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'masshelp.db'}"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdfs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
