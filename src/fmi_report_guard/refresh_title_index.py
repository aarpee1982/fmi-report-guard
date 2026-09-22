from __future__ import annotations

import argparse
from pathlib import Path

from .scraper import FMIClient
from .title_index import TITLE_INDEX_PATH, refresh_title_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild the FMI title cache from public sitemaps without an AI model."
    )
    parser.add_argument("--index-path", default=str(TITLE_INDEX_PATH))
    parser.add_argument("--min-titles", type=int, default=25_000)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    titles = refresh_title_index(
        client=FMIClient(timeout_seconds=args.timeout_seconds),
        path=Path(args.index_path),
        min_titles=args.min_titles,
    )
    print(f"Built FMI title index with {len(titles):,} unique titles. No AI API was called.")


if __name__ == "__main__":
    main()
