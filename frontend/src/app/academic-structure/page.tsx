"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { isLeadershipRole } from "@/lib/auth";
import {
  getMasterDataSetupSummary,
  listCampuses,
  listAcademicYears,
  listGradeLevels,
  listTerms,
  createCampus,
  updateCampus,
  createAcademicYear,
  updateAcademicYear,
  createGradeLevel,
  updateGradeLevel,
  createTerm,
  updateTerm,
  type Campus,
  type AcademicYear,
  type GradeLevel,
  type Term,
  type MasterDataSetupSummary,
  MasterDataApiError,
} from "@/lib/master-data-api";
import {
  listClasses,
  listSubjectOfferings,
  listTeacherAssignments,
  createClass,
  updateClass,
  updateSubjectOffering,
  createTeacherAssignment,
  updateTeacherAssignment,
  getAcademicStructureSummary,
  getTeacherAssignmentSummary,
  type CanonicalClass,
  type SubjectOffering,
  type TeacherAssignment,
  AcademicStructureApiError,
} from "@/lib/academic-structure-api";
import {
  listEnrolments,
  createEnrolment,
  updateEnrolment,
  transferEnrolment,
  getEnrolmentSummary,
  getReconciliationDiagnostics,
  type StudentEnrolment,
  type StudentEnrolmentSummary,
  type ReconciliationRow,
  EnrolmentApiError,
} from "@/lib/enrolment-api";

// ─── Utilities ────────────────────────────────────────────────────────────────

const TABS = [
  "Overview",
  "Campuses",
  "Academic Years",
  "Grade Levels",
  "Classes",
  "Subject Offerings",
  "Assignments",
  "Enrolments",
  "Reconciliation",
] as const;

type Tab = (typeof TABS)[number];

function errorMessage(err: unknown): string {
  if (err instanceof MasterDataApiError || err instanceof AcademicStructureApiError || err instanceof EnrolmentApiError) {
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "An unexpected error occurred.";
}

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
      }`}
    >
      {active ? "Active" : "Inactive"}
    </span>
  );
}

function SourceBadge({ source }: { source: "canonical" | "legacy" | string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        source === "canonical" ? "bg-indigo-100 text-indigo-700" : "bg-amber-100 text-amber-700"
      }`}
    >
      {source === "canonical" ? "Canonical" : "Legacy"}
    </span>
  );
}

