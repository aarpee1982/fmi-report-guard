from __future__ import annotations

from dataclasses import dataclass
import re

from .models import Finding, ReportPage


MONEY_RE = re.compile(
    r"(?:USD|US\$|\$)\s*([\d,]+(?:\.\d+)?)\s*(thousand|million|billion|trillion)?",
    flags=re.I,
)
CAGR_RE = re.compile(r"([\d]+(?:\.\d+)?)\s*%\s*(?:CAGR|compound annual growth rate)?", flags=re.I)
PERIOD_RE = re.compile(r"\b(20\d{2})\s*(?:-|to|through|until)\s*(20\d{2})\b", flags=re.I)
YEAR_RE = re.compile(r"\b(20\d{2})\b")

UNIT_TO_MN = {
    "thousand": 0.001,
    "million": 1,
    "billion": 1000,
    "trillion": 1_000_000,
}

AUTHORITY_SIGNALS = {
    ".gov",
    "administration",
    "annual report",
    "association",
    "bureau",
    "commission",
    "company filing",
    "department",
    "epa",
    "european commission",
    "fda",
    "filing",
    "government",
    "iec",
    "iso",
    "ministry",
    "oecd",
    "regulator",
    "regulatory",
    "sec filing",
    "standards organization",
    "trade association",
    "who",
}

IMPORTANT_CLAIM_SIGNALS = {
    "approval",
    "approved",
    "clinical",
    "compliance",
    "funding",
    "investment",
    "launched",
    "mandate",
    "merger",
    "policy",
    "regulation",
    "standard",
    "subsidy",
}

GROWTH_REASON_SIGNALS = {
    "adoption",
    "because",
    "demand",
    "driven by",
    "due to",
    "investment",
    "need for",
    "regulation",
    "rising",
    "supported by",
    "use of",
}

HOW_MARKET_SIGNALS = {
    "buyer",
    "customers",
    "deployment",
    "end user",
    "enterprise",
    "manufacturer",
    "provider",
    "regulation",
    "technology",
    "vendor",
}

SEGMENT_SIGNALS = {
    "application",
    "country",
    "end user",
    "end-use",
    "region",
    "segment",
    "type",
    "use case",
}

NON_INDUSTRIAL_TITLE_SIGNALS = {
    "ai",
    "analytics",
    "cloud",
    "cybersecurity",
    "digital",
    "fintech",
    "healthcare service",
    "platform",
    "saas",
    "security software",
    "software",
}

INDUSTRIAL_CONTAMINATION_SIGNALS = {
    "commodity pricing",
    "export volume",
    "feedstock",
    "import/export",
    "manufacturing capacity",
    "plant utilization",
    "production capacity",
    "raw material",
    "refinery",
}

COUNTRY_OR_REGION_WORDS = {
    "asia",
    "australia",
    "canada",
    "china",
    "europe",
    "france",
    "germany",
    "india",
    "italy",
    "japan",
    "north america",
    "new zealand",
    "australia-new zealand",
    "brazil",
    "mexico",
    "gcc",
    "asean",
    "south korea",
    "uk",
    "united kingdom",
    "united states",
    "usa",
}

KNOWN_TERM_FIXES = {
    "deception stach": "Deception Stack",
    "unites states": "United States",
    "assesment": "assessment",
    "forcast": "forecast",
    "compund annual growth rate": "compound annual growth rate",
}


@dataclass(frozen=True, slots=True)
class TextBlock:
    location: str
    text: str


@dataclass(frozen=True, slots=True)
class MoneyMention:
    location: str
    sentence: str
    year: int
    amount_usd_mn: float
    display: str


@dataclass(frozen=True, slots=True)
class CagrMention:
    location: str
    sentence: str
    value: float
    display: str


def run_aio_audit(report: ReportPage) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(check_number_consistency(report))
    findings.extend(check_forecast_period_consistency(report))
    findings.extend(check_content_contamination(report))
    findings.extend(check_aio_ready_summary(report))
    findings.extend(check_missing_evidence(report))
    findings.extend(check_what_why_how(report))
    findings.extend(check_faq_quality(report))
    findings.extend(check_segment_country_logic(report))
    findings.extend(check_terminology(report))
    return _dedupe_findings(findings)


