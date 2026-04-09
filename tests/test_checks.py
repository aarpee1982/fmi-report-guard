from fmi_report_guard.checks import check_forecast_years, check_topic_mismatch
from fmi_report_guard.models import ReportPage


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


def test_topic_mismatch_is_flagged() -> None:
    report = make_report(page_title="Hospital Bedsheet & Pillow Cover Market | Global Industry Analysis Report - 2036")
    findings = check_topic_mismatch(report)
    assert findings
    assert findings[0].category == "topic_mismatch"
