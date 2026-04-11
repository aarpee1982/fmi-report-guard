from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import requests

from .daily_summary import DigestIssue, parse_digest_issue
from .models import Finding, ReportPage

DIGEST_ISSUE_TITLE = "[FMI Guard] Open correction digest"


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
        if finding.uploader_summary:
            lines.append("Dumbed-down version for upload team:")
            lines.append(f"- {finding.uploader_summary}")
            lines.append("")
        if finding.correction_instruction:
            lines.append("Copy-paste fix for upload team:")
            lines.append(f"- {finding.correction_instruction}")
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
                    "uploader_summary": finding.uploader_summary,
                    "correction_instruction": finding.correction_instruction,
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


def build_digest_issue_body(open_report_issues: list[DigestIssue]) -> str:
    grouped_findings: dict[str, list[tuple[DigestIssue, object]]] = defaultdict(list)
    seen_keys: set[tuple[str, str, str, str]] = set()

    for issue in sorted(open_report_issues, key=lambda item: ((item.report_title or "").lower(), item.report_url, item.issue_url)):
        for finding in issue.findings:
            dedupe_key = (
                issue.report_url,
                finding.title,
                finding.correction_instruction.strip(),
                "||".join(finding.evidence),
            )
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            group_key = finding.correction_instruction.strip() or finding.title.strip()
            grouped_findings[group_key].append((issue, finding))

    lines = [
        "# FMI Guard open correction digest",
        "",
        "This issue is updated automatically from the currently open FMI Guard report issues.",
        "Use it as the single queue for content corrections.",
        "",
        f"- Open report issues: {len(open_report_issues)}",
        f"- Unique correction groups: {len(grouped_findings)}",
        f"- Unique findings: {sum(len(items) for items in grouped_findings.values())}",
        "",
    ]

    if not grouped_findings:
        lines.append("No open glaring corrections are pending right now.")
        return "\n".join(lines).strip() + "\n"

    for index, instruction in enumerate(sorted(grouped_findings), start=1):
        items = grouped_findings[instruction]
        lines.append(f"## Correction Group {index}")
        lines.append(f"Copy-paste fix for upload team: {instruction}")
        lines.append(f"Affected findings: {len(items)}")
        lines.append("")

        for issue, finding in items:
            lines.append(f"### {issue.report_title}")
            lines.append(f"- Report URL: {issue.report_url or 'unknown'}")
            lines.append(f"- GitHub issue: {issue.issue_url or issue.issue_title}")
            lines.append(f"- Finding: {finding.title}")
            lines.append(
                f"- Category: {finding.category} | Source: {finding.source} | Confidence: {finding.confidence:.2f}"
            )
            lines.append(
                f"- Dumbed-down version: {finding.uploader_summary or finding.explanation}"
            )
            lines.append(f"- Why this is an error: {finding.explanation}")
            if finding.evidence:
                lines.append("- Exact sentence(s):")
                for snippet in finding.evidence:
                    lines.append(f"  - {snippet}")
            else:
                lines.append("- Exact sentence(s): not captured")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


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

    def sync_correction_digest(self) -> None:
        open_report_issues = self._load_open_report_issues()
        digest_body = build_digest_issue_body(open_report_issues)
        self._upsert_issue(DIGEST_ISSUE_TITLE, digest_body)

    def _issue_exists(self, title: str) -> bool:
        return self._find_issue_by_title(title, state="open") is not None

    def _upsert_issue(self, title: str, body: str) -> None:
        existing = self._find_issue_by_title(title, state="open")
        if existing:
            if str(existing.get("body", "")) == body:
                return
            response = self.session.patch(
                f"https://api.github.com/repos/{self.repository}/issues/{existing['number']}",
                json={"body": body},
                timeout=30,
            )
            response.raise_for_status()
            return

        response = self.session.post(
            f"https://api.github.com/repos/{self.repository}/issues",
            json={"title": title, "body": body},
            timeout=30,
        )
        response.raise_for_status()

    def _load_open_report_issues(self) -> list[DigestIssue]:
        digest_issues: list[DigestIssue] = []
        for item in self._list_issues(state="open"):
            title = str(item.get("title", ""))
            if title == DIGEST_ISSUE_TITLE or "pull_request" in item:
                continue
            if not title.startswith("[FMI Guard] Glaring errors detected:"):
                continue
            digest_issues.append(
                parse_digest_issue(
                    issue_title=title,
                    issue_url=str(item.get("html_url", "")),
                    created_at=str(item.get("created_at", "")),
                    body=str(item.get("body", "")),
                )
            )
        return digest_issues

    def _find_issue_by_title(self, title: str, *, state: str) -> dict[str, object] | None:
        for item in self._list_issues(state=state):
            if "pull_request" in item:
                continue
            if item.get("title") == title:
                return item
        return None

    def _list_issues(self, *, state: str) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []
        page = 1
        while True:
            response = self.session.get(
                f"https://api.github.com/repos/{self.repository}/issues",
                params={"state": state, "per_page": 100, "page": page},
                timeout=30,
            )
            response.raise_for_status()
            items = response.json()
            if not items:
                break
            issues.extend(items)
            page += 1
        return issues