def check_number_consistency(report: ReportPage) -> list[Finding]:
    findings: list[Finding] = []
    money_mentions = _extract_global_money_mentions(report)
    for year in sorted({mention.year for mention in money_mentions}):
        mentions = [mention for mention in money_mentions if mention.year == year]
        if len(mentions) < 2:
            continue
        low = min(mentions, key=lambda item: item.amount_usd_mn)
        high = max(mentions, key=lambda item: item.amount_usd_mn)
        if high.amount_usd_mn <= 0:
            continue
        if (high.amount_usd_mn - low.amount_usd_mn) / high.amount_usd_mn > 0.02:
            findings.append(
                _finding(
                    category="number_consistency",
                    title=f"Market value for {year} differs across page sections",
                    explanation=(
                        f"The page exposes {low.display} in {low.location} and {high.display} "
                        f"in {high.location} for {year}."
                    ),
                    uploader_summary=(
                        f"{year} market value changes across the page. Upload team must align the value and unit."
                    ),
                    correction=(
                        f"Use one verified {year} market value and one unit everywhere: summary, snapshot, "
                        "key takeaways, FAQs, metadata, and schema."
                    ),
                    evidence=[
                        f"Metric: {year} market value",
                        f"Location 1: {low.location}",
                        f"Control+F: {_trim(low.sentence)}",
                        f"Location 2: {high.location}",
                        f"Control+F: {_trim(high.sentence)}",
                        "Change with: Replace the incorrect value or unit with the verified market value.",
                    ],
                    confidence=0.93,
                )
            )
            break

    cagr_mentions = _extract_global_cagr_mentions(report)
    if len(cagr_mentions) >= 2:
        low_cagr = min(cagr_mentions, key=lambda item: item.value)
        high_cagr = max(cagr_mentions, key=lambda item: item.value)
        if abs(high_cagr.value - low_cagr.value) > 0.1:
            findings.append(
                _finding(
                    category="number_consistency",
                    title="Global CAGR differs across page sections",
                    explanation=(
                        f"The page exposes {low_cagr.display} in {low_cagr.location} and "
                        f"{high_cagr.display} in {high_cagr.location}."
                    ),
                    uploader_summary="Global CAGR changes across the page and must be aligned.",
                    correction=(
                        "Use the same verified global CAGR everywhere: summary, snapshot, key takeaways, "
                        "FAQs, metadata, and schema."
                    ),
                    evidence=[
                        "Metric: CAGR",
                        f"Location 1: {low_cagr.location}",
                        f"Control+F: {_trim(low_cagr.sentence)}",
                        f"Location 2: {high_cagr.location}",
                        f"Control+F: {_trim(high_cagr.sentence)}",
                        "Change with: Replace the incorrect CAGR with the verified global CAGR.",
                    ],
                    confidence=0.94,
                )
            )

    return findings


def check_forecast_period_consistency(report: ReportPage) -> list[Finding]:
    periods: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for block in _audit_blocks(report):
        if block.location == "full visible page":
            continue
        for sentence in _sentences(block.text):
            lower = sentence.lower()
            if any(keyword in lower for keyword in ("historical", "history", "from 2019", "past")):
                continue
            if not any(keyword in lower for keyword in ("forecast", "cagr", "by ", "through", "period", "outlook")):
                continue
            for match in PERIOD_RE.finditer(sentence.replace("\u2013", "-").replace("\u2014", "-")):
                period = (int(match.group(1)), int(match.group(2)))
                if period[1] <= period[0]:
                    continue
                periods.setdefault(period, []).append((block.location, sentence))

    if len(periods) <= 1:
        return []

    examples = []
    for period, items in sorted(periods.items()):
        location, sentence = items[0]
        examples.append(f"{period[0]}-{period[1]} in {location}: {_trim(sentence)}")

    return [
        _finding(
            category="forecast_period",
            title="Forecast period changes across page sections",
            explanation="The page exposes more than one forecast period across public sections.",
            uploader_summary="Forecast years are mixed. This damages AI extraction and user trust.",
            correction="Use one verified historical, base, estimated, and forecast period across all sections.",
            evidence=[
                *examples[:6],
                "Change with: Align every forecast-period mention to the approved report period.",
            ],
            confidence=0.96,
        )
    ]


