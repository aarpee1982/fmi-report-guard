from datetime import date

from fmi_report_guard.daily_summary import build_daily_summary_markdown, parse_digest_issue


def test_parse_digest_issue_extracts_findings_and_evidence() -> None:
    body = """# FMI Report Guard alert

- Report: Sample Market
- URL: https://example.com/report
- Listed date: April 10, 2026
- Page publish date: 2026-04-10T09:00:00+05:30

## Findings

### Published CAGR does not match the exposed market values (numeric_inconsistency, rule, confidence 0.94)
After normalizing the public start and end values, the exposed figures still do not support the published CAGR.

Correction instruction:
- Please correct this by updating the market values or CAGR so they match mathematically across the stated forecast period.

Evidence:
- meta_description: Sample Market was valued at USD 1.0 billion and is expected to reach USD 2.6 million by 2036.
- h1_end: Sample Market (2026 - 2036)
"""
    issue = parse_digest_issue(
        issue_title="[FMI Guard] Glaring errors detected: Sample Market",
        issue_url="https://github.com/example/repo/issues/1",
        created_at="2026-04-10T10:00:00Z",
        body=body,
    )

    assert issue.report_title == "Sample Market"
    assert issue.report_url == "https://example.com/report"
    assert len(issue.findings) == 1
    assert issue.findings[0].category == "numeric_inconsistency"
    assert issue.findings[0].correction_instruction.startswith("Please correct this by")
    assert issue.findings[0].evidence[0].startswith("meta_description:")


def test_build_daily_summary_markdown_includes_exact_sentences_and_reason() -> None:
    issue = parse_digest_issue(
        issue_title="[FMI Guard] Glaring errors detected: Sample Market",
        issue_url="https://github.com/example/repo/issues/1",
        created_at="2026-04-10T10:00:00Z",
        body="""# FMI Report Guard alert

- Report: Sample Market
- URL: https://example.com/report
- Listed date: April 10, 2026
- Page publish date: 2026-04-10T09:00:00+05:30

## Findings

### Fabricated acquisition claim (company_development_error, openai, confidence 0.96)
The report claims a company acquisition that appears invented.

Correction instruction:
- Please correct this by removing or replacing the acquisition claim with a verified company development.

Evidence:
- Company X acquired Company Y in 2025.
""",
    )

    summary = build_daily_summary_markdown(
        issues=[issue],
        summary_date=date(2026, 4, 10),
        timezone_name="Asia/Calcutta",
        repository="aarpee1982/fmi-report-guard",
    )

    assert "Why this is an error: The report claims a company acquisition that appears invented." in summary
    assert "Uploader instruction: Please correct this by removing or replacing the acquisition claim with a verified company development." in summary
    assert "- Company X acquired Company Y in 2025." in summary
    assert "https://github.com/example/repo/issues/1" in summary
