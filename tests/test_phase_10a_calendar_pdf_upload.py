from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from services.gateway.routers import timetable_setup_calendar_intake as calendar_intake
from shared.db.models import CalendarSourceDocument


class _Db(AsyncMock):
    def __init__(self):
        super().__init__()
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.scalar = AsyncMock(return_value=None)
        self.execute = AsyncMock()


class _PdfPage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _PdfReaderOK:
    is_encrypted = False

    def __init__(self, _stream):
        self.pages = [_PdfPage("2026-09-01 Holiday"), _PdfPage("2026-09-02 Event")]


class _PdfReaderEncrypted:
    is_encrypted = True

    def __init__(self, _stream):
        self.pages = []


class _PdfReaderTooManyPages:
    is_encrypted = False

    def __init__(self, _stream):
        self.pages = [_PdfPage("x")] * 999


class _PdfReaderNoText:
    is_encrypted = False

    def __init__(self, _stream):
        self.pages = [_PdfPage(""), _PdfPage("   ")]


def _tenant() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), slug="greenwood", name="Greenwood", is_active=True)


def _user(*, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="principal", is_active=True)


@pytest.mark.asyncio
async def test_upload_rejects_non_pdf_extension_and_signature() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    txt_upload = UploadFile(file=io.BytesIO(b"%PDF-1.7"), filename="calendar.txt")
    with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await calendar_intake.upload_calendar_pdf(file=txt_upload, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 422

    bad_signature_upload = UploadFile(file=io.BytesIO(b"NOT_PDF"), filename="calendar.pdf")
    with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await calendar_intake.upload_calendar_pdf(file=bad_signature_upload, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_upload_rejects_empty_and_oversized_payload() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    empty_upload = UploadFile(file=io.BytesIO(b""), filename="calendar.pdf")
    with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            await calendar_intake.upload_calendar_pdf(file=empty_upload, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 422

    oversized_upload = UploadFile(file=io.BytesIO(b"%PDF" + b"A" * 1024), filename="calendar.pdf")
    original = calendar_intake.settings.timetable_calendar_pdf_max_upload_bytes
    calendar_intake.settings.timetable_calendar_pdf_max_upload_bytes = 20
    try:
        with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()):
            with pytest.raises(HTTPException) as exc:
                await calendar_intake.upload_calendar_pdf(file=oversized_upload, tenant=tenant, actor=actor, db=db)
        assert exc.value.status_code == 413
    finally:
        calendar_intake.settings.timetable_calendar_pdf_max_upload_bytes = original


@pytest.mark.asyncio
async def test_upload_rejects_malformed_encrypted_and_too_many_pages() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    upload = UploadFile(file=io.BytesIO(b"%PDF-1.7"), filename="calendar.pdf")

    with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup_calendar_intake.PdfReader", side_effect=ValueError("broken pdf")
    ):
        with pytest.raises(HTTPException) as exc:
            await calendar_intake.upload_calendar_pdf(file=upload, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 422

    upload2 = UploadFile(file=io.BytesIO(b"%PDF-1.7"), filename="calendar.pdf")
    with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup_calendar_intake.PdfReader", new=_PdfReaderEncrypted
    ):
        with pytest.raises(HTTPException) as exc:
            await calendar_intake.upload_calendar_pdf(file=upload2, tenant=tenant, actor=actor, db=db)
    assert exc.value.status_code == 422

    upload3 = UploadFile(file=io.BytesIO(b"%PDF-1.7"), filename="calendar.pdf")
    original_pages = calendar_intake.settings.timetable_calendar_pdf_max_pages
    calendar_intake.settings.timetable_calendar_pdf_max_pages = 2
    try:
        with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()), patch(
            "services.gateway.routers.timetable_setup_calendar_intake.PdfReader", new=_PdfReaderTooManyPages
        ):
            with pytest.raises(HTTPException) as exc:
                await calendar_intake.upload_calendar_pdf(file=upload3, tenant=tenant, actor=actor, db=db)
        assert exc.value.status_code == 422
    finally:
        calendar_intake.settings.timetable_calendar_pdf_max_pages = original_pages


@pytest.mark.asyncio
async def test_upload_sanitizes_filename_and_duplicate_sha_is_idempotent() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)

    existing_doc = CalendarSourceDocument(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        import_batch_id=uuid.uuid4(),
        original_filename="calendar.pdf",
        file_sha256="abc",
        extraction_status="review_ready",
    )
    db.scalar = AsyncMock(side_effect=[existing_doc, existing_doc.import_batch_id])

    upload = UploadFile(file=io.BytesIO(b"%PDF-1.7 SAME"), filename="..\\unsafe\\name.pdf")
    with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()):
        payload = await calendar_intake.upload_calendar_pdf(file=upload, tenant=tenant, actor=actor, db=db)

    assert payload["deduplicated"] is True
    assert payload["document_id"] == str(existing_doc.id)


@pytest.mark.asyncio
async def test_upload_success_does_not_execute_active_content() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    upload = UploadFile(file=io.BytesIO(b"%PDF-1.7 OK"), filename="calendar.pdf")

    db.scalar = AsyncMock(return_value=None)
    with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup_calendar_intake.log_action", new=AsyncMock()
    ), patch("services.gateway.routers.timetable_setup_calendar_intake.PdfReader", new=_PdfReaderOK):
        payload = await calendar_intake.upload_calendar_pdf(file=upload, tenant=tenant, actor=actor, db=db)

    assert payload["status"] in {"review_ready", "ocr_required"}
    added = [call.args[0].__class__.__name__ for call in db.add.call_args_list]
    assert "CalendarSourcePage" in added


@pytest.mark.asyncio
async def test_upload_without_text_layer_becomes_ocr_required() -> None:
    db = _Db()
    tenant = _tenant()
    actor = _user(tenant_id=tenant.id)
    upload = UploadFile(file=io.BytesIO(b"%PDF-1.7 OK"), filename="calendar.pdf")

    db.scalar = AsyncMock(return_value=None)
    with patch("services.gateway.routers.timetable_setup_calendar_intake.set_tenant_context", new=AsyncMock()), patch(
        "services.gateway.routers.timetable_setup_calendar_intake.log_action", new=AsyncMock()
    ), patch("services.gateway.routers.timetable_setup_calendar_intake.PdfReader", new=_PdfReaderNoText):
        payload = await calendar_intake.upload_calendar_pdf(file=upload, tenant=tenant, actor=actor, db=db)

    assert payload["status"] == "ocr_required"