def check_content_contamination(report: ReportPage) -> list[Finding]:
    title = _market_title(report)
    text = _page_text(report)
    lower_title = title.lower()
    lower_text = text.lower()
    findings: list[Finding] = []

    if _has_phrase_signal(lower_title, NON_INDUSTRIAL_TITLE_SIGNALS):
        contamination = [signal for signal in INDUSTRIAL_CONTAMINATION_SIGNALS if signal in lower_text]
        if len(contamination) >= 2:
            sentence = _first_sentence_with(text, contamination[0]) or _first_sentence_with(text, contamination[1])
            findings.append(
                _finding(
                    category="content_contamination",
                    title="Wrong-industry manufacturing language appears on a non-industrial report",
                    explanation=(
                        "The title looks like software, cybersecurity, SaaS, cloud, or service-market content, "
                        "but the page includes industrial production or commodity language."
                    ),
                    uploader_summary="Likely copied/wrong-industry text is present on the page.",
                    correction="Remove copied industrial language and replace it with market-specific buyer, vendor, technology, regulation, or end-user drivers.",
                    evidence=[
                        f"Market name: {title}",
                        f"Control+F: {_trim(sentence)}",
                        f"Wrong-language signals: {', '.join(contamination[:5])}",
                        "Change with: Rewrite this section for the actual market scope.",
                    ],
                    confidence=0.91,
                )
            )

    title_tokens = _important_title_tokens(title)
    summary_text = _opening_summary(report)
    overlap = title_tokens & set(re.findall(r"[a-z0-9]+", summary_text.lower()))
    if len(title_tokens) >= 3 and summary_text and len(overlap) / len(title_tokens) < 0.25:
        findings.append(
            _finding(
                category="content_contamination",
                title="Opening summary has weak topic alignment with report title",
                explanation="Few important title terms appear in the opening summary, which can indicate pasted or generic content.",
                uploader_summary="Opening summary may not be about the target market.",
                correction="Rewrite the first summary paragraph so it clearly names the target market and uses the core product, technology, end-user, or country terms from the title.",
                evidence=[
                    f"Market name: {title}",
                    f"Control+F: {_trim(summary_text)}",
                    f"Missing title terms: {', '.join(sorted(title_tokens - overlap)[:8])}",
                    "Change with: Add the target market name and relevant scope terms in the opening summary.",
                ],
                confidence=0.86,
            )
        )

    return findings


def check_aio_ready_summary(report: ReportPage) -> list[Finding]:
    summary = _opening_summary(report)
    words = re.findall(r"\S+", summary)
    lower = summary.lower()
    missing: list[str] = []

    if len(words) < 120:
        missing.append("150-250 word answer-ready opening")
    if "market" not in lower:
        missing.append("clear market definition")
    if not MONEY_RE.search(summary):
        missing.append("market size or forecast value")
    if "cagr" not in lower and not re.search(r"\d+(?:\.\d+)?%", summary):
        missing.append("CAGR")
    if not any(signal in lower for signal in GROWTH_REASON_SIGNALS):
        missing.append("business reason for growth")
    if not any(signal in lower for signal in SEGMENT_SIGNALS):
        missing.append("important segments, countries, regions, or end users")

    if not missing:
        return []

    return [
        _finding(
            category="aio_summary",
            title="Opening summary is not AI Overview ready",
            explanation=(
                "The first 150-250 words do not answer the market definition, growth reason, size, "
                "CAGR, and important segment/country/end-user signals cleanly."
            ),
            uploader_summary="Opening summary is too generic or incomplete for AI extraction.",
            correction=(
                "Rewrite the opening 150-200 words with: what the market is, 2026 value, 2036 value, CAGR, "
                "main growth reason, and leading segment/country/end-user signals."
            ),
            evidence=[
                f"Missing: {', '.join(missing)}",
                f"Control+F: {_trim(summary)}",
                "Change with: Use the recommended opening summary in the AIO audit artifact after verifying numbers.",
            ],
            confidence=0.9,
        )
    ]


def check_missing_evidence(report: ReportPage) -> list[Finding]:
    text = _page_text(report)
    lower = text.lower()
    claim_hits = [signal for signal in IMPORTANT_CLAIM_SIGNALS if signal in lower]
    if not claim_hits:
        return []
    if any(signal in lower for signal in AUTHORITY_SIGNALS):
        return []

    sentence = ""
    for signal in claim_hits:
        sentence = _first_sentence_with(text, signal)
        if sentence:
            break

    return [
        _finding(
            category="missing_evidence",
            title="Important claims lack visible authority signals",
            explanation=(
                "The page makes claim types that usually need a government, regulator, company filing, "
                "standards body, trade association, or first-party company signal, but no such signal is visible."
            ),
            uploader_summary="Important growth or company/regulatory claims need evidence.",
            correction="Add credible source support or remove unsupported regulatory, company, investment, launch, approval, or standards claims.",
            evidence=[
                f"Claim signal(s): {', '.join(claim_hits[:6])}",
                f"Control+F: {_trim(sentence)}",
                "Change with: Add a credible source-backed sentence or remove the unsupported claim.",
            ],
            confidence=0.86,
        )
    ]


