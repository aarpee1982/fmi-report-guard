from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SeenState:
    bootstrapped: bool
    seen_urls: set[str]

    @classmethod
    def load(cls, path: Path) -> "SeenState":
        if not path.exists():
            return cls(bootstrapped=False, seen_urls=set())

        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            bootstrapped=bool(payload.get("bootstrapped", False)),
            seen_urls=set(payload.get("seen_urls", [])),
        )

    def save(self, path: Path, keep_last: int = 5000) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        seen_urls = sorted(self.seen_urls)
        if len(seen_urls) > keep_last:
            seen_urls = seen_urls[-keep_last:]
        payload = {
            "bootstrapped": self.bootstrapped,
            "seen_urls": seen_urls,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
