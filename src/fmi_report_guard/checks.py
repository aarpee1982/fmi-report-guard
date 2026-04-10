from __future__ import annotations

import math
import re

from .models import Finding, ReportPage

MONEY_UNIT_MULTIPLIERS = {
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}


def run_rule_checks(report: ReportPage) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(check_forecast_years(report))
    findings.extend(check_market_math(report))
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
                correction_instruction=(
                    "Please correct the forecast end year so the page title, H1, meta description, and card summary "
                    "all show the same reporting period and the same terminal year."
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
                correction_instruction=(
                    "Please correct the published market values or the CAGR so they are mathematically consistent "
                    f"across the {years[0]}-{years[1]} forecast period, and confirm the million/billion unit labels are correct."
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