def check_what_why_how(report: ReportPage) -> list[Finding]:
    summary = _opening_summary(report)
    lower = summary.lower()
    has_size = bool(MONEY_RE.search(summary) or "cagr" in lower)
    if not has_size:
        return []
    has_why = any(signal in lower for signal in GROWTH_REASON_SIGNALS)
    has_how = any(signal in lower for signal in HOW_MARKET_SIGNALS)
    if has_why and has_how:
        return []

    missing = []
    if not has_why:
        missing.append("why buyers are adopting it")
    if not has_how:
        missing.append("how vendors, technologies, regulations, or end users shape demand")

    return [
        _finding(
            category="what_why_how",
            title="Market explanation repeats numbers without enough business logic",
            explanation="The summary mentions market figures but does not sufficiently explain what is changing, why buyers adopt, or how demand is shaped.",
            uploader_summary="Summary needs business logic, not only size and CAGR.",
            correction="Add one concrete driver sentence and one how-demand-forms sentence tied to buyers, vendors, technologies, regulations, or end users.",
            evidence=[
                f"Missing: {', '.join(missing)}",
                f"Control+F: {_trim(summary)}",
                "Change with: Add specific adoption and demand-shaping explanation after the market-size sentence.",
            ],
            confidence=0.87,
        )
    ]


def check_faq_quality(report: ReportPage) -> list[Finding]:
    findings: list[Finding] = []
    if not report.faq_items:
        return [
            _finding(
                category="faq_quality",
                title="FAQ schema or FAQ content is missing",
                explanation="No FAQ items were extracted from the page/schema.",
                uploader_summary="FAQ section is missing or not exposed to schema extraction.",
                correction="Add useful FAQs with consistent market size, forecast value, CAGR, leading segment, leading country, and growth-driver answers.",
                evidence=["Control+F: FAQ", "Change with: Add FAQPage schema and visible FAQ answers."],
                confidence=0.88,
            )
        ]

    answer_fingerprints: dict[str, int] = {}
    for index, faq in enumerate(report.faq_items, start=1):
        question = faq.get("question", "")
        answer = faq.get("answer", "")
        q_lower = question.lower()
        a_lower = answer.lower()
        if any(keyword in q_lower for keyword in ("market size", "how big", "worth", "cagr", "growth rate", "forecast value")):
            needs_number = any(keyword in q_lower for keyword in ("market size", "how big", "worth", "cagr", "growth rate", "forecast value"))
            has_number = bool(MONEY_RE.search(answer) or re.search(r"\d+(?:\.\d+)?%", answer) or YEAR_RE.search(answer))
            if needs_number and not has_number:
                findings.append(
                    _finding(
                        category="faq_quality",
                        title=f"FAQ {index} gives a vague answer to a numeric query",
                        explanation="The FAQ asks a size, value, CAGR, or forecast question but the answer has no extractable number or year.",
                        uploader_summary="FAQ answer is not independently useful for AI extraction.",
                        correction="Rewrite the FAQ answer with the verified value, unit, year, and CAGR where relevant.",
                        evidence=[
                            f"FAQ: {question}",
                            f"Control+F: {_trim(answer)}",
                            "Change with: Add the verified numeric answer.",
                        ],
                        confidence=0.9,
                    )
                )

        fingerprint = re.sub(r"[^a-z0-9]+", " ", a_lower).strip()
        if fingerprint:
            answer_fingerprints[fingerprint] = answer_fingerprints.get(fingerprint, 0) + 1

    repeated = [fingerprint for fingerprint, count in answer_fingerprints.items() if count > 1 and len(fingerprint) > 40]
    if repeated:
        findings.append(
            _finding(
                category="faq_quality",
                title="FAQ answers repeat the same content",
                explanation="Two or more FAQ answers appear identical or near-identical.",
                uploader_summary="FAQ section repeats itself and should be merged or rewritten.",
                correction="Merge duplicate FAQs or rewrite each FAQ so it answers a distinct search query.",
                evidence=[
                    f"Control+F: {_trim(repeated[0])}",
                    "Change with: Keep one answer and rewrite/remove the duplicate FAQ.",
                ],
                confidence=0.88,
            )
        )

    return findings[:4]