function ReadinessChip({ level }: { level: "configured" | "partial" | "action_required" }) {
  const map = {
    configured: "bg-green-100 text-green-700",
    partial: "bg-yellow-100 text-yellow-700",
    action_required: "bg-red-100 text-red-700",
  };
  const labels = { configured: "Configured", partial: "Partial", action_required: "Action Required" };
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${map[level]}`}>{labels[level]}</span>;
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h3 className="font-semibold text-gray-800 mb-3">{title}</h3>
      {children}
    </div>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 mb-3">
      <label className="text-xs font-medium text-gray-600">{label}</label>
      {children}
    </div>
  );
}

function Input({
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  );
}

function Btn({
  children,
  onClick,
  variant = "primary",
  disabled = false,
  size = "sm",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean;
  size?: "sm" | "xs";
}) {
  const base = `inline-flex items-center rounded-lg font-medium transition-colors ${
    size === "xs" ? "px-2 py-1 text-xs" : "px-3 py-1.5 text-sm"
  }`;
  const variants = {
    primary: "bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-indigo-300",
    secondary: "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
    danger: "bg-red-600 text-white hover:bg-red-700",
    ghost: "text-indigo-600 hover:underline",
  };
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={`${base} ${variants[variant]}`}>
      {children}
    </button>
  );
}

function ErrorAlert({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700 flex items-start justify-between gap-2">
      <span>{message}</span>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="text-red-400 hover:text-red-600 shrink-0">
          ✕
        </button>
      )}
    </div>
  );
}

function SuccessAlert({ message }: { message: string }) {
  return (
    <div className="rounded-lg bg-green-50 border border-green-200 p-3 text-sm text-green-700">
      {message}
    </div>
  );
}

// ─── Overview Tab ─────────────────────────────────────────────────────────────

function OverviewTab() {
  const [mdSummary, setMdSummary] = useState<MasterDataSetupSummary | null>(null);
  const [asSummary, setAsSummary] = useState<Awaited<ReturnType<typeof getAcademicStructureSummary>> | null>(null);
  const [taSummary, setTaSummary] = useState<Awaited<ReturnType<typeof getTeacherAssignmentSummary>> | null>(null);
  const [enrolSummary, setEnrolSummary] = useState<StudentEnrolmentSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getMasterDataSetupSummary(),
      getAcademicStructureSummary(),
      getTeacherAssignmentSummary(),
      getEnrolmentSummary(),
    ])
      .then(([md, as_, ta, en]) => {
        setMdSummary(md as MasterDataSetupSummary);
        setAsSummary(as_);
        setTaSummary(ta);
        setEnrolSummary(en);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-sm text-gray-500 py-4">Loading overview…</p>;
  if (error) return <ErrorAlert message={error} />;

  const hasCampus = (mdSummary?.active_campus_count ?? 0) > 0;
  const hasYear = (mdSummary?.active_academic_year_count ?? 0) > 0;
  const hasGrade = (mdSummary?.active_grade_level_count ?? 0) > 0;
  const hasClasses = ((asSummary as { canonical_class_count?: number } | null)?.canonical_class_count ?? 0) > 0;
  const hasOfferings = ((asSummary as { active_subject_offering_count?: number } | null)?.active_subject_offering_count ?? 0) > 0;
  const hasAssignments = ((taSummary as { active_assignment_count?: number } | null)?.active_assignment_count ?? 0) > 0;
  const hasEnrolments = (enrolSummary?.students_with_active_canonical_enrollment ?? 0) > 0;

  function readiness(ok: boolean, partial?: boolean): "configured" | "partial" | "action_required" {
    if (ok) return "configured";
    if (partial) return "partial";
    return "action_required";
  }

  const reconciliationIssues =
    (enrolSummary?.students_with_terminal_canonical_history_and_stale_class_id ?? 0) +
    (enrolSummary?.students_with_class_id_conflicting_active_enrollment ?? 0) +
    (enrolSummary?.students_with_multiple_active_enrollments ?? 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Campuses", value: mdSummary?.active_campus_count ?? 0, level: readiness(hasCampus) },
          { label: "Academic Years", value: `${mdSummary?.active_academic_year_count ?? 0} active`, level: readiness(hasYear) },
          { label: "Grade Levels", value: mdSummary?.active_grade_level_count ?? 0, level: readiness(hasGrade) },
          { label: "Terms", value: mdSummary?.term_count ?? 0, level: readiness((mdSummary?.term_count ?? 0) > 0, true) },
          { label: "Canonical Classes", value: (asSummary as { canonical_class_count?: number } | null)?.canonical_class_count ?? 0, level: readiness(hasClasses) },
          { label: "Subject Offerings", value: (asSummary as { active_subject_offering_count?: number } | null)?.active_subject_offering_count ?? 0, level: readiness(hasOfferings, true) },
          { label: "Active Assignments", value: (taSummary as { active_assignment_count?: number } | null)?.active_assignment_count ?? 0, level: readiness(hasAssignments, true) },
          { label: "Active Enrolments", value: enrolSummary?.active_enrollments ?? 0, level: readiness(hasEnrolments, true) },
        ].map((item) => (
          <div key={item.label} className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500">{item.label}</span>
              <ReadinessChip level={item.level} />
            </div>
            <p className="text-xl font-bold text-gray-800">{item.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <SectionCard title="Legacy Compatibility">
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-600">Legacy-only students</span>
              <span className="font-medium">{enrolSummary?.students_with_legacy_class_id_but_no_canonical_enrollment ?? "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Stale class pointer</span>
              <span className="font-medium">{enrolSummary?.students_with_terminal_canonical_history_and_stale_class_id ?? "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Pointer mismatch</span>
              <span className="font-medium">{enrolSummary?.students_with_class_id_conflicting_active_enrollment ?? "—"}</span>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Reconciliation Status">
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-600">Open issues</span>
              <span className={`font-medium ${reconciliationIssues > 0 ? "text-red-600" : "text-green-600"}`}>
                {reconciliationIssues}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Assignment coverage</span>
              <span className="font-medium">
                {(taSummary as { canonical_assignment_coverage_percentage?: number } | null)?.canonical_assignment_coverage_percentage?.toFixed(0) ?? "—"}%
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Current year</span>
              <span className="font-medium">{mdSummary?.current_academic_year?.name ?? "Not set"}</span>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

// ─── Campuses Tab ─────────────────────────────────────────────────────────────

function CampusesTab() {
  const [items, setItems] = useState<Campus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", code: "", description: "", is_active: true });
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    listCampuses().then(setItems).catch((e) => setError(errorMessage(e))).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const startEdit = (item: Campus) => {
    setEditing(item.id);
    setForm({ name: item.name, code: item.code, description: item.description ?? "", is_active: item.is_active });
    setShowCreate(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updateCampus(editing, { name: form.name, code: form.code, description: form.description || null, is_active: form.is_active });
        setSuccess("Campus updated.");
      } else {
        await createCampus({ name: form.name, code: form.code, description: form.description || undefined, is_active: form.is_active });
        setSuccess("Campus created.");
      }
      setEditing(null);
      setShowCreate(false);
      setForm({ name: "", code: "", description: "", is_active: true });
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (item: Campus) => {
    if (item.is_active) {
      setConfirmDeactivate(item.id);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateCampus(item.id, { is_active: true });
      setSuccess("Campus activated.");
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const confirmDeactivateAction = async () => {
    if (!confirmDeactivate) return;
    setSaving(true);
    setError(null);
    try {
      await updateCampus(confirmDeactivate, { is_active: false });
      setSuccess("Campus deactivated.");
      setConfirmDeactivate(null);
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const renderForm = () => (
    <div className="bg-gray-50 rounded-lg p-4 border border-gray-200 space-y-3">
      <FieldRow label="Name">
        <Input value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} placeholder="Main Campus" />
      </FieldRow>
      <FieldRow label="Code">
        <Input value={form.code} onChange={(v) => setForm((f) => ({ ...f, code: v }))} placeholder="MAIN" />
      </FieldRow>
      <FieldRow label="Description (optional)">
        <Input value={form.description} onChange={(v) => setForm((f) => ({ ...f, description: v }))} placeholder="Optional description" />
      </FieldRow>
      <div className="flex items-center gap-2">
        <input
          id="campus-active"
          type="checkbox"
          checked={form.is_active}
          onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
          className="rounded"
        />
        <label htmlFor="campus-active" className="text-sm text-gray-700">Active</label>
      </div>
      <div className="flex gap-2">
        <Btn onClick={handleSave} disabled={saving}>{saving ? "Saving…" : "Save"}</Btn>
        <Btn variant="secondary" onClick={() => { setEditing(null); setShowCreate(false); }}>Cancel</Btn>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {success && <SuccessAlert message={success} />}
      {confirmDeactivate && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 p-4 text-sm text-amber-800 space-y-3">
          <p>Are you sure you want to deactivate this campus? Existing records are not affected, but new classes cannot reference an inactive campus.</p>
          <div className="flex gap-2">
            <Btn variant="danger" onClick={confirmDeactivateAction} disabled={saving}>Deactivate</Btn>
            <Btn variant="secondary" onClick={() => setConfirmDeactivate(null)}>Cancel</Btn>
          </div>
        </div>
      )}
      {loading ? (
        <p className="text-sm text-gray-500">Loading campuses…</p>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <div key={item.id} className="bg-white border border-gray-200 rounded-xl p-4">
              {editing === item.id ? renderForm() : (
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div>
                    <span className="font-medium">{item.name}</span>
                    <span className="ml-2 text-sm text-gray-500">{item.code}</span>
                    {item.description && <span className="ml-2 text-xs text-gray-400">{item.description}</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge active={item.is_active} />
                    <Btn size="xs" variant="secondary" onClick={() => startEdit(item)}>Edit</Btn>
                    <Btn size="xs" variant={item.is_active ? "danger" : "secondary"} onClick={() => handleToggle(item)}>
                      {item.is_active ? "Deactivate" : "Activate"}
                    </Btn>
                  </div>
                </div>
              )}
            </div>
          ))}
          {items.length === 0 && <p className="text-sm text-gray-500">No campuses configured. Add one below.</p>}
        </div>
      )}
      {!editing && !showCreate && (
        <Btn onClick={() => { setShowCreate(true); setForm({ name: "", code: "", description: "", is_active: true }); }}>+ Add Campus</Btn>
      )}
      {showCreate && renderForm()}
    </div>
  );
}

// ─── Academic Years Tab ───────────────────────────────────────────────────────

function AcademicYearsTab() {
  const [years, setYears] = useState<AcademicYear[]>([]);
  const [terms, setTerms] = useState<Term[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [editYear, setEditYear] = useState<string | null>(null);
  const [showCreateYear, setShowCreateYear] = useState(false);
  const [showCreateTerm, setShowCreateTerm] = useState(false);
  const [editTerm, setEditTerm] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState<string | null>(null);
  const [yearForm, setYearForm] = useState({ name: "", start_date: "", end_date: "", is_current: false, is_active: true });
  const [termForm, setTermForm] = useState({ academic_year_id: "", name: "", code: "", start_date: "", end_date: "", sequence: 1, is_active: true });

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([listAcademicYears(), listTerms()])
      .then(([y, t]) => { setYears(y); setTerms(t); })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveYear = async () => {
    setSaving(true);
    setError(null);
    try {
      if (editYear) {
        await updateAcademicYear(editYear, { name: yearForm.name, start_date: yearForm.start_date, end_date: yearForm.end_date, is_current: yearForm.is_current, is_active: yearForm.is_active });
        setSuccess("Academic year updated.");
      } else {
        await createAcademicYear({ name: yearForm.name, start_date: yearForm.start_date, end_date: yearForm.end_date, is_current: yearForm.is_current, is_active: yearForm.is_active });
        setSuccess("Academic year created.");
      }
      setEditYear(null);
      setShowCreateYear(false);
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const saveTerm = async () => {
    if (!termForm.name.trim() || !termForm.code.trim()) {
      setError("Term name and code are required.");
      return;
    }
    if (!termForm.start_date || !termForm.end_date) {
      setError("Term start and end dates are required.");
      return;
    }
    if (termForm.start_date > termForm.end_date) {
      setError("Term start date cannot be after end date.");
      return;
    }
    const selectedYear = years.find((y) => y.id === termForm.academic_year_id);
    if (selectedYear) {
      if (termForm.start_date < selectedYear.start_date || termForm.end_date > selectedYear.end_date) {
        setError(`Term dates must be within ${selectedYear.name} (${selectedYear.start_date} to ${selectedYear.end_date}).`);
        return;
      }
    }

    setSaving(true);
    setError(null);
    try {
      if (editTerm) {
        await updateTerm(editTerm, {
          name: termForm.name,
          code: termForm.code,
          start_date: termForm.start_date,
          end_date: termForm.end_date,
          sequence: termForm.sequence,
          is_active: termForm.is_active,
        });
        setSuccess("Term updated.");
      } else {
        await createTerm({ ...termForm });
        setSuccess("Term created.");
      }
      setShowCreateTerm(false);
      setEditTerm(null);
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const toggleYear = async (item: AcademicYear) => {
    if (item.is_active) {
      setConfirmDeactivate(item.id);
    } else {
      setSaving(true);
      setError(null);
      try {
        await updateAcademicYear(item.id, { is_active: true });
        setSuccess("Academic year activated.");
        load();
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        setSaving(false);
      }
    }
  };

  return (
    <div className="space-y-4">
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {success && <SuccessAlert message={success} />}
      {confirmDeactivate && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 p-4 text-sm text-amber-800 space-y-3">
          <p>Deactivating an academic year prevents new classes and enrollments from referencing it. Existing records are preserved.</p>
          <div className="flex gap-2">
            <Btn variant="danger" onClick={async () => {
              setSaving(true);
              try { await updateAcademicYear(confirmDeactivate, { is_active: false }); setSuccess("Academic year deactivated."); setConfirmDeactivate(null); load(); }
              catch (e) { setError(errorMessage(e)); }
              finally { setSaving(false); }
            }} disabled={saving}>Deactivate</Btn>
            <Btn variant="secondary" onClick={() => setConfirmDeactivate(null)}>Cancel</Btn>
          </div>
        </div>
      )}
      {loading ? <p className="text-sm text-gray-500">Loading…</p> : (
        <div className="space-y-3">
          {years.map((y) => (
            <div key={y.id} className="bg-white border border-gray-200 rounded-xl p-4">
              {editYear === y.id ? (
                <div className="space-y-3">
                  <FieldRow label="Name"><Input value={yearForm.name} onChange={(v) => setYearForm((f) => ({ ...f, name: v }))} placeholder="2026–2027" /></FieldRow>
                  <div className="grid grid-cols-2 gap-3">
                    <FieldRow label="Start date"><Input type="date" value={yearForm.start_date} onChange={(v) => setYearForm((f) => ({ ...f, start_date: v }))} /></FieldRow>
                    <FieldRow label="End date"><Input type="date" value={yearForm.end_date} onChange={(v) => setYearForm((f) => ({ ...f, end_date: v }))} /></FieldRow>
                  </div>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={yearForm.is_current} onChange={(e) => setYearForm((f) => ({ ...f, is_current: e.target.checked }))} /> Current year</label>
                    <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={yearForm.is_active} onChange={(e) => setYearForm((f) => ({ ...f, is_active: e.target.checked }))} /> Active</label>
                  </div>
                  <div className="flex gap-2">
                    <Btn onClick={saveYear} disabled={saving}>{saving ? "Saving…" : "Save"}</Btn>
                    <Btn variant="secondary" onClick={() => setEditYear(null)}>Cancel</Btn>
                  </div>
                </div>
              ) : (
                <div className="flex items-start justify-between flex-wrap gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{y.name}</span>
                      {y.is_current && <span className="text-xs rounded-full bg-indigo-100 text-indigo-700 px-2 py-0.5">Current</span>}
                      <StatusBadge active={y.is_active} />
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5">{y.start_date} → {y.end_date}</p>
                    <div className="mt-2 space-y-1">
                      {terms
                        .filter((t) => t.academic_year_id === y.id)
                        .sort((a, b) => a.sequence - b.sequence)
                        .map((t) => (
                          <div key={t.id} className="flex items-center justify-between gap-2 rounded-md border border-gray-200 px-2 py-1">
                            <div className="text-xs">
                              <span className="font-medium">{t.name}</span>{" "}
                              <span className="text-gray-500">({t.code})</span>{" "}
                              <span className="text-gray-400">Seq {t.sequence}</span>{" "}
                              <span className="text-gray-400">{t.start_date} → {t.end_date}</span>{" "}
                              <span className={`ml-1 rounded-full px-1.5 py-0.5 ${t.is_active ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-500"}`}>
                                {t.is_active ? "Active" : "Inactive"}
                              </span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Btn
                                size="xs"
                                variant="secondary"
                                onClick={() => {
                                  setShowCreateTerm(true);
                                  setEditTerm(t.id);
                                  setTermForm({
                                    academic_year_id: t.academic_year_id,
                                    name: t.name,
                                    code: t.code,
                                    start_date: t.start_date,
                                    end_date: t.end_date,
                                    sequence: t.sequence,
                                    is_active: t.is_active,
                                  });
                                }}
                              >
                                Edit Term
                              </Btn>
                              <Btn
                                size="xs"
                                variant={t.is_active ? "danger" : "secondary"}
                                onClick={async () => {
                                  setSaving(true);
                                  setError(null);
                                  try {
                                    await updateTerm(t.id, { is_active: !t.is_active });
                                    setSuccess(t.is_active ? "Term deactivated." : "Term activated.");
                                    load();
                                  } catch (e) {
                                    setError(errorMessage(e));
                                  } finally {
                                    setSaving(false);
                                  }
                                }}
                              >
                                {t.is_active ? "Deactivate" : "Activate"}
                              </Btn>
                            </div>
                          </div>
                        ))}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Btn size="xs" variant="secondary" onClick={() => { setEditYear(y.id); setYearForm({ name: y.name, start_date: y.start_date, end_date: y.end_date, is_current: y.is_current, is_active: y.is_active }); }}>Edit</Btn>
                    <Btn size="xs" variant={y.is_active ? "danger" : "secondary"} onClick={() => toggleYear(y)}>{y.is_active ? "Deactivate" : "Activate"}</Btn>
                    <Btn size="xs" variant="ghost" onClick={() => { setShowCreateTerm(true); setEditTerm(null); setTermForm({ academic_year_id: y.id, name: "", code: "", start_date: y.start_date, end_date: y.end_date, sequence: (terms.filter((t) => t.academic_year_id === y.id).length + 1), is_active: true }); }}>+ Term</Btn>
                  </div>
                </div>
              )}
            </div>
          ))}
          {years.length === 0 && <p className="text-sm text-gray-500">No academic years. Add one below.</p>}
        </div>
      )}

      {showCreateTerm && (
        <SectionCard title={editTerm ? "Edit Term" : "Add Term"}>
          <div className="space-y-3">
            <FieldRow label="Name"><Input value={termForm.name} onChange={(v) => setTermForm((f) => ({ ...f, name: v }))} placeholder="Term 1" /></FieldRow>
            <FieldRow label="Code"><Input value={termForm.code} onChange={(v) => setTermForm((f) => ({ ...f, code: v }))} placeholder="T1" /></FieldRow>
            <FieldRow label="Academic Year Association">
              <select
                className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm"
                value={termForm.academic_year_id}
                onChange={(e) => {
                  const nextYearId = e.target.value;
                  const nextYear = years.find((y) => y.id === nextYearId);
                  setTermForm((f) => ({
                    ...f,
                    academic_year_id: nextYearId,
                    start_date: nextYear ? nextYear.start_date : f.start_date,
                    end_date: nextYear ? nextYear.end_date : f.end_date,
                  }));
                }}
              >
                <option value="">Select academic year…</option>
                {years.map((y) => (
                  <option key={y.id} value={y.id}>
                    {y.name} ({y.start_date} to {y.end_date})
                  </option>
                ))}
              </select>
            </FieldRow>
            <div className="grid grid-cols-2 gap-3">
              <FieldRow label="Start date"><Input type="date" value={termForm.start_date} onChange={(v) => setTermForm((f) => ({ ...f, start_date: v }))} /></FieldRow>
              <FieldRow label="End date"><Input type="date" value={termForm.end_date} onChange={(v) => setTermForm((f) => ({ ...f, end_date: v }))} /></FieldRow>
            </div>
            <FieldRow label="Sequence">
              <input type="number" min={1} value={termForm.sequence} onChange={(e) => setTermForm((f) => ({ ...f, sequence: Number(e.target.value) }))} className="w-24 rounded-lg border border-gray-300 px-3 py-1.5 text-sm" />
            </FieldRow>
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={termForm.is_active} onChange={(e) => setTermForm((f) => ({ ...f, is_active: e.target.checked }))} /> Active</label>
            <div className="flex gap-2">
              <Btn onClick={saveTerm} disabled={saving}>{saving ? "Saving…" : editTerm ? "Save Term" : "Add Term"}</Btn>
              <Btn variant="secondary" onClick={() => { setShowCreateTerm(false); setEditTerm(null); }}>Cancel</Btn>
            </div>
          </div>
        </SectionCard>
      )}

      {!showCreateYear && !editYear && (
        <Btn onClick={() => { setShowCreateYear(true); setYearForm({ name: "", start_date: "", end_date: "", is_current: false, is_active: true }); }}>+ Add Academic Year</Btn>
      )}
      {showCreateYear && (
        <SectionCard title="New Academic Year">
          <div className="space-y-3">
            <FieldRow label="Name"><Input value={yearForm.name} onChange={(v) => setYearForm((f) => ({ ...f, name: v }))} placeholder="2027–2028" /></FieldRow>
            <div className="grid grid-cols-2 gap-3">
              <FieldRow label="Start date"><Input type="date" value={yearForm.start_date} onChange={(v) => setYearForm((f) => ({ ...f, start_date: v }))} /></FieldRow>
              <FieldRow label="End date"><Input type="date" value={yearForm.end_date} onChange={(v) => setYearForm((f) => ({ ...f, end_date: v }))} /></FieldRow>
            </div>
            <div className="flex gap-4">
              <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={yearForm.is_current} onChange={(e) => setYearForm((f) => ({ ...f, is_current: e.target.checked }))} /> Set as current year</label>
              <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={yearForm.is_active} onChange={(e) => setYearForm((f) => ({ ...f, is_active: e.target.checked }))} /> Active</label>
            </div>
            <div className="flex gap-2">
              <Btn onClick={saveYear} disabled={saving}>{saving ? "Saving…" : "Create"}</Btn>
              <Btn variant="secondary" onClick={() => setShowCreateYear(false)}>Cancel</Btn>
            </div>
          </div>
        </SectionCard>
      )}
    </div>
  );
}

