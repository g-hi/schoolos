from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData

# ─────────────────────────────────────────────────────────────────────────────
# Naming convention for all database constraints.
#
# Why this matters:
# Alembic (the migration tool) needs predictable constraint names so it can
# generate correct ALTER TABLE statements when you change a model later.
# Without this, Alembic generates names like "constraint_1" which break
# on some databases.
# ─────────────────────────────────────────────────────────────────────────────

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """
    All SQLAlchemy models inherit from this class.
    It carries the naming convention so every model gets consistent
    constraint names automatically.
    """
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