def check_segment_country_logic(report: ReportPage) -> list[Finding]:
    text = " ".join(
        [
            report.meta_description,
            report.lead_summary,
            " ".join(report.summary_paragraphs[:4]),
            " ".join(f"{item.get('question', '')} {item.get('answer', '')}" for item in report.faq_items[:8]),
        ]
    )
    leader_sentences = []
    for sentence in _sentences(text):
        lower = sentence.lower()
        if not any(term in lower for term in ("lead", "dominat", "largest", "fastest-growing", "fastest growing")):
            continue
        if not any(scope in lower for scope in ("global", "overall", "market share", "share of the market")):
            continue
        if any(place in lower for place in COUNTRY_OR_REGION_WORDS):
            leader_sentences.append(sentence)

    if len(leader_sentences) < 2:
        return []

    places_by_claim: dict[str, set[str]] = {}
    for sentence in leader_sentences:
        lower = sentence.lower()
        if "largest" in lower or "lead" in lower or "dominat" in lower:
            places = {place for place in COUNTRY_OR_REGION_WORDS if place in lower}
            if places:
                places_by_claim.setdefault("leader", set()).update(places)

    if len(places_by_claim.get("leader", set())) <= 1:
        return []

    examples = leader_sentences[:3]
    return [
        _finding(
            category="segment_country_logic",
            title="Multiple countries or regions are described as leading without explanation",
            explanation="The page appears to name more than one leading country or region without clarifying scope.",
            uploader_summary="Regional/country leadership claims may contradict each other.",
            correction="Clarify whether each claim is about global share, regional share, country growth, or a specific segment.",
            evidence=[
                *[f"Control+F: {_trim(sentence)}" for sentence in examples],
                "Change with: Use one global leader claim, or explain the scope difference for each leader claim.",
            ],
            confidence=0.82,
        )
    ]


def check_terminology(report: ReportPage) -> list[Finding]:
    text = _page_text(report)
    lower = text.lower()
    findings: list[Finding] = []

    for typo, replacement in KNOWN_TERM_FIXES.items():
        if typo in lower:
            sentence = _first_sentence_with(text, typo)
            findings.append(
                _finding(
                    category="terminology",
                    title=f"Terminology typo: {typo}",
                    explanation=f"The page contains '{typo}', which should be '{replacement}'.",
                    uploader_summary="Terminology typo needs correction.",
                    correction=f"Replace '{typo}' with '{replacement}' everywhere.",
                    evidence=[
                        f"Control+F: {_trim(sentence)}",
                        f"Change with: {replacement}",
                    ],
                    confidence=0.98,
                )
            )

    duplicate = re.search(r"\b([A-Za-z]{4,})\s+\1\b", text, flags=re.I)
    if duplicate:
        if duplicate.group(1).lower() not in {"market", "report", "analysis", "future", "insights"}:
            sentence = _first_sentence_with(text, duplicate.group(0)) or duplicate.group(0)
            findings.append(
                _finding(
                    category="terminology",
                    title="Duplicate word appears in page content",
                    explanation=f"The page repeats the word '{duplicate.group(1)}' consecutively.",
                    uploader_summary="Duplicate word should be removed.",
                    correction=f"Remove one repeated '{duplicate.group(1)}'.",
                    evidence=[
                        f"Control+F: {_trim(sentence)}",
                        f"Change with: {sentence.replace(duplicate.group(0), duplicate.group(1), 1)}",
                    ],
                    confidence=0.9,
                )
            )

    if "â" in text or "�" in text:
        sentence = _first_sentence_with(text, "â") or _first_sentence_with(text, "�") or text[:180]
        findings.append(
            _finding(
                category="terminology",
                title="Broken character encoding appears in page content",
                explanation="The page includes mojibake or replacement characters.",
                uploader_summary="Broken characters need cleanup before publish.",
                correction="Replace broken encoded characters with normal punctuation or plain text.",
                evidence=[
                    f"Control+F: {_trim(sentence)}",
                    "Change with: Correct the broken character sequence.",
                ],
                confidence=0.96,
            )
        )

    return findings[:3]


