from fmi_report_guard.checks import check_forecast_years, check_market_math, run_rule_checks
from fmi_report_guard.models import ReportPage
from fmi_report_guard.openai_review import _is_material_finding


def make_report(**overrides) -> ReportPage:
    payload = {
        "url": "https://example.com/report",
        "card_title": "Hospital Bedsheet & Pillow Cover Market",
        "card_summary": (
            "The Hospital Bedsheet & Pillow Cover Market is segmented by Type "
            "(LED Lighting, Surgical Lights, Examination Lights, Microscope Lights). "
            "Forecast for 2026 to 2036."
        ),
        "card_published_on": "April 09, 2026",
        "page_title": "Hospital Bedsheet & Pillow Cover Market | Global Industry Analysis Report - 2035",
        "h1": "Hospital Bedsheet & Pillow Cover Market (2026 - 2036)",
        "meta_description": (
            "Hospital Bedsheet & Pillow Cover Market was valued at USD 1.2 billion and "
            "is expected to reach USD 1.6 billion by 2036, growing at a CAGR of 2.4%."
        ),
        "lead_summary": (
            "The Hospital Bedsheet & Pillow Cover Market is segmented by Type "
            "(LED Lighting, Surgical Lights, Examination Lights, Microscope Lights, "
            "Emergency Lights, Fluorescent Lighting), Installation Type "
            "(Recessed Lighting, Surface Mounted Lighting, Pendant Lighting), Technology "
            "(LED, Fluorescent, Incandescent), and Region."
        ),
        "publish_date": "2026-04-09T17:22:16-04:00",
        "summary_paragraphs": [],
        "competitive_paragraphs": [],
        "faq_items": [],
    }
    payload.update(overrides)
    return ReportPage(**payload)


def test_forecast_year_mismatch_is_flagged() -> None:
    report = make_report()
    findings = check_forecast_years(report)
    assert findings
    assert findings[0].category == "numeric_inconsistency"


def test_topic_mismatch_is_not_included_in_rule_checks() -> None:
    report = make_report(page_title="Hospital Bedsheet & Pillow Cover Market | Global Industry Analysis Report - 2036")
    findings = run_rule_checks(report)
    assert all(finding.category != "topic_mismatch" for finding in findings)


def test_cagr_difference_of_exactly_one_percent_is_ignored() -> None:
    report = make_report(
        page_title="Test Market | Global Industry Analysis Report - 2036",
        card_title="Test Market",
        h1="Test Market (2026 - 2036)",
        meta_description=(
            "Test Market was valued at USD 1.0 billion and is expected to reach "
            "USD 2.6 billion by 2036, growing at a CAGR of 10.0%."
        ),
    )
    findings = check_market_math(report)
    assert findings == []


def test_cross_unit_market_math_is_ignored_when_values_support_the_stated_cagr() -> None:
    report = make_report(
        page_title="Test Market | Global Industry Analysis Report - 2036",
        card_title="Test Market",
        h1="Test Market (2026 - 2036)",
        meta_description=(
            "Test Market was valued at USD 950 million and is expected to reach "
            "USD 1.2 billion by 2036, growing at a CAGR of 2.4%."
        ),
    )
    findings = check_market_math(report)
    assert findings == []


def test_cross_unit_market_math_flags_glaring_scale_error() -> None:
    report = make_report(
        page_title="Test Market | Global Industry Analysis Report - 2036",
        card_title="Test Market",
        h1="Test Market (2026 - 2036)",
        meta_description=(
            "Test Market was valued at USD 1.0 billion and is expected to reach "
            "USD 2.6 million by 2036, growing at a CAGR of 10.0%."
        ),
    )
    findings = check_market_math(report)
    assert findings
    assert findings[0].category == "numeric_inconsistency"


def test_minor_editorial_openai_finding_is_filtered() -> None:
    item = {
        "category": "Editorial / Typo",
        "title": "Duplicated word in meta description",
        "explanation": "The meta description contains a duplicated word and should be edited.",
        "uploader_summary": "This is just a minor copy issue.",
        "correction_instruction": "Please correct this by removing the duplicated word.",
    }
    assert _is_material_finding(item) is False


def test_company_hallucination_openai_finding_is_kept() -> None:
    item = {
        "category": "company_development_error",
        "title": "Fabricated acquisition claim",
        "explanation": "The report claims a company acquired another firm, but that development appears invented.",
        "uploader_summary": "The company development mentioned on the page appears to be made up.",
        "correction_instruction": "Please correct this by removing the acquisition claim unless it can be verified from a reliable public source.",
    }
    assert _is_material_finding(item) is True


def test_segmentation_driven_openai_finding_is_filtered() -> None:
    item = {
        "category": "company_name_error",
        "title": "Segment list appears unrelated to the market",
        "explanation": "The segmentation appears unrelated to the report title and may be pasted here.",
        "uploader_summary": "The segment list looks unrelated to the market definition.",
        "correction_instruction": "Please correct this by reviewing the segment list against the intended market definition.",
    }
    assert _is_material_finding(item) is False


def test_unit_scale_openai_finding_is_kept() -> None:
    item = {
        "category": "unit_scale_error",
        "title": "Million versus billion market value mismatch",
        "explanation": "The report says USD 2.6 million instead of USD 2.6 billion, creating an order of magnitude scale error.",
        "uploader_summary": "The market value unit is wrong and needs to be changed from million to billion.",
        "correction_instruction": "Please correct this by updating the unit label so the market value uses the verified billion-scale figure.",
    }
    assert _is_material_finding(item) is True


def test_openai_finding_without_correction_instruction_is_filtered() -> None:
    item = {
        "category": "company_development_error",
        "title": "Fabricated acquisition claim",
        "explanation": "The report claims a company acquired another firm, but that development appears invented.",
        "uploader_summary": "The company development mentioned on the page appears to be made up.",
        "correction_instruction": "",
    }
    assert _is_material_finding(item) is False


def test_openai_finding_without_uploader_summary_is_filtered() -> None:
    item = {
        "category": "company_development_error",
        "title": "Fabricated acquisition claim",
        "explanation": "The report claims a company acquired another firm, but that development appears invented.",
        "uploader_summary": "",
        "correction_instruction": "Please correct this by removing the acquisition claim unless it can be verified from a reliable public source.",
    }
    assert _is_material_finding(item) is False
