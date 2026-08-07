from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


REVISION_ID = "a84f2c1d9e30"
DOWN_REVISION = "f91c2d7a6b55"


def test_phase_10b_revision_head_and_down_revision() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert heads == [REVISION_ID]

    revision = script.get_revision(REVISION_ID)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION


def test_phase_10b_migration_contains_upgrade_and_downgrade_objects() -> None:
    migration_path = Path("alembic/versions/a84f2c1d9e30_phase_10b_timetable_policy_constraints_foundation.py")
    text = migration_path.read_text(encoding="utf-8")

    assert "def upgrade()" in text
    assert "def downgrade()" in text
    assert "timetable_policy_sets" in text
    assert "timetable_policy_constraints" in text
    assert "timetable_policy_exceptions" in text
