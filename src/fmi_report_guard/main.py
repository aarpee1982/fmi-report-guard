from __future__ import annotations

import argparse
from pathlib import Path

from .checks import run_rule_checks
from .config import AppConfig
from .issues import GitHubIssueClient, build_issue_body, build_issue_title, write_run_artifacts
from .models import Finding, ReportCard, ReportPage
from .openai_review import review_with_openai
from .scraper import FMIClient
from .state_store import SeenState


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor FMI report pages for glaring public errors.")
    parser.add_argument("--state-path", default="state/seen_reports.json")
    parser.add_argument("--artifacts-dir", default="artifacts")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--records-per-page", type=int, default=150)
    parser.add_argument("--max-new", type=int, default=25)
    parser.add_argument("--audit-initial", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-url")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = AppConfig.from_env()
    client = FMIClient(timeout_seconds=config.request_timeout_seconds)
    state_path = Path(args.state_path)
    artifacts_dir = Path(args.artifacts_dir)
    state = SeenState.load(state_path)

    if args.force_url:
        cards = [ReportCard(title="", url=args.force_url, summary="", published_on="")]
    else:
        cards = client.fetch_report_cards(pages=args.pages, records_per_page=args.records_per_page)

    if not args.force_url and not state.bootstrapped and not args.audit_initial:
        for card in cards:
            state.seen_urls.add(card.url)
        state.bootstrapped = True
        state.save(state_path)
        write_run_artifacts([], artifacts_dir)
        print(f"Bootstrapped {len(cards)} report URLs without auditing.")
        return

    if args.force_url:
        new_cards = cards
    elif args.audit_initial:
        new_cards = cards[: args.max_new]
    else:
        new_cards = [card for card in cards if card.url not in state.seen_urls][: args.max_new]

    results: list[tuple[ReportPage, list[Finding]]] = []
    for card in new_cards:
        report = client.fetch_report_page(card)
        findings = collect_findings(report, config)
        if findings:
            results.append((report, findings))
        if not args.force_url:
            state.seen_urls.add(card.url)

    if not args.force_url:
        state.bootstrapped = True
        state.save(state_path)

    write_run_artifacts(results, artifacts_dir)

    if not args.dry_run and results and config.github_token and config.github_repository:
        github = GitHubIssueClient(token=config.github_token, repository=config.github_repository)
        for report, findings in results:
            github.ensure_issue(
                title=build_issue_title(report),
                body=build_issue_body(report, findings),
            )

    print(f"Audited {len(new_cards)} report(s); found issues in {len(results)} report(s).")


def collect_findings(report: ReportPage, config: AppConfig) -> list[Finding]:
    findings = run_rule_checks(report)
    seen_keys = {(finding.category, finding.title) for finding in findings}

    if config.openai_api_key:
        for finding in review_with_openai(
            report=report,
            api_key=config.openai_api_key,
            model=config.openai_model,
            rule_findings=findings,
        ):
            key = (finding.category, finding.title)
            if key not in seen_keys:
                findings.append(finding)
                seen_keys.add(key)

    return findings


if __name__ == "__main__":
    main()
