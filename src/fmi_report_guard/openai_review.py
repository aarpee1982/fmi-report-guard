from __future__ import annotations

import json

from openai import OpenAI

from .models import Finding, ReportPage

MIN_CONFIDENCE = 0.90
ALLOWED_CATEGORIES = {
    "numeric_inconsistency",
    "unit_scale_error",
    "company_name_error",
    "company_development_error",
}
MINOR_ERROR_KEYWORDS = {
    "duplicate word",
    "duplicated word",
    "typographical",
    "typographical error",
    "editorial",
    "editorial typo",
    "typo",
    "formatting",
    "metadata",
    "redundant",
    "omits unit",
    "missing unit",
    "wording",
}
SEGMENTATION_KEYWORDS = {
    "segmentation",
    "segment",
    "segmented by",
    "topic mismatch",
    "mismatched product",
    "pasted here",
    "unrelated to the report title",
}
NUMERIC_CONTRADICTION_KEYWORDS = {
    "numeric",
    "number",
    "conflicting",
    "contradictory",
    "inconsistent",
    "more than one",
    "multiple",
    "cagr",
    "forecast year",
    "forecast period",
    "market size",
    "market value",
    "terminal value",
}
UNIT_SCALE_KEYWORDS = {
    "million",
    "billion",
    "thousand",
    "unit scale",
    "scale error",
    "magnitude",
    "order of magnitude",
}
COMPANY_NAME_KEYWORDS = {
    "company name",
    "company names",
    "wrong company",
    "incorrect company",
    "misspelled company",
    "wrong player",
    "incorrect player",
    "stale merged companies",
    "merged companies",
    "still listed separately",
    "listed separately",
    "duplicate company",
    "duplicate companies",
}
COMPANY_DEVELOPMENT_KEYWORDS = {
    "company development",
    "company developments",
    "fabricated development",
    "invented development",
    "fabricated news",
    "invented news",
    "acquisition",
    "acquired",
    "acquire",
    "partnership",
    "partnered",
    "merger",
    "merged",
    "launch",
    "launched",
    "announced",
}


def review_with_openai(
    report: ReportPage,
    api_key: str,
    model: str,
    rule_findings: list[Finding],
) -> list[Finding]:
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=_build_messages(report, rule_findings),
        text={
            "format": {
                "type": "json_schema",
                "name": "fmi_glaring_errors",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "should_alert": {"type": "boolean"},
                        "summary": {"type": "string"},
                        "findings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "category": {
                                        "type": "string",
                                        "enum": sorted(ALLOWED_CATEGORIES),
                                    },
                                    "title": {"type": "string"},
                                    "explanation": {"type": "string"},
                                    "uploader_summary": {"type": "string"},
                                    "correction_instruction": {"type": "string"},
                                    "confidence": {
                                        "type": "number",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                    "evidence": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": [
                                    "category",
                                    "title",
                                    "explanation",
                                    "uploader_summary",
                                    "correction_instruction",
                                    "confidence",
                                    "evidence",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["should_alert", "summary", "findings"],
                    "additionalProperties": False,
                },
            }
        },
    )

    payload = json.loads(response.output_text)
    if not payload.get("should_alert"):
        return []

    findings: list[Finding] = []
    for item in payload.get("findings", []):
        confidence = float(item.get("confidence", 0))
        if confidence < MIN_CONFIDENCE:
            continue
        if not _is_material_finding(item):
            continue
        findings.append(
            Finding(
                category=str(item.get("category", "other")),
                title=str(item.get("title", "Possible glaring issue")),
                explanation=str(item.get("explanation", "")),
                uploader_summary=str(item.get("uploader_summary", "")),
                correction_instruction=str(item.get("correction_instruction", "")),
                confidence=confidence,
                source="openai",
                evidence=[str(value) for value in item.get("evidence", [])[:3]],
            )
        )
    return findings


def _build_messages(report: ReportPage, rule_findings: list[Finding]) -> list[dict[str, str]]:
    rules_text = "\n".join(
        f"- {finding.title}: {finding.explanation}"
        for finding in rule_findings
    ) or "- No rule-based findings."

    prompt = {
        "task": (
            "Review this public market-report page for glaring errors only. "
            "Do not flag stylistic issues, weak writing, or debatable analysis. "
            "Only alert on high-confidence problems in these categories: numeric_inconsistency, "
            "unit_scale_error, company_name_error, and company_development_error."
        ),
        "rules": [
            "If confidence is below 0.90, return no finding.",
            "If the evidence could still plausibly be correct, return no finding.",
            "Use only the supplied page content and widely known corporate facts.",
            "Prefer false negatives over false positives.",
            "Never alert on segmentation alignment, segment taxonomy, or segment completeness by itself.",
            "If the analyst's segmentation could plausibly be intentional, return no finding.",
            "Focus on glaring number inconsistencies, million/billion unit-scale mistakes, wrong company names, and wrong or fabricated company developments only.",
            "For every finding, include a short uploader_summary in plain language for a non-editor.",
            "For every finding, include a single concrete correction_instruction written as a copy-paste sentence for the upload team, starting with 'Please'.",
            "Ignore duplicated words, minor editorial mistakes, metadata wording issues, and missing-unit formatting issues.",
            "Ignore CAGR differences of 1.0 percentage point or less.",
        ],
        "report": report.as_prompt_payload(),
        "rule_findings": rules_text,
    }

    return [
        {
            "role": "system",
            "content": (
                "You are a strict QA reviewer for public market-report pages. "
                "You only report glaring, editor-worthy errors and ignore minor copy-edit problems."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(prompt, ensure_ascii=True),
        },
    ]


def _is_material_finding(item: dict[str, object]) -> bool:
    category = str(item.get("category", "")).strip().lower()
    if category not in ALLOWED_CATEGORIES:
        return False
    if not str(item.get("uploader_summary", "")).strip():
        return False
    if not str(item.get("correction_instruction", "")).strip():
        return False

    text = " ".join(
        str(item.get(key, ""))
        for key in ("category", "title", "explanation", "uploader_summary", "correction_instruction")
    ).lower()

    has_minor_signal = any(keyword in text for keyword in MINOR_ERROR_KEYWORDS)
    has_segmentation_signal = any(keyword in text for keyword in SEGMENTATION_KEYWORDS)

    if has_minor_signal:
        return False

    if has_segmentation_signal and category not in {"company_name_error", "company_development_error"}:
        return False

    if category == "numeric_inconsistency":
        return any(keyword in text for keyword in NUMERIC_CONTRADICTION_KEYWORDS)

    if category == "unit_scale_error":
        return any(keyword in text for keyword in UNIT_SCALE_KEYWORDS)

    if category == "company_name_error":
        return any(keyword in text for keyword in COMPANY_NAME_KEYWORDS)

    if category == "company_development_error":
        return any(keyword in text for keyword in COMPANY_DEVELOPMENT_KEYWORDS)

    return False
