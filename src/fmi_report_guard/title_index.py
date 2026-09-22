from __future__ import annotations

import json
import re
import sqlite3
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


def refresh_title_index(
    *,
    client: FMIClient,
    path: Path = TITLE_INDEX_PATH,
    min_titles: int = 25_000,
) -> list[IndexedTitle]:
    """Rebuild the cache from FMI sitemaps without invoking any AI service."""
    titles = client.fetch_title_index()
    if len(titles) < min_titles:
        raise ValueError(
            f"Refusing to replace the title index: found {len(titles):,}, "
            f"expected at least {min_titles:,}."
        )
    _save_payload(path, titles=titles, refreshed_at=datetime.now(UTC))
    return titles


def load_cached_title_index(path: Path = TITLE_INDEX_PATH) -> list[IndexedTitle]:
    """Load the local title cache without making a network request."""
    payload = _load_payload(path)
    return _payload_to_titles(payload) if payload else []


def load_titles_from_benchmark_db(path: str | Path | None) -> list[IndexedTitle]:
    """Load all report titles from a healthy FMI benchmark database.

    A broken or older database is treated as unavailable so the caller can fall
    back to the sitemap-backed JSON cache.
    """
    if not path:
        return []
    db_path = Path(path)
    if not db_path.exists():
        return []

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            """
            SELECT url, COALESCE(NULLIF(TRIM(market_name), ''), NULLIF(TRIM(meta_title), ''))
            FROM reports
            WHERE COALESCE(NULLIF(TRIM(market_name), ''), NULLIF(TRIM(meta_title), '')) IS NOT NULL
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        if "conn" in locals():
            conn.close()

    return [make_indexed_title(url=str(url), title=str(title)) for url, title in rows]


def load_title_corpus(
    *,
    index_path: Path = TITLE_INDEX_PATH,
    benchmark_db_path: str | Path | None = None,
) -> list[IndexedTitle]:
    """Merge the cached sitemap titles with any titles in the benchmark DB."""
    candidates = load_cached_title_index(index_path)
    candidates.extend(load_titles_from_benchmark_db(benchmark_db_path))

    by_url: dict[str, IndexedTitle] = {}
    without_url: dict[str, IndexedTitle] = {}
    for item in candidates:
        if not item.normalized_title:
            continue
        url_key = item.url.rstrip("/").lower()
        if url_key:
            by_url[url_key] = item
        else:
            without_url.setdefault(item.singular_title, item)
    return list(by_url.values()) + list(without_url.values())


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
