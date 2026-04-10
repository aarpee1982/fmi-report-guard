from __future__ import annotations

import argparse
import re
import smtplib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .config import AppConfig

ISSUE_TITLE_PREFIX = "[FMI Guard] Glaring errors detected:"


@dataclass(slots=True)
class DigestFinding:
    title: str
    category: str
    source: str
    confidence: float
    explanation: str
    correction_instruction: str
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DigestIssue:
    report_title: str
    report_url: str
    listed_date: str
    page_publish_date: str
    issue_title: str
    issue_url: str
    created_at: str
    findings: list[DigestFinding] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and send the FMI Report Guard daily email summary.")
    parser.add_argument("--date", help="Local summary date in YYYY-MM-DD format. Defaults to today in summary timezone.")
    parser.add_argument("--output-path", default="artifacts/daily_summary.md")
    parser.add_argument("--dry-run", action="store_true", help="Build the summary artifact without sending email.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = AppConfig.from_env()
    summary_date = _resolve_summary_date(args.date, config.summary_timezone)
    issues = fetch_daily_issues(
        token=config.github_token,
        repository=config.github_repository,
        summary_date=summary_date,
        timezone_name=config.summary_timezone,
    )
    summary_markdown = build_daily_summary_markdown(
        issues=issues,
        summary_date=summary_date,
        timezone_name=config.summary_timezone,
        repository=config.github_repository or "unknown-repository",
    )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary_markdown, encoding="utf-8")

    if args.dry_run:
        print(f"Built daily summary for {summary_date.isoformat()} with {len(issues)} issue(s); email skipped.")
        return

    send_summary_email(
        config=config,
        summary_date=summary_date,
        timezone_name=config.summary_timezone,
        body=summary_markdown,
        issue_count=len(issues),
    )
    print(f"Built and emailed daily summary for {summary_date.isoformat()} with {len(issues)} issue(s).")


def fetch_daily_issues(
    *,
    token: str | None,
    repository: str | None,
    summary_date: date,
    timezone_name: str,
) -> list[DigestIssue]:
    if not token:
        raise ValueError("GITHUB_TOKEN is required to build the daily summary.")
    if not repository:
        raise ValueError("GITHUB_REPOSITORY is required to build the daily summary.")

    start_at, end_at = _summary_window(summary_date, timezone_name)
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )

    issues: list[DigestIssue] = []
    page = 1
    while True:
        response = session.get(
            f"https://api.github.com/repos/{repository}/issues",
            params={
                "state": "all",
                "per_page": 100,
                "page": page,
                "sort": "created",
                "direction": "desc",
            },
            timeout=30,
        )
        response.raise_for_status()
        items = response.json()
        if not items:
            break

        stop_paging = False
        for item in items:
            if "pull_request" in item:
                continue
            if not str(item.get("title", "")).startswith(ISSUE_TITLE_PREFIX):
                continue

            created_at = _parse_github_timestamp(str(item.get("created_at", "")))
            if created_at < start_at:
                stop_paging = True
                continue
            if created_at >= end_at:
                continue

            issues.append(
                parse_digest_issue(
                    issue_title=str(item.get("title", "")),
                    issue_url=str(item.get("html_url", "")),
                    created_at=str(item.get("created_at", "")),
                    body=str(item.get("body", "")),
                )
            )

        if stop_paging:
            break
        page += 1

    return issues


def parse_digest_issue(*, issue_title: str, issue_url: str, created_at: str, body: str) -> DigestIssue:
    report_title = "Unknown report"
    report_url = ""
    listed_date = "unknown"
    page_publish_date = "unknown"
    findings: list[DigestFinding] = []

    lines = [line.rstrip() for line in body.splitlines()]
    current: DigestFinding | None = None
    collecting_evidence = False
    collecting_correction_instruction = False

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("- Report: "):
            report_title = line.removeprefix("- Report: ").strip()
            continue
        if line.startswith("- URL: "):
            report_url = line.removeprefix("- URL: ").strip()
            continue
        if line.startswith("- Listed date: "):
            listed_date = line.removeprefix("- Listed date: ").strip()
            continue
        if line.startswith("- Page publish date: "):
            page_publish_date = line.removeprefix("- Page publish date: ").strip()
            continue

        if line.startswith("### "):
            if current:
                findings.append(current)
            current = _parse_finding_heading(line.removeprefix("### ").strip())
            collecting_evidence = False
            collecting_correction_instruction = False
            continue

        if not current:
            continue

        if line == "Correction instruction:":
            collecting_correction_instruction = True
            collecting_evidence = False
            continue

        if line == "Evidence:":
            collecting_evidence = True
            collecting_correction_instruction = False
            continue

        if not line:
            collecting_evidence = False
            collecting_correction_instruction = False
            continue

        if collecting_correction_instruction and line.startswith("- "):
            current.correction_instruction = line.removeprefix("- ").strip()
            continue

        if collecting_evidence and line.startswith("- "):
            current.evidence.append(line.removeprefix("- ").strip())
            continue

        if not current.explanation:
            current.explanation = line

    if current:
        findings.append(current)

    return DigestIssue(
        report_title=report_title,
        report_url=report_url,
        listed_date=listed_date,
        page_publish_date=page_publish_date,
        issue_title=issue_title,
        issue_url=issue_url,
        created_at=created_at,
        findings=findings,
    )


