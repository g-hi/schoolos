"""
substitution_pdf.py
───────────────────
Generates a printable PDF substitution plan for a given date using fpdf2.

Layout:
  - Single page (landscape A4).
  - Header: school name + "Substitution Plan" + date.
  - Table: Absent Teacher | Substitute | Subject | Class | Period | Status | AI Reasoning
"""

import io
from datetime import date as date_type
from uuid import UUID

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.db.connection import AsyncSessionLocal, set_tenant_context
from shared.db.models import (
    Substitution,
    Teacher,
    Tenant,
    TimetableEntry,
)


async def build_substitution_pdf(tenant_id: UUID, report_date: date_type) -> bytes:
    data = await _load_data(tenant_id, report_date)
    return _render_pdf(data)


async def _load_data(tenant_id: UUID, report_date: date_type) -> dict:
    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, tenant_id)

        tenant_q = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = tenant_q.scalar_one()

        subs_q = await session.execute(
            select(Substitution)
            .where(
                Substitution.tenant_id == tenant_id,
                Substitution.date == report_date,
            )
            .options(
                selectinload(Substitution.timetable_entry).selectinload(TimetableEntry.period),
                selectinload(Substitution.timetable_entry).selectinload(TimetableEntry.klass),
                selectinload(Substitution.timetable_entry).selectinload(TimetableEntry.subject),
                selectinload(Substitution.absent_teacher).selectinload(Teacher.user),
                selectinload(Substitution.substitute_teacher).selectinload(Teacher.user),
            )
            .order_by(Substitution.created_at)
        )
        subs = subs_q.scalars().all()

    rows = []
    for s in subs:
        entry = s.timetable_entry
        absent_name = s.absent_teacher.user.name if s.absent_teacher and s.absent_teacher.user else "—"
        sub_name = s.substitute_teacher.user.name if s.substitute_teacher and s.substitute_teacher.user else "—"
        subject = entry.subject.name if entry and entry.subject else "—"
        cls = f"{entry.klass.grade} {entry.klass.section}" if entry and entry.klass else "—"
        period = entry.period.name if entry and entry.period else "—"
        status = s.status or "—"
        reasoning = ""
        if s.confidence_reasons and isinstance(s.confidence_reasons, dict):
            reasoning = s.confidence_reasons.get("ai_reasoning", "")

        rows.append({
            "absent": absent_name,
            "substitute": sub_name,
            "subject": subject,
            "class": cls,
            "period": period,
            "status": status,
            "reasoning": reasoning,
        })

    return {
        "school_name": tenant.name,
        "date": report_date,
        "rows": rows,
    }


class _PDF(FPDF):
    def __init__(self, school_name: str):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.school_name = school_name
        self.set_auto_page_break(auto=True, margin=15)


def _render_pdf(data: dict) -> bytes:
    school_name = data["school_name"]
    report_date: date_type = data["date"]
    rows = data["rows"]

    pdf = _PDF(school_name)
    pdf.add_page()

    PAGE_W = 297
    MARGIN = 10
    USABLE_W = PAGE_W - 2 * MARGIN
    pdf.set_margins(MARGIN, MARGIN)

    day_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                "Saturday", "Sunday"][report_date.weekday()]

    # ── Title bar ─────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_fill_color(30, 80, 160)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(
        USABLE_W, 10,
        f"{school_name}  |  Substitution Plan",
        border=0, new_x="LMARGIN", new_y="NEXT", align="C", fill=True,
    )
    pdf.ln(1)

    # ── Date subtitle ─────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(
        USABLE_W, 8,
        f"{day_name}, {report_date.strftime('%B %d, %Y')}",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.ln(3)

    if not rows:
        pdf.set_font("Helvetica", "I", 12)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(USABLE_W, 10, "No substitutions for this date.", align="C")
        buf = io.BytesIO()
        pdf.output(buf)
        return buf.getvalue()

    # ── Column widths ─────────────────────────────────────────────────────
    COL_W = {
        "absent":     35,
        "substitute": 35,
        "subject":    32,
        "class":      28,
        "period":     22,
        "status":     25,
    }
    reasoning_w = USABLE_W - sum(COL_W.values())
    ROW_H = 9

    # ── Table header ──────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(220, 230, 245)
    pdf.set_text_color(0, 0, 0)

    headers = [
        ("Absent Teacher", COL_W["absent"]),
        ("Substitute",     COL_W["substitute"]),
        ("Subject",        COL_W["subject"]),
        ("Class",          COL_W["class"]),
        ("Period",         COL_W["period"]),
        ("Status",         COL_W["status"]),
        ("AI Reasoning",   reasoning_w),
    ]
    for label, w in headers:
        pdf.cell(w, ROW_H, f" {label}", border=1, fill=True)
    pdf.ln()

    # ── Table rows ────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 8)
    fill = False
    for row in rows:
        # Alternate row shading
        if fill:
            pdf.set_fill_color(245, 247, 252)
        else:
            pdf.set_fill_color(255, 255, 255)

        # Status color
        status_display = "Assigned" if row["status"] == "assigned" else "Unassigned"

        # Truncate reasoning to fit
        reasoning_text = row["reasoning"][:80] + ("..." if len(row["reasoning"]) > 80 else "")

        cells = [
            (row["absent"],     COL_W["absent"]),
            (row["substitute"], COL_W["substitute"]),
            (row["subject"],    COL_W["subject"]),
            (row["class"],      COL_W["class"]),
            (row["period"],     COL_W["period"]),
            (status_display,    COL_W["status"]),
            (reasoning_text,    reasoning_w),
        ]
        for text, w in cells:
            pdf.cell(w, ROW_H, f" {text}", border=1, fill=True)
        pdf.ln()
        fill = not fill

    # ── Summary ───────────────────────────────────────────────────────────
    pdf.ln(4)
    assigned = sum(1 for r in rows if r["status"] == "assigned")
    total = len(rows)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(30, 80, 160)
    pdf.cell(USABLE_W, 8, f"Total: {total}  |  Assigned: {assigned}  |  Unassigned: {total - assigned}", align="R")

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
