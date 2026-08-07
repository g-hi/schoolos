from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


REVISION_ID = "c3d9a7b2e410"
DOWN_REVISION = "a84f2c1d9e30"


def test_phase_10c_revision_head_and_down_revision() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert heads == [REVISION_ID]

    revision = script.get_revision(REVISION_ID)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION


def test_phase_10c_migration_contains_upgrade_and_downgrade_objects() -> None:
    migration_path = Path("alembic/versions/c3d9a7b2e410_phase_10c_timetable_generation_foundation.py")
    text = migration_path.read_text(encoding="utf-8")

    assert "def upgrade()" in text
    assert "def downgrade()" in text
    assert "timetable_generation_configurations" in text
    assert "timetable_teacher_scheduling_preferences" in text
    assert "timetable_generation_overrides" in text
    assert "timetable_generation_locks" in text
    assert "timetable_parallel_lesson_blocks" in text
    assert "timetable_parallel_lesson_children" in text
