from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import requests

from .daily_summary import DigestFinding, DigestIssue, parse_digest_issue
from .models import Finding, ReportPage

DIGEST_ISSUE_TITLE = "[FMI Guard] Open correction digest"


def build_issue_title(report: ReportPage) -> str:
    title = report.card_title or report.h1 or report.page_title or report.url
    return f"[FMI Guard] Glaring errors detected: {title}"


def build_issue_body(report: ReportPage, findings: list[Finding]) -> str:
    digest_issue = DigestIssue(
        report_title=report.card_title or report.h1,
        report_url=report.url,
        listed_date=report.card_published_on or "unknown",
        page_publish_date=report.publish_date or "unknown",
        issue_title="",
        issue_url="",
        created_at="",
        findings=[
            DigestFinding(
                title=finding.title,
                category=finding.category,
                source=finding.source,
                confidence=finding.confidence,
                explanation=finding.explanation,
                uploader_summary=finding.uploader_summary,
                correction_instruction=finding.correction_instruction,
                evidence=finding.evidence,
            )
            for finding in findings
        ],
    )
    return build_issue_body_from_digest_issue(digest_issue)


def build_issue_body_from_digest_issue(issue: DigestIssue) -> str:
    lines = [
        "# FMI Report Guard alert",
        "",
        f"- Report: {issue.report_title}",
        f"- URL: {issue.report_url}",
        f"- Listed date: {issue.listed_date or 'unknown'}",
        f"- Page publish date: {issue.page_publish_date or 'unknown'}",
        "",
        "## Findings",
        "",
    ]

    for finding in issue.findings:
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
        self.backfill_open_report_issues()
        open_report_issues = self._load_open_report_issues()
        digest_body = build_digest_issue_body(open_report_issues)
        self._upsert_issue(DIGEST_ISSUE_TITLE, digest_body)

    def backfill_open_report_issues(self) -> None:
        for item in self._list_issues(state="open"):
            title = str(item.get("title", ""))
            if title == DIGEST_ISSUE_TITLE or "pull_request" in item:
                continue
            if not title.startswith("[FMI Guard] Glaring errors detected:"):
                continue

            issue = parse_digest_issue(
                issue_title=title,
                issue_url=str(item.get("html_url", "")),
                created_at=str(item.get("created_at", "")),
                body=str(item.get("body", "")),
            )
            upgraded_issue = _upgrade_digest_issue(issue)
            upgraded_body = build_issue_body_from_digest_issue(upgraded_issue)
            if upgraded_body == str(item.get("body", "")):
                continue

            response = self.session.patch(
                f"https://api.github.com/repos/{self.repository}/issues/{item['number']}",
                json={"body": upgraded_body},
                timeout=30,
            )
            response.raise_for_status()

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


def _upgrade_digest_issue(issue: DigestIssue) -> DigestIssue:
    upgraded_findings: list[DigestFinding] = []
    for finding in issue.findings:
        uploader_summary = finding.uploader_summary.strip() or _default_uploader_summary(finding)
        correction_instruction = finding.correction_instruction.strip()
        if not correction_instruction or not correction_instruction.lower().startswith("please"):
            correction_instruction = _default_correction_instruction(finding)

        upgraded_findings.append(
            DigestFinding(
                title=finding.title,
                category=finding.category,
                source=finding.source,
                confidence=finding.confidence,
                explanation=finding.explanation,
                uploader_summary=uploader_summary,
                correction_instruction=correction_instruction,
                evidence=finding.evidence,
            )
        )

    return DigestIssue(
        report_title=issue.report_title,
        report_url=issue.report_url,
        listed_date=issue.listed_date,
        page_publish_date=issue.page_publish_date,
        issue_title=issue.issue_title,
        issue_url=issue.issue_url,
        created_at=issue.created_at,
        findings=upgraded_findings,
    )


def _default_uploader_summary(finding: DigestFinding) -> str:
    text = f"{finding.title} {finding.category} {finding.explanation}".lower()
    if any(keyword in text for keyword in {"cagr", "market size", "market value", "forecast", "million", "billion", "numeric"}):
        return "The market numbers on this page do not match and need correction before upload."
    if any(keyword in text for keyword in {"company", "player", "brand", "merged", "acquisition", "partnership", "launch"}):
        return "A company name or company development on this page looks incorrect and needs correction."
    if any(keyword in text for keyword in {"segment", "segmentation", "type", "application", "end use"}):
        return "The segment list on this page looks incorrect and needs to be aligned with the correct market definition."
    return "This sentence on the page looks wrong and needs correction before upload."


def _default_correction_instruction(finding: DigestFinding) -> str:
    text = f"{finding.title} {finding.category} {finding.explanation}".lower()
    if any(keyword in text for keyword in {"cagr", "market size", "market value", "forecast", "million", "billion", "numeric"}):
        return "Please verify the market values, CAGR, forecast year, and million or billion unit labels, then update the affected sentence so all numbers match the approved source."
    if any(keyword in text for keyword in {"company", "player", "brand", "merged"}):
        return "Please replace the incorrect company name or merged-company reference with the verified company name everywhere it appears in the affected sentence."
    if any(keyword in text for keyword in {"acquisition", "partnership", "launch", "announced", "development"}):
        return "Please remove or replace the unverified company development with a verified company update from a reliable public source."
    if any(keyword in text for keyword in {"segment", "segmentation", "type", "application", "end use"}):
        return "Please replace the incorrect segment list with the verified segmentation for this market and remove any pasted labels that do not belong."
    return "Please review the affected sentence and replace it with the verified wording from the approved source."
