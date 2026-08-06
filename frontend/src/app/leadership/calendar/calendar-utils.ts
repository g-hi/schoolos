import type { EventLifecycleStatus, EventReviewStatus, ManualEvent } from "@/lib/timetable-calendar-api";

export function toFriendlyError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "Request failed.";
}

export function lifecycleBadgeTone(status: EventLifecycleStatus): string {
  switch (status) {
    case "draft":
      return "bg-slate-100 text-slate-800";
    case "pending_review":
      return "bg-amber-100 text-amber-800";
    case "approved":
      return "bg-emerald-100 text-emerald-800";
    case "published":
      return "bg-blue-100 text-blue-800";
    case "rescheduled":
      return "bg-cyan-100 text-cyan-800";
    case "cancelled":
      return "bg-rose-100 text-rose-800";
    case "archived":
      return "bg-zinc-200 text-zinc-700";
    case "rejected":
      return "bg-red-100 text-red-800";
    default:
      return "bg-gray-100 text-gray-800";
  }
}

export function reviewBadgeTone(status: EventReviewStatus): string {
  switch (status) {
    case "approved":
      return "bg-emerald-100 text-emerald-800";
    case "rejected":
      return "bg-rose-100 text-rose-800";
    default:
      return "bg-amber-100 text-amber-900";
  }
}

export function publicationLabel(item: ManualEvent): string {
  if (item.lifecycle_status === "published") {
    return "Published";
  }
  if (item.notification_plan_status === "planned" || item.notification_plan_status === "queued") {
    return "Planned";
  }
  if (item.notification_plan_status === "sent") {
    return "Sent";
  }
  if (item.notification_plan_status === "cancelled") {
    return "Cancelled";
  }
  return "Not published";
}

export function hasHighImpact(scopeType: string): boolean {
  return scopeType === "whole_school";
}

export function allowedActions(item: ManualEvent): string[] {
  const actions = new Set<string>();

  if (item.lifecycle_status === "draft") {
    actions.add("edit");
    actions.add("submit");
  }
  if (item.lifecycle_status === "pending_review") {
    actions.add("approve");
    actions.add("edit");
  }
  if (item.review_status === "approved" && ["approved", "rescheduled"].includes(item.lifecycle_status)) {
    actions.add("publish");
  }
  if (["published", "approved", "rescheduled"].includes(item.lifecycle_status)) {
    actions.add("reschedule");
    actions.add("cancel");
  }
  if (["cancelled", "archived"].includes(item.lifecycle_status)) {
    actions.add("restore");
  }
  if (item.lifecycle_status !== "archived") {
    actions.add("archive");
  }

  return Array.from(actions.values());
}

export function summaryForAudience(item: ManualEvent): string {
  const scopeType = item.impact_scope_json?.scope_type || "public_information";
  if (scopeType === "whole_school") {
    return "Whole school";
  }
  if (scopeType === "public_information") {
    return "Public information";
  }
  if (scopeType === "campus") {
    return "Campus scoped";
  }
  return scopeType.replaceAll("_", " ");
}
