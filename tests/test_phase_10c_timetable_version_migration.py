from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


REVISION_ID = "e7b1c9d4a2f0"
DOWN_REVISION = "c3d9a7b2e410"


def test_batch5_revision_is_linear_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == [REVISION_ID]

    revision = script.get_revision(REVISION_ID)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION


def test_batch5_migration_declares_timetable_versioning_tables() -> None:
    path = Path("alembic/versions/e7b1c9d4a2f0_phase_10c_timetable_versioning_batch5.py")
    text = path.read_text(encoding="utf-8")

    assert "def upgrade()" in text
    assert "def downgrade()" in text
    assert "timetables" in text
    assert "timetable_versions" in text
    assert "timetable_version_assignments" in text
    assert "baseline_timetable_version_id" in text
    assert "uq_timetable_versions_timetable_version_number" in text
