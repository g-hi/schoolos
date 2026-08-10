from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


REVISION_ID = "f3a2d8c1e9b4"
DOWN_REVISION = "e7b1c9d4a2f0"
MIGRATION_FILE = Path("alembic/versions/f3a2d8c1e9b4_phase_10d_daily_sessions_foundation.py")


def test_phase_10d_revision_is_linear_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == [REVISION_ID]

    revision = script.get_revision(REVISION_ID)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION


def test_phase_10d_migration_chain_includes_prior_phases() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    chain = {r.revision for r in script.iterate_revisions(heads[0], "base")}

    # Phase 10C batch 5 (timetable versioning)
    assert "e7b1c9d4a2f0" in chain
    # Phase 10C foundation
    assert "c3d9a7b2e410" in chain
    # Phase 10A
    assert "9a10b1c2d3e4" in chain


def test_phase_10d_migration_declares_operational_tables() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")

    assert "def upgrade()" in text
    assert "def downgrade()" in text
    assert "operational_school_days" in text
    assert "daily_sessions" in text


def test_phase_10d_migration_declares_key_columns() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")

    # operational_school_days columns
    assert "timetable_id" in text
    assert "timetable_version_id" in text
    assert "campus_id" in text
    assert "school_date" in text
    assert "timetable_day_key" in text
    assert "is_teaching_day" in text
    assert "non_teaching_reason" in text
    assert "materialization_status" in text
    assert "source_fingerprint" in text
    assert "calendar_override_event_id" in text

    # daily_sessions columns
    assert "operational_school_day_id" in text
    assert "session_key" in text
    assert "session_status" in text
    assert "periods_span" in text
    assert "parallel_block_id" in text
    assert "class_facing_session_key" in text


def test_phase_10d_migration_has_no_subject_name_heuristics() -> None:
    """Guard against subject-name-based branching in the migration itself."""
    text = MIGRATION_FILE.read_text(encoding="utf-8").lower()

    forbidden = [
        "foreign language",
        "french",
        "german",
        "spanish",
        "elective",
        "grade 8",
    ]
    for term in forbidden:
        assert term not in text, (
            f"Migration must not hard-code subject/grade name '{term}'. "
            "Parallel structure is expressed via parallel_block_id / parallel_child_id only."
        )


def test_phase_10d_migration_unique_constraint_names_fit_pg_identifier_limit() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    import re

    max_len = 63
    # Capture all explicitly-named identifiers: named= args and index/constraint
    # names passed as first positional string arg to create_index / drop_index.
    named_args = re.findall(r'name=["\']([^"\']+)["\']', text)
    positional_ids = re.findall(r'op\.(?:create_index|drop_index)\(\s*["\']([^"\']+)["\']', text)
    all_names = named_args + positional_ids

    long_names = [(n, len(n)) for n in all_names if len(n) > max_len]
    assert not long_names, (
        f"Identifier(s) exceed PostgreSQL's {max_len}-char limit: {long_names}"
    )


def test_phase_10d_migration_identifier_audit_table() -> None:
    """Enumerate every explicit identifier and verify none exceed 63 chars.

    This is the authoritative audit mandated after Phase 10C's deployment
    failure on PostgreSQL's identifier limit.
    """
    import re
    from pathlib import Path

    text = MIGRATION_FILE.read_text(encoding="utf-8")
    max_len = 63

    named = re.findall(r'name=["\']([^"\']+)["\']', text)
    positional = re.findall(r'op\.(?:create_index|drop_index)\(\s*["\']([^"\']+)["\']', text)
    all_identifiers = sorted(set(named + positional))

    # Build an audit report for the final validation section
    audit_rows = [(name, len(name), "OK" if len(name) <= max_len else "EXCEEDS_LIMIT")
                  for name in all_identifiers]

    violations = [(name, length) for name, length, status in audit_rows if status != "OK"]
    assert not violations, (
        f"PostgreSQL identifier limit ({max_len}) exceeded:\n"
        + "\n".join(f"  {name!r} ({length} chars)" for name, length in violations)
    )

    # Spot-check a few expected identifiers to ensure the regex captures them
    assert any("uq_operational_school_days_timetable_date" in name for name in all_identifiers)
    assert any("uq_daily_sessions_osd_session_key" in name for name in all_identifiers)
    assert any("ix_daily_sessions_tenant_date_class" in name for name in all_identifiers)
    assert any("ix_daily_sessions_class_facing_key" in name for name in all_identifiers)
    assert any("ix_osd_calendar_override_event_id" in name for name in all_identifiers)


def test_phase_10d_migration_declares_source_fingerprint() -> None:
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    assert "source_fingerprint" in text
    assert "class_facing_session_key" in text
    assert "calendar_override_event_id" in text
    assert "timetable_id" in text
