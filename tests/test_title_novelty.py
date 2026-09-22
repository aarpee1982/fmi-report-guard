from __future__ import annotations

from dataclasses import dataclass

from fmi_report_guard.title_index import make_indexed_title
from fmi_report_guard.title_novelty import (
    JevPairScore,
    TitleRetriever,
    TypeSafeJevClient,
    assess_title_novelty,
)


def _corpus():
    return [
        make_indexed_title(
            url="https://example.test/egg-wash-substitutes",
            title="Egg Wash Substitutes Market",
        ),
        make_indexed_title(
            url="https://example.test/commercial-vehicle-brake-chambers",
            title="Commercial Vehicle Brake Chambers Market",
        ),
        make_indexed_title(
            url="https://example.test/beverage-packaging",
            title="Beverage Packaging Market",
        ),
    ]


@dataclass
class FakeJevClient:
    model: str = "jev-test"

    def score_pair(self, proposed_title: str, existing_title: str) -> JevPairScore:
        if existing_title == "Egg Wash Substitutes Market":
            return JevPairScore(0.94, 0.04, 0.01, self.model, 20, 3)
        return JevPairScore(0.05, 0.08, 0.02, self.model, 20, 3)


@dataclass
class ScopeOverlapJevClient:
    model: str = "jev-test"

    def score_pair(self, proposed_title: str, existing_title: str) -> JevPairScore:
        return JevPairScore(0.20, 0.84, 0.03, self.model)


def test_exact_or_plural_collision_rejects_without_jev() -> None:
    result = assess_title_novelty(
        proposed_title="Commercial Vehicle Brake Chamber Market",
        corpus=_corpus(),
    )

    assert result.status == "reject"
    assert result.matches[0].title == "Commercial Vehicle Brake Chambers Market"


def test_missing_key_returns_local_shortlist() -> None:
    result = assess_title_novelty(
        proposed_title="Egg Wash Alternatives Market",
        aliases=["Egg Wash Substitutes Market"],
        corpus=_corpus(),
        top_k=2,
    )

    assert result.status == "needs_jev"
    assert result.matches[0].title == "Egg Wash Substitutes Market"


def test_jev_duplicate_probability_rejects_title() -> None:
    result = assess_title_novelty(
        proposed_title="Egg Wash Alternatives Market",
        aliases=["Egg Wash Substitutes Market"],
        corpus=TitleRetriever(_corpus()),
        top_k=3,
        jev_client=FakeJevClient(),  # type: ignore[arg-type]
    )

    assert result.status == "reject"
    assert result.input_tokens == 60
    assert result.output_tokens == 9


def test_jev_scope_overlap_routes_title_to_review() -> None:
    result = assess_title_novelty(
        proposed_title="Vehicle Brake Systems Market",
        corpus=_corpus(),
        top_k=3,
        jev_client=ScopeOverlapJevClient(),  # type: ignore[arg-type]
    )

    assert result.status == "review"
    assert "parent, child, or subset" in result.reason


def test_low_jev_probabilities_allow_provisional_pass() -> None:
    result = assess_title_novelty(
        proposed_title="Novel Fermentation Sensors Market",
        corpus=[
            make_indexed_title(
                url="https://example.test/beverage-packaging",
                title="Beverage Packaging Market",
            )
        ],
        top_k=1,
        jev_client=FakeJevClient(),  # type: ignore[arg-type]
    )

    assert result.status == "pass"
    assert result.thresholds_calibrated is False


class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {
            "model": "jev-1.13.0",
            "answers": {
                "same_market": {"type": "noul", "noul": 0.91},
                "scope_overlap": {"type": "noul", "noul": 0.12},
                "geography_variant": {"type": "noul", "noul": 0.03},
            },
            "usage": {"input_tokens": 123, "output_tokens": 20},
        }


def test_typesafe_request_uses_named_state_and_three_nouls() -> None:
    captured = {}

    def transport(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    client = TypeSafeJevClient(api_key="secret", transport=transport)
    score = client.score_pair("Pimple Patches Market", "Anti-Acne Dermal Patch Market")

    assert captured["json"]["state"] == {
        "proposed_title": "Pimple Patches Market",
        "existing_fmi_title": "Anti-Acne Dermal Patch Market",
    }
    assert set(captured["json"]["questions"]) == {
        "same_market",
        "scope_overlap",
        "geography_variant",
    }
    assert all(
        question["type"] == "noul"
        for question in captured["json"]["questions"].values()
    )
    assert score.same_market == 0.91
    assert score.input_tokens == 123
