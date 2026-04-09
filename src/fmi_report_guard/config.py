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

    @classmethod
    def from_env(cls) -> "AppConfig":
        openai_model = os.getenv("OPENAI_MODEL") or "gpt-5-mini"
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=openai_model,
            github_token=os.getenv("GITHUB_TOKEN"),
            github_repository=os.getenv("GITHUB_REPOSITORY"),
            request_timeout_seconds=float(os.getenv("FMI_REQUEST_TIMEOUT", "30")),
        )