// ─── Grade Levels Tab ─────────────────────────────────────────────────────────

function GradeLevelsTab() {
  const [items, setItems] = useState<GradeLevel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", code: "", sequence: 1, is_active: true });

  const load = useCallback(() => {
    setLoading(true);
    listGradeLevels().then(setItems).catch((e) => setError(errorMessage(e))).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updateGradeLevel(editing, form);
        setSuccess("Grade level updated.");
      } else {
        await createGradeLevel(form);
        setSuccess("Grade level created.");
      }
      setEditing(null);
      setShowCreate(false);
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const renderForm = () => (
    <div className="bg-gray-50 rounded-lg p-4 border border-gray-200 space-y-3">
      <FieldRow label="Name"><Input value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} placeholder="Grade 5" /></FieldRow>
      <FieldRow label="Code"><Input value={form.code} onChange={(v) => setForm((f) => ({ ...f, code: v }))} placeholder="G5" /></FieldRow>
      <FieldRow label="Sequence">
        <input type="number" min={1} value={form.sequence} onChange={(e) => setForm((f) => ({ ...f, sequence: Number(e.target.value) }))} className="w-24 rounded-lg border border-gray-300 px-3 py-1.5 text-sm" />
      </FieldRow>
      <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} /> Active</label>
      <div className="flex gap-2">
        <Btn onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</Btn>
        <Btn variant="secondary" onClick={() => { setEditing(null); setShowCreate(false); }}>Cancel</Btn>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {success && <SuccessAlert message={success} />}
      {confirmDeactivate && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 p-4 text-sm text-amber-800 space-y-3">
          <p>Deactivating this grade level will prevent new classes from referencing it. Existing records are preserved.</p>
          <div className="flex gap-2">
            <Btn variant="danger" onClick={async () => {
              setSaving(true);
              try { await updateGradeLevel(confirmDeactivate, { is_active: false }); setSuccess("Deactivated."); setConfirmDeactivate(null); load(); }
              catch (e) { setError(errorMessage(e)); }
              finally { setSaving(false); }
            }} disabled={saving}>Deactivate</Btn>
            <Btn variant="secondary" onClick={() => setConfirmDeactivate(null)}>Cancel</Btn>
          </div>
        </div>
      )}
      {loading ? <p className="text-sm text-gray-500">Loading…</p> : (
        <div className="space-y-2">
          {items.map((item) => (
            <div key={item.id} className="bg-white border border-gray-200 rounded-xl p-4">
              {editing === item.id ? renderForm() : (
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div>
                    <span className="font-medium">{item.name}</span>
                    <span className="ml-2 text-sm text-gray-500">{item.code}</span>
                    <span className="ml-2 text-xs text-gray-400">Seq {item.sequence}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge active={item.is_active} />
                    <Btn size="xs" variant="secondary" onClick={() => { setEditing(item.id); setForm({ name: item.name, code: item.code, sequence: item.sequence, is_active: item.is_active }); }}>Edit</Btn>
                    <Btn size="xs" variant={item.is_active ? "danger" : "secondary"} onClick={() => item.is_active ? setConfirmDeactivate(item.id) : updateGradeLevel(item.id, { is_active: true }).then(() => { setSuccess("Activated."); load(); }).catch((e) => setError(errorMessage(e)))}>
                      {item.is_active ? "Deactivate" : "Activate"}
                    </Btn>
                  </div>
                </div>
              )}
            </div>
          ))}
          {items.length === 0 && <p className="text-sm text-gray-500">No grade levels configured.</p>}
        </div>
      )}
      {!editing && !showCreate && (
        <Btn onClick={() => { setShowCreate(true); setForm({ name: "", code: "", sequence: (items.length + 1), is_active: true }); }}>+ Add Grade Level</Btn>
      )}
      {showCreate && renderForm()}
    </div>
  );
}