def build_daily_summary_markdown(
    *,
    issues: list[DigestIssue],
    summary_date: date,
    timezone_name: str,
    repository: str,
) -> str:
    day_label = summary_date.strftime("%B %d, %Y")
    lines = [
        f"# FMI Report Guard daily summary for {day_label}",
        "",
        f"- Time zone: {timezone_name}",
        f"- Repository: {repository}",
        f"- Reports with issues: {len(issues)}",
        f"- Total findings: {sum(len(issue.findings) for issue in issues)}",
        "",
    ]

    if not issues:
        lines.append("No glaring issues were opened for this day.")
        return "\n".join(lines).strip() + "\n"

    for issue in issues:
        lines.append(f"## {issue.report_title}")
        lines.append(f"- Report URL: {issue.report_url or 'unknown'}")
        lines.append(f"- GitHub issue: {issue.issue_url or issue.issue_title}")
        lines.append(f"- Listed date: {issue.listed_date}")
        lines.append(f"- Page publish date: {issue.page_publish_date}")
        lines.append("")

        for finding in issue.findings:
            lines.append(f"### {finding.title}")
            lines.append(
                f"Category: {finding.category} | Source: {finding.source} | Confidence: {finding.confidence:.2f}"
            )
            lines.append(f"Why this is an error: {finding.explanation}")
            lines.append(
                f"Uploader instruction: {finding.correction_instruction or 'Please review this finding and correct the page content to match the verified source facts.'}"
            )
            lines.append("Exact sentence(s):")
            if finding.evidence:
                for snippet in finding.evidence:
                    lines.append(f"- {snippet}")
            else:
                lines.append("- No evidence snippet was captured in the issue body.")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def send_summary_email(
    *,
    config: AppConfig,
    summary_date: date,
    timezone_name: str,
    body: str,
    issue_count: int,
) -> None:
    if not config.summary_email_to:
        raise ValueError("FMI_SUMMARY_EMAIL_TO is required to send the daily summary email.")
    if not config.summary_email_from:
        raise ValueError("FMI_SUMMARY_EMAIL_FROM is required to send the daily summary email.")
    if not config.smtp_host:
        raise ValueError("FMI_SMTP_HOST is required to send the daily summary email.")

    subject = (
        f"FMI Report Guard daily summary for {summary_date.isoformat()} "
        f"({timezone_name}, {issue_count} report issue{'s' if issue_count != 1 else ''})"
    )
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.summary_email_from
    message["To"] = config.summary_email_to
    message.set_content(body)

    if config.smtp_use_ssl:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30) as smtp:
            _smtp_login_and_send(smtp, config, message)
        return

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        if config.smtp_starttls:
            smtp.starttls()
            smtp.ehlo()
        _smtp_login_and_send(smtp, config, message)


def _smtp_login_and_send(smtp: smtplib.SMTP, config: AppConfig, message: EmailMessage) -> None:
    if config.smtp_username:
        smtp.login(config.smtp_username, config.smtp_password or "")
    smtp.send_message(message)


def _resolve_summary_date(raw_value: str | None, timezone_name: str) -> date:
    if raw_value:
        return date.fromisoformat(raw_value)
    return datetime.now(ZoneInfo(timezone_name)).date()


def _summary_window(summary_date: date, timezone_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    start_at = datetime.combine(summary_date, time.min, tzinfo=tz)
    end_at = start_at + timedelta(days=1)
    return start_at.astimezone(ZoneInfo("UTC")), end_at.astimezone(ZoneInfo("UTC"))


def _parse_github_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_finding_heading(value: str) -> DigestFinding:
    match = re.match(
        r"(?P<title>.+?) \((?P<category>[^,]+), (?P<source>[^,]+), confidence (?P<confidence>[\d.]+)\)$",
        value,
    )
    if not match:
        return DigestFinding(
            title=value,
            category="unknown",
            source="unknown",
            confidence=0.0,
            explanation="",
            correction_instruction="",
        )

    return DigestFinding(
        title=match.group("title"),
        category=match.group("category"),
        source=match.group("source"),
        confidence=float(match.group("confidence")),
        explanation="",
        correction_instruction="",
    )
