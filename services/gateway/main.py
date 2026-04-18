"""
SchoolOS – API Gateway (Entry Point)
=====================================
This is the single FastAPI application that all HTTP traffic hits first.

In later phases, this gateway will:
  - Route requests to the correct MCP microservice
  - Handle webhook calls from Twilio (incoming WhatsApp/SMS)
  - Enforce authentication (JWT)
  - Apply rate limiting

For Phase 0, it provides:
  - /health           → confirms the service is running
  - /tenant-info      → confirms tenant resolution works
  - /db-health        → confirms database connection works
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth.tenant import resolve_tenant
from shared.config import settings
from shared.db.connection import get_db
from shared.db.models import Tenant
from services.gateway.routers.ingest import router as ingest_router
from services.gateway.routers.timetable import router as timetable_router
from services.gateway.routers.substitution import router as substitution_router
from services.gateway.routers.communication import router as communication_router
from services.gateway.routers.pickup import router as pickup_router
from services.gateway.routers.audit import router as audit_router
from services.gateway.routers.dashboard import router as dashboard_router
from services.gateway.routers.social import router as social_router
from services.gateway.routers.duty import router as duty_router


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan: runs startup/shutdown logic around the app's lifetime.
# FastAPI replaced the old @app.on_event("startup") pattern with this.
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    print(f"SchoolOS Gateway starting in '{settings.app_env}' mode")

    # Auto-create tables (safe for Render where init.sql doesn't run)
    import asyncio
    for attempt in range(5):
        try:
            from shared.db.connection import engine
            from shared.db.models import Base
            async with engine.begin() as conn:
                # One-time schema fix: drop old duty_assignments table so
                # create_all can recreate it with the correct schema
                # (removed week_start column, changed constraints)
                await conn.execute(text("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'duty_assignments'
                              AND column_name = 'week_start'
                        ) THEN
                            DROP TABLE duty_assignments CASCADE;
                        END IF;
                    END $$
                """))

                await conn.run_sync(Base.metadata.create_all)

            # Seed default tenant if it doesn't exist
            from shared.db.connection import AsyncSessionLocal
            from shared.db.models import Tenant
            from sqlalchemy import select
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Tenant).limit(1))
                if result.scalar_one_or_none() is None:
                    session.add(Tenant(
                        name="Greenwood International Academy",
                        slug="greenwood",
                    ))
                    await session.commit()
            print("Database ready")
            break
        except Exception as e:
            print(f"DB init attempt {attempt+1}/5 failed: {e}")
            if attempt < 4:
                await asyncio.sleep(3)
            else:
                print("WARNING: Could not connect to database, starting anyway")

    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    print("SchoolOS Gateway shutting down")


# ─────────────────────────────────────────────────────────────────────────────
# App instance
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SchoolOS Gateway",
    version="0.1.0",
    description="Multi-tenant AI Operating System for International Schools",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# In development, allow all origins so you can call the API from Postman,
# a browser, or any frontend without issues.
# In production, this should be locked to your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTERS
# =============================================================================

app.include_router(ingest_router)
app.include_router(timetable_router)
app.include_router(substitution_router)
app.include_router(communication_router)
app.include_router(pickup_router)
app.include_router(audit_router)
app.include_router(dashboard_router)
app.include_router(social_router)
app.include_router(duty_router)

# =============================================================================
# ROUTES
# =============================================================================

@app.get("/health", tags=["System"])
async def health_check():
    """
    Simple liveness check.
    Used by Docker, load balancers, and monitoring tools.
    If this returns 200, the process is alive.
    """
    return {"status": "ok", "version": "0.1.0", "env": settings.app_env}


@app.get("/db-health", tags=["System"])
async def db_health(db: AsyncSession = Depends(get_db)):
    """
    Confirms the database connection is working.
    Runs 'SELECT 1' — the simplest possible query.
    If this fails, check DATABASE_URL in your .env file.
    """
    await db.execute(text("SELECT 1"))
    return {"status": "database ok"}


@app.get("/tenant-info", tags=["Multi-Tenancy"])
async def tenant_info(tenant: Tenant = Depends(resolve_tenant)):
    """
    Test endpoint for the tenant resolver.

    Try it with:
      curl -H "X-Tenant-Slug: greenwood" http://localhost:8000/tenant-info

    Expected response:
      { "tenant_id": "...", "name": "Greenwood International School", "slug": "greenwood" }

    Without the header:
      401 Unauthorized — "School identity could not be resolved."

    With an unknown slug:
      404 Not Found — "School 'xyz' not found or is inactive."
    """
    return {
        "tenant_id": str(tenant.id),
        "name":      tenant.name,
        "slug":      tenant.slug,
        "settings":  tenant.settings,
    }
