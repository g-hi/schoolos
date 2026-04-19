"use client";

import { useEffect, useState } from "react";
import { api, apiPost } from "@/lib/api";

/* ───────── Types ───────── */

interface Agent {
  id: string;
  name: string;
  description: string;
  trigger: string;
  channel: string;
  icon: string;
  messages_7d: number;
}

interface Stats {
  period_days: number;
  total: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_channel: Record<string, number>;
}

interface GradeInfo {
  grade: string;
  sections: string[];
}

interface LogMessage {
  id: string;
  recipient: string | null;
  student: string | null;
  channel: string;
  message_type: string;
  status: string;
  error: string | null;
  body: string;
  sent_at: string;
}

/* ───────── Helpers ───────── */

const statusColor: Record<string, string> = {
  sent: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  skipped: "bg-yellow-100 text-yellow-700",
};

const channelIcon: Record<string, string> = {
  whatsapp: "💬",
  sms: "📱",
  email: "📧",
};

/* ───────── Page ───────── */

export default function CommunicationPage() {
  const [tab, setTab] = useState<"agents" | "broadcast" | "log">("agents");

  /* agents tab */
  const [agents, setAgents] = useState<Agent[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);

  /* broadcast tab */
  const [grades, setGrades] = useState<GradeInfo[]>([]);
  const [bcSubject, setBcSubject] = useState("");
  const [bcBody, setBcBody] = useState("");
  const [bcGrade, setBcGrade] = useState("");
  const [bcSection, setBcSection] = useState("");
  const [sending, setSending] = useState<string | null>(null);
  const [bcResult, setBcResult] = useState<{ ok: boolean; text: string } | null>(null);

  /* log tab */
  const [logs, setLogs] = useState<LogMessage[]>([]);
  const [logType, setLogType] = useState("");
  const [logChannel, setLogChannel] = useState("");
  const [logStatus, setLogStatus] = useState("");
  const [expandedLog, setExpandedLog] = useState<string | null>(null);

  /* ─── Load data ─── */

  useEffect(() => {
    loadAgents();
    loadStats();
    loadGrades();
    loadLogs();
  }, []);

  async function loadAgents() {
    try { setAgents(await api<Agent[]>("/communication/agents")); } catch { /* */ }
  }
  async function loadStats() {
    try { setStats(await api<Stats>("/communication/stats")); } catch { /* */ }
  }
  async function loadGrades() {
    try { setGrades(await api<GradeInfo[]>("/communication/grades")); } catch { /* */ }
  }
  async function loadLogs() {
    try {
      const params: Record<string, string> = {};
      if (logType) params.message_type = logType;
      if (logChannel) params.channel = logChannel;
      if (logStatus) params.status = logStatus;
      setLogs(await api<LogMessage[]>("/communication/log", { params }));
    } catch { /* */ }
  }

  /* ─── Actions ─── */

  async function sendDigest() {
    setSending("digest");
    setBcResult(null);
    try {
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      const dateStr = tomorrow.toISOString().split("T")[0];
      const res = await apiPost<{ summary: { sent: number; failed: number; skipped: number } }>(
        "/communication/daily-digest",
        { target_date: dateStr },
      );
      setBcResult({ ok: true, text: `Daily digest: ${res.summary.sent} sent, ${res.summary.failed} failed, ${res.summary.skipped} skipped` });
      loadStats();
      loadLogs();
    } catch (err) {
      setBcResult({ ok: false, text: `Error: ${err}` });
    } finally {
      setSending(null);
    }
  }

  async function sendBroadcast() {
    if (!bcBody.trim()) return;
    setSending("broadcast");
    setBcResult(null);
    try {
      const payload: Record<string, string> = { body: bcBody };
      if (bcSubject) payload.subject = bcSubject;
      if (bcGrade) payload.grade = bcGrade;
      if (bcSection) payload.section = bcSection;
      const res = await apiPost<{ scope: string; recipients: number; summary: { sent: number; failed: number; skipped: number } }>(
        "/communication/broadcast",
        payload,
      );
      setBcResult({ ok: true, text: `Broadcast to ${res.scope}: ${res.recipients} recipients — ${res.summary.sent} sent, ${res.summary.failed} failed` });
      setBcSubject("");
      setBcBody("");
      loadStats();
      loadLogs();
    } catch (err) {
      setBcResult({ ok: false, text: `Error: ${err}` });
    } finally {
      setSending(null);
    }
  }

  /* ─── Sections for selected grade ─── */
  const selectedGradeInfo = grades.find((g) => g.grade === bcGrade);

  /* ───────── Render ───────── */

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Communication</h1>

      {/* Tab bar */}
      <div className="flex gap-2 border-b border-gray-200">
        {(
          [
            ["agents", "Autonomous Agents"],
            ["broadcast", "Send Message"],
            ["log", "Message Log"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === key
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ═══════════ AGENTS TAB ═══════════ */}
      {tab === "agents" && (
        <div className="space-y-6">
          {/* Stats cards */}
          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Total Messages (7d)</p>
                <p className="text-2xl font-bold mt-1">{stats.total}</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Sent</p>
                <p className="text-2xl font-bold mt-1 text-green-600">{stats.by_status.sent || 0}</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Failed</p>
                <p className="text-2xl font-bold mt-1 text-red-600">{stats.by_status.failed || 0}</p>
              </div>
              <div className="bg-white rounded-xl border border-gray-200 p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Skipped</p>
                <p className="text-2xl font-bold mt-1 text-yellow-600">{stats.by_status.skipped || 0}</p>
              </div>
            </div>
          )}

          {/* Agent cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {agents.map((a) => (
              <div
                key={a.id}
                className="bg-white rounded-xl border border-gray-200 p-5 flex flex-col gap-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-2xl">{a.icon}</span>
                    <h3 className="font-semibold text-sm">{a.name}</h3>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
                    Active
                  </span>
                </div>
                <p className="text-sm text-gray-500">{a.description}</p>
                <div className="flex items-center justify-between text-xs text-gray-400 mt-auto pt-2 border-t border-gray-100">
                  <span>⏱ {a.trigger}</span>
                  <span>{a.channel}</span>
                </div>
                <div className="text-xs text-gray-500">
                  📨 <span className="font-medium text-gray-700">{a.messages_7d}</span> messages in last 7 days
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══════════ BROADCAST TAB ═══════════ */}
      {tab === "broadcast" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Manual broadcast */}
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="font-semibold mb-4">Broadcast Message</h2>

              {/* Target filter */}
              <div className="flex gap-2 mb-3">
                <select
                  value={bcGrade}
                  onChange={(e) => { setBcGrade(e.target.value); setBcSection(""); }}
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm flex-1"
                >
                  <option value="">All Grades</option>
                  {grades.map((g) => (
                    <option key={g.grade} value={g.grade}>{g.grade}</option>
                  ))}
                </select>
                {selectedGradeInfo && selectedGradeInfo.sections.length > 1 && (
                  <select
                    value={bcSection}
                    onChange={(e) => setBcSection(e.target.value)}
                    className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-24"
                  >
                    <option value="">All</option>
                    {selectedGradeInfo.sections.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                )}
              </div>

              <input
                type="text"
                placeholder="Subject (optional)"
                value={bcSubject}
                onChange={(e) => setBcSubject(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm mb-3"
              />
              <textarea
                placeholder="Type your message to parents..."
                value={bcBody}
                onChange={(e) => setBcBody(e.target.value)}
                rows={4}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm mb-3"
              />
              <button
                onClick={sendBroadcast}
                disabled={sending === "broadcast" || !bcBody.trim()}
                className="w-full px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
              >
                {sending === "broadcast" ? "Sending..." : "Send Broadcast"}
              </button>
            </div>

            {/* Daily digest */}
            <div className="bg-white rounded-xl border border-gray-200 p-6 flex flex-col">
              <h2 className="font-semibold mb-4">Daily Digest</h2>
              <p className="text-sm text-gray-500 mb-3">
                Send tomorrow&apos;s personalized schedule to every parent via their preferred channel (WhatsApp, SMS, or Email).
              </p>
              <p className="text-xs text-gray-400 mb-4">
                In production, the <strong>Daily Digest Agent</strong> sends this automatically at 7 PM every school night.
              </p>
              <div className="mt-auto">
                <button
                  onClick={sendDigest}
                  disabled={sending === "digest"}
                  className="w-full px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
                >
                  {sending === "digest" ? "Sending..." : "📅 Send Daily Digest Now"}
                </button>
              </div>
            </div>
          </div>

          {/* Result banner */}
          {bcResult && (
            <div
              className={`rounded-lg p-3 text-sm ${
                bcResult.ok
                  ? "bg-green-50 border border-green-200 text-green-700"
                  : "bg-red-50 border border-red-200 text-red-700"
              }`}
            >
              {bcResult.text}
            </div>
          )}
        </div>
      )}

      {/* ═══════════ LOG TAB ═══════════ */}
      {tab === "log" && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          {/* Filters */}
          <div className="flex flex-wrap gap-3 mb-4">
            <select
              value={logType}
              onChange={(e) => { setLogType(e.target.value); }}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">All Types</option>
              <option value="daily_digest">Daily Digest</option>
              <option value="broadcast">Broadcast</option>
              <option value="substitution_alert">Substitution Alert</option>
              <option value="duty_reminder">Duty Reminder</option>
              <option value="attendance_alert">Attendance Alert</option>
              <option value="pickup_notify">Pickup</option>
            </select>
            <select
              value={logChannel}
              onChange={(e) => { setLogChannel(e.target.value); }}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">All Channels</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="sms">SMS</option>
              <option value="email">Email</option>
            </select>
            <select
              value={logStatus}
              onChange={(e) => { setLogStatus(e.target.value); }}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">All Status</option>
              <option value="sent">Sent</option>
              <option value="failed">Failed</option>
              <option value="skipped">Skipped</option>
            </select>
            <button
              onClick={loadLogs}
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
            >
              Apply
            </button>
          </div>

          {/* Table */}
          {logs.length === 0 ? (
            <p className="text-gray-500 text-sm py-8 text-center">No messages found.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium">Type</th>
                    <th className="text-left px-4 py-3 font-medium">Channel</th>
                    <th className="text-left px-4 py-3 font-medium">Recipient</th>
                    <th className="text-left px-4 py-3 font-medium">Student</th>
                    <th className="text-left px-4 py-3 font-medium">Status</th>
                    <th className="text-left px-4 py-3 font-medium">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((m) => (
                    <>
                      <tr
                        key={m.id}
                        className="border-b last:border-0 cursor-pointer hover:bg-gray-50"
                        onClick={() => setExpandedLog(expandedLog === m.id ? null : m.id)}
                      >
                        <td className="px-4 py-3">
                          <span className="px-2 py-1 bg-indigo-50 text-indigo-700 rounded text-xs font-medium">
                            {m.message_type.replace(/_/g, " ")}
                          </span>
                        </td>
                        <td className="px-4 py-3">{channelIcon[m.channel] || "📨"} {m.channel}</td>
                        <td className="px-4 py-3">{m.recipient || "—"}</td>
                        <td className="px-4 py-3 text-gray-500">{m.student || "—"}</td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-1 rounded text-xs font-medium ${statusColor[m.status] || "bg-gray-100"}`}>
                            {m.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-500 text-xs">
                          {new Date(m.sent_at).toLocaleString()}
                        </td>
                      </tr>
                      {expandedLog === m.id && (
                        <tr key={`${m.id}-detail`} className="bg-gray-50">
                          <td colSpan={6} className="px-4 py-3">
                            <p className="text-xs text-gray-600 whitespace-pre-wrap">{m.body}</p>
                            {m.error && (
                              <p className="text-xs text-red-500 mt-1">Error: {m.error}</p>
                            )}
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
