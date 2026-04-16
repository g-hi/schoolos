"use client";

import { useEffect, useState } from "react";
import { api, apiPost } from "@/lib/api";

interface Message {
  id: string;
  channel: string;
  recipient_name: string;
  subject: string | null;
  body: string;
  status: string;
  created_at: string;
}

export default function CommunicationPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [broadcastBody, setBroadcastBody] = useState("");
  const [broadcastSubject, setBroadcastSubject] = useState("");
  const [sending, setSending] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    loadMessages();
  }, []);

  async function loadMessages() {
    try {
      const data = await api<Message[]>("/communication/log");
      setMessages(data);
    } catch (err) {
      console.error(err);
    }
  }

  async function sendDigest() {
    setSending("digest");
    setResult(null);
    try {
      const res = await apiPost("/communication/daily-digest", {});
      setResult(`Daily digest sent: ${JSON.stringify(res)}`);
      loadMessages();
    } catch (err) {
      setResult(`Error: ${err}`);
    } finally {
      setSending(null);
    }
  }

  async function sendBroadcast() {
    setSending("broadcast");
    setResult(null);
    try {
      const res = await apiPost("/communication/broadcast", {
        subject: broadcastSubject,
        body: broadcastBody,
      });
      setResult(`Broadcast sent: ${JSON.stringify(res)}`);
      setBroadcastSubject("");
      setBroadcastBody("");
      loadMessages();
    } catch (err) {
      setResult(`Error: ${err}`);
    } finally {
      setSending(null);
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Communication</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
        {/* Daily Digest */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="font-semibold mb-3">Daily Digest</h2>
          <p className="text-sm text-gray-500 mb-4">
            Send tomorrow&apos;s schedule to all parents via their preferred channel.
          </p>
          <button
            onClick={sendDigest}
            disabled={sending === "digest"}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {sending === "digest" ? "Sending..." : "Send Daily Digest"}
          </button>
        </div>

        {/* Broadcast */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="font-semibold mb-3">Broadcast Message</h2>
          <input
            type="text"
            placeholder="Subject"
            value={broadcastSubject}
            onChange={(e) => setBroadcastSubject(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm mb-3"
          />
          <textarea
            placeholder="Message body..."
            value={broadcastBody}
            onChange={(e) => setBroadcastBody(e.target.value)}
            rows={3}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm mb-3"
          />
          <button
            onClick={sendBroadcast}
            disabled={sending === "broadcast" || !broadcastBody}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {sending === "broadcast" ? "Sending..." : "Send Broadcast"}
          </button>
        </div>
      </div>

      {result && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-sm text-green-700 mb-6">
          {result}
        </div>
      )}

      {/* Message Log */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Message Log</h2>
          <button onClick={loadMessages} className="text-sm text-indigo-600 hover:underline">
            Refresh
          </button>
        </div>
        {messages.length === 0 ? (
          <p className="text-gray-500 text-sm">No messages sent yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium">Channel</th>
                <th className="text-left px-4 py-3 font-medium">Recipient</th>
                <th className="text-left px-4 py-3 font-medium">Subject</th>
                <th className="text-left px-4 py-3 font-medium">Status</th>
                <th className="text-left px-4 py-3 font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {messages.map((m) => (
                <tr key={m.id} className="border-b last:border-0">
                  <td className="px-4 py-3">
                    <span className="px-2 py-1 bg-gray-100 rounded text-xs font-medium">{m.channel}</span>
                  </td>
                  <td className="px-4 py-3">{m.recipient_name}</td>
                  <td className="px-4 py-3">{m.subject || "—"}</td>
                  <td className="px-4 py-3">{m.status}</td>
                  <td className="px-4 py-3 text-gray-500">{new Date(m.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