def build_aio_audit_report(report: ReportPage, findings: list[Finding]) -> str:
    score = aio_readiness_score(findings)
    decision = aio_decision(score, findings)
    lines = [
        f"# AIO Audit: {_market_title(report)}",
        "",
        f"Market name: {_market_title(report)}",
        f"URL: {report.url}",
        "",
        f"## A. Overall AI readiness score: {score}/10",
        f"AIO summary score: {aio_summary_score(report)}/10",
        "",
        "## B. Pass / fail decision:",
        f"- {decision}",
        "",
        "## C. Critical issues:",
    ]

    critical = _critical_findings(findings)
    if critical:
        for finding in critical:
            lines.append(f"- {finding.title}: {finding.uploader_summary or finding.explanation}")
    else:
        lines.append("- None detected.")

    lines.extend(["", "## D. Number mismatch table:", ""])
    number_findings = [
        finding
        for finding in findings
        if finding.category in {"number_consistency", "numeric_inconsistency", "unit_scale_error", "forecast_period", "benchmark_hierarchy"}
    ]
    lines.extend(_number_mismatch_table(number_findings))

    lines.extend(["", "## E. Content contamination:"])
    lines.extend(_finding_lines(findings, {"content_contamination"}))

    lines.extend(["", "## F. Missing evidence:"])
    lines.append(f"- Evidence/authority grade: {evidence_authority_grade(report)}")
    lines.extend(_finding_lines(findings, {"missing_evidence"}))

    lines.extend(["", "## G. FAQ fixes:"])
    lines.append(f"- FAQ quality score: {faq_quality_score(report, findings)}/10")
    lines.extend(_finding_lines(findings, {"faq_quality"}))

    lines.extend(["", "## H. Recommended improved opening summary:"])
    lines.append(_recommended_opening_summary(report))

    lines.extend(["", "## I. Final action checklist:"])
    lines.extend(
        [
            "- Align market size, forecast value, CAGR, units, and forecast years across summary, snapshot, FAQ, metadata, and schema.",
            "- Fix or remove every critical Control+F sentence listed above.",
            "- Add source support for regulatory, company, standards, approval, funding, or launch claims.",
            "- Confirm segment, country, and benchmark hierarchy logic against FMI global benchmark DB.",
            "- Re-run FMI Report Guard after edits and publish only when no critical findings remain.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def aio_readiness_score(findings: list[Finding]) -> int:
    penalties = {
        "benchmark_hierarchy": 2.0,
        "number_consistency": 1.8,
        "numeric_inconsistency": 1.8,
        "unit_scale_error": 1.8,
        "forecast_period": 1.5,
        "content_contamination": 1.7,
        "aio_summary": 1.2,
        "missing_evidence": 1.0,
        "what_why_how": 0.9,
        "faq_quality": 0.9,
        "segment_country_logic": 1.0,
        "terminology": 0.4,
    }
    total = 0.0
    for finding in findings:
        total += penalties.get(finding.category, 0.6)
    return max(1, min(10, int(round(10 - total))))


def aio_summary_score(report: ReportPage) -> int:
    summary = _opening_summary(report)
    lower = summary.lower()
    checks = [
        len(re.findall(r"\S+", summary)) >= 120,
        "market" in lower,
        bool(MONEY_RE.search(summary)),
        "cagr" in lower or bool(re.search(r"\d+(?:\.\d+)?%", summary)),
        any(signal in lower for signal in GROWTH_REASON_SIGNALS),
        any(signal in lower for signal in SEGMENT_SIGNALS),
    ]
    return max(1, round(sum(1 for passed in checks if passed) / len(checks) * 10))


def evidence_authority_grade(report: ReportPage) -> str:
    text = _page_text(report).lower()
    claim_count = sum(1 for signal in IMPORTANT_CLAIM_SIGNALS if signal in text)
    authority_count = sum(1 for signal in AUTHORITY_SIGNALS if signal in text)
    if claim_count == 0:
        return "Adequate - no high-evidence claim type detected by rules"
    if authority_count >= 2:
        return "Strong - multiple authority signals visible"
    if authority_count == 1:
        return "Basic - one authority signal visible"
    return "Weak - important claims visible without authority signals"


def faq_quality_score(report: ReportPage, findings: list[Finding]) -> int:
    if not report.faq_items:
        return 1
    faq_penalty = sum(2 for finding in findings if finding.category == "faq_quality")
    base = 10 if len(report.faq_items) >= 3 else 7
    return max(1, min(10, base - faq_penalty))


def aio_decision(score: int, findings: list[Finding]) -> str:
    critical_categories = {
        "benchmark_hierarchy",
        "content_contamination",
        "forecast_period",
        "number_consistency",
        "numeric_inconsistency",
        "unit_scale_error",
    }
    if score >= 8 and not any(finding.category in critical_categories for finding in findings):
        return "Ready to publish"
    if score >= 6:
        return "Publish after minor fixes"
    return "Do not publish until corrected"


def _audit_blocks(report: ReportPage) -> list[TextBlock]:
    faq_text = " ".join(
        f"{item.get('question', '')} {item.get('answer', '')}" for item in report.faq_items
    )
    return [
        TextBlock("title/meta description", f"{report.page_title} {report.meta_description} {report.metadata_text}"),
        TextBlock("opening summary", _opening_summary(report)),
        TextBlock("market snapshot/table", " ".join(report.table_texts[:8])),
        TextBlock("key takeaways/segment/regional sections", " ".join(report.summary_paragraphs[:8])),
        TextBlock("FAQ", faq_text),
        TextBlock("schema-visible content", report.schema_text),
        TextBlock("full visible page", report.visible_text[:30000]),
    ]


def _extract_global_money_mentions(report: ReportPage) -> list[MoneyMention]:
    mentions: list[MoneyMention] = []
    for block in _audit_blocks(report):
        for sentence in _sentences(block.text):
            if not _is_global_market_size_sentence(sentence):
                continue
            years = [(int(match.group(1)), match.start()) for match in YEAR_RE.finditer(sentence)]
            if not years:
                continue
            for match in MONEY_RE.finditer(sentence):
                amount = float(match.group(1).replace(",", ""))
                unit = (match.group(2) or "million").lower()
                nearest_year = min(years, key=lambda item: abs(item[1] - match.start()))[0]
                display = f"USD {match.group(1)} {unit}"
                mentions.append(
                    MoneyMention(
                        location=block.location,
                        sentence=sentence,
                        year=nearest_year,
                        amount_usd_mn=amount * UNIT_TO_MN.get(unit, 1),
                        display=display,
                    )
                )
    return mentions


def _extract_global_cagr_mentions(report: ReportPage) -> list[CagrMention]:
    mentions: list[CagrMention] = []
    for block in _audit_blocks(report):
        for sentence in _sentences(block.text):
            if "cagr" not in sentence.lower() and "compound annual growth rate" not in sentence.lower():
                continue
            if not _is_global_cagr_sentence(sentence):
                continue
            for match in CAGR_RE.finditer(sentence):
                value = float(match.group(1))
                if value > 100:
                    continue
                mentions.append(
                    CagrMention(
                        location=block.location,
                        sentence=sentence,
                        value=value,
                        display=f"{value:g}%",
                    )
                )
    return mentions


def _is_global_market_size_sentence(sentence: str) -> bool:
    lower = sentence.lower()
    if not MONEY_RE.search(sentence):
        return False
    if any(skip in lower for skip in ("incremental opportunity", "absolute dollar", "investment", "funding round")):
        return False
    if any(skip in lower for skip in (" segment ", " country ", " regional ", " revenue share", "share of")):
        return False
    if any(place in lower for place in COUNTRY_OR_REGION_WORDS):
        return False
    return any(
        signal in lower
        for signal in (
            "market size",
            "market value",
            "valued at",
            "estimated at",
            "estimated to be valued",
            "expected to reach",
            "projected to reach",
            "anticipated to reach",
            "worth",
        )
    )


def _is_global_cagr_sentence(sentence: str) -> bool:
    lower = sentence.lower()
    if any(word in lower for word in COUNTRY_OR_REGION_WORDS):
        return False
    if any(skip in lower for skip in ("segment", "country", "regional", "region ", "end user")):
        return False
    return "market" in lower or "global" in lower


def _opening_summary(report: ReportPage) -> str:
    parts = [report.lead_summary, *report.summary_paragraphs[:3]]
    text = " ".join(part for part in parts if part).strip()
    if len(re.findall(r"\S+", text)) >= 80:
        return text
    if report.visible_text:
        words = re.findall(r"\S+", report.visible_text)
        return " ".join(words[:240])
    return text


def _page_text(report: ReportPage) -> str:
    return " ".join(
        part
        for part in (
            report.page_title,
            report.h1,
            report.meta_description,
            report.metadata_text,
            report.lead_summary,
            " ".join(report.headings),
            " ".join(report.summary_paragraphs),
            " ".join(report.table_texts),
            " ".join(f"{item.get('question', '')} {item.get('answer', '')}" for item in report.faq_items),
            report.schema_text,
            report.visible_text[:40000],
        )
        if part
    )


def _market_title(report: ReportPage) -> str:
    return report.card_title or report.h1 or report.page_title or report.url


def _important_title_tokens(title: str) -> set[str]:
    stop = {
        "analysis",
        "forecast",
        "global",
        "industry",
        "market",
        "outlook",
        "report",
        "share",
        "size",
        "the",
        "and",
        "for",
        "with",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", title.lower())
        if len(token) > 2 and token not in stop and not token.isdigit()
    }


def _recommended_opening_summary(report: ReportPage) -> str:
    title = _market_title(report)
    money_mentions = _extract_global_money_mentions(report)
    cagr_mentions = _extract_global_cagr_mentions(report)
    start = min(money_mentions, key=lambda item: item.year) if money_mentions else None
    end = max(money_mentions, key=lambda item: item.year) if money_mentions else None
    cagr = cagr_mentions[0].display if cagr_mentions else ""
    reason = _growth_reason_sentence(report)
    segment = _segment_sentence(report)
    if reason == segment:
        reason = "Growth should be tied to the strongest verified buyer, regulatory, technology, or end-user driver."

    if not (start and end and cagr):
        return (
            f"The opening summary for {title} should be rewritten after the editor verifies the approved "
            "2026 value, 2036 value, CAGR, forecast period, leading segment, leading country or region, "
            "and primary growth driver. Current page text does not expose enough consistent values for an "
            "automatic replacement summary."
        )

    return (
        f"The {title} covers demand, revenue, and adoption trends for the products and services defined in "
        f"this report scope. FMI values the market at {start.display} in {start.year} and expects it to reach "
        f"{end.display} by {end.year}, reflecting a {cagr} CAGR over the forecast period. {reason} "
        f"{segment} The summary should keep these same figures across the snapshot table, key takeaways, "
        "segment analysis, country analysis, FAQs, metadata, and schema so AI search systems can extract one "
        "clear answer without conflicting values."
    )


def _growth_reason_sentence(report: ReportPage) -> str:
    for sentence in _sentences(_opening_summary(report)):
        lower = sentence.lower()
        if any(signal in lower for signal in GROWTH_REASON_SIGNALS) and not MONEY_RE.search(sentence) and "cagr" not in lower:
            return _trim(sentence, 240)
    return "Growth should be tied to the strongest verified buyer, regulatory, technology, or end-user driver."


def _segment_sentence(report: ReportPage) -> str:
    for sentence in _sentences(_opening_summary(report)):
        lower = sentence.lower()
        if any(signal in lower for signal in SEGMENT_SIGNALS):
            return _trim(sentence, 240)
    return "Editors should name the leading segment, fastest-growing segment, and most important country or region."


def _number_mismatch_table(findings: list[Finding]) -> list[str]:
    lines = [
        "| Metric | Location 1 | Location 2 | Issue | Corrected recommendation |",
        "| --- | --- | --- | --- | --- |",
    ]
    if not findings:
        lines.append("| None detected | - | - | No number mismatch found by deterministic rules. | Recheck manually before publishing. |")
        return lines

    for finding in findings:
        evidence = finding.evidence
        metric = _evidence_value(evidence, "Metric") or finding.category
        location_1 = _evidence_value(evidence, "Location 1") or "-"
        location_2 = _evidence_value(evidence, "Location 2") or "-"
        issue = finding.title.replace("|", "/")
        recommendation = finding.correction_instruction.replace("|", "/")
        lines.append(f"| {metric} | {location_1} | {location_2} | {issue} | {recommendation} |")
    return lines


def _finding_lines(findings: list[Finding], categories: set[str]) -> list[str]:
    selected = [finding for finding in findings if finding.category in categories]
    if not selected:
        return ["- None detected."]
    lines: list[str] = []
    for finding in selected:
        lines.append(f"- {finding.title}: {finding.uploader_summary or finding.explanation}")
        control_f = [item for item in finding.evidence if item.startswith("Control+F:")]
        if control_f:
            lines.append(f"  - {control_f[0]}")
        lines.append(f"  - Change with: {finding.correction_instruction}")
    return lines


def _critical_findings(findings: list[Finding]) -> list[Finding]:
    critical_categories = {
        "benchmark_hierarchy",
        "content_contamination",
        "forecast_period",
        "number_consistency",
        "numeric_inconsistency",
        "unit_scale_error",
    }
    return [finding for finding in findings if finding.category in critical_categories]


def _finding(
    *,
    category: str,
    title: str,
    explanation: str,
    uploader_summary: str,
    correction: str,
    evidence: list[str],
    confidence: float,
) -> Finding:
    return Finding(
        category=category,
        title=title,
        explanation=explanation,
        uploader_summary=uploader_summary,
        correction_instruction=correction,
        confidence=confidence,
        source="aio_rule",
        evidence=evidence,
    )


def _sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def _first_sentence_with(text: str, needle: str) -> str:
    needle_lower = needle.lower()
    for sentence in _sentences(text):
        if needle_lower in sentence.lower():
            return sentence
    return ""


def _trim(text: str, max_length: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _evidence_value(evidence: list[str], key: str) -> str:
    prefix = f"{key}:"
    for item in evidence:
        if item.startswith(prefix):
            return item.removeprefix(prefix).strip()
    return ""


def _has_phrase_signal(text: str, signals: set[str]) -> bool:
    for signal in signals:
        if " " in signal or "-" in signal:
            if signal in text:
                return True
            continue
        if re.search(rf"\b{re.escape(signal)}\b", text):
            return True
    return False


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    deduped: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.category, finding.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped
