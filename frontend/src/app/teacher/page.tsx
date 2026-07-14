"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import StatCard from "@/components/stat-card";

interface TimetableEntry {
  id: string;
  day: string;
  day_of_week: number;
  period: {
    id: string;
    name: string;
    start_time: string;
    end_time: string;
  } | null;
  class: {
    id: string;
    grade: string;
    section: string;
  } | null;
  subject: {
    id: string;
    code: string;
    name: string;
  } | null;
  teacher: {
    id: string;
    name: string | null;
  } | null;
  is_active: boolean;
}

interface DutyItem {
  id: string;
  day: string;
  slot: string;
  slot_time: string;
  location: string;
  teacher: string | null;
  reasoning: string | null;
}

interface MessageLogItem {
  id: string;
  recipient: string | null;
  student: string | null;
  channel: string;
  message_type: string;
  status: string;
  body: string;
  sent_at: string;
}

interface PickupLogItem {
  id: string;
  status: string;
  student: { name: string } | null;
  parent: { name: string } | null;
  requested_at: string;
  released_at: string | null;
}

interface AsyncState<T> {
  status: "loading" | "success" | "error";
  data?: T;
  error?: string;
}

const dayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
const quickActions = [
  { href: "/teacher/lesson-planning", label: "Generate Lesson Plan", description: "Draft the next teaching sequence", icon: "✍️" },
  { href: "/teacher/assessment-studio", label: "Assessment Studio", description: "Shape formative checks", icon: "🧠" },
  { href: "/teacher/exam-marking", label: "Exam Marking", description: "Review progress and feedback", icon: "✅" },
  { href: "/teacher/copilot", label: "Teacher Copilot", description: "Open the daily workspace", icon: "✨" },
  { href: "/teacher/my-classes", label: "My Classes", description: "Stay across the day’s groups", icon: "🏫" },
  { href: "/teacher/parent-communication", label: "Parent Communication", description: "Review recent outreach", icon: "💬" },
  { href: "/teacher/student-pickup", label: "Student Pickup", description: "Monitor pickup workflow", icon: "🚗" },
  { href: "/teacher/settings", label: "Settings", description: "Adjust your workspace", icon: "⚙️" },
];

