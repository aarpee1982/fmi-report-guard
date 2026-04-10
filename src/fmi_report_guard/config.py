from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class AppConfig:
    openai_api_key: str | None
    openai_model: str
    github_token: str | None
    github_repository: str | None
    request_timeout_seconds: float
    summary_timezone: str
    summary_email_to: str | None
    summary_email_from: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_use_ssl: bool
    smtp_starttls: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        openai_model = os.getenv("OPENAI_MODEL") or "gpt-5-mini"
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=openai_model,
            github_token=os.getenv("GITHUB_TOKEN") or None,
            github_repository=os.getenv("GITHUB_REPOSITORY") or None,
            request_timeout_seconds=float(os.getenv("FMI_REQUEST_TIMEOUT") or "30"),
            summary_timezone=os.getenv("FMI_SUMMARY_TIMEZONE") or "Asia/Calcutta",
            summary_email_to=os.getenv("FMI_SUMMARY_EMAIL_TO") or None,
            summary_email_from=os.getenv("FMI_SUMMARY_EMAIL_FROM") or None,
            smtp_host=os.getenv("FMI_SMTP_HOST") or None,
            smtp_port=int(os.getenv("FMI_SMTP_PORT") or "587"),
            smtp_username=os.getenv("FMI_SMTP_USERNAME") or None,
            smtp_password=os.getenv("FMI_SMTP_PASSWORD") or None,
            smtp_use_ssl=_env_flag("FMI_SMTP_USE_SSL", default=False),
            smtp_starttls=_env_flag("FMI_SMTP_STARTTLS", default=True),
        )


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
