from fmi_report_guard.daily_summary import parse_digest_issue
from fmi_report_guard.issues import _upgrade_digest_issue, build_digest_issue_body


def test_build_digest_issue_body_groups_same_correction_instruction() -> None:
    issue_one = parse_digest_issue(
        issue_title="[FMI Guard] Glaring errors detected: Market One",
        issue_url="https://github.com/example/repo/issues/1",
        created_at="2026-04-10T10:00:00Z",
        body="""# FMI Report Guard alert

- Report: Market One
- URL: https://example.com/market-one
- Listed date: April 10, 2026
- Page publish date: 2026-04-10T09:00:00+05:30

## Findings

### Million versus billion market value mismatch (unit_scale_error, openai, confidence 0.96)
The report says USD 2.6 million instead of USD 2.6 billion.

Dumbed-down version for upload team:
- The market value unit is wrong and needs to be changed from million to billion.

Copy-paste fix for upload team:
- Please change the market value unit from million to billion and verify the number everywhere it appears on the page.

Evidence:
- meta_description: Market One was valued at USD 1.0 billion and is expected to reach USD 2.6 million by 2036.
""",
    )
    issue_two = parse_digest_issue(
        issue_title="[FMI Guard] Glaring errors detected: Market Two",
        issue_url="https://github.com/example/repo/issues/2",
        created_at="2026-04-10T11:00:00Z",
        body="""# FMI Report Guard alert

- Report: Market Two
- URL: https://example.com/market-two
- Listed date: April 10, 2026
- Page publish date: 2026-04-10T10:00:00+05:30

## Findings

### Million versus billion market value mismatch (unit_scale_error, openai, confidence 0.95)
The report says USD 3.1 million instead of USD 3.1 billion.

Dumbed-down version for upload team:
- The market value unit is wrong and needs to be changed from million to billion.

Copy-paste fix for upload team:
- Please change the market value unit from million to billion and verify the number everywhere it appears on the page.

Evidence:
- meta_description: Market Two was valued at USD 1.4 billion and is expected to reach USD 3.1 million by 2036.
""",
    )

    digest = build_digest_issue_body([issue_one, issue_two])

    assert digest.count("## Correction Group") == 1
    assert "Affected findings: 2" in digest
    assert "Copy-paste fix for upload team: Please change the market value unit from million to billion and verify the number everywhere it appears on the page." in digest
    assert "### Market One" in digest
    assert "### Market Two" in digest


def test_build_digest_issue_body_handles_empty_queue() -> None:
    digest = build_digest_issue_body([])
    assert "No open glaring corrections are pending right now." in digest


def test_upgrade_digest_issue_backfills_old_issue_fields() -> None:
    old_issue = parse_digest_issue(
        issue_title="[FMI Guard] Glaring errors detected: Legacy Market",
        issue_url="https://github.com/example/repo/issues/9",
        created_at="2026-04-10T12:00:00Z",
        body="""# FMI Report Guard alert

- Report: Legacy Market
- URL: https://example.com/legacy-market
- Listed date: April 10, 2026
- Page publish date: 2026-04-10T11:00:00+05:30

## Findings

### Conflicting 2036 market-size figures (Numeric inconsistency, openai, confidence 0.96)
The report gives conflicting 2036 market-size figures and they cannot both be correct.

Evidence:
- meta_description: Legacy Market is projected to reach USD 6.4 billion by 2036.
""",
    )

    upgraded = _upgrade_digest_issue(old_issue)

    assert upgraded.findings[0].uploader_summary == "The market numbers on this page do not match and need correction before upload."
    assert upgraded.findings[0].correction_instruction.startswith("Please verify the market values")
