from __future__ import annotations

import json

from openai import OpenAI

from .models import Finding, ReportPage


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
                                    "category": {"type": "string"},
                                    "title": {"type": "string"},
                                    "explanation": {"type": "string"},
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
        if confidence < 0.85:
            continue
        findings.append(
            Finding(
                category=str(item.get("category", "other")),
                title=str(item.get("title", "Possible glaring issue")),
                explanation=str(item.get("explanation", "")),
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
            "Only alert on high-confidence problems such as a clearly wrong topic, obvious pasted segmentation from another market, "
            "material numeric inconsistency, or merged-company duplication based on universally known corporate facts."
        ),
        "rules": [
            "If confidence is below 0.85, return no finding.",
            "If the evidence could still plausibly be correct, return no finding.",
            "Use only the supplied page content and widely known corporate facts.",
            "Prefer false negatives over false positives.",
        ],
        "report": report.as_prompt_payload(),
        "rule_findings": rules_text,
    }

    return [
        {
            "role": "system",
            "content": (
                "You are a strict QA reviewer for public market-report pages. "
                "You only report glaring, editor-worthy errors."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(prompt, ensure_ascii=True),
        },
    ]
