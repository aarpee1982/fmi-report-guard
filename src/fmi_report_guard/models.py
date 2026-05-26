from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class ReportCard:
    title: str
    url: str
    summary: str
    published_on: str


@dataclass(slots=True)
class ReportPage:
    url: str
    card_title: str
    card_summary: str
    card_published_on: str
    page_title: str
    h1: str
    meta_description: str
    lead_summary: str
    publish_date: str
    summary_paragraphs: list[str] = field(default_factory=list)
    competitive_paragraphs: list[str] = field(default_factory=list)
    faq_items: list[dict[str, str]] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    table_texts: list[str] = field(default_factory=list)
    metadata_text: str = ""
    schema_text: str = ""
    visible_text: str = ""

    def as_prompt_payload(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("schema_text", "visible_text"):
            if isinstance(payload.get(key), str):
                payload[key] = str(payload[key])[:12000]
        return payload


@dataclass(slots=True)
class Finding:
    category: str
    title: str
    explanation: str
    uploader_summary: str
    correction_instruction: str
    confidence: float
    source: str
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReviewResult:
    report: ReportPage
    findings: list[Finding] = field(default_factory=list)
    issue_title: str = ""
    issue_body: str = ""
