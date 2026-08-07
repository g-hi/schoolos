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
from typing import Any

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
from services.gateway.routers.ai_copilot import router as ai_copilot_router
from services.gateway.routers.exam_marking import router as exam_marking_router
# Phase 8.1 — Parent Experience
from services.gateway.routers.auth import router as auth_router
from services.gateway.routers.parent import router as parent_router
from services.gateway.routers.parent_assistant import router as parent_assistant_router
from services.gateway.routers.families import leadership_router as leadership_families_router
from services.gateway.routers.families import router as families_router
from services.gateway.routers.people import router as people_router
from services.gateway.routers.weekly_reports import router as weekly_reports_router
from services.gateway.routers.parent_reports import router as parent_reports_router
from services.gateway.routers.appointments import router as appointments_router
from services.gateway.routers.announcements import router as announcements_router
from services.gateway.routers.master_data import router as master_data_router
from services.gateway.routers.academic_structure import router as academic_structure_router
from services.gateway.routers.teacher_assignments import router as teacher_assignments_router
from services.gateway.routers.teacher_classes import router as teacher_classes_router
from services.gateway.routers.student_enrollments import router as student_enrollments_router
from services.gateway.routers.imports import router as imports_router
from services.gateway.routers.onboarding import router as onboarding_router
from services.gateway.routers.timetable_setup import router as timetable_setup_router
from services.gateway.routers.timetable_setup_imports import router as timetable_setup_imports_router
from services.gateway.routers.timetable_setup_calendar_intake import router as timetable_setup_calendar_intake_router
from services.gateway.routers.timetable_setup_centre import router as timetable_setup_centre_router
from services.gateway.routers.timetable_policies import router as timetable_policies_router
from services.gateway.routers.timetable_generation import router as timetable_generation_router


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan: runs startup/shutdown logic around the app's lifetime.
# FastAPI replaced the old @app.on_event("startup") pattern with this.
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    print(f"SchoolOS Gateway starting in '{settings.app_env}' mode")

    # ── Step 0: Production secret key validation ──────────────────────
    from shared.auth.jwt import validate_secret_key_for_environment
    validate_secret_key_for_environment()

    # Schema evolution is Alembic-managed.
    # The local Docker gateway container and deployment Dockerfile both run
    # `alembic upgrade head` before uvicorn starts. Avoid create_all here so
    # development startup cannot silently create future tables ahead of the
    # recorded Alembic revision.
    if settings.app_env != "production":
        print("Development mode: schema managed externally by Alembic.")
    else:
        print("Production mode: schema managed by Alembic.")

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


def _parse_cors_allowed_origins(raw: str | None) -> list[str]:
  """Parse comma-separated CORS origins and drop unsafe wildcard entries."""
  if not raw:
    return []

  allowed: list[str] = []
  for part in raw.split(","):
    origin = part.strip()
    if not origin:
      continue
    # Never allow wildcard when credentials are enabled.
    if origin == "*":
      continue
    allowed.append(origin)
  return allowed


def _build_cors_middleware_options(*, app_env: str, cors_allowed_origins_raw: str | None) -> dict[str, Any]:
  """Build CORS middleware options with an environment-driven allowlist."""
  del app_env
  allowed_origins = _parse_cors_allowed_origins(cors_allowed_origins_raw)
  return {
    "allow_origins": allowed_origins,
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
  }

# ── CORS ─────────────────────────────────────────────────────────────────────
# CORS origins are loaded from CORS_ALLOWED_ORIGINS as a comma-separated list.
# Missing or empty configuration produces an empty allowlist (fail-safe).
app.add_middleware(CORSMiddleware, **_build_cors_middleware_options(app_env=settings.app_env, cors_allowed_origins_raw=settings.cors_allowed_origins))


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
app.include_router(ai_copilot_router)
app.include_router(exam_marking_router)
# Phase 8.1 — Parent Experience
app.include_router(auth_router)
app.include_router(parent_router)
app.include_router(parent_assistant_router)
app.include_router(families_router)
app.include_router(leadership_families_router)
app.include_router(people_router)
app.include_router(weekly_reports_router)
app.include_router(parent_reports_router)
app.include_router(appointments_router)
app.include_router(announcements_router)
app.include_router(master_data_router)
app.include_router(academic_structure_router)
app.include_router(teacher_assignments_router)
app.include_router(teacher_classes_router)
app.include_router(student_enrollments_router)
app.include_router(imports_router)
app.include_router(onboarding_router)
app.include_router(timetable_setup_router)
app.include_router(timetable_setup_imports_router)
app.include_router(timetable_setup_calendar_intake_router)
app.include_router(timetable_setup_centre_router)
app.include_router(timetable_policies_router)
app.include_router(timetable_generation_router)

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
