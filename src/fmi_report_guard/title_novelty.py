from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Callable, Iterable

import requests

from .title_index import IndexedTitle, make_indexed_title


DEFAULT_TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_TYPESAFE_MODEL = "jev-latest"


@dataclass(frozen=True, slots=True)
class DecisionThresholds:
    same_market_reject: float = 0.85
    same_market_review: float = 0.55
    scope_overlap_review: float = 0.70
    geography_variant_review: float = 0.80


@dataclass(frozen=True, slots=True)
class ShortlistMatch:
    title: str
    url: str
    lexical_score: float


@dataclass(frozen=True, slots=True)
class JevPairScore:
    same_market: float
    scope_overlap: float
    geography_variant: float
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class AssessedMatch:
    title: str
    url: str
    lexical_score: float
    same_market: float | None = None
    scope_overlap: float | None = None
    geography_variant: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TitleNoveltyResult:
    proposed_title: str
    status: str
    reason: str
    corpus_size: int
    matches: tuple[AssessedMatch, ...]
    typesafe_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    thresholds_calibrated: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class TypeSafeError(RuntimeError):
    pass


class TypeSafeJevClient:
    """Small HTTP client for TypeSafe's System One endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_TYPESAFE_MODEL,
        endpoint: str = DEFAULT_TYPESAFE_ENDPOINT,
        timeout_seconds: float = 120.0,
        max_retries: int = 3,
        transport: Callable[..., requests.Response] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A TypeSafe API key is required.")
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._transport = transport or requests.post

    def score_pair(self, proposed_title: str, existing_title: str) -> JevPairScore:
        payload = {
            "state": {
                "proposed_title": proposed_title,
                "existing_fmi_title": existing_title,
            },
            "model": self.model,
            "questions": _jev_questions(),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(self.max_retries + 1):
            response = self._transport(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            if response.status_code not in {429, 529} and response.status_code < 500:
                break
            if attempt == self.max_retries:
                break
            time.sleep(min(2**attempt, 8))

        if response.status_code >= 400:
            detail = response.text.strip()[:300]
            raise TypeSafeError(f"TypeSafe returned HTTP {response.status_code}: {detail}")

        try:
            data = response.json()
            answers = data["answers"]
            usage = data.get("usage", {})
            return JevPairScore(
                same_market=_noul(answers, "same_market"),
                scope_overlap=_noul(answers, "scope_overlap"),
                geography_variant=_noul(answers, "geography_variant"),
                model=str(data.get("model") or self.model),
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TypeSafeError("TypeSafe returned an unexpected response shape.") from exc


class TitleRetriever:
    """Token-free local shortlist retrieval over the FMI title corpus."""

    def __init__(self, titles: Iterable[IndexedTitle]) -> None:
        self.titles = tuple(titles)
        self._tokens = tuple(set(item.singular_title.split()) for item in self.titles)
        document_frequency: dict[str, int] = {}
        for tokens in self._tokens:
            for token in tokens:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        count = max(len(self.titles), 1)
        self._idf = {
            token: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            for token, frequency in document_frequency.items()
        }

    def exact_match(self, proposed_title: str) -> IndexedTitle | None:
        proposed = make_indexed_title(url="", title=proposed_title)
        for existing in self.titles:
            if existing.normalized_title == proposed.normalized_title:
                return existing
            if existing.singular_title == proposed.singular_title:
                return existing
        return None

    def shortlist(
        self,
        proposed_title: str,
        *,
        aliases: Iterable[str] = (),
        limit: int = 30,
    ) -> list[ShortlistMatch]:
        query_forms = [make_indexed_title(url="", title=proposed_title)]
        query_forms.extend(make_indexed_title(url="", title=alias) for alias in aliases if alias.strip())
        queries = [item for item in query_forms if item.singular_title]
        if not queries or not self.titles:
            return []

        ranked: list[ShortlistMatch] = []
        for existing, existing_tokens in zip(self.titles, self._tokens):
            score = max(
                self._similarity(query.singular_title, set(query.singular_title.split()), existing.singular_title, existing_tokens)
                for query in queries
            )
            ranked.append(
                ShortlistMatch(
                    title=existing.title,
                    url=existing.url,
                    lexical_score=round(score, 6),
                )
            )
        ranked.sort(key=lambda item: (-item.lexical_score, item.title.lower(), item.url))
        return ranked[: max(1, min(limit, len(ranked)))]

    def _similarity(
        self,
        query_text: str,
        query_tokens: set[str],
        candidate_text: str,
        candidate_tokens: set[str],
    ) -> float:
        shared = query_tokens & candidate_tokens
        query_weight = sum(self._idf.get(token, 1.0) for token in query_tokens) or 1.0
        token_score = sum(self._idf.get(token, 1.0) for token in shared) / query_weight
        trigram_score = _dice(_ngrams(query_text.replace(" ", ""), 3), _ngrams(candidate_text.replace(" ", ""), 3))
        containment = 1.0 if query_tokens <= candidate_tokens or candidate_tokens <= query_tokens else 0.0
        return 0.68 * token_score + 0.22 * trigram_score + 0.10 * containment


def assess_title_novelty(
    *,
    proposed_title: str,
    corpus: Iterable[IndexedTitle] | TitleRetriever,
    aliases: Iterable[str] = (),
    top_k: int = 30,
    jev_client: TypeSafeJevClient | None = None,
    thresholds: DecisionThresholds = DecisionThresholds(),
    max_workers: int = 8,
) -> TitleNoveltyResult:
    retriever = corpus if isinstance(corpus, TitleRetriever) else TitleRetriever(corpus)
    corpus_size = len(retriever.titles)
    exact = retriever.exact_match(proposed_title)
    if exact:
        return TitleNoveltyResult(
            proposed_title=proposed_title,
            status="reject",
            reason="Exact or singular/plural FMI title collision found locally.",
            corpus_size=corpus_size,
            matches=(AssessedMatch(exact.title, exact.url, 1.0, same_market=1.0),),
        )

    shortlist = retriever.shortlist(proposed_title, aliases=aliases, limit=top_k)
    if jev_client is None:
        return TitleNoveltyResult(
            proposed_title=proposed_title,
            status="needs_jev",
            reason="Local shortlist is ready, but TYPESAFE_API_KEY is not configured.",
            corpus_size=corpus_size,
            matches=tuple(AssessedMatch(item.title, item.url, item.lexical_score) for item in shortlist),
        )

    assessed: list[AssessedMatch] = []
    models: set[str] = set()
    input_tokens = 0
    output_tokens = 0
    with ThreadPoolExecutor(max_workers=min(max_workers, max(len(shortlist), 1))) as pool:
        futures = {
            pool.submit(jev_client.score_pair, proposed_title, match.title): match
            for match in shortlist
        }
        for future in as_completed(futures):
            match = futures[future]
            try:
                score = future.result()
                models.add(score.model)
                input_tokens += score.input_tokens
                output_tokens += score.output_tokens
                assessed.append(
                    AssessedMatch(
                        match.title,
                        match.url,
                        match.lexical_score,
                        score.same_market,
                        score.scope_overlap,
                        score.geography_variant,
                    )
                )
            except (requests.RequestException, TypeSafeError) as exc:
                assessed.append(
                    AssessedMatch(match.title, match.url, match.lexical_score, error=str(exc))
                )

    assessed.sort(
        key=lambda item: (
            -(item.same_market if item.same_market is not None else -1.0),
            -item.lexical_score,
        )
    )
    status, reason = _decide(assessed, thresholds)
    return TitleNoveltyResult(
        proposed_title=proposed_title,
        status=status,
        reason=reason,
        corpus_size=corpus_size,
        matches=tuple(assessed),
        typesafe_model=", ".join(sorted(models)) or jev_client.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _decide(matches: list[AssessedMatch], thresholds: DecisionThresholds) -> tuple[str, str]:
    successful = [match for match in matches if match.same_market is not None]
    if any((match.same_market or 0) >= thresholds.same_market_reject for match in successful):
        return "reject", "Jev found a high-probability duplicate market."
    if any(match.error for match in matches):
        return "review", "One or more Jev comparisons failed, so the title cannot pass automatically."
    if any((match.same_market or 0) >= thresholds.same_market_review for match in successful):
        return "review", "Jev found a possible duplicate market that needs human review."
    if any((match.scope_overlap or 0) >= thresholds.scope_overlap_review for match in successful):
        return "review", "Jev found a likely parent, child, or subset relationship."
    if any((match.geography_variant or 0) >= thresholds.geography_variant_review for match in successful):
        return "review", "Jev found the same core market with a different geographic scope."
    if not successful:
        return "review", "No Jev comparisons completed successfully."
    return "pass", "No material FMI title collision was found in the retrieved shortlist."


def _jev_questions() -> dict[str, dict[str, object]]:
    return {
        "same_market": {
            "type": "noul",
            "instructions": (
                "Do `proposed_title` and `existing_fmi_title` describe substantially the same "
                "commercial market-report topic?"
            ),
            "criteria": {
                "true": (
                    "They cover the same product or service market after allowing for synonyms, "
                    "acronyms, spelling, word order, and singular/plural wording. Publishing both "
                    "would substantially duplicate the topic."
                ),
                "false": (
                    "They are different markets. Shared words, adjacency, a parent-child relation, "
                    "or a geography-only relation is not enough for this answer to be true."
                ),
            },
        },
        "scope_overlap": {
            "type": "noul",
            "instructions": (
                "Is either title a parent, child, subset, component, application, technology, "
                "or sales-channel scope of the other title?"
            ),
            "criteria": {
                "true": "One market is materially contained within the other market's commercial scope.",
                "false": "The markets are merely adjacent, are siblings, or have no material containment relationship.",
            },
        },
        "geography_variant": {
            "type": "noul",
            "instructions": (
                "Do the titles describe the same core market while differing mainly in geographic scope?"
            ),
            "criteria": {
                "true": "The underlying market is the same and the main distinction is a country or region.",
                "false": "Geography is not the main distinction between the market topics.",
            },
        },
    }


def _noul(answers: dict[str, object], key: str) -> float:
    answer = answers[key]
    if not isinstance(answer, dict):
        raise TypeError(key)
    value = float(answer["noul"])
    if not 0 <= value <= 1:
        raise ValueError(key)
    return value


def _ngrams(value: str, size: int) -> set[str]:
    if len(value) <= size:
        return {value} if value else set()
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def _dice(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))
