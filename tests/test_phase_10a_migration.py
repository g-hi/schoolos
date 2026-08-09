from alembic.config import Config
from alembic.script import ScriptDirectory


def test_phase_10a_migration_head_and_chain() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()

    assert heads == ["e7b1c9d4a2f0"]

    revision_chain = {
        revision.revision
        for revision in script.iterate_revisions(heads[0], "base")
    }

    assert "c3d9a7b2e410" in revision_chain
    assert "a84f2c1d9e30" in revision_chain
    assert "f91c2d7a6b55" in revision_chain
    assert "d2f6e7a9b4c1" in revision_chain
    assert "9a10b1c2d3e4" in revision_chain
    assert "c4f7a8e2d911" in revision_chain