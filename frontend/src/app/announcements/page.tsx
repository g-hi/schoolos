"use client";

import { useEffect, useState } from "react";
import {
  AnnouncementsApiError,
  AnnouncementDetail,
  AnnouncementDeliveriesResponse,
  AnnouncementLookupTargetType,
  AnnouncementStatus,
  AnnouncementSummary,
  AnnouncementTargetOption,
  AnnouncementTargetOptionsQuery,
  AnnouncementTargetRequest,
  AnnouncementTargetType,
  archiveAnnouncement,
  createAnnouncement,
  getAnnouncement,
  listAnnouncementDeliveries,
  listAnnouncementTargetOptions,
  listAnnouncements,
  publishAnnouncement,
  scheduleAnnouncement,
  unscheduleAnnouncement,
  updateAnnouncement,
} from "@/lib/announcements-api";
import { ReportEmptyState, ReportErrorState, ReportPageSkeleton, ReportStatusBadge } from "@/components/reports/report-page-states";

const announcementStatuses: Array<{ value: AnnouncementStatus | "all"; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "scheduled", label: "Scheduled" },
  { value: "publishing", label: "Publishing" },
  { value: "published", label: "Published" },
  { value: "archived", label: "Archived" },
];

const targetTypeOptions: Array<{ value: AnnouncementTargetType; label: string }> = [
  { value: "school", label: "School" },
  { value: "grade", label: "Grade" },
  { value: "class", label: "Class" },
  { value: "family", label: "Family" },
  { value: "student", label: "Student" },
];

const deliveryPageSize = 20;

type EditorMode = "create" | "edit" | null;
type ConfirmAction = "publish" | "archive" | null;

interface AnnouncementFormState {
  title: string;
  body: string;
  timezone: string;
  targets: AnnouncementTargetRequest[];
}

function emptyFormState(): AnnouncementFormState {
  return {
    title: "",
    body: "",
    timezone: "UTC",
    targets: [],
  };
}

function isLookupTargetType(targetType: AnnouncementTargetType): targetType is AnnouncementLookupTargetType {
  return targetType !== "school";
}

function targetKey(target: AnnouncementTargetRequest): string {
  if (target.target_type === "school") {
    return "school";
  }
  if (target.target_type === "grade") {
    return `grade:${target.grade ?? ""}`;
  }
  if (target.target_type === "class") {
    return `class:${target.class_id ?? ""}`;
  }
  if (target.target_type === "family") {
    return `family:${target.family_id ?? ""}`;
  }
  return `student:${target.student_id ?? ""}`;
}

function targetLabel(target: AnnouncementTargetRequest): string {
  if (target.target_type === "school") {
    return "School";
  }
  if (target.target_type === "grade") {
    return `Grade ${target.grade ?? ""}`;
  }
  if (target.target_type === "class") {
    return `Class ${target.class_id ?? ""}`;
  }
  if (target.target_type === "family") {
    return `Family ${target.family_id ?? ""}`;
  }
  return `Student ${target.student_id ?? ""}`;
}

function announcementTargetsMatch(targets: AnnouncementTargetRequest[], candidate: AnnouncementTargetRequest): boolean {
  return targets.some((target) => targetKey(target) === targetKey(candidate));
}

function formatTimestamp(value: string | null): string {
  return value ?? "Not set";
}

function targetRequestFromOption(option: AnnouncementTargetOption): AnnouncementTargetRequest {
  if (option.target_type === "grade") {
    return { target_type: "grade", grade: option.target_value };
  }
  if (option.target_type === "class") {
    return { target_type: "class", class_id: option.target_value };
  }
  if (option.target_type === "family") {
    return { target_type: "family", family_id: option.target_value };
  }
  return { target_type: "student", student_id: option.target_value };
}

