from __future__ import annotations

import math
import re

from .aio_audit import run_aio_audit
from .benchmarks import BenchmarkMarket, find_hierarchy_matches
from .models import Finding, ReportPage
from .title_index import IndexedTitle, make_indexed_title

MONEY_UNIT_MULTIPLIERS = {
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}


def run_rule_checks(
    report: ReportPage,
    *,
    title_index: list[IndexedTitle] | None = None,
    benchmarks: list[BenchmarkMarket] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(check_forecast_years(report))
    findings.extend(check_market_math(report))
    findings.extend(check_duplicate_title(report, title_index=title_index or []))
    findings.extend(check_benchmark_hierarchy(report, benchmarks=benchmarks or []))
    findings.extend(run_aio_audit(report))
    return findings


def check_forecast_years(report: ReportPage) -> list[Finding]:
    findings: list[Finding] = []
    title_year = _extract_trailing_year(report.page_title)
    h1_range = _extract_range_years(report.h1)
    meta_year = _extract_year_after_by(report.meta_description)
    card_range = _extract_range_years(report.card_summary)
    candidate_evidence = {
        "page_title": report.page_title,
        "h1_end": report.h1,
        "meta_description": report.meta_description,
        "card_summary_end": report.card_summary,
    }

    candidate_years = {
        label: year
        for label, year in {
            "page_title": title_year,
            "h1_end": h1_range[1] if h1_range else None,
            "meta_description": meta_year,
            "card_summary_end": card_range[1] if card_range else None,
        }.items()
        if year
    }

    unique_years = sorted(set(candidate_years.values()))
    if len(unique_years) > 1:
        findings.append(
            Finding(
                category="numeric_inconsistency",
                title="Forecast years disagree across the same report page",
                explanation=(
                    "The report exposes more than one ending forecast year across its public title "
                    "and summary fields."
                ),
                uploader_summary=(
                    "The forecast years do not match across the page, so the upload team needs to align the period everywhere."
                ),
                correction_instruction=(
                    "Please align the forecast period across the page title, H1, meta description, and card summary so all of them show the same verified end year."
                ),
                confidence=0.98,
                source="rule",
                evidence=[
                    f"{label}: {candidate_evidence[label]}"
                    for label in candidate_years
                ],
            )
        )

    return findings


def check_market_math(report: ReportPage) -> list[Finding]:
    findings: list[Finding] = []
    window = "\n".join(
        [report.meta_description]
        + [item["question"] + " " + item["answer"] for item in report.faq_items]
        + report.summary_paragraphs[:2]
    )

    start_value = _extract_money_value(window, start=True)
    end_value = _extract_money_value(window, start=False)
    cagr = _extract_percentage(window)
    years = _extract_range_years(report.h1)
    if not (start_value and end_value and cagr and years):
        return findings

    start_amount, start_unit = start_value
    end_amount, end_unit = end_value
    normalized_start = _normalize_money_value(start_amount, start_unit)
    normalized_end = _normalize_money_value(end_amount, end_unit)
    if normalized_start <= 0 or normalized_end <= 0:
        return findings

    periods = max(years[1] - years[0], 1)
    implied_cagr = ((normalized_end / normalized_start) ** (1 / periods) - 1) * 100
    if not math.isfinite(implied_cagr):
        return findings

    if abs(implied_cagr - cagr) > 1.0:
        findings.append(
            Finding(
                category="numeric_inconsistency",
                title="Published CAGR does not match the exposed market values",
                explanation=(
                    f"After normalizing the public start and end values across thousand/million/billion units, "
                    f"the exposed figures imply roughly {implied_cagr:.1f}% CAGR over {periods} years, which "
                    f"materially differs from the stated {cagr:.1f}%."
                ),
                uploader_summary=(
                    "The market numbers and CAGR do not match, so the upload team needs to fix the values or the unit labels before publishing."
                ),
                correction_instruction=(
                    f"Please verify the start value, end value, CAGR, and million or billion unit labels, then update the page so the figures are mathematically consistent across the {years[0]}-{years[1]} forecast period."
                ),
                confidence=0.94,
                source="rule",
                evidence=[
                    report.meta_description,
                    report.h1,
                ],
            )
        )

    return findings


def check_duplicate_title(report: ReportPage, *, title_index: list[IndexedTitle]) -> list[Finding]:
    if not title_index:
        return []

    current_title = report.card_title or report.h1 or report.page_title
    candidate = make_indexed_title(url=report.url, title=current_title)
    if not candidate.normalized_title:
        return []

    best_exact: IndexedTitle | None = None
    best_plural: IndexedTitle | None = None
    for existing in title_index:
        if not existing.url or existing.url == report.url:
            continue
        if existing.normalized_title == candidate.normalized_title:
            best_exact = existing
            break
        if existing.singular_title == candidate.singular_title:
            best_plural = existing

    match = best_exact or best_plural
    if not match:
        return []

    variant_kind = "exact title duplicate" if best_exact else "singular or plural duplicate"
    return [
        Finding(
            category="duplicate_title",
            title="Report title duplicates an existing FMI report title",
            explanation=(
                f'The new report title "{current_title}" appears to be a {variant_kind} of the already indexed FMI title '
                f'"{match.title}" at {match.url}. This check intentionally ignores looser thematic overlap and only '
                "flags exact or plural-only title collisions."
            ),
            uploader_summary=(
                "This report title looks like a duplicate of an already published FMI title and needs to be reviewed before upload."
            ),
            correction_instruction=(
                f"Please review the title against the existing FMI report {match.url} and rename this report if it is a duplicate or only a singular-plural variant."
            ),
            confidence=0.99 if best_exact else 0.96,
            source="rule",
            evidence=[
                f"current_title: {current_title}",
                f"existing_title: {match.title}",
                f"existing_url: {match.url}",
            ],
        )
    ]


def check_benchmark_hierarchy(report: ReportPage, *, benchmarks: list[BenchmarkMarket]) -> list[Finding]:
    if not benchmarks:
        return []

    market_name = report.card_title or report.h1 or report.page_title
    current = _extract_current_market_values(report)
    if not market_name or not current:
        return []

    findings: list[Finding] = []
    current_estimated_usd_mn, current_forecast_usd_mn, control_sentence = current
    for relation, benchmark in find_hierarchy_matches(
        market_name=market_name,
        url=report.url,
        benchmarks=benchmarks,
    ):
        if relation == "candidate_subset":
            if current_forecast_usd_mn > benchmark.forecast_value_usd_mn * 1.02:
                findings.append(
                    _benchmark_finding(
                        report=report,
                        title="Subset market is larger than broader FMI benchmark",
                        explanation=(
                            f"{market_name} appears narrower than {benchmark.market_name}, but its exposed forecast "
                            f"value is larger than the broader FMI benchmark."
                        ),
                        control_sentence=control_sentence,
                        correction=(
                            f"Recheck scope or value. {market_name} should not exceed {benchmark.market_name}. "
                            f"Benchmark: {benchmark.forecast_year} {benchmark.forecast_value:g} {benchmark.forecast_unit} at {benchmark.url}."
                        ),
                    )
                )
            if current_estimated_usd_mn > benchmark.estimated_value_usd_mn * 1.02:
                findings.append(
                    _benchmark_finding(
                        report=report,
                        title="Subset base value is larger than broader FMI benchmark",
                        explanation=(
                            f"{market_name} appears narrower than {benchmark.market_name}, but its exposed base or "
                            f"estimated value is larger than the broader FMI benchmark."
                        ),
                        control_sentence=control_sentence,
                        correction=(
                            f"Recheck scope or value. The subset market should not exceed {benchmark.market_name}. "
                            f"Benchmark: {benchmark.estimated_year} {benchmark.estimated_value:g} {benchmark.estimated_unit} at {benchmark.url}."
                        ),
                    )
                )
        elif relation == "candidate_parent":
            if current_forecast_usd_mn < benchmark.forecast_value_usd_mn * 0.98:
                findings.append(
                    _benchmark_finding(
                        report=report,
                        title="Parent market is smaller than FMI subset benchmark",
                        explanation=(
                            f"{market_name} appears broader than {benchmark.market_name}, but its exposed forecast "
                            f"value is smaller than the narrower FMI benchmark."
                        ),
                        control_sentence=control_sentence,
                        correction=(
                            f"Recheck scope or value. {market_name} should not be smaller than subset {benchmark.market_name}. "
                            f"Benchmark: {benchmark.forecast_year} {benchmark.forecast_value:g} {benchmark.forecast_unit} at {benchmark.url}."
                        ),
                    )
                )

    return findings


def _benchmark_finding(
    *,
    report: ReportPage,
    title: str,
    explanation: str,
    control_sentence: str,
    correction: str,
) -> Finding:
    return Finding(
        category="benchmark_hierarchy",
        title=title,
        explanation=explanation,
        uploader_summary=(
            "This report appears to break the parent/submarket size rule, so the upload team needs to verify the scope and market values."
        ),
        correction_instruction=correction,
        confidence=0.92,
        source="benchmark_db",
        evidence=[
            f"Market name: {report.card_title or report.h1 or report.page_title}",
            f"URL: {report.url}",
            f"Control+F: {control_sentence}",
            f"Change with: {correction}",
        ],
    )


def _extract_current_market_values(report: ReportPage) -> tuple[float, float, str] | None:
    window = "\n".join(
        [report.meta_description, report.card_summary, report.lead_summary]
        + report.summary_paragraphs[:3]
        + [item["question"] + " " + item["answer"] for item in report.faq_items[:4]]
    )
    values = _extract_money_values_by_year(window)
    if not values:
        return None

    estimated_candidates = [
        item for item in values if item[0] in {2025, 2026}
    ]
    forecast_candidates = [
        item for item in values if item[0] >= 2030
    ]
    if not estimated_candidates or not forecast_candidates:
        return None

    estimated = sorted(estimated_candidates, key=lambda item: item[0])[0]
    forecast = sorted(forecast_candidates, key=lambda item: item[0], reverse=True)[0]
    return estimated[1], forecast[1], forecast[2]


def _extract_money_values_by_year(text: str) -> list[tuple[int, float, str]]:
    money_pattern = re.compile(
        r"(?:USD|US\$|\$)\s*([\d,]+(?:\.\d+)?)\s*(thousand|million|billion)?",
        flags=re.I,
    )
    out: list[tuple[int, float, str]] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"incremental opportunity|absolute dollar opportunity|opportunity of", sentence, flags=re.I):
            continue
        year_positions = [(int(match.group(1)), match.start()) for match in re.finditer(r"\b(20\d{2})\b", sentence)]
        if not year_positions:
            continue
        for match in money_pattern.finditer(sentence):
            amount = float(match.group(1).replace(",", ""))
            unit = (match.group(2) or "million").lower()
            nearest_year = min(year_positions, key=lambda item: abs(item[1] - match.start()))[0]
            out.append((nearest_year, _normalize_money_value(amount, unit) / 1_000_000, sentence.strip()))
    return out