// ─── Classes Tab ──────────────────────────────────────────────────────────────

function ClassesTab() {
  const [items, setItems] = useState<CanonicalClass[]>([]);
  const [campuses, setCampuses] = useState<Campus[]>([]);
  const [years, setYears] = useState<AcademicYear[]>([]);
  const [grades, setGrades] = useState<GradeLevel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ campus_id: "", academic_year_id: "", grade_level_id: "", code: "", section: "", is_active: true });

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([listClasses(), listCampuses(), listAcademicYears(), listGradeLevels()])
      .then(([cls, c, y, g]) => { setItems(cls); setCampuses(c); setYears(y); setGrades(g); })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await createClass(form);
      setSuccess("Class created.");
      setShowCreate(false);
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (item: CanonicalClass) => {
    setSaving(true);
    setError(null);
    try {
      await updateClass(item.id, { is_active: !item.is_active });
      setSuccess(item.is_active ? "Class deactivated." : "Class activated.");
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const isCanonical = (c: CanonicalClass) => Boolean(c.campus_id && c.academic_year_id && c.grade_level_id);

  return (
    <div className="space-y-4">
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {success && <SuccessAlert message={success} />}
      {loading ? <p className="text-sm text-gray-500">Loading…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
                <th className="py-2 pr-4">Code</th>
                <th className="py-2 pr-4">Grade / Section</th>
                <th className="py-2 pr-4">Year</th>
                <th className="py-2 pr-4">Campus</th>
                <th className="py-2 pr-4">Source</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-2 pr-4 font-medium">{item.code ?? "—"}</td>
                  <td className="py-2 pr-4">{item.grade ?? item.grade_level_name ?? "—"} / {item.section ?? "—"}</td>
                  <td className="py-2 pr-4">{item.academic_year ?? item.academic_year_name ?? "—"}</td>
                  <td className="py-2 pr-4">{item.campus_name ?? <span className="text-gray-400 italic">Legacy</span>}</td>
                  <td className="py-2 pr-4"><SourceBadge source={isCanonical(item) ? "canonical" : "legacy"} /></td>
                  <td className="py-2 pr-4"><StatusBadge active={item.is_active} /></td>
                  <td className="py-2">
                    {isCanonical(item) && (
                      <Btn size="xs" variant={item.is_active ? "danger" : "secondary"} onClick={() => toggleActive(item)}>
                        {item.is_active ? "Deactivate" : "Activate"}
                      </Btn>
                    )}
                    {!isCanonical(item) && <span className="text-xs text-gray-400 italic">Legacy — read-only</span>}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={7} className="py-4 text-sm text-gray-500">No classes found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {!showCreate && (
        <Btn onClick={() => setShowCreate(true)}>+ Create Canonical Class</Btn>
      )}
      {showCreate && (
        <SectionCard title="New Canonical Class">
          <div className="space-y-3">
            <FieldRow label="Campus">
              <select className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm" value={form.campus_id} onChange={(e) => setForm((f) => ({ ...f, campus_id: e.target.value }))}>
                <option value="">Select campus…</option>
                {campuses.filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{c.name} ({c.code})</option>)}
              </select>
            </FieldRow>
            <FieldRow label="Academic Year">
              <select className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm" value={form.academic_year_id} onChange={(e) => setForm((f) => ({ ...f, academic_year_id: e.target.value }))}>
                <option value="">Select year…</option>
                {years.filter((y) => y.is_active).map((y) => <option key={y.id} value={y.id}>{y.name}</option>)}
              </select>
            </FieldRow>
            <FieldRow label="Grade Level">
              <select className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm" value={form.grade_level_id} onChange={(e) => setForm((f) => ({ ...f, grade_level_id: e.target.value }))}>
                <option value="">Select grade…</option>
                {grades.filter((g) => g.is_active).map((g) => <option key={g.id} value={g.id}>{g.name} ({g.code})</option>)}
              </select>
            </FieldRow>
            <div className="grid grid-cols-2 gap-3">
              <FieldRow label="Class Code"><Input value={form.code} onChange={(v) => setForm((f) => ({ ...f, code: v }))} placeholder="5A" /></FieldRow>
              <FieldRow label="Section"><Input value={form.section} onChange={(v) => setForm((f) => ({ ...f, section: v }))} placeholder="A" /></FieldRow>
            </div>
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} /> Active</label>
            <div className="flex gap-2">
              <Btn onClick={save} disabled={saving}>{saving ? "Creating…" : "Create Class"}</Btn>
              <Btn variant="secondary" onClick={() => setShowCreate(false)}>Cancel</Btn>
            </div>
          </div>
        </SectionCard>
      )}
    </div>
  );
}

