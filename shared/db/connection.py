from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shared.config import settings

# ─────────────────────────────────────────────────────────────────────────────
# Async database engine
#
# create_async_engine builds a connection pool.
# pool_size=10   → keep 10 connections open permanently (reused across requests)
# max_overflow=20 → allow up to 20 extra connections during traffic spikes
# echo=True in dev → prints every SQL query to the console (great for learning)
# ─────────────────────────────────────────────────────────────────────────────

engine = create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),
    pool_size=10,
    max_overflow=20,
)

# ─────────────────────────────────────────────────────────────────────────────
# Session factory
#
# async_sessionmaker creates AsyncSession objects on demand.
# expire_on_commit=False means ORM objects stay usable after a commit
# (important for async code where we return objects to FastAPI).
# ─────────────────────────────────────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — inject this into any route that needs the database.

    Usage in a route:
        @app.get("/something")
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...

    The 'async with' block ensures the session is always closed,
    even if the route raises an exception.
    """
    async with AsyncSessionLocal() as session:
        yield session


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """
    Activates Row-Level Security for this database session.

    How it works:
    1. PostgreSQL has a session variable called app.tenant_id.
    2. Every table has an RLS policy: only return rows where
       tenant_id = current_setting('app.tenant_id').
    3. Before any query, we call this function to set that variable.
    4. Result: queries automatically filter to the correct school's data.

    'SET LOCAL' means the variable resets at the end of the transaction,
    so there is no risk of one school's session leaking into another.
    """
    # SET LOCAL does not support bind parameters — the value must be a literal.
    # We cast to str and quote it safely since tenant_id is always a UUID
    # (hex digits and hyphens only — no SQL injection possible).
    safe_id = str(tenant_id).replace("'", "")
    await session.execute(text(f"SET LOCAL app.tenant_id = '{safe_id}'"))
