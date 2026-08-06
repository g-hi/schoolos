"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { EventScope, ManualEvent, ManualEventCreateRequest } from "@/lib/timetable-calendar-api";

interface ManualEventFormProps {
  onCreate: (payload: ManualEventCreateRequest) => Promise<ManualEvent>;
}

interface DraftFields {
  event_name: string;
  description: string;
  event_type: string;
  start_date: string;
  end_date: string;
  teaching_day_effect: string;
  source_reference: string;
  all_day: boolean;
  start_time: string;
  end_time: string;
  academic_year: string;
  term: string;
  campus_name: string;
  location: string;
  priority: string;
  reminder_hours: string;
  scope_type: EventScope["scope_type"];
  scope_campus: string;
  scope_grade_levels: string;
  scope_classes: string;
  scope_departments: string;
  scope_staff_roles: string;
  scope_selected_users: string;
  scope_public_info: boolean;
  scope_confidential: boolean;
}

const DEFAULT_FIELDS: DraftFields = {
  event_name: "",
  description: "",
  event_type: "school_event",
  start_date: "",
  end_date: "",
  teaching_day_effect: "no_change",
  source_reference: "manual-entry",
  all_day: true,
  start_time: "",
  end_time: "",
  academic_year: "",
  term: "",
  campus_name: "",
  location: "",
  priority: "normal",
  reminder_hours: "24",
  scope_type: "public_information",
  scope_campus: "",
  scope_grade_levels: "",
  scope_classes: "",
  scope_departments: "",
  scope_staff_roles: "",
  scope_selected_users: "",
  scope_public_info: true,
  scope_confidential: false,
};