function apiMessage(error: unknown): string {
  if (error instanceof AnnouncementsApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}

function actionAllowed(status: AnnouncementStatus, action: "edit" | "schedule" | "unschedule" | "publish" | "archive"): boolean {
  if (action === "edit") return status === "draft" || status === "scheduled";
  if (action === "schedule") return status === "draft";
  if (action === "unschedule") return status === "scheduled";
  if (action === "publish") return status === "draft" || status === "scheduled";
  return status === "published";
}

export default function AnnouncementsPage() {
  const [statusFilter, setStatusFilter] = useState<AnnouncementStatus | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [listItems, setListItems] = useState<AnnouncementSummary[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<AnnouncementDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [deliveries, setDeliveries] = useState<AnnouncementDeliveriesResponse | null>(null);
  const [deliveriesLoading, setDeliveriesLoading] = useState(false);
  const [deliveriesError, setDeliveriesError] = useState<string | null>(null);
  const [deliveryPage, setDeliveryPage] = useState(1);

  const [editorMode, setEditorMode] = useState<EditorMode>(null);
  const [formState, setFormState] = useState<AnnouncementFormState>(emptyFormState());
  const [formError, setFormError] = useState<string | null>(null);
  const [formPending, setFormPending] = useState(false);

  const [targetType, setTargetType] = useState<AnnouncementTargetType>("school");
  const [targetQuery, setTargetQuery] = useState("");
  const [targetGrade, setTargetGrade] = useState("");
  const [targetClassId, setTargetClassId] = useState("");
  const [targetLimit, setTargetLimit] = useState(50);
  const [targetOptions, setTargetOptions] = useState<AnnouncementTargetOption[]>([]);
  const [targetOptionsLoading, setTargetOptionsLoading] = useState(false);
  const [targetOptionsError, setTargetOptionsError] = useState<string | null>(null);

  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);
  const [actionPending, setActionPending] = useState<ConfirmAction | "schedule" | "unschedule" | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [scheduleDateTime, setScheduleDateTime] = useState("");
  const [scheduleTimezone, setScheduleTimezone] = useState("UTC");
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [schedulePending, setSchedulePending] = useState(false);

  const selectedAnnouncement = selectedDetail ?? listItems.find((item) => item.id === selectedId) ?? null;
  const canEdit = selectedAnnouncement ? actionAllowed(selectedAnnouncement.status, "edit") : false;
  const canSchedule = selectedAnnouncement ? actionAllowed(selectedAnnouncement.status, "schedule") : false;
  const canUnschedule = selectedAnnouncement ? actionAllowed(selectedAnnouncement.status, "unschedule") : false;
  const canPublish = selectedAnnouncement ? actionAllowed(selectedAnnouncement.status, "publish") : false;
  const canArchive = selectedAnnouncement ? actionAllowed(selectedAnnouncement.status, "archive") : false;

  useEffect(() => {
    let active = true;
    async function loadAnnouncements() {
      setListLoading(true);
      setListError(null);
      try {
        const response = await listAnnouncements({
          status: statusFilter === "all" ? undefined : statusFilter,
          page,
          page_size: pageSize,
        });
        if (active) {
          setListItems(response.items);
        }
      } catch (error) {
        if (active) {
          setListError(apiMessage(error));
        }
      } finally {
        if (active) {
          setListLoading(false);
        }
      }
    }

    void loadAnnouncements();
    return () => {
      active = false;
    };
  }, [statusFilter, page, pageSize]);

  useEffect(() => {
    if (!selectedId || editorMode === "create") {
      return;
    }

    const announcementId = selectedId;

    let active = true;
    setDetailLoading(true);
    setDetailError(null);
    setDeliveriesLoading(true);
    setDeliveriesError(null);

    async function loadSelected() {
      try {
        const [detailResponse, deliveryResponse] = await Promise.all([
          getAnnouncement(announcementId),
          listAnnouncementDeliveries(announcementId, { page: deliveryPage, page_size: deliveryPageSize }),
        ]);
        if (!active) {
          return;
        }
        setSelectedDetail(detailResponse);
        setDeliveries(deliveryResponse);
        if (editorMode === "edit") {
          setFormState({
            title: detailResponse.title,
            body: detailResponse.body,
            timezone: detailResponse.timezone,
            targets: detailResponse.targets,
          });
        }
        setScheduleTimezone(detailResponse.timezone);
      } catch (error) {
        if (active) {
          setDetailError(apiMessage(error));
        }
      } finally {
        if (active) {
          setDetailLoading(false);
          setDeliveriesLoading(false);
        }
      }
    }

    void loadSelected();
    return () => {
      active = false;
    };
  }, [selectedId, deliveryPage, editorMode]);

  function resetSelectionState() {
    setSelectedId(null);
    setSelectedDetail(null);
    setDeliveries(null);
    setDeliveriesError(null);
    setDeliveryPage(1);
    setConfirmAction(null);
    setDetailError(null);
    setActionMessage(null);
    setScheduleError(null);
  }

  function openCreateForm() {
    resetSelectionState();
    setEditorMode("create");
    setFormState(emptyFormState());
    setFormError(null);
    setTargetType("school");
    setTargetOptions([]);
    setTargetOptionsError(null);
    setTargetQuery("");
    setTargetGrade("");
    setTargetClassId("");
    setTargetLimit(50);
    setScheduleDateTime("");
    setScheduleTimezone("UTC");
  }

  function openEditForm() {
    if (!selectedDetail || !canEdit) {
      return;
    }
    setEditorMode("edit");
    setFormState({
      title: selectedDetail.title,
      body: selectedDetail.body,
      timezone: selectedDetail.timezone,
      targets: selectedDetail.targets,
    });
    setFormError(null);
    setTargetOptions([]);
    setTargetOptionsError(null);
    setScheduleTimezone(selectedDetail.timezone);
  }

  function cancelEditor() {
    setEditorMode(null);
    setFormError(null);
    setTargetOptionsError(null);
    setActionMessage(null);
    setScheduleError(null);
  }

  function selectAnnouncement(item: AnnouncementSummary) {
    setSelectedId(item.id);
    setEditorMode(null);
    setFormError(null);
    setTargetOptions([]);
    setTargetOptionsError(null);
    setConfirmAction(null);
    setActionMessage(null);
    setScheduleError(null);
    setDeliveryPage(1);
    setSelectedDetail(null);
    setDeliveries(null);
  }

  function updateFormTarget(target: AnnouncementTargetRequest) {
    setFormState((current) => {
      if (announcementTargetsMatch(current.targets, target)) {
        return current;
      }
      return { ...current, targets: [...current.targets, target] };
    });
  }

  function removeFormTarget(target: AnnouncementTargetRequest) {
    setFormState((current) => ({
      ...current,
      targets: current.targets.filter((item) => targetKey(item) !== targetKey(target)),
    }));
  }

  async function loadTargetOptions() {
    if (editorMode === null || !isLookupTargetType(targetType)) {
      return;
    }
    setTargetOptionsLoading(true);
    setTargetOptionsError(null);
    try {
      const query: AnnouncementTargetOptionsQuery = {
        target_type: targetType,
        q: targetQuery.trim() || undefined,
        grade: targetGrade.trim() || undefined,
        class_id: targetClassId.trim() || undefined,
        limit: targetLimit,
      };
      const response = await listAnnouncementTargetOptions(query);
      setTargetOptions(response.items);
    } catch (error) {
      setTargetOptionsError(apiMessage(error));
    } finally {
      setTargetOptionsLoading(false);
    }
  }

  async function saveAnnouncement() {
    const trimmedTitle = formState.title.trim();
    const trimmedBody = formState.body.trim();
    const trimmedTimezone = formState.timezone.trim();
    if (!trimmedTitle) {
      setFormError("Title is required.");
      return;
    }
    if (!trimmedBody) {
      setFormError("Body is required.");
      return;
    }
    if (!trimmedTimezone) {
      setFormError("Timezone is required.");
      return;
    }
    if (formState.targets.length === 0) {
      setFormError("Add at least one target.");
      return;
    }

    setFormPending(true);
    setFormError(null);
    setActionMessage(null);
    try {
      if (editorMode === "create") {
        const created = await createAnnouncement({
          title: trimmedTitle,
          body: trimmedBody,
          timezone: trimmedTimezone,
          targets: formState.targets,
        });
        setActionMessage("Draft created.");
        setEditorMode(null);
        setSelectedId(created.id);
        setSelectedDetail(null);
        setDeliveries(null);
        setDeliveryPage(1);
        void listAnnouncements({
          status: statusFilter === "all" ? undefined : statusFilter,
          page,
          page_size: pageSize,
        }).then((response) => setListItems(response.items));
      } else if (editorMode === "edit" && selectedId) {
        await updateAnnouncement(selectedId, {
          title: trimmedTitle,
          body: trimmedBody,
          timezone: trimmedTimezone,
          targets: formState.targets,
        });
        setActionMessage("Draft updated.");
        setEditorMode(null);
        setSelectedDetail(null);
        setDeliveries(null);
        void getAnnouncement(selectedId).then((response) => setSelectedDetail(response));
        void listAnnouncementDeliveries(selectedId, { page: deliveryPage, page_size: deliveryPageSize }).then((response) => setDeliveries(response));
        void listAnnouncements({
          status: statusFilter === "all" ? undefined : statusFilter,
          page,
          page_size: pageSize,
        }).then((response) => setListItems(response.items));
      }
    } catch (error) {
      setFormError(apiMessage(error));
    } finally {
      setFormPending(false);
    }
  }

  async function scheduleSelectedAnnouncement() {
    if (!selectedId) {
      return;
    }
    if (!scheduleDateTime) {
      setScheduleError("Scheduled time is required.");
      return;
    }
    setSchedulePending(true);
    setScheduleError(null);
    setActionMessage(null);
    setActionPending("schedule");
    try {
      const scheduledAt = new Date(scheduleDateTime).toISOString();
      await scheduleAnnouncement(selectedId, {
        scheduled_at: scheduledAt,
        timezone: scheduleTimezone.trim() || undefined,
      });
      setActionMessage("Announcement scheduled.");
      void getAnnouncement(selectedId).then((response) => setSelectedDetail(response));
      void listAnnouncements({
        status: statusFilter === "all" ? undefined : statusFilter,
        page,
        page_size: pageSize,
      }).then((response) => setListItems(response.items));
    } catch (error) {
      setScheduleError(apiMessage(error));
    } finally {
      setSchedulePending(false);
      setActionPending(null);
    }
  }

  async function runAnnouncementAction(action: ConfirmAction) {
    if (!selectedId || !action) {
      return;
    }
    setActionPending(action);
    setActionMessage(null);
    try {
      if (action === "publish") {
        await publishAnnouncement(selectedId);
        setActionMessage("Announcement published.");
      } else {
        await archiveAnnouncement(selectedId);
        setActionMessage("Announcement archived.");
      }
      setConfirmAction(null);
      void getAnnouncement(selectedId).then((response) => setSelectedDetail(response));
      void listAnnouncementDeliveries(selectedId, { page: deliveryPage, page_size: deliveryPageSize }).then((response) => setDeliveries(response));
      void listAnnouncements({
        status: statusFilter === "all" ? undefined : statusFilter,
        page,
        page_size: pageSize,
      }).then((response) => setListItems(response.items));
    } catch (error) {
      setActionMessage(apiMessage(error));
    } finally {
      setActionPending(null);
    }
  }

  async function runUnschedule() {
    if (!selectedId) {
      return;
    }
    setActionPending("unschedule");
    setActionMessage(null);
    try {
      await unscheduleAnnouncement(selectedId);
      setActionMessage("Announcement returned to draft.");
      void getAnnouncement(selectedId).then((response) => setSelectedDetail(response));
      void listAnnouncements({
        status: statusFilter === "all" ? undefined : statusFilter,
        page,
        page_size: pageSize,
      }).then((response) => setListItems(response.items));
    } catch (error) {
      setActionMessage(apiMessage(error));
    } finally {
      setActionPending(null);
    }
  }

  function renderTargetBuilder() {
    if (!editorMode) {
      return null;
    }

    return (
      <section className="space-y-4 rounded-2xl border border-gray-200 bg-gray-50 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Targets</h3>
            <p className="text-xs text-gray-500">Use school for all-campus announcements or load lookup options for the scoped target types.</p>
          </div>
          <select
            aria-label="Target type"
            value={targetType}
            onChange={(event) => {
              setTargetType(event.target.value as AnnouncementTargetType);
              setTargetOptions([]);
              setTargetOptionsError(null);
            }}
            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
          >
            {targetTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {targetType === "school" ? (
          <div className="space-y-3 rounded-xl border border-dashed border-gray-300 bg-white p-4">
            <p className="text-sm text-gray-600">School target does not need a lookup or identifier.</p>
            <button
              type="button"
              onClick={() => updateFormTarget({ target_type: "school" })}
              disabled={announcementTargetsMatch(formState.targets, { target_type: "school" })}
              className="inline-flex rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              Add school target
            </button>
          </div>
        ) : (
          <div className="space-y-4 rounded-xl border border-dashed border-gray-300 bg-white p-4">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <label className="space-y-1 text-sm">
                <span className="font-medium text-gray-700">Search</span>
                <input
                  type="search"
                  value={targetQuery}
                  onChange={(event) => setTargetQuery(event.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2"
                  placeholder="Search labels"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-gray-700">Grade filter</span>
                <input
                  type="text"
                  value={targetGrade}
                  onChange={(event) => setTargetGrade(event.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2"
                  placeholder="Grade 1"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-gray-700">Class UUID</span>
                <input
                  type="text"
                  value={targetClassId}
                  onChange={(event) => setTargetClassId(event.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2"
                  placeholder="UUID"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-gray-700">Limit</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={targetLimit}
                  onChange={(event) => setTargetLimit(Number(event.target.value) || 50)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2"
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={loadTargetOptions}
                disabled={targetOptionsLoading}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                {targetOptionsLoading ? "Loading..." : "Load options"}
              </button>
              <button
                type="button"
                onClick={() => updateFormTarget({ target_type: targetType, ...(targetType === "grade" ? { grade: "" } : {}) })}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-100"
              >
                Add empty target
              </button>
            </div>
            {targetOptionsError ? <p className="text-sm text-red-600">{targetOptionsError}</p> : null}
            <div className="space-y-2">
              {targetOptions.length === 0 ? (
                <p className="text-sm text-gray-500">No target options loaded yet.</p>
              ) : (
                <ul className="space-y-2">
                  {targetOptions.map((option) => {
                    const candidate = targetRequestFromOption(option);
                    const selected = announcementTargetsMatch(formState.targets, candidate);
                    return (
                      <li key={`${option.target_type}:${option.target_value}`} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 px-3 py-2">
                        <div>
                          <p className="text-sm font-medium text-gray-900">{option.label}</p>
                          {option.secondary_label ? <p className="text-xs text-gray-500">{option.secondary_label}</p> : null}
                        </div>
                        <button
                          type="button"
                          onClick={() => updateFormTarget(candidate)}
                          disabled={selected}
                          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:bg-gray-200"
                        >
                          {selected ? "Added" : "Add"}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        )}

        <div className="space-y-2">
          <p className="text-sm font-medium text-gray-700">Selected targets</p>
          {formState.targets.length === 0 ? (
            <p className="text-sm text-gray-500">No targets added.</p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {formState.targets.map((target) => (
                <li key={targetKey(target)} className="flex items-center gap-2 rounded-full border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700">
                  <span>{targetLabel(target)}</span>
                  <button
                    type="button"
                    onClick={() => removeFormTarget(target)}
                    className="rounded-full px-2 py-0.5 text-xs font-semibold text-gray-500 transition hover:bg-gray-100 hover:text-gray-900"
                    aria-label={`Remove ${targetLabel(target)}`}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    );
  }

  function renderEditor() {
    if (!editorMode) {
      return null;
    }

    const heading = editorMode === "create" ? "Create draft" : "Edit draft";
    const submitLabel = formPending ? "Saving..." : editorMode === "create" ? "Create draft" : "Save changes";

    return (
      <section className="space-y-4 rounded-3xl border border-gray-200 bg-white p-6 shadow-sm" aria-labelledby="announcement-editor-title">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="announcement-editor-title" className="text-xl font-semibold text-gray-900">
              {heading}
            </h2>
            <p className="text-sm text-gray-500">Drafts can be edited before publishing or archiving.</p>
          </div>
          <button
            type="button"
            onClick={cancelEditor}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
          >
            Cancel
          </button>
        </div>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void saveAnnouncement();
          }}
        >
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="font-medium text-gray-700">Title</span>
              <input
                type="text"
                value={formState.title}
                onChange={(event) => setFormState((current) => ({ ...current, title: event.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2"
                required
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-gray-700">Timezone</span>
              <input
                type="text"
                value={formState.timezone}
                onChange={(event) => setFormState((current) => ({ ...current, timezone: event.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2"
                placeholder="UTC"
                required
              />
            </label>
          </div>
          <label className="space-y-1 text-sm block">
            <span className="font-medium text-gray-700">Body</span>
            <textarea
              value={formState.body}
              onChange={(event) => setFormState((current) => ({ ...current, body: event.target.value }))}
              className="min-h-40 w-full rounded-lg border border-gray-300 px-3 py-2"
              required
            />
          </label>

          {renderTargetBuilder()}

          {formError ? <p className="text-sm text-red-600">{formError}</p> : null}
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={formPending}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              {submitLabel}
            </button>
            <button
              type="button"
              onClick={cancelEditor}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-100"
            >
              Close
            </button>
          </div>
        </form>
      </section>
    );
  }

  function renderSelectionActions() {
    if (!selectedAnnouncement || editorMode === "create") {
      return null;
    }

    return (
      <section className="space-y-4 rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">Announcement detail</h2>
            <p className="text-sm text-gray-500">Lifecycle controls only appear when the backend permits them.</p>
          </div>
          <ReportStatusBadge status={selectedAnnouncement.status} />
        </div>

        {detailLoading ? (
          <ReportPageSkeleton title="Loading announcement" />
        ) : detailError ? (
          <ReportErrorState title="Could not load announcement" description={detailError} />
        ) : (
          <div className="space-y-6">
            <div className="space-y-3">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">{selectedAnnouncement.title}</h3>
                <p className="mt-2 whitespace-pre-wrap text-sm text-gray-700">{selectedAnnouncement.body}</p>
              </div>
              <dl className="grid gap-3 text-sm text-gray-600 md:grid-cols-2">
                <div className="rounded-xl bg-gray-50 p-3">
                  <dt className="font-medium text-gray-700">Timezone</dt>
                  <dd>{selectedAnnouncement.timezone}</dd>
                </div>
                <div className="rounded-xl bg-gray-50 p-3">
                  <dt className="font-medium text-gray-700">Created</dt>
                  <dd><time dateTime={selectedAnnouncement.created_at}>{formatTimestamp(selectedAnnouncement.created_at)}</time></dd>
                </div>
                <div className="rounded-xl bg-gray-50 p-3">
                  <dt className="font-medium text-gray-700">Updated</dt>
                  <dd><time dateTime={selectedAnnouncement.updated_at}>{formatTimestamp(selectedAnnouncement.updated_at)}</time></dd>
                </div>
                <div className="rounded-xl bg-gray-50 p-3">
                  <dt className="font-medium text-gray-700">Scheduled</dt>
                  <dd>{selectedAnnouncement.scheduled_at ? <time dateTime={selectedAnnouncement.scheduled_at}>{selectedAnnouncement.scheduled_at}</time> : <span>Not set</span>}</dd>
                </div>
                <div className="rounded-xl bg-gray-50 p-3">
                  <dt className="font-medium text-gray-700">Published</dt>
                  <dd>{selectedAnnouncement.published_at ? <time dateTime={selectedAnnouncement.published_at}>{selectedAnnouncement.published_at}</time> : <span>Not set</span>}</dd>
                </div>
                <div className="rounded-xl bg-gray-50 p-3">
                  <dt className="font-medium text-gray-700">Archived</dt>
                  <dd>{selectedAnnouncement.archived_at ? <time dateTime={selectedAnnouncement.archived_at}>{selectedAnnouncement.archived_at}</time> : <span>Not set</span>}</dd>
                </div>
              </dl>
            </div>

            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-gray-900">Targets</h3>
              {!selectedDetail || selectedDetail.targets.length === 0 ? (
                <p className="text-sm text-gray-500">No targets returned.</p>
              ) : (
                <ul className="flex flex-wrap gap-2">
                  {selectedDetail.targets.map((target, index) => (
                    <li key={`${targetKey(target)}-${index}`} className="rounded-full border border-gray-300 bg-gray-50 px-3 py-1.5 text-sm text-gray-700">
                      {targetLabel(target)}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="flex flex-wrap gap-3">
              {canEdit ? (
                <button type="button" onClick={openEditForm} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700">
                  Edit draft
                </button>
              ) : null}
              {canUnschedule ? (
                <button type="button" onClick={() => void runUnschedule()} disabled={actionPending === "unschedule"} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:bg-gray-200">
                  {actionPending === "unschedule" ? "Unscheduling..." : "Unschedule"}
                </button>
              ) : null}
              {canPublish ? (
                <button type="button" onClick={() => setConfirmAction("publish")} disabled={actionPending !== null} className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-gray-300">
                  Publish
                </button>
              ) : null}
              {canArchive ? (
                <button type="button" onClick={() => setConfirmAction("archive")} disabled={actionPending !== null} className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm font-semibold text-amber-800 transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:bg-gray-200">
                  Archive
                </button>
              ) : null}
            </div>

            {canSchedule ? (
              <section className="space-y-3 rounded-2xl border border-gray-200 bg-gray-50 p-4">
                <h3 className="text-sm font-semibold text-gray-900">Schedule announcement</h3>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="space-y-1 text-sm">
                    <span className="font-medium text-gray-700">Scheduled at</span>
                    <input
                      type="datetime-local"
                      value={scheduleDateTime}
                      onChange={(event) => setScheduleDateTime(event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2"
                    />
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="font-medium text-gray-700">Timezone</span>
                    <input
                      type="text"
                      value={scheduleTimezone}
                      onChange={(event) => setScheduleTimezone(event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2"
                    />
                  </label>
                </div>
                {scheduleError ? <p className="text-sm text-red-600">{scheduleError}</p> : null}
                <button
                  type="button"
                  onClick={() => void scheduleSelectedAnnouncement()}
                  disabled={schedulePending}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-300"
                >
                  {schedulePending ? "Scheduling..." : "Save schedule"}
                </button>
              </section>
            ) : null}

            {confirmAction ? (
              <section className="rounded-2xl border border-gray-200 bg-gray-50 p-4" role="alert" aria-live="polite">
                <h3 className="text-sm font-semibold text-gray-900">Confirm {confirmAction}</h3>
                <p className="mt-1 text-sm text-gray-600">
                  {confirmAction === "publish"
                    ? "Publish this announcement now?"
                    : "Archive this announcement? Archived announcements remain read-only."}
                </p>
                <div className="mt-3 flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => void runAnnouncementAction(confirmAction)}
                    disabled={actionPending !== null}
                    className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-gray-300"
                  >
                    {actionPending === confirmAction ? "Working..." : "Confirm"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmAction(null)}
                    className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-100"
                  >
                    Cancel
                  </button>
                </div>
              </section>
            ) : null}

            {actionMessage ? <p className="text-sm text-gray-700">{actionMessage}</p> : null}
          </div>
        )}

        <section className="space-y-3 rounded-2xl border border-gray-200 bg-gray-50 p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-gray-900">Deliveries</h3>
            <div className="flex items-center gap-2 text-sm">
              <button
                type="button"
                onClick={() => setDeliveryPage((current) => Math.max(1, current - 1))}
                disabled={deliveryPage === 1 || deliveriesLoading}
                className="rounded-lg border border-gray-300 px-3 py-1.5 font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:bg-gray-200"
              >
                Previous
              </button>
              <span className="text-gray-600">Page {deliveryPage}</span>
              <button
                type="button"
                onClick={() => setDeliveryPage((current) => current + 1)}
                disabled={deliveriesLoading}
                className="rounded-lg border border-gray-300 px-3 py-1.5 font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:bg-gray-200"
              >
                Next
              </button>
            </div>
          </div>
          {deliveriesLoading ? (
            <ReportPageSkeleton title="Loading deliveries" />
          ) : deliveriesError ? (
            <ReportErrorState title="Could not load deliveries" description={deliveriesError} />
          ) : deliveries?.items.length ? (
            <div className="space-y-2">
              {deliveries.items.map((delivery) => (
                <article key={delivery.id} className="rounded-xl border border-gray-200 bg-white p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-medium text-gray-900">Recipient {delivery.recipient_user_id}</p>
                      <p className="text-xs text-gray-500">Attempts: {delivery.attempt_count}</p>
                    </div>
                    <ReportStatusBadge status={delivery.delivery_status} />
                  </div>
                  <dl className="mt-3 grid gap-2 text-xs text-gray-600 md:grid-cols-2">
                    <div>
                      <dt className="font-medium text-gray-700">Read at</dt>
                      <dd>{delivery.read_at ? <time dateTime={delivery.read_at}>{delivery.read_at}</time> : <span>Not set</span>}</dd>
                    </div>
                    <div>
                      <dt className="font-medium text-gray-700">Last error code</dt>
                      <dd>{delivery.last_error_code ?? "Not set"}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          ) : (
            <ReportEmptyState title="No deliveries yet" description="This announcement has no recorded deliveries on the selected page." />
          )}
        </section>
      </section>
    );
  }

  const selectedSummary = selectedId ? listItems.find((item) => item.id === selectedId) ?? null : null;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 md:px-6">
      <div className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.25em] text-indigo-600">Leadership</p>
            <h1 className="mt-2 text-3xl font-bold text-gray-900">Announcements</h1>
            <p className="mt-2 max-w-2xl text-sm text-gray-600">Create, schedule, publish, and audit announcements across school, grade, class, family, and student audiences.</p>
          </div>
          <button
            type="button"
            onClick={openCreateForm}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700"
          >
            New draft
          </button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <section className="space-y-4 rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-gray-900">Announcement list</h2>
              <p className="text-sm text-gray-500">Filter by backend status and page through results.</p>
            </div>
            <div className="flex items-center gap-3">
              <label className="space-y-1 text-sm">
                <span className="font-medium text-gray-700">Status</span>
                <select
                  value={statusFilter}
                  onChange={(event) => {
                    setStatusFilter(event.target.value as AnnouncementStatus | "all");
                    setPage(1);
                    setSelectedId(null);
                    setSelectedDetail(null);
                    setDeliveries(null);
                    setEditorMode(null);
                    setConfirmAction(null);
                  }}
                  className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
                >
                  {announcementStatuses.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-gray-700">Page size</span>
                <select
                  value={pageSize}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    setPage(1);
                    setSelectedId(null);
                    setSelectedDetail(null);
                    setDeliveries(null);
                    setEditorMode(null);
                    setConfirmAction(null);
                  }}
                  className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
                >
                  {[10, 20, 50, 100].map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {listLoading ? (
            <ReportPageSkeleton title="Loading announcements" />
          ) : listError ? (
            <ReportErrorState title="Could not load announcements" description={listError} />
          ) : listItems.length === 0 ? (
            <ReportEmptyState
              title="No announcements found"
              description="Create a draft to start a new announcement or change the status filter."
              action={
                <button type="button" onClick={openCreateForm} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700">
                  Create draft
                </button>
              }
            />
          ) : (
            <div className="space-y-3">
              {listItems.map((item) => {
                const selected = item.id === selectedId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => selectAnnouncement(item)}
                    className={`w-full rounded-2xl border p-4 text-left transition focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                      selected ? "border-indigo-300 bg-indigo-50" : "border-gray-200 bg-gray-50 hover:border-gray-300 hover:bg-gray-100"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="truncate text-base font-semibold text-gray-900">{item.title}</h3>
                        <p className="mt-1 text-sm text-gray-600">{item.body}</p>
                      </div>
                      <ReportStatusBadge status={item.status} />
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-gray-500">
                      <span>Timezone: {item.timezone}</span>
                      <span>Created: <time dateTime={item.created_at}>{item.created_at}</time></span>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-gray-600 sm:grid-cols-2">
                      <div className="rounded-lg bg-white/80 p-2">
                        <p className="font-medium text-gray-700">Scheduled</p>
                        <p>{formatTimestamp(item.scheduled_at)}</p>
                      </div>
                      <div className="rounded-lg bg-white/80 p-2">
                        <p className="font-medium text-gray-700">Published</p>
                        <p>{formatTimestamp(item.published_at)}</p>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          <div className="flex items-center justify-between gap-3 border-t border-gray-200 pt-4 text-sm">
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page === 1 || listLoading}
              className="rounded-lg border border-gray-300 px-4 py-2 font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:bg-gray-200"
            >
              Previous
            </button>
            <span className="text-gray-600">Page {page}</span>
            <button
              type="button"
              onClick={() => setPage((current) => current + 1)}
              disabled={listLoading}
              className="rounded-lg border border-gray-300 px-4 py-2 font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:bg-gray-200"
            >
              Next
            </button>
          </div>
        </section>

        <div className="space-y-6">
          {editorMode ? renderEditor() : renderSelectionActions()}
          {!editorMode && !selectedSummary && !selectedDetail && !detailLoading ? (
            <ReportEmptyState
              title="Select an announcement"
              description="Choose a row from the list to view details, deliveries, and lifecycle controls."
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}