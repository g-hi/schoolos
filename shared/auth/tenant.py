"""
Tenant Resolver
===============
Determines WHICH school is making a request before any route handler runs.

This is injected as a FastAPI dependency:
    tenant: Tenant = Depends(resolve_tenant)

Resolution order (first match wins):
  1. X-Tenant-Slug header   ← used by internal services and API clients
  2. Subdomain              ← e.g., greenwood.schoolos.com → slug = 'greenwood'

Why not use tenant_id (UUID) directly?
  Slugs are human-readable and safe to put in headers without exposing UUIDs.
  The UUID is only used inside the database.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.connection import get_db
from shared.db.models import Tenant


async def resolve_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """
    FastAPI dependency — call Depends(resolve_tenant) in any route
    that needs to know which school is making the request.

    Raises 401 if no slug can be found.
    Raises 404 if the slug does not match any active school.
    """
    slug = _extract_slug(request)

    if not slug:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "School identity could not be resolved. "
                "Add the 'X-Tenant-Slug' header to your request."
            ),
        )

    result = await db.execute(
        select(Tenant).where(
            Tenant.slug == slug,
            Tenant.is_active.is_(True),
        )
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"School '{slug}' not found or is inactive.",
        )

    return tenant


def _extract_slug(request: Request) -> str | None:
    """
    Extracts the tenant slug from the incoming HTTP request.

    Priority 1 — explicit header (e.g., from Postman, mobile app, or internal service):
        X-Tenant-Slug: greenwood

    Priority 2 — subdomain (e.g., browser navigating to greenwood.schoolos.com):
        host: greenwood.schoolos.com → returns 'greenwood'
        host: localhost:8000         → returns None (local dev, use header instead)
    """
    # 1. Header check (highest priority)
    slug = request.headers.get("X-Tenant-Slug")
    if slug:
        return slug.lower().strip()

    # 2. Subdomain check
    host = request.headers.get("host", "")
    # Remove port if present: "greenwood.schoolos.com:8000" → "greenwood.schoolos.com"
    host = host.split(":")[0]
    parts = host.split(".")
    # Need at least subdomain + domain + tld (3 parts) to extract subdomain
    if len(parts) >= 3:
        candidate = parts[0].lower()
        # Reject common non-tenant subdomains
        if candidate not in ("www", "api", "admin", "localhost"):
            return candidate

    return None
