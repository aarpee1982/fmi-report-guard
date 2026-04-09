from __future__ import annotations

import json
from pathlib import Path

import requests

from .models import Finding, ReportPage


def build_issue_title(report: ReportPage) -> str:
    title = report.card_title or report.h1 or report.page_title or report.url
    return f"[FMI Guard] Glaring errors detected: {title}"


def build_issue_body(report: ReportPage, findings: list[Finding]) -> str:
    lines = [
        "# FMI Report Guard alert",
        "",
        f"- Report: {report.card_title or report.h1}",
        f"- URL: {report.url}",
        f"- Listed date: {report.card_published_on or 'unknown'}",
        f"- Page publish date: {report.publish_date or 'unknown'}",
        "",
        "## Findings",
        "",
    ]

    for finding in findings:
        lines.append(
            f"### {finding.title} ({finding.category}, {finding.source}, confidence {finding.confidence:.2f})"
        )
        lines.append(finding.explanation)
        lines.append("")
        if finding.evidence:
            lines.append("Evidence:")
            for snippet in finding.evidence:
                lines.append(f"- {snippet}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def write_run_artifacts(results: list[tuple[ReportPage, list[Finding]]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_payload = [
        {
            "url": report.url,
            "title": report.card_title or report.h1,
            "findings": [
                {
                    "category": finding.category,
                    "title": finding.title,
                    "explanation": finding.explanation,
                    "confidence": finding.confidence,
                    "source": finding.source,
                    "evidence": finding.evidence,
                }
                for finding in findings
            ],
        }
        for report, findings in results
    ]
    (output_dir / "latest_run.json").write_text(
        json.dumps(summary_payload, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = ["# FMI Report Guard run summary", ""]
    if not results:
        lines.append("No glaring report issues were detected.")
    else:
        for report, findings in results:
            lines.append(f"## {report.card_title or report.h1}")
            lines.append(report.url)
            lines.append("")
            for finding in findings:
                lines.append(f"- {finding.title} [{finding.category}, {finding.source}, {finding.confidence:.2f}]")
            lines.append("")
    (output_dir / "latest_run.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


class GitHubIssueClient:
    def __init__(self, token: str, repository: str) -> None:
        self.repository = repository
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def ensure_issue(self, title: str, body: str) -> None:
        if self._issue_exists(title):
            return

        response = self.session.post(
            f"https://api.github.com/repos/{self.repository}/issues",
            json={"title": title, "body": body},
            timeout=30,
        )
        response.raise_for_status()

    def _issue_exists(self, title: str) -> bool:
        response = self.session.get(
            f"https://api.github.com/repos/{self.repository}/issues",
            params={"state": "open", "per_page": 100},
            timeout=30,
        )
        response.raise_for_status()
        items = response.json()
        return any(item.get("title") == title for item in items if "pull_request" not in item)
