from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


STOPWORDS = {
    "market",
    "global",
    "industry",
    "report",
    "analysis",
    "forecast",
    "outlook",
    "size",
    "share",
    "and",
    "or",
    "of",
    "the",
    "in",
    "for",
    "by",
    "to",
}

REGION_WORDS = {
    "africa",
    "asia",
    "australia",
    "brazil",
    "canada",
    "china",
    "europe",
    "france",
    "gcc",
    "germany",
    "india",
    "indonesia",
    "italy",
    "japan",
    "korea",
    "latin",
    "mexico",
    "middle",
    "north",
    "russia",
    "saudi",
    "south",
    "spain",
    "turkey",
    "uae",
    "uk",
    "united",
    "usa",
    "western",
}


@dataclass(frozen=True, slots=True)
class BenchmarkMarket:
    market_name: str
    url: str
    category: str
    estimated_year: int
    estimated_value: float
    estimated_unit: str
    estimated_value_usd_mn: float
    forecast_year: int
    forecast_value: float
    forecast_unit: str
    forecast_value_usd_mn: float
    cagr_percent: float


def load_benchmarks(db_path: str | None) -> list[BenchmarkMarket]:
    if not db_path:
        return []

    path = Path(db_path)
    if not path.exists():
        return []

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT market_name, url, category, estimated_year, estimated_value,
                   estimated_unit, estimated_value_usd_mn, forecast_year,
                   forecast_value, forecast_unit, forecast_value_usd_mn, cagr_percent
            FROM valid_global_benchmarks
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    return [
        BenchmarkMarket(
            market_name=str(row["market_name"]),
            url=str(row["url"]),
            category=str(row["category"] or ""),
            estimated_year=int(row["estimated_year"]),
            estimated_value=float(row["estimated_value"]),
            estimated_unit=str(row["estimated_unit"]),
            estimated_value_usd_mn=float(row["estimated_value_usd_mn"]),
            forecast_year=int(row["forecast_year"]),
            forecast_value=float(row["forecast_value"]),
            forecast_unit=str(row["forecast_unit"]),
            forecast_value_usd_mn=float(row["forecast_value_usd_mn"]),
            cagr_percent=float(row["cagr_percent"]),
        )
        for row in rows
    ]


def title_tokens(title: str) -> set[str]:
    raw_tokens = re.findall(r"[a-z0-9]+", title.lower())
    return {
        token
        for token in raw_tokens
        if token not in STOPWORDS and token not in REGION_WORDS and len(token) > 1
    }


def relation_to(candidate_title: str, benchmark_title: str) -> str | None:
    candidate = title_tokens(candidate_title)
    benchmark = title_tokens(benchmark_title)
    if not candidate or not benchmark:
        return None
    if benchmark < candidate:
        return "candidate_subset"
    if candidate < benchmark:
        return "candidate_parent"
    return None


def find_hierarchy_matches(
    *,
    market_name: str,
    url: str,
    benchmarks: list[BenchmarkMarket],
    max_matches: int = 8,
) -> list[tuple[str, BenchmarkMarket]]:
    matches: list[tuple[str, BenchmarkMarket]] = []
    for benchmark in benchmarks:
        if benchmark.url.rstrip("/") == url.rstrip("/"):
            continue
        relation = relation_to(market_name, benchmark.market_name)
        if relation:
            matches.append((relation, benchmark))
    return matches[:max_matches]
