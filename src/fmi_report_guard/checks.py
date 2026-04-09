from __future__ import annotations

import math
import re

from .models import Finding, ReportPage

GENERIC_TITLE_WORDS = {
    "market",
    "global",
    "industry",
    "analysis",
    "report",
    "forecast",
    "future",
    "insights",
    "size",
    "outlook",
    "summary",
    "company",
    "companies",
    "cover",
    "covers",
    "worldwide",
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
}


def run_rule_checks(report: ReportPage) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(check_forecast_years(report))
    findings.extend(check_market_math(report))
    findings.extend(check_topic_mismatch(report))
    return findings


def check_forecast_years(report: ReportPage) -> list[Finding]:
    findings: list[Finding] = []
    title_year = _extract_trailing_year(report.page_title)
    h1_range = _extract_range_years(report.h1)
    meta_year = _extract_year_after_by(report.meta_description)
    card_range = _extract_range_years(report.card_summary)

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
                confidence=0.98,
                source="rule",
                evidence=[f"{label}: {year}" for label, year in candidate_years.items()],
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
    if start_unit != end_unit:
        return findings

    periods = max(years[1] - years[0], 1)
    implied_cagr = ((end_amount / start_amount) ** (1 / periods) - 1) * 100
    if not math.isfinite(implied_cagr):
        return findings

    if abs(implied_cagr - cagr) >= 1.0:
        findings.append(
            Finding(
                category="numeric_inconsistency",
                title="Published CAGR does not match the exposed market values",
                explanation=(
                    f"Using the public start and end values over {periods} years implies roughly "
                    f"{implied_cagr:.1f}% CAGR, which materially differs from the stated {cagr:.1f}%."
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


def check_topic_mismatch(report: ReportPage) -> list[Finding]:
    findings: list[Finding] = []
    title_terms = _significant_terms(report.card_title or report.h1 or report.page_title)
    if len(title_terms) < 3:
        return findings

    candidate_texts: list[str] = []
    lead_focus = _trim_after_marker(report.lead_summary, "segmented by")
    if lead_focus:
        candidate_texts.append(lead_focus)

    for paragraph in report.summary_paragraphs[:5]:
        for marker in ("refers to the category of", "designed for use in", "encompasses"):
            trimmed = _trim_after_marker(paragraph, marker)
            if trimmed:
                candidate_texts.append(trimmed)

    for candidate in candidate_texts:
        lowered = candidate.lower()
        if len(lowered) < 40:
            continue
        overlap = sum(1 for term in title_terms if term in lowered)
        overlap_ratio = overlap / len(title_terms)
        has_signature = ("," in candidate) or ("(" in candidate and ")" in candidate)
        if overlap_ratio <= 0.20 and has_signature:
            findings.append(
                Finding(
                    category="topic_mismatch",
                    title="Lead segmentation appears unrelated to the report title",
                    explanation=(
                        "The public descriptive text barely overlaps with the report topic named in the title, "
                        "which is a strong sign that text from a different market page was pasted here."
                    ),
                    confidence=0.92,
                    source="rule",
                    evidence=[
                        report.card_title or report.h1,
                        candidate,
                    ],
                )
            )
            break

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


def _significant_terms(text: str) -> list[str]:
    raw_terms = re.findall(r"[a-zA-Z]{4,}", text.lower())
    return [
        term
        for term in raw_terms
        if term not in GENERIC_TITLE_WORDS
    ]


def _trim_after_marker(text: str, marker: str) -> str:
    if marker.lower() not in text.lower():
        return ""
    return re.split(re.escape(marker), text, flags=re.I, maxsplit=1)[1].strip(" .,:;-")
