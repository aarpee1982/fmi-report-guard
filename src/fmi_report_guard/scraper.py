from __future__ import annotations

import json
import re
from html import unescape

import requests
from bs4 import BeautifulSoup

from .models import ReportCard, ReportPage

REPORTS_AJAX_URL = "https://www.futuremarketinsights.com/reportajax/reports_by_reportajax"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


class FMIClient:
    def __init__(self, timeout_seconds: float = 30) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "fmi-report-guard/0.1 (+https://github.com/)",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def fetch_report_cards(self, pages: int, records_per_page: int) -> list[ReportCard]:
        cards: list[ReportCard] = []
        seen_urls: set[str] = set()

        for page_number in range(1, pages + 1):
            response = self.session.get(
                REPORTS_AJAX_URL,
                params={
                    "sortIndustry": "",
                    "sortGeaography": "",
                    "sortYear": "",
                    "page": page_number,
                    "num_record": records_per_page,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            soup = BeautifulSoup(payload["reports"], "html.parser")

            for node in soup.select("div.rep_div"):
                anchor = node.select_one("h3 a[href]")
                summary_node = node.select_one("div.info_content p")
                date_node = node.select_one("div.date_box")
                if not anchor:
                    continue

                url = normalize_text(anchor.get("href", ""))
                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                cards.append(
                    ReportCard(
                        title=normalize_text(anchor.get_text(" ", strip=True)),
                        url=url,
                        summary=normalize_text(summary_node.get_text(" ", strip=True) if summary_node else ""),
                        published_on=normalize_text(date_node.get_text(" ", strip=True) if date_node else ""),
                    )
                )

        return cards

    def fetch_report_page(self, card: ReportCard) -> ReportPage:
        response = self.session.get(card.url, timeout=self.timeout_seconds)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        page_title = normalize_text(soup.title.get_text(" ", strip=True) if soup.title else "")
        meta_description = normalize_text(
            (soup.find("meta", attrs={"name": "description"}) or {}).get("content", "")
        )
        h1_node = soup.find("h1")
        h1 = normalize_text(h1_node.get_text(" ", strip=True) if h1_node else "")

        h2_nodes = [normalize_text(node.get_text(" ", strip=True)) for node in soup.find_all("h2")]
        lead_summary = h2_nodes[0] if h2_nodes else ""

        paragraphs = [normalize_text(node.get_text(" ", strip=True)) for node in soup.find_all("p")]
        paragraphs = [paragraph for paragraph in paragraphs if len(paragraph) >= 50]

        summary_paragraphs: list[str] = []
        competitive_paragraphs: list[str] = []
        for paragraph in paragraphs:
            lower = paragraph.lower()
            if len(summary_paragraphs) < 8 and (
                "market" in lower
                or "forecast" in lower
                or "demand" in lower
                or "analysis" in lower
            ):
                summary_paragraphs.append(paragraph)
            if (
                "key players" in lower
                or "competitive landscape" in lower
                or "providers have" in lower
                or "acquiring" in lower
                or "partnerships" in lower
            ):
                competitive_paragraphs.append(paragraph)

        faq_items, publish_date = self._extract_json_ld_metadata(soup)

        return ReportPage(
            url=card.url,
            card_title=card.title,
            card_summary=card.summary,
            card_published_on=card.published_on,
            page_title=page_title,
            h1=h1,
            meta_description=meta_description,
            lead_summary=lead_summary,
            publish_date=publish_date,
            summary_paragraphs=summary_paragraphs[:8],
            competitive_paragraphs=competitive_paragraphs[:6],
            faq_items=faq_items[:8],
        )

    def _extract_json_ld_metadata(self, soup: BeautifulSoup) -> tuple[list[dict[str, str]], str]:
        faq_items: list[dict[str, str]] = []
        publish_date = ""

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = normalize_text(script.string or script.get_text(" ", strip=True))
            if not raw:
                continue

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue

            for item in self._yield_json_ld_items(payload):
                if not publish_date:
                    publish_date = normalize_text(str(item.get("datePublished", "")))

                item_type = item.get("@type")
                entities = item.get("mainEntity", [])
                if item_type == "FAQPage" and isinstance(entities, list):
                    for entity in entities:
                        question = normalize_text(str(entity.get("name", "")))
                        answer = normalize_text(
                            str((entity.get("acceptedAnswer") or {}).get("text", ""))
                        )
                        if question and answer:
                            faq_items.append({"question": question, "answer": answer})

        return faq_items, publish_date

    def _yield_json_ld_items(self, payload: object) -> list[dict[str, object]]:
        if isinstance(payload, list):
            items: list[dict[str, object]] = []
            for value in payload:
                items.extend(self._yield_json_ld_items(value))
            return items

        if isinstance(payload, dict):
            if "@graph" in payload and isinstance(payload["@graph"], list):
                return [item for item in payload["@graph"] if isinstance(item, dict)]
            return [payload]

        return []
