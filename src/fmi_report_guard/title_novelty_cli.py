from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .title_index import TITLE_INDEX_PATH, load_title_corpus
from .title_novelty import (
    DEFAULT_TYPESAFE_ENDPOINT,
    DEFAULT_TYPESAFE_MODEL,
    TitleRetriever,
    TypeSafeJevClient,
    assess_title_novelty,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check up to five proposed market titles against the local FMI corpus and Jev."
    )
    parser.add_argument("titles", nargs="+", help="One to five proposed FMI market titles.")
    parser.add_argument("--top-k", type=int, default=30, choices=range(5, 51))
    parser.add_argument("--index-path", default=str(TITLE_INDEX_PATH))
    parser.add_argument("--benchmark-db", default=os.getenv("FMI_BENCHMARK_DB"))
    parser.add_argument("--show-matches", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if len(args.titles) > 5:
        raise SystemExit("Pass no more than five titles at a time.")

    corpus = load_title_corpus(
        index_path=Path(args.index_path),
        benchmark_db_path=args.benchmark_db,
    )
    if not corpus:
        raise SystemExit("No FMI title corpus was found.")

    api_key = os.getenv("TYPESAFE_API_KEY")
    jev_client = None
    if api_key:
        jev_client = TypeSafeJevClient(
            api_key=api_key,
            model=os.getenv("TYPESAFE_MODEL", DEFAULT_TYPESAFE_MODEL),
            endpoint=os.getenv("TYPESAFE_ENDPOINT", DEFAULT_TYPESAFE_ENDPOINT),
        )

    retriever = TitleRetriever(corpus)
    results = []
    for title in args.titles:
        result = assess_title_novelty(
            proposed_title=title,
            corpus=retriever,
            top_k=args.top_k,
            jev_client=jev_client,
        ).as_dict()
        result["matches"] = result["matches"][: max(args.show_matches, 0)]
        results.append(result)

    print(json.dumps({"corpus_size": len(corpus), "results": results}, indent=2))


if __name__ == "__main__":
    main()