function getGreeting(date: Date) {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function getAcademicTerm(date: Date) {
  const month = date.getMonth() + 1;
  if (month >= 8 || month <= 1) return "Fall Semester";
  if (month >= 2 && month <= 5) return "Spring Semester";
  return "Summer Term";
}

function getTodayName(date: Date) {
  const today = date.getDay();
  const index = today === 0 ? 4 : Math.min(today - 1, 4);
  return dayNames[index] ?? "Today";
}

function parseClockTime(raw: string | undefined) {
  if (!raw) return null;
  const match = raw.match(/(\d{1,2}):(\d{2})/);
  if (!match) return null;
  return parseInt(match[1], 10) * 60 + parseInt(match[2], 10);
}

function getCurrentLesson(entries: TimetableEntry[], date: Date) {
  const nowMinutes = date.getHours() * 60 + date.getMinutes();
  const active = entries.find((entry) => {
    const start = parseClockTime(entry.period?.start_time);
    const end = parseClockTime(entry.period?.end_time);
    if (start === null || end === null) return false;
    return start <= nowMinutes && nowMinutes <= end;
  });
  return active ?? entries[0] ?? null;
}

export default function TeacherDashboardPage() {
  const [timetableState, setTimetableState] = useState<AsyncState<TimetableEntry[]>>({ status: "loading" });
  const [dutiesState, setDutiesState] = useState<AsyncState<DutyItem[]>>({ status: "loading" });
  const [messagesState, setMessagesState] = useState<AsyncState<MessageLogItem[]>>({ status: "loading" });
  const [pickupsState, setPickupsState] = useState<AsyncState<PickupLogItem[]>>({ status: "loading" });

  useEffect(() => {
    const load = async () => {
      const [timetableResult, dutiesResult, messagesResult, pickupsResult] = await Promise.allSettled([
        api<TimetableEntry[]>("/timetable/"),
        api<DutyItem[]>("/duties/"),
        api<MessageLogItem[]>("/communication/log?limit=5"),
        api<PickupLogItem[]>("/pickup/log?limit=5"),
      ]);

      setTimetableState(
        timetableResult.status === "fulfilled"
          ? { status: "success", data: timetableResult.value }
          : { status: "error", error: timetableResult.reason instanceof Error ? timetableResult.reason.message : "Unable to load timetable." }
      );
      setDutiesState(
        dutiesResult.status === "fulfilled"
          ? { status: "success", data: dutiesResult.value }
          : { status: "error", error: dutiesResult.reason instanceof Error ? dutiesResult.reason.message : "Unable to load duties." }
      );
      setMessagesState(
        messagesResult.status === "fulfilled"
          ? { status: "success", data: messagesResult.value }
          : { status: "error", error: messagesResult.reason instanceof Error ? messagesResult.reason.message : "Unable to load messages." }
      );
      setPickupsState(
        pickupsResult.status === "fulfilled"
          ? { status: "success", data: pickupsResult.value }
          : { status: "error", error: pickupsResult.reason instanceof Error ? pickupsResult.reason.message : "Unable to load pickups." }
      );
    };

    void load();
  }, []);

  const now = useMemo(() => new Date(), []);
  const todayName = useMemo(() => getTodayName(now), [now]);
  const formattedDate = now.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
  const schoolName = "Greenwood International Academy";

  const todaysLessons = useMemo(() => {
    if (timetableState.status !== "success") return [];
    const todayIndex = dayNames.indexOf(todayName);
    return (timetableState.data ?? []).filter((entry) => entry.day_of_week === todayIndex);
  }, [timetableState, todayName]);

  const currentLesson = useMemo(() => getCurrentLesson(todaysLessons, now), [todaysLessons, now]);
  const upcomingLessons = useMemo(() => {
    if (!currentLesson) return todaysLessons.slice(0, 3);
    const index = todaysLessons.findIndex((lesson) => lesson.id === currentLesson.id);
    return index >= 0 ? todaysLessons.slice(index + 1, index + 4) : todaysLessons.slice(0, 3);
  }, [todaysLessons, currentLesson]);

  const todaysDuties = useMemo(() => {
    if (dutiesState.status !== "success") return [];
    return (dutiesState.data ?? []).filter((duty) => duty.day === todayName);
  }, [dutiesState, todayName]);

  const unreadCount = useMemo(() => {
    const messageCount = messagesState.status === "success" ? (messagesState.data ?? []).length : 0;
    const pickupCount = pickupsState.status === "success" ? (pickupsState.data ?? []).filter((item) => item.status !== "released").length : 0;
    return messageCount + pickupCount;
  }, [messagesState, pickupsState]);

  const isLoading = timetableState.status === "loading" || dutiesState.status === "loading" || messagesState.status === "loading" || pickupsState.status === "loading";

  if (isLoading) {
    return <Skeleton />;
  }

  return (
    <div className="space-y-6 lg:space-y-8">
      <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-2xl">
            <p className="text-[11px] font-semibold uppercase tracking-[0.35em] text-indigo-600">Teacher portal</p>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight text-gray-900 sm:text-3xl">
              {getGreeting(now)}, Ms. Amina
            </h1>
            <p className="mt-3 text-sm leading-6 text-gray-600">
              {schoolName} · {formattedDate}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-600">
                {getAcademicTerm(now)}
              </span>
              <span className="rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
                {todayName} · {currentLesson ? `${currentLesson.period?.name ?? currentLesson.period?.start_time ?? "Lesson"}` : "No lessons scheduled"}
              </span>
            </div>
          </div>
          <div className="rounded-2xl border border-indigo-100 bg-indigo-50/80 px-5 py-4 shadow-sm">
            <p className="text-sm font-medium text-indigo-800">Today&apos;s rhythm</p>
            <p className="mt-2 text-xl font-semibold text-indigo-900">
              {currentLesson ? `${currentLesson.subject?.name ?? "Lesson"} · ${currentLesson.class ? `${currentLesson.class.grade} ${currentLesson.class.section}` : "Class"}` : "No active lesson"}
            </p>
            <p className="mt-1 text-sm text-indigo-700">
              {currentLesson ? `${currentLesson.period?.start_time ?? "—"}–${currentLesson.period?.end_time ?? "—"} · ${currentLesson.teacher?.name ?? "Teacher"}` : "The timetable is currently clear."}
            </p>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <StatCard title="Current lesson" value={currentLesson?.period?.name ?? "—"} subtitle={currentLesson ? `${currentLesson.subject?.name ?? "Subject"} · ${currentLesson.class ? `${currentLesson.class.grade} ${currentLesson.class.section}` : "Class"}` : "No lesson detected"} color="indigo" />
        <StatCard title="Unread updates" value={unreadCount} subtitle="Messages and pickups pending review" color="amber" />
        <StatCard title="Duties today" value={todaysDuties.length} subtitle="Scheduled for the current day" color="green" />
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {quickActions.map((action) => (
          <Link
            key={action.label}
            href={action.href}
            className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-gray-900">{action.label}</p>
                <p className="mt-2 text-sm text-gray-600">{action.description}</p>
              </div>
              <span className="text-xl">{action.icon}</span>
            </div>
          </Link>
        ))}
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Today&apos;s Timetable</h2>
              <p className="mt-1 text-sm text-gray-500">Live view of the current day&apos;s teaching rhythm</p>
            </div>
            <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">{todayName}</span>
          </div>
          <div className="mt-5 space-y-3">
            <div className="rounded-2xl border border-indigo-100 bg-indigo-50 p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-600">Current lesson</p>
                <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-indigo-700">Now</span>
              </div>
              {currentLesson ? (
                <>
                  <p className="mt-3 text-sm font-semibold text-gray-900">{currentLesson.period?.name ?? "Lesson"} · {currentLesson.subject?.name ?? "Subject"}</p>
                  <p className="mt-1 text-sm text-gray-600">{currentLesson.class ? `${currentLesson.class.grade} ${currentLesson.class.section}` : "Class"} · {currentLesson.period?.start_time ?? "—"}–{currentLesson.period?.end_time ?? "—"}</p>
                  <div className="mt-3 flex flex-wrap gap-2 text-sm text-gray-600">
                    <span className="rounded-full border border-indigo-100 bg-white px-3 py-1">Subject: {currentLesson.subject?.name ?? "TBD"}</span>
                    <span className="rounded-full border border-indigo-100 bg-white px-3 py-1">Grade: {currentLesson.class ? `${currentLesson.class.grade} ${currentLesson.class.section}` : "TBD"}</span>
                    <span className="rounded-full border border-indigo-100 bg-white px-3 py-1">Room: TBD</span>
                    <span className="rounded-full border border-indigo-100 bg-white px-3 py-1">Time: {currentLesson.period?.start_time ?? "—"}–{currentLesson.period?.end_time ?? "—"}</span>
                  </div>
                </>
              ) : (
                <p className="mt-3 text-sm text-gray-600">No lessons are scheduled for this time slot.</p>
              )}
            </div>
            {upcomingLessons.length > 0 ? (
              upcomingLessons.map((lesson) => (
                <div key={lesson.id} className="rounded-2xl border border-gray-200 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-gray-900">{lesson.period?.name ?? "Lesson"}</p>
                    <span className="text-sm text-gray-500">{lesson.period?.start_time ?? "—"}–{lesson.period?.end_time ?? "—"}</span>
                  </div>
                  <p className="mt-1 text-sm text-gray-700">{lesson.subject?.name ?? "Subject"} · {lesson.class ? `${lesson.class.grade} ${lesson.class.section}` : "Class"}</p>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-gray-300 p-4 text-sm text-gray-600">No additional lessons are scheduled for the rest of the day.</div>
            )}
          </div>
        </section>

        <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">School Pulse</h2>
              <p className="mt-1 text-sm text-gray-500">Operational awareness for the day ahead</p>
            </div>
            <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">Live feed pending</span>
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {[
              { title: "Today&apos;s Events", value: "—", hint: "Calendar feed pending" },
              { title: "Educational Trips", value: "—", hint: "Awaiting trip schedule" },
              { title: "School Meetings", value: "—", hint: "Meeting roster pending" },
              { title: "Upcoming Holidays", value: "—", hint: "Calendar integration pending" },
              { title: "Special Activities", value: "—", hint: "Activity board pending" },
              { title: "Inspection Notices", value: "—", hint: "Inspection feed pending" },
              { title: "Announcements", value: "—", hint: "Message center pending" },
            ].map((item) => (
              <div key={item.title} className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
                <p className="text-sm font-medium text-gray-900">{item.title}</p>
                <p className="mt-2 text-2xl font-semibold text-indigo-700">{item.value}</p>
                <p className="mt-1 text-xs uppercase tracking-[0.2em] text-gray-500">{item.hint}</p>
              </div>
            ))}
          </div>
          <p className="mt-4 text-sm text-gray-500">{/* TODO: replace this placeholder with /calendar/announcements once those endpoints are available. */}</p>
        </section>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Smart Notifications</h2>
              <p className="mt-1 text-sm text-gray-500">Critical updates requiring attention</p>
            </div>
            <span className="rounded-full bg-indigo-50 px-3 py-1 text-sm font-medium text-indigo-700">{unreadCount} unread</span>
          </div>
          <div className="mt-5 space-y-3">
            <div className="rounded-2xl border border-gray-200 p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-gray-900">Pickup requests</p>
                <span className="text-sm font-medium text-gray-500">{pickupsState.status === "success" ? (pickupsState.data ?? []).length : "—"}</span>
              </div>
              {pickupsState.status === "error" ? (
                <p className="mt-2 text-sm text-red-600">Unable to load pickup updates.</p>
              ) : pickupsState.status === "success" && (pickupsState.data ?? []).length > 0 ? (
                <p className="mt-2 text-sm text-gray-600">{(pickupsState.data ?? [])[0].status} · {(pickupsState.data ?? [])[0].parent?.name ?? "Parent"}</p>
              ) : (
                <p className="mt-2 text-sm text-gray-600">No pickup updates to review.</p>
              )}
            </div>
            <div className="rounded-2xl border border-gray-200 p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-gray-900">Parent messages</p>
                <span className="text-sm font-medium text-gray-500">{messagesState.status === "success" ? (messagesState.data ?? []).length : "—"}</span>
              </div>
              {messagesState.status === "error" ? (
                <p className="mt-2 text-sm text-red-600">Unable to load parent communication.</p>
              ) : messagesState.status === "success" && (messagesState.data ?? []).length > 0 ? (
                <p className="mt-2 text-sm text-gray-600">{(messagesState.data ?? [])[0].body}</p>
              ) : (
                <p className="mt-2 text-sm text-gray-600">No new parent messages available.</p>
              )}
            </div>
            <div className="rounded-2xl border border-gray-200 p-4">
              <p className="text-sm font-medium text-gray-900">Timetable changes</p>
              <p className="mt-2 text-sm text-gray-600">The live timetable feed is available through /timetable/ and will surface changes here in a future pass.</p>
            </div>
            <div className="rounded-2xl border border-gray-200 p-4">
              <p className="text-sm font-medium text-gray-900">Substitution alerts</p>
              <p className="mt-2 text-sm text-gray-600">No substitution alerts were detected for the current day.</p>
            </div>
            <div className="rounded-2xl border border-gray-200 p-4">
              <p className="text-sm font-medium text-gray-900">Announcements</p>
              <p className="mt-2 text-sm text-gray-600">No urgent school announcements are pending.</p>
            </div>
          </div>
        </section>

        <div className="space-y-6">
          <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Today&apos;s Duties</h2>
                <p className="mt-1 text-sm text-gray-500">Current duty roster for the active day</p>
              </div>
              <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">/duties/</span>
            </div>
            <div className="mt-5 space-y-3">
              {todaysDuties.length > 0 ? (
                todaysDuties.slice(0, 4).map((duty) => (
                  <div key={duty.id} className="rounded-2xl border border-gray-200 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-gray-900">{duty.slot}</p>
                      <span className="text-sm text-gray-500">{duty.slot_time}</span>
                    </div>
                    <p className="mt-1 text-sm text-gray-600">{duty.location} · {duty.teacher ?? "Unassigned"}</p>
                  </div>
                ))
              ) : (
                <div className="rounded-2xl border border-dashed border-gray-300 p-4 text-sm text-gray-600">No duties assigned today.</div>
              )}
            </div>
          </section>

          <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Upcoming Parent Appointments</h2>
                <p className="mt-1 text-sm text-gray-500">Bookings will appear once the appointments workflow is connected</p>
              </div>
              <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">Placeholder</span>
            </div>
            <div className="mt-5 space-y-3">
              <div className="rounded-2xl border border-dashed border-gray-300 p-4 text-sm text-gray-600">
                No appointments are scheduled yet. The frontend is ready for an appointments API once the backend endpoint is available.
              </div>
            </div>
            <p className="mt-4 text-sm text-gray-500">{/* TODO: replace this placeholder with /appointments/ once that service is available. */}</p>
          </section>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Recent Activity</h2>
              <p className="mt-1 text-sm text-gray-500">What changed most recently in the teacher workspace</p>
            </div>
            <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">Workspace</span>
          </div>
          <div className="mt-5 space-y-3">
            <div className="rounded-2xl border border-gray-200 p-4">
              <p className="text-sm font-medium text-gray-900">Recent pickup releases</p>
              <p className="mt-2 text-sm text-gray-600">
                {pickupsState.status === "success" && (pickupsState.data ?? []).length > 0
                  ? `${(pickupsState.data ?? []).filter((item) => item.released_at).length} pickup release events were logged.`
                  : "No recent pickup releases recorded."}
              </p>
            </div>
            <div className="rounded-2xl border border-gray-200 p-4">
              <p className="text-sm font-medium text-gray-900">Recent parent communication</p>
              <p className="mt-2 text-sm text-gray-600">
                {messagesState.status === "success" && (messagesState.data ?? []).length > 0
                  ? `${(messagesState.data ?? []).length} message updates were surfaced from /communication/log.`
                  : "No recent communications are available yet."}
              </p>
            </div>
            <div className="rounded-2xl border border-gray-200 p-4">
              <p className="text-sm font-medium text-gray-900">Lesson updates</p>
              <p className="mt-2 text-sm text-gray-600">Timetable changes and lesson adjustments will be surfaced here through /timetable/.</p>
            </div>
            <div className="rounded-2xl border border-gray-200 p-4">
              <p className="text-sm font-medium text-gray-900">Generated resources</p>
              <p className="mt-2 text-sm text-gray-600">Lesson resources and assets will appear here once the teaching resource workflow is enabled.</p>
            </div>
          </div>
        </section>

        <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">AI Daily Briefing</h2>
              <p className="mt-1 text-sm text-gray-500">A premium surface for tomorrow&apos;s teaching context</p>
            </div>
            <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">Coming soon</span>
          </div>
          <div className="mt-5 rounded-3xl border border-dashed border-indigo-200 bg-linear-to-br from-indigo-50 via-white to-slate-50 p-6 text-sm text-gray-700">
            <div className="flex items-center gap-2">
              <span className="text-lg">✨</span>
              <p className="font-semibold text-gray-900">AI Daily Briefing</p>
            </div>
            <p className="mt-3 leading-6">
              Your AI teaching assistant will summarize your day, recommend lesson resources, notify you about important events, and provide proactive insights.
            </p>
            <div className="mt-4 rounded-2xl border border-indigo-100 bg-white/80 p-4 text-sm text-gray-600">
              This surface is intentionally reserved for a future AI-enabled sprint. It does not introduce new backend behavior today.
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-6">
      <div className="h-32 rounded-3xl bg-gray-200" />
      <div className="grid gap-4 md:grid-cols-3">
        {[1, 2, 3].map((item) => (
          <div key={item} className="h-24 rounded-2xl bg-gray-200" />
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[1, 2, 3, 4].map((item) => (
          <div key={item} className="h-24 rounded-2xl bg-gray-200" />
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <div className="h-72 rounded-3xl bg-gray-200" />
        <div className="h-72 rounded-3xl bg-gray-200" />
      </div>
    </div>
  );
}