def _extract_trailing_year(text: str) -> int | None:
    match = re.search(r"[-–]\s*(20\d{2})\s*$", text)
    return int(match.group(1)) if match else None


def _extract_range_years(text: str) -> tuple[int, int] | None:
    match = re.search(r"(20\d{2})\s*[-–]\s*(20\d{2})", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _extract_year_after_by(text: str) -> int | None:
    match = re.search(r"\bby\s+(20\d{2})\b", text, flags=re.I)
    return int(match.group(1)) if match else None


def _extract_percentage(text: str) -> float | None:
    match = re.search(r"cagr of\s+([\d.]+)%", text, flags=re.I)
    return float(match.group(1)) if match else None


def _extract_money_value(text: str, *, start: bool) -> tuple[float, str] | None:
    if start:
        patterns = [
            r"(?:valued at|estimated to be valued at|worth)\s+usd\s+([\d.]+)\s+(billion|million|thousand)",
            r"in\s+20\d{2}.*?usd\s+([\d.]+)\s+(billion|million|thousand)",
        ]
    else:
        patterns = [
            r"reach\s+usd\s+([\d.]+)\s+(billion|million|thousand)\s+by\s+20\d{2}",
            r"to\s+reach\s+usd\s+([\d.]+)\s+(billion|million|thousand)\s+by\s+20\d{2}",
        ]

    lowered = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.I)
        if match:
            return float(match.group(1)), match.group(2)
    return None

def _normalize_money_value(amount: float, unit: str) -> float:
    return amount * MONEY_UNIT_MULTIPLIERS[unit.lower()]
