from __future__ import annotations

import json

import pytest

from fmi_report_guard.title_index import make_indexed_title, refresh_title_index


class FakeClient:
    def __init__(self, titles):
        self.titles = titles

    def fetch_title_index(self):
        return self.titles


def test_refresh_title_index_writes_deterministic_cache(tmp_path) -> None:
    path = tmp_path / "titles.json"
    titles = [
        make_indexed_title(url="https://example.test/a", title="Alpha Market"),
        make_indexed_title(url="https://example.test/b", title="Beta Markets"),
    ]

    result = refresh_title_index(client=FakeClient(titles), path=path, min_titles=2)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert result == titles
    assert len(payload["titles"]) == 2
    assert payload["titles"][1]["singular_title"] == "beta"


def test_refresh_title_index_refuses_partial_corpus(tmp_path) -> None:
    path = tmp_path / "titles.json"
    titles = [make_indexed_title(url="https://example.test/a", title="Alpha Market")]

    with pytest.raises(ValueError, match="Refusing to replace"):
        refresh_title_index(client=FakeClient(titles), path=path, min_titles=2)

    assert not path.exists()
