from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .scraper import FMIClient

TITLE_INDEX_PATH = Path("state/fmi_title_index.json")

GENERIC_TITLE_TOKENS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "the",
    "to",
    "with",
    "global",
    "industry",
    "analysis",
    "report",
    "reports",
    "market",
    "markets",
}


@dataclass(slots=True)
class IndexedTitle:
    url: str
    title: str
    normalized_title: str
    singular_title: str


def normalize_duplicate_title(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b(20\d{2})\s*[-–]\s*(20\d{2})\b", " ", text)
    text = re.sub(r"\bglobal industry analysis report\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token and token not in GENERIC_TITLE_TOKENS]
    return " ".join(tokens)


def singularize_token(token: str) -> str:
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith(("sses", "shes", "ches", "xes", "zes")) and len(token) > 4:
        return token[:-2]
    if token.endswith("oes") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def singularize_phrase(value: str) -> str:
    return " ".join(singularize_token(token) for token in value.split())


def make_indexed_title(*, url: str, title: str) -> IndexedTitle:
    normalized_title = normalize_duplicate_title(title)
    return IndexedTitle(
        url=url,
        title=title,
        normalized_title=normalized_title,
        singular_title=singularize_phrase(normalized_title),
    )


def load_or_refresh_title_index(
    *,
    client: FMIClient,
    path: Path = TITLE_INDEX_PATH,
    max_age_hours: int = 24,
) -> list[IndexedTitle]:
    payload = _load_payload(path)
    now = datetime.now(UTC)
    if payload:
        refreshed_at_raw = str(payload.get("refreshed_at", "")).strip()
        refreshed_at = _parse_timestamp(refreshed_at_raw)
        if refreshed_at and now - refreshed_at <= timedelta(hours=max_age_hours):
            return _payload_to_titles(payload)

    titles = client.fetch_title_index()
    _save_payload(path, titles=titles, refreshed_at=now)
    return titles


def _load_payload(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _payload_to_titles(payload: dict[str, object]) -> list[IndexedTitle]:
    items = payload.get("titles", [])
    if not isinstance(items, list):
        return []
    titles: list[IndexedTitle] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        titles.append(
            IndexedTitle(
                url=str(item.get("url", "")),
                title=str(item.get("title", "")),
                normalized_title=str(item.get("normalized_title", "")),
                singular_title=str(item.get("singular_title", "")),
            )
        )
    return titles


def _save_payload(path: Path, *, titles: list[IndexedTitle], refreshed_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "refreshed_at": refreshed_at.isoformat(),
        "titles": [
            {
                "url": item.url,
                "title": item.title,
                "normalized_title": item.normalized_title,
                "singular_title": item.singular_title,
            }
            for item in titles
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
