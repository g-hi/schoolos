"""
pdf_export.py
─────────────
Generates a printable PDF timetable using fpdf2.

Layout:
  - One page per class.
  - Header: school name (from tenant) + class name + academic year.
  - Grid table: rows = periods (Period 1 … Period N), 
                cols = days (Mon–Fri).
  - Each cell shows: Subject\nTeacher name.
  - Empty cells (no lesson scheduled) left blank.

Why fpdf2?
  - Pure Python, no Java or wkhtmltopdf dependency.
  - Simple grid API with multi_cell for wrapping text.
  - Generates a real binary PDF, not HTML.

Usage (from the router):
  pdf_bytes = await build_timetable_pdf(tenant_id, academic_year)
  return Response(pdf_bytes, media_type="application/pdf", ...)
"""

import io
from uuid import UUID

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db.connection import AsyncSessionLocal, set_tenant_context
from shared.db.models import (
    Class,
    Period,
    Subject,
    Teacher,
    Tenant,
    TimetableEntry,
)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

async def build_timetable_pdf(tenant_id: UUID, academic_year: str) -> bytes:
    """
    Build a multi-page PDF timetable (one page per class).
    Returns raw bytes suitable for a FastAPI FileResponse / Response.
    """
    data = await _load_pdf_data(tenant_id, academic_year)

    # Run the synchronous fpdf2 work on the current thread
    # (fpdf2 is fast enough that we don't need run_in_executor)
    pdf_bytes = _render_pdf(data, academic_year)
    return pdf_bytes


# ─────────────────────────────────────────────────────────────────────────────
# DB loading
# ─────────────────────────────────────────────────────────────────────────────

async def _load_pdf_data(tenant_id: UUID, academic_year: str) -> dict:
    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id)

        # Tenant name for header
        tenant_q = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = tenant_q.scalar_one()

        # Periods sorted by order
        periods_q = await session.execute(
            select(Period)
            .where(Period.tenant_id == tenant_id)
            .order_by(Period.sort_order)
        )
        periods = periods_q.scalars().all()

        # Classes
        classes_q = await session.execute(
            select(Class).where(Class.tenant_id == tenant_id)
        )
        classes = classes_q.scalars().all()

        # Timetable entries with all relations eagerly loaded
        entries_q = await session.execute(
            select(TimetableEntry)
            .where(
                TimetableEntry.tenant_id == tenant_id,
                TimetableEntry.academic_year == academic_year,
                TimetableEntry.is_active.is_(True),
            )
            .options(
                selectinload(TimetableEntry.period),
                selectinload(TimetableEntry.klass),
                selectinload(TimetableEntry.subject),
                selectinload(TimetableEntry.teacher).selectinload(Teacher.user),
            )
        )
        entries = entries_q.scalars().all()

    # Build lookup:  (class_id, day_of_week, period_id) → (subject_name, teacher_name)
    cell: dict[tuple, tuple[str, str]] = {}
    for e in entries:
        key = (str(e.class_id), e.day_of_week, str(e.period_id))
        cell[key] = (e.subject.name, e.teacher.user.name)

    return {
        "school_name": tenant.name,
        "classes":     classes,
        "periods":     periods,
        "cell":        cell,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PDF rendering
# ─────────────────────────────────────────────────────────────────────────────

class _PDF(FPDF):
    """Custom FPDF subclass for the school timetable style."""

    def __init__(self, school_name: str):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.school_name = school_name
        self.set_auto_page_break(auto=False)

    def header(self):
        # Called automatically at the top of each page — left empty,
        # we build our own header in _render_class_page.
        pass


def _render_pdf(data: dict, academic_year: str) -> bytes:
    school_name = data["school_name"]
    classes     = data["classes"]
    periods     = data["periods"]
    cell        = data["cell"]

    pdf = _PDF(school_name)

    # Column width math (A4 landscape = 297mm, margins 10mm each side)
    PAGE_W      = 297
    MARGIN      = 10
    USABLE_W    = PAGE_W - 2 * MARGIN
    N_DAYS      = 5
    PERIOD_COL  = 28           # width of the "Period" label column
    DAY_COL_W   = (USABLE_W - PERIOD_COL) / N_DAYS  # width per day column
    ROW_H       = 14           # height per period row
    HEADER_H    = 8            # height of day-name header row

    for cls in classes:
        pdf.add_page()
        pdf.set_margins(MARGIN, MARGIN)

        class_label = f"{cls.grade} {cls.section}"

        # ── Page title ────────────────────────────────────────────────────
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_fill_color(30, 80, 160)     # dark blue
        pdf.set_text_color(255, 255, 255)
        pdf.cell(
            USABLE_W, 10,
            f"{school_name}  |  {class_label}  |  {academic_year}",
            border=0, new_x="LMARGIN", new_y="NEXT",
            align="C", fill=True,
        )
        pdf.ln(2)

        # ── Day header row ────────────────────────────────────────────────
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(220, 230, 245)
        pdf.set_text_color(0, 0, 0)

        # blank cell above the period column
        pdf.cell(PERIOD_COL, HEADER_H, "", border=1, fill=True)
        for day_name in DAYS:
            pdf.cell(DAY_COL_W, HEADER_H, day_name, border=1, align="C", fill=True)
        pdf.ln()

        # ── Period rows ───────────────────────────────────────────────────
        for period in periods:
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(245, 245, 245)
            pdf.set_text_color(50, 50, 50)

            period_label = f"P{period.sort_order}\n{period.start_time[:5]}-{period.end_time[:5]}"
            # Use multi_cell for the period label (supports \n)
            x_before = pdf.get_x()
            y_before = pdf.get_y()
            pdf.multi_cell(
                PERIOD_COL, ROW_H / 2,
                period_label,
                border=1, align="C", fill=True,
            )
            row_bottom = pdf.get_y()

            # Now draw 5 day cells at the same y level as period label start
            pdf.set_xy(x_before + PERIOD_COL, y_before)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(0, 0, 0)

            for day_idx in range(N_DAYS):
                key = (str(cls.id), day_idx, str(period.id))
                subject_name, teacher_name = cell.get(key, ("", ""))
                cell_text = f"{subject_name}\n{teacher_name}" if subject_name else ""
                pdf.multi_cell(
                    DAY_COL_W, ROW_H / 2,
                    cell_text,
                    border=1, align="C", fill=True, max_line_height=4,
                )
                # Move to right of current cell start for next day
                if day_idx < N_DAYS - 1:
                    pdf.set_xy(
                        x_before + PERIOD_COL + (day_idx + 1) * DAY_COL_W,
                        y_before,
                    )

            # Advance to next row
            new_y = max(row_bottom, y_before + ROW_H)
            pdf.set_xy(MARGIN, new_y)

    # Return bytes
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
