from __future__ import annotations

from datetime import date

from services.gateway.routers import timetable_setup_calendar_intake as calendar_intake


def test_extract_preserves_page_numbers_and_source_excerpts() -> None:
    rows = calendar_intake._extract_lines(
        [
            (1, "2026-09-01 - School Opening"),
            (2, "2026-09-15 to 2026-09-20 - Examination Period"),
        ]
    )

    assert rows[0]["page_number"] == 1
    assert rows[1]["page_number"] == 2
    assert rows[0]["line"] == "2026-09-01 - School Opening"


def test_arabic_and_hijri_text_preserved_without_translation() -> None:
    arabic_line = "1448-01-05 اجتماع اولياء الامور"
    rows = calendar_intake._extract_lines([(3, arabic_line)])

    assert rows[0]["line"] == arabic_line
    assert rows[0]["date_parse_status"] in {"hijri_unresolved", "parsed"}
    if rows[0]["date_parse_status"] == "hijri_unresolved":
        assert rows[0]["start_date"] is None


def test_gregorian_single_and_range_dates_parse_deterministically() -> None:
    rows = calendar_intake._extract_lines(
        [
            (1, "2026-10-04 - Public Holiday"),
            (1, "2026-10-10 to 2026-10-12 - Midterm Exam"),
        ]
    )

    single = rows[0]
    ranged = rows[1]
    assert single["start_date"] == date(2026, 10, 4)
    assert single["end_date"] == date(2026, 10, 4)
    assert ranged["start_date"] == date(2026, 10, 10)
    assert ranged["end_date"] == date(2026, 10, 12)


def test_ambiguous_numeric_and_invalid_range_generate_issues() -> None:
    ambiguous = calendar_intake._extract_lines([(1, "01/02/2026 - Event")])[0]
    invalid_range = calendar_intake._extract_lines([(1, "2026-11-10 to 2026-11-01 - Event")])[0]

    assert ambiguous["date_parse_status"] == "ambiguous"
    assert "ambiguous" in ambiguous["issues"]["warnings"]
    assert invalid_range["date_parse_status"] == "invalid_range"
    assert "invalid_range" in invalid_range["issues"]["blockers"]


def test_mixed_calendars_generate_warning() -> None:
    mixed = calendar_intake._extract_lines([(1, "2026-12-01 Hijri رمضان holiday")])[0]
    assert "mixed_calendar_warning" in mixed["issues"]["warnings"]


def test_candidate_classification_includes_required_fields() -> None:
    row = calendar_intake._extract_lines([(1, "2026-09-15 - parent conference")])[0]
    classification = row["classification"]

    assert classification["proposed_type"] in {
        "teaching_day_override",
        "public_holiday",
        "school_holiday",
        "examination_period",
        "professional_development",
        "parent_conference",
        "school_event",
        "half_day",
        "special_schedule",
        "term_boundary",
        "information_only",
    }
    assert "confidence" in classification
    assert "matched_rule" in classification
    assert "explanation" in classification
    assert "uncertainty" in classification
