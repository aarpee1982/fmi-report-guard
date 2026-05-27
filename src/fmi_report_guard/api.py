from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, Field


DEFAULT_ALLOWED_ORIGINS = [
    "https://fmi-benchmark-checker.onrender.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
MAX_MATCHES = 20


class CandidateInput(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    estimated_year: int = Field(ge=2000, le=2100)
    estimated_value_usd_mn: float = Field(gt=0)
    forecast_year: int = Field(ge=2000, le=2100)
    forecast_value_usd_mn: float = Field(gt=0)
    cagr_percent: float = Field(ge=-50, le=200)


class BenchmarkInput(BaseModel):
    market_name: str = Field(min_length=3, max_length=220)
    url: str = Field(default="", max_length=500)
    category: str = Field(default="", max_length=160)
    estimated_year: int = Field(ge=2000, le=2100)
    estimated_value_usd_mn: float = Field(gt=0)
    forecast_year: int = Field(ge=2000, le=2100)
    forecast_value_usd_mn: float = Field(gt=0)
    cagr_percent: float = Field(ge=-50, le=200)


class MatchInput(BaseModel):
    relationship_hint: str = Field(default="", max_length=80)
    issue_hint: str = Field(default="", max_length=800)
    recommendation_hint: str = Field(default="", max_length=800)
    benchmark: BenchmarkInput


class JudgeRequest(BaseModel):
    candidate: CandidateInput
    matches: list[MatchInput] = Field(default_factory=list, max_length=MAX_MATCHES)


def _allowed_origins() -> list[str]:
    configured = os.getenv("ALLOWED_ORIGINS", "")
    if not configured.strip():
        return DEFAULT_ALLOWED_ORIGINS
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


app = FastAPI(title="FMI Benchmark Brain API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
    }


@app.post("/api/judge")
def judge_market_relationship(payload: JudgeRequest) -> dict[str, object]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")

    if not payload.matches:
        return {
            "summary": "No benchmark candidates were found for LLM review.",
            "should_escalate": False,
            "judgments": [],
        }

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    response = client.responses.create(
        model=model,
        input=_build_messages(payload),
        text={
            "format": {
                "type": "json_schema",
                "name": "fmi_market_relationship_judgment",
                "strict": True,
                "schema": _judgment_schema(),
            }
        },
    )

    return json.loads(response.output_text)


def _build_messages(payload: JudgeRequest) -> list[dict[str, str]]:
    prompt = {
        "task": (
            "Judge whether the candidate market title is a parent, child, sibling, adjacent, "
            "or unrelated market compared with each benchmark row. Then decide whether the "
            "entered 2026 and 2036 values violate parent-child market size logic."
        ),
        "rules": [
            "Do not rely only on shared words. Use market taxonomy and business scope.",
            "A child/subset market cannot be larger than its parent market.",
            "A parent market cannot be smaller than an existing child/subset market.",
            "Adjacent markets, ingredients, components, technologies, channels, or end uses are not automatically parent-child.",
            "If relationship is ambiguous, return unclear and do not create a hard violation.",
            "Prefer false negatives over false positives.",
            "Use USD million values exactly as provided.",
            "Return concise editor-friendly text. No markdown.",
        ],
        "candidate": payload.candidate.model_dump(),
        "candidate_unit_note": "All values are normalized to USD million.",
        "benchmark_matches": [match.model_dump() for match in payload.matches[:MAX_MATCHES]],
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a strict market taxonomy and sizing auditor for FMI report titles. "
                "Your job is to reduce false parent-child alarms and catch true hierarchy violations."
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
    ]


def _judgment_schema() -> dict[str, object]:
    relationship_values = [
        "candidate_is_child",
        "candidate_is_parent",
        "sibling_or_adjacent",
        "unrelated",
        "unclear",
    ]
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "should_escalate": {"type": "boolean"},
            "judgments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "market_name": {"type": "string"},
                        "url": {"type": "string"},
                        "relationship": {"type": "string", "enum": relationship_values},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "violates_parent_child_rule": {"type": "boolean"},
                        "issue": {"type": "string"},
                        "control_f": {"type": "string"},
                        "change_with": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "market_name",
                        "url",
                        "relationship",
                        "confidence",
                        "violates_parent_child_rule",
                        "issue",
                        "control_f",
                        "change_with",
                        "reason",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "should_escalate", "judgments"],
        "additionalProperties": False,
    }