// ─── Subject Offerings Tab ────────────────────────────────────────────────────

function SubjectOfferingsTab() {
  const [items, setItems] = useState<SubjectOffering[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    listSubjectOfferings().then(setItems).catch((e) => setError(errorMessage(e))).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = async (item: SubjectOffering) => {
    setSaving(true);
    setError(null);
    try {
      await updateSubjectOffering(item.id, { is_active: !item.is_active });
      setSuccess(item.is_active ? "Offering deactivated." : "Offering activated.");
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {success && <SuccessAlert message={success} />}
      {loading ? <p className="text-sm text-gray-500">Loading…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
                <th className="py-2 pr-4">Subject</th>
                <th className="py-2 pr-4">Grade</th>
                <th className="py-2 pr-4">Year</th>
                <th className="py-2 pr-4">Campus</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-2 pr-4 font-medium">{item.subject_name} <span className="text-xs text-gray-500">({item.subject_code})</span></td>
                  <td className="py-2 pr-4">{item.grade_level_name}</td>
                  <td className="py-2 pr-4">{item.academic_year_name}</td>
                  <td className="py-2 pr-4">{item.campus_name}</td>
                  <td className="py-2 pr-4"><StatusBadge active={item.is_active} /></td>
                  <td className="py-2">
                    <Btn size="xs" variant={item.is_active ? "danger" : "secondary"} disabled={saving} onClick={() => toggle(item)}>
                      {item.is_active ? "Deactivate" : "Activate"}
                    </Btn>
                  </td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={6} className="py-4 text-sm text-gray-500">No subject offerings. Create canonical classes and use the CSV import or API to add offerings.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Teacher Assignments Tab ──────────────────────────────────────────────────

function AssignmentsTab() {
  const [items, setItems] = useState<TeacherAssignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [filterActive, setFilterActive] = useState<boolean | undefined>(true);

  const load = useCallback(() => {
    setLoading(true);
    listTeacherAssignments(filterActive !== undefined ? { is_active: filterActive } : undefined)
      .then(setItems)
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, [filterActive]);

  useEffect(() => { load(); }, [load]);

  const toggle = async (item: TeacherAssignment) => {
    setSaving(true);
    setError(null);
    try {
      await updateTeacherAssignment(item.id, { is_active: !item.is_active });
      setSuccess(item.is_active ? "Assignment deactivated." : "Assignment reactivated.");
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {success && <SuccessAlert message={success} />}
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-600">Filter:</span>
        {[
          { label: "Active", value: true as boolean | undefined },
          { label: "Inactive", value: false as boolean | undefined },
          { label: "All", value: undefined },
        ].map(({ label, value }) => (
          <button
            key={label}
            type="button"
            onClick={() => setFilterActive(value)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${filterActive === value ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2">
        To reassign a teacher, deactivate the existing assignment and create a new one. Structural fields (teacher, class, subject) cannot be silently rewritten.
      </p>
      {loading ? <p className="text-sm text-gray-500">Loading…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
                <th className="py-2 pr-4">Teacher</th>
                <th className="py-2 pr-4">Type</th>
                <th className="py-2 pr-4">Class</th>
                <th className="py-2 pr-4">Subject</th>
                <th className="py-2 pr-4">Year</th>
                <th className="py-2 pr-4">Dates</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-2 pr-4 font-medium">{item.teacher_name}</td>
                  <td className="py-2 pr-4">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${item.assignment_type === "homeroom" ? "bg-purple-100 text-purple-700" : "bg-blue-100 text-blue-700"}`}>
                      {item.assignment_type === "homeroom" ? "Homeroom" : "Subject"}
                    </span>
                  </td>
                  <td className="py-2 pr-4">{item.class_code ?? "—"} {item.class_section ? `/ ${item.class_section}` : ""}</td>
                  <td className="py-2 pr-4">{item.subject_name ? `${item.subject_name} (${item.subject_code})` : "—"}</td>
                  <td className="py-2 pr-4">{item.academic_year_name}</td>
                  <td className="py-2 pr-4 text-xs text-gray-500">{item.start_date}{item.end_date ? ` → ${item.end_date}` : ""}</td>
                  <td className="py-2 pr-4"><StatusBadge active={item.is_active} /></td>
                  <td className="py-2">
                    <Btn size="xs" variant={item.is_active ? "danger" : "secondary"} disabled={saving} onClick={() => toggle(item)}>
                      {item.is_active ? "Deactivate" : "Reactivate"}
                    </Btn>
                  </td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={8} className="py-4 text-sm text-gray-500">No assignments found for the current filter.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Enrolments Tab ───────────────────────────────────────────────────────────

function EnrolmentsTab() {
  const [items, setItems] = useState<StudentEnrolment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [filterStatus, setFilterStatus] = useState("active");
  const [transferId, setTransferId] = useState<string | null>(null);
  const [transferForm, setTransferForm] = useState({ new_class_id: "", transfer_date: "", reason: "" });

  const load = useCallback(() => {
    setLoading(true);
    listEnrolments(filterStatus ? { status: filterStatus } : undefined)
      .then(setItems)
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, [filterStatus]);

  useEffect(() => { load(); }, [load]);

  const handleTransfer = async () => {
    if (!transferId) return;
    setSaving(true);
    setError(null);
    try {
      await transferEnrolment(transferId, {
        new_class_id: transferForm.new_class_id,
        transfer_date: transferForm.transfer_date,
        reason: transferForm.reason || undefined,
      });
      setSuccess("Transfer completed. The original enrolment history is preserved.");
      setTransferId(null);
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const handleWithdraw = async (id: string) => {
    const today = new Date().toISOString().split("T")[0];
    setSaving(true);
    setError(null);
    try {
      await updateEnrolment(id, { status: "withdrawn", exited_on: today, exit_reason: "Withdrawn via admin portal" });
      setSuccess("Student withdrawn.");
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const statusFilters = ["active", "transferred", "withdrawn", "completed", ""];

  return (
    <div className="space-y-4">
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {success && <SuccessAlert message={success} />}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm text-gray-600">Status:</span>
        {statusFilters.map((s) => (
          <button
            key={s || "all"}
            type="button"
            onClick={() => setFilterStatus(s)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${filterStatus === s ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"}`}
          >
            {s || "All"}
          </button>
        ))}
      </div>

      {transferId && (
        <SectionCard title="Transfer Student">
          <p className="text-xs text-amber-700 mb-3">Transferring preserves the original enrolment history. The source enrolment will be marked as transferred.</p>
          <div className="space-y-3">
            <FieldRow label="Destination Class ID (canonical class UUID)">
              <Input value={transferForm.new_class_id} onChange={(v) => setTransferForm((f) => ({ ...f, new_class_id: v }))} placeholder="UUID of destination class" />
            </FieldRow>
            <FieldRow label="Transfer Date"><Input type="date" value={transferForm.transfer_date} onChange={(v) => setTransferForm((f) => ({ ...f, transfer_date: v }))} /></FieldRow>
            <FieldRow label="Reason (optional)"><Input value={transferForm.reason} onChange={(v) => setTransferForm((f) => ({ ...f, reason: v }))} placeholder="Optional transfer reason" /></FieldRow>
            <div className="flex gap-2">
              <Btn onClick={handleTransfer} disabled={saving}>{saving ? "Transferring…" : "Confirm Transfer"}</Btn>
              <Btn variant="secondary" onClick={() => setTransferId(null)}>Cancel</Btn>
            </div>
          </div>
        </SectionCard>
      )}

      {loading ? <p className="text-sm text-gray-500">Loading…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
                <th className="py-2 pr-4">Student</th>
                <th className="py-2 pr-4">Class</th>
                <th className="py-2 pr-4">Grade</th>
                <th className="py-2 pr-4">Year</th>
                <th className="py-2 pr-4">Enrolled On</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-2 pr-4 font-medium">{item.student_name}</td>
                  <td className="py-2 pr-4">{item.class_code ?? "—"}{item.class_section ? ` / ${item.class_section}` : ""}</td>
                  <td className="py-2 pr-4">{item.grade_level_name}</td>
                  <td className="py-2 pr-4">{item.academic_year_name}</td>
                  <td className="py-2 pr-4 text-xs text-gray-500">{item.enrolled_on}</td>
                  <td className="py-2 pr-4">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                      item.status === "active" ? "bg-green-100 text-green-700" :
                      item.status === "transferred" ? "bg-blue-100 text-blue-700" :
                      item.status === "withdrawn" ? "bg-red-100 text-red-700" :
                      "bg-gray-100 text-gray-500"
                    }`}>{item.status}</span>
                  </td>
                  <td className="py-2">
                    {item.status === "active" && (
                      <div className="flex gap-1">
                        <Btn size="xs" variant="secondary" onClick={() => { setTransferId(item.id); setTransferForm({ new_class_id: "", transfer_date: new Date().toISOString().split("T")[0], reason: "" }); }}>Transfer</Btn>
                        <Btn size="xs" variant="danger" disabled={saving} onClick={() => handleWithdraw(item.id)}>Withdraw</Btn>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={7} className="py-4 text-sm text-gray-500">No enrolments found.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Reconciliation Tab ───────────────────────────────────────────────────────

const ISSUE_LABELS: Record<string, string> = {
  legacy_only: "Legacy only",
  terminal_canonical_history_stale_class_id: "Stale class pointer",
  class_id_conflicts_with_active_enrollment: "Pointer mismatch",
  multiple_active_enrollments: "Multiple active enrolments",
};

function ReconciliationTab() {
  const [rows, setRows] = useState<ReconciliationRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    getReconciliationDiagnostics().then(setRows).catch((e) => setError(errorMessage(e))).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-blue-50 border border-blue-200 p-3 text-sm text-blue-800">
        This view is read-only. No automatic repairs are performed. Use the Enrolments and Classes sections to address issues manually.
      </div>
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {loading ? <p className="text-sm text-gray-500">Loading diagnostics…</p> : (
        <>
          {rows.length === 0 ? (
            <div className="rounded-lg bg-green-50 border border-green-200 p-4 text-sm text-green-700">
              No reconciliation issues found. All students have consistent enrolment records.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
                    <th className="py-2 pr-4">Student</th>
                    <th className="py-2 pr-4">Issue</th>
                    <th className="py-2 pr-4">Legacy Class ID</th>
                    <th className="py-2 pr-4">Canonical Active Class ID</th>
                    <th className="py-2">Recommended Action</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.student_id + row.issue_code} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-2 pr-4 font-medium">{row.display_name}</td>
                      <td className="py-2 pr-4">
                        <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700">
                          {ISSUE_LABELS[row.issue_code] ?? row.issue_code}
                        </span>
                      </td>
                      <td className="py-2 pr-4 font-mono text-xs text-gray-500">{row.legacy_class_id ?? "—"}</td>
                      <td className="py-2 pr-4 font-mono text-xs text-gray-500">{row.canonical_active_class_id ?? "—"}</td>
                      <td className="py-2 text-xs text-gray-700">{row.recommended_action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Btn variant="secondary" onClick={load}>Refresh</Btn>
        </>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AcademicStructurePage() {
  const { user, isHydrating } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>("Overview");

  if (isHydrating) {
    return <p className="text-sm text-gray-600">Loading session…</p>;
  }

  if (!user || !isLeadershipRole(user.role)) {
    return (
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-800" role="alert">
        Permission denied. Leadership access is required for the Academic Structure workspace.
      </section>
    );
  }

  const tabContent: Record<Tab, React.ReactNode> = {
    Overview: <OverviewTab />,
    Campuses: <CampusesTab />,
    "Academic Years": <AcademicYearsTab />,
    "Grade Levels": <GradeLevelsTab />,
    Classes: <ClassesTab />,
    "Subject Offerings": <SubjectOfferingsTab />,
    Assignments: <AssignmentsTab />,
    Enrolments: <EnrolmentsTab />,
    Reconciliation: <ReconciliationTab />,
  };

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Academic Structure</h1>
        <p className="text-sm text-gray-500 mt-1">
          Manage campuses, academic years, grade levels, classes, subject offerings, teacher assignments, and student enrolments.
        </p>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-gray-200 -mb-px">
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div>{tabContent[activeTab]}</div>
    </div>
  );
}
