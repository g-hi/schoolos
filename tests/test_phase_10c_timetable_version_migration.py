from __future__ import annotations

from pathlib import Path
import re

from alembic.config import Config
from alembic.script import ScriptDirectory


REVISION_ID = "e7b1c9d4a2f0"
DOWN_REVISION = "c3d9a7b2e410"
MAX_PG_IDENTIFIER_LEN = 63
NEW_BASELINE_FK_NAME = "fk_tt_gen_cfg_baseline_version"
OLD_BASELINE_FK_NAME = "fk_timetable_generation_configurations_baseline_timetable_version_id"


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


def _explicit_identifier_names(migration_text: str) -> set[str]:
    names: set[str] = set()
    patterns = [
        r"create_foreign_key\(\s*\"([^\"]+)\"",
        r"create_index\(\s*\"([^\"]+)\"",
        r"drop_index\(\s*\"([^\"]+)\"",
        r"drop_constraint\(\s*\"([^\"]+)\"",
        r"create_check_constraint\(\s*\"([^\"]+)\"",
        r"name=\"([^\"]+)\"",
    ]
    for pattern in patterns:
        names.update(re.findall(pattern, migration_text))
    return names


def test_batch5_migration_identifiers_are_postgres_safe() -> None:
    path = Path("alembic/versions/e7b1c9d4a2f0_phase_10c_timetable_versioning_batch5.py")
    text = path.read_text(encoding="utf-8")
    names = _explicit_identifier_names(text)

    assert NEW_BASELINE_FK_NAME in names
    assert len(NEW_BASELINE_FK_NAME) <= MAX_PG_IDENTIFIER_LEN
    assert OLD_BASELINE_FK_NAME not in names

    too_long = sorted((name, len(name)) for name in names if len(name) > MAX_PG_IDENTIFIER_LEN)
    assert too_long == []
