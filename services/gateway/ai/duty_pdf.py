"""
duty_pdf.py
───────────
Generates a printable PDF duty roster for a given week using fpdf2.

Layout:
  - Landscape A4
  - Header: school name + "Weekly Duty Roster" + week range
  - Grid: rows = duty slots, columns = Mon-Fri, cells = Teacher @ Location
"""

import io
from datetime import date as date_type, timedelta
from uuid import UUID

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db.connection import AsyncSessionLocal, set_tenant_context
from shared.db.models import (
    DutyAssignment,
    DutyLocation,
    DutySlot,
    Teacher,
    Tenant,
    User,
)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


async def build_duty_pdf(tenant_id: UUID, week_start: date_type) -> bytes:
    data = await _load_data(tenant_id, week_start)
    return _render_pdf(data)


async def _load_data(tenant_id: UUID, week_start: date_type) -> dict:
    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id)

        tenant_q = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = tenant_q.scalar_one()

        slots_q = await session.execute(
            select(DutySlot)
            .where(DutySlot.tenant_id == tenant_id, DutySlot.is_active.is_(True))
            .order_by(DutySlot.start_time)
        )
        slots = slots_q.scalars().all()

        assignments_q = await session.execute(
            select(DutyAssignment)
            .where(
                DutyAssignment.tenant_id == tenant_id,
                DutyAssignment.week_start == week_start,
            )
            .options(
                selectinload(DutyAssignment.teacher).selectinload(Teacher.user),
                selectinload(DutyAssignment.duty_slot),
                selectinload(DutyAssignment.location),
            )
        )
        assignments = assignments_q.scalars().all()

    # Build lookup: (slot_id, day) -> list of {teacher, location}
    grid: dict[tuple, list[dict]] = {}
    for a in assignments:
        key = (str(a.duty_slot_id), a.day_of_week)
        teacher_name = a.teacher.user.name if a.teacher and a.teacher.user else "—"
        loc_name = a.location.name if a.location else "—"
        grid.setdefault(key, []).append({"teacher": teacher_name, "location": loc_name})

    week_end = week_start + timedelta(days=4)

    return {
        "school_name": tenant.name,
        "week_start": week_start,
        "week_end": week_end,
        "slots": [{"id": str(s.id), "name": s.name, "start": s.start_time, "end": s.end_time} for s in slots],
        "grid": grid,
    }


class _PDF(FPDF):
    def __init__(self, school_name: str):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.school_name = school_name
        self.set_auto_page_break(auto=True, margin=15)


def _render_pdf(data: dict) -> bytes:
    school_name = data["school_name"]
    week_start: date_type = data["week_start"]
    week_end: date_type = data["week_end"]
    slots = data["slots"]
    grid = data["grid"]

    pdf = _PDF(school_name)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_fill_color(66, 66, 150)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 12, f"{school_name} - Weekly Duty Roster", align="C", fill=True, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, f"Week: {week_start.strftime('%B %d')} - {week_end.strftime('%B %d, %Y')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Column widths
    page_w = pdf.w - 20  # margins
    slot_col_w = 50
    day_col_w = (page_w - slot_col_w) / 5

    # Header row
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(66, 66, 150)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(slot_col_w, 10, "Duty Slot", border=1, fill=True, align="C")
    for day_name in DAY_NAMES:
        pdf.cell(day_col_w, 10, day_name, border=1, fill=True, align="C")
    pdf.ln()

    # Data rows
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(30, 30, 30)
    row_h = 14

    for i, slot in enumerate(slots):
        # Alternating row color
        if i % 2 == 0:
            pdf.set_fill_color(240, 240, 255)
        else:
            pdf.set_fill_color(255, 255, 255)

        y_start = pdf.get_y()

        # Slot label
        slot_label = f"{slot['name']}\n{slot['start']}-{slot['end']}"
        pdf.set_font("Helvetica", "B", 9)
        pdf.multi_cell(slot_col_w, row_h / 2, slot_label, border=1, fill=True, align="C", new_x="RIGHT", new_y="TOP")

        pdf.set_font("Helvetica", "", 9)
        for day_idx in range(5):
            key = (slot["id"], day_idx)
            entries = grid.get(key, [])
            if entries:
                cell_text = "\n".join(f"{e['teacher']} @ {e['location']}" for e in entries)
            else:
                cell_text = "—"

            pdf.set_xy(pdf.l_margin + slot_col_w + day_idx * day_col_w, y_start)
            pdf.multi_cell(day_col_w, row_h / 2, cell_text, border=1, fill=True, align="C", new_x="RIGHT", new_y="TOP")

        pdf.set_y(y_start + row_h)

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
