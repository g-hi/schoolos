from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from services.gateway.main import app
from shared.auth.dependencies import require_role


REQUIRED_WORKBOOK_ROUTES = {
    "/leadership/timetable-setup/imports/template",
    "/leadership/timetable-setup/imports/workbooks",
    "/leadership/timetable-setup/imports/workbooks/{batch_id}",
    "/leadership/timetable-setup/imports/workbooks/{batch_id}/sheets",
    "/leadership/timetable-setup/imports/workbooks/{batch_id}/preview",
    "/leadership/timetable-setup/imports/workbooks/{batch_id}/mappings",
    "/leadership/timetable-setup/imports/workbooks/{batch_id}/validate",
    "/leadership/timetable-setup/imports/workbooks/{batch_id}/commit",
    "/leadership/timetable-setup/imports/workbooks/{batch_id}/cancel",
    "/leadership/timetable-setup/imports/workbooks/{batch_id}/diagnostics",
}


def _user(*, tenant_id: uuid.UUID, role: str, is_active: bool = True):
    return type("U", (), {"id": uuid.uuid4(), "tenant_id": tenant_id, "role": role, "is_active": is_active})()


def test_workbook_routes_exist_and_do_not_expose_delete() -> None:
    paths = app.openapi()["paths"]
    assert REQUIRED_WORKBOOK_ROUTES.issubset(paths.keys())
    for path, methods in paths.items():
        if path.startswith("/leadership/timetable-setup/imports"):
            assert "delete" not in methods


@pytest.mark.asyncio
async def test_leadership_only_contract_for_new_routes() -> None:
    dep = require_role("principal", "school_admin")
    tenant_id = uuid.uuid4()

    await dep(current_user=_user(tenant_id=tenant_id, role="principal"))
    await dep(current_user=_user(tenant_id=tenant_id, role="school_admin"))

    for disallowed in ("teacher", "parent", "student"):
        with pytest.raises(HTTPException) as exc:
            await dep(current_user=_user(tenant_id=tenant_id, role=disallowed))
        assert exc.value.status_code == 403