function parseList(input: string): string[] {
  return input
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

export default function ManualEventForm({ onCreate }: ManualEventFormProps) {
  const [fields, setFields] = useState<DraftFields>(DEFAULT_FIELDS);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const hasUnsavedChanges = useMemo(() => JSON.stringify(fields) !== JSON.stringify(DEFAULT_FIELDS), [fields]);

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedChanges) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [hasUnsavedChanges]);

  function update<K extends keyof DraftFields>(key: K, value: DraftFields[K]) {
    setFields((current) => ({ ...current, [key]: value }));
  }

  function validate(): string | null {
    if (!fields.event_name.trim()) return "Event name is required.";
    if (!fields.start_date) return "Start date is required.";
    if (!fields.end_date) return "End date is required.";
    if (fields.end_date < fields.start_date) return "End date cannot be before start date.";
    if (!fields.event_type.trim()) return "Event type is required.";
    if (fields.scope_type === "campus" && !fields.scope_campus.trim()) return "Campus scope requires a campus id.";
    if (fields.scope_type === "classes" && parseList(fields.scope_classes).length === 0) return "Classes scope requires at least one class id.";
    if (fields.scope_type === "selected_users" && parseList(fields.scope_selected_users).length === 0) {
      return "Selected users scope requires at least one user id.";
    }
    return null;
  }

  function buildScope(): EventScope {
    return {
      scope_type: fields.scope_type,
      campus: fields.scope_campus || null,
      grade_levels: parseList(fields.scope_grade_levels),
      classes: parseList(fields.scope_classes),
      departments: parseList(fields.scope_departments),
      staff_roles: parseList(fields.scope_staff_roles),
      selected_users: parseList(fields.scope_selected_users),
      public_information: fields.scope_public_info,
      contains_confidential_staffing: fields.scope_confidential,
    };
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    const metadataSummary = {
      all_day: fields.all_day,
      start_time: fields.start_time || null,
      end_time: fields.end_time || null,
      academic_year: fields.academic_year || null,
      term: fields.term || null,
      campus: fields.campus_name || null,
      location: fields.location || null,
      priority: fields.priority,
      reminder_hours: Number(fields.reminder_hours || "24"),
      phase_note: "UI planning metadata retained for leadership review; backend contract stores canonical event fields.",
    };

    const payload: ManualEventCreateRequest = {
      event_name: fields.event_name.trim(),
      description: [fields.description.trim(), JSON.stringify(metadataSummary)]
        .filter((value) => value.length > 0)
        .join("\n\n"),
      start_date: fields.start_date,
      end_date: fields.end_date,
      event_type: fields.event_type.trim(),
      teaching_day_effect: fields.teaching_day_effect,
      scope: buildScope(),
      source_reference: fields.source_reference || "manual-entry",
    };

    setSaving(true);
    try {
      await onCreate(payload);
      setFields(DEFAULT_FIELDS);
      setSuccess("Draft event saved. This record is not published and still requires review and approval.");
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Unable to create draft event.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" aria-label="Manual event authoring form">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="text-sm font-medium text-gray-700">
          Event name (required)
          <input
            value={fields.event_name}
            onChange={(event) => update("event_name", event.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            required
          />
        </label>

        <label className="text-sm font-medium text-gray-700">
          Event type (required)
          <input
            value={fields.event_type}
            onChange={(event) => update("event_type", event.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            required
          />
        </label>

        <label className="text-sm font-medium text-gray-700 md:col-span-2">
          Description (optional)
          <textarea
            value={fields.description}
            onChange={(event) => update("description", event.target.value)}
            className="mt-1 min-h-20 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
        </label>

        <label className="text-sm font-medium text-gray-700">
          Start date (required)
          <input
            type="date"
            value={fields.start_date}
            onChange={(event) => update("start_date", event.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            required
          />
        </label>

        <label className="text-sm font-medium text-gray-700">
          End date (required)
          <input
            type="date"
            value={fields.end_date}
            onChange={(event) => update("end_date", event.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            required
          />
        </label>

        <label className="text-sm font-medium text-gray-700">
          Start time (optional planning field)
          <input
            type="time"
            value={fields.start_time}
            onChange={(event) => update("start_time", event.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
        </label>

        <label className="text-sm font-medium text-gray-700">
          End time (optional planning field)
          <input
            type="time"
            value={fields.end_time}
            onChange={(event) => update("end_time", event.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
        </label>

        <label className="text-sm font-medium text-gray-700">
          Teaching-day effect
          <select
            value={fields.teaching_day_effect}
            onChange={(event) => update("teaching_day_effect", event.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="no_change">no_change</option>
            <option value="non_teaching_day">non_teaching_day</option>
            <option value="teaching_day">teaching_day</option>
            <option value="special_schedule">special_schedule</option>
          </select>
        </label>

        <label className="text-sm font-medium text-gray-700">
          Source reference
          <input
            value={fields.source_reference}
            onChange={(event) => update("source_reference", event.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
        </label>

        <label className="text-sm font-medium text-gray-700">
          Academic year (planning)
          <input value={fields.academic_year} onChange={(event) => update("academic_year", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        </label>

        <label className="text-sm font-medium text-gray-700">
          Term (planning)
          <input value={fields.term} onChange={(event) => update("term", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        </label>

        <label className="text-sm font-medium text-gray-700">
          Campus (planning)
          <input value={fields.campus_name} onChange={(event) => update("campus_name", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        </label>

        <label className="text-sm font-medium text-gray-700">
          Location (planning)
          <input value={fields.location} onChange={(event) => update("location", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        </label>

        <label className="text-sm font-medium text-gray-700">
          Priority (planning)
          <select value={fields.priority} onChange={(event) => update("priority", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
            <option value="low">low</option>
            <option value="normal">normal</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
        </label>

        <label className="text-sm font-medium text-gray-700">
          Reminder hours (planning)
          <input type="number" min={0} value={fields.reminder_hours} onChange={(event) => update("reminder_hours", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        </label>
      </div>

      <fieldset className="rounded-xl border border-gray-200 p-4">
        <legend className="px-1 text-sm font-semibold text-gray-800">Affected scope</legend>
        <p className="mb-3 text-xs text-gray-500">Structured targeting is required for deterministic impact analysis.</p>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm font-medium text-gray-700">
            Scope type
            <select
              value={fields.scope_type}
              onChange={(event) => update("scope_type", event.target.value as EventScope["scope_type"])}
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="whole_school">whole_school</option>
              <option value="campus">campus</option>
              <option value="grade_levels">grade_levels</option>
              <option value="classes">classes</option>
              <option value="departments">departments</option>
              <option value="staff_roles">staff_roles</option>
              <option value="selected_users">selected_users</option>
              <option value="public_information">public_information</option>
            </select>
          </label>

          <label className="text-sm font-medium text-gray-700">
            Campus id
            <input value={fields.scope_campus} onChange={(event) => update("scope_campus", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </label>

          <label className="text-sm font-medium text-gray-700">
            Grade levels (comma-separated)
            <input value={fields.scope_grade_levels} onChange={(event) => update("scope_grade_levels", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </label>

          <label className="text-sm font-medium text-gray-700">
            Class ids (comma-separated)
            <input value={fields.scope_classes} onChange={(event) => update("scope_classes", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </label>

          <label className="text-sm font-medium text-gray-700">
            Departments (comma-separated)
            <input value={fields.scope_departments} onChange={(event) => update("scope_departments", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </label>

          <label className="text-sm font-medium text-gray-700">
            Staff roles (comma-separated)
            <input value={fields.scope_staff_roles} onChange={(event) => update("scope_staff_roles", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </label>

          <label className="text-sm font-medium text-gray-700 md:col-span-2">
            Selected user ids (comma-separated)
            <input value={fields.scope_selected_users} onChange={(event) => update("scope_selected_users", event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </label>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-5">
          <label className="inline-flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={fields.scope_public_info} onChange={(event) => update("scope_public_info", event.target.checked)} />
            Public information
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={fields.scope_confidential} onChange={(event) => update("scope_confidential", event.target.checked)} />
            Contains confidential staffing
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={fields.all_day} onChange={(event) => update("all_day", event.target.checked)} />
            All day
          </label>
        </div>
      </fieldset>

      {error ? <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}
      {success ? <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{success}</p> : null}

      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={saving} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
          {saving ? "Saving draft..." : "Save draft event"}
        </button>
      </div>

      <p className="text-xs text-gray-500">Agent proposals remain suggestions. Leadership approval is required before publication.</p>
    </form>
  );
}
