"use client";

import { useEffect, useState } from "react";
import { api, apiPost } from "@/lib/api";
import StatCard from "@/components/stat-card";

interface Mention {
  id: string;
  platform: string;
  author: string;
  content: string;
  sentiment: string | null;
  sentiment_score: number | null;
  published_at: string;
}

interface Report {
  period: string;
  total_mentions: number;
  analyzed: number;
  sentiment_breakdown: Record<string, number>;
  avg_sentiment_score: number | null;
  top_positive: { content: string; score: number }[];
  top_negative: { content: string; score: number }[];
  platform_breakdown: Record<string, number>;
}

export default function SocialPage() {
  const [mentions, setMentions] = useState<Mention[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    loadMentions();
    loadReport();
  }, []);

  async function loadMentions() {
    try {
      const data = await api<Mention[]>("/social/mentions");
      setMentions(data);
    } catch (err) {
      console.error(err);
    }
  }

  async function loadReport() {
    try {
      const data = await api<Report>("/social/report");
      setReport(data);
    } catch (err) {
      console.error(err);
    }
  }

  async function runAnalysis() {
    setAnalyzing(true);
    try {
      const res = await apiPost("/social/analyze", {});
      setResult(JSON.stringify(res));
      loadMentions();
      loadReport();
    } catch (err) {
      setResult(`Error: ${err}`);
    } finally {
      setAnalyzing(false);
    }
  }

  async function crisisCheck() {
    setLoading(true);
    try {
      const res = await apiPost("/social/crisis-check", { threshold: 3 });
      setResult(JSON.stringify(res, null, 2));
    } catch (err) {
      setResult(`Error: ${err}`);
    } finally {
      setLoading(false);
    }
  }

  const sentimentColor: Record<string, string> = {
    positive: "text-green-600 bg-green-50",
    negative: "text-red-600 bg-red-50",
    neutral: "text-gray-600 bg-gray-50",
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Social Media Analytics</h1>

      {/* Actions */}
      <div className="flex gap-3 mb-6">
        <button
          onClick={runAnalysis}
          disabled={analyzing}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {analyzing ? "Analyzing..." : "Run AI Analysis"}
        </button>
        <button
          onClick={crisisCheck}
          disabled={loading}
          className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
        >
          {loading ? "Checking..." : "Crisis Check"}
        </button>
      </div>

      {result && (
        <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-xs mb-6 overflow-auto max-h-40">
          {result}
        </pre>
      )}

      {/* Report Stats */}
      {report && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <StatCard title="Total Mentions" value={report.total_mentions} />
          <StatCard title="Analyzed" value={report.analyzed} color="green" />
          <StatCard
            title="Avg Sentiment"
            value={report.avg_sentiment_score != null ? report.avg_sentiment_score.toFixed(1) : "N/A"}
            color={report.avg_sentiment_score != null && report.avg_sentiment_score >= 0.5 ? "green" : "amber"}
          />
          <StatCard
            title="Platforms"
            value={Object.keys(report.platform_breakdown).length}
            color="gray"
          />
        </div>
      )}

      {/* Mentions Table */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Recent Mentions</h2>
          <button onClick={loadMentions} className="text-sm text-indigo-600 hover:underline">Refresh</button>
        </div>
        {mentions.length === 0 ? (
          <p className="text-gray-500 text-sm">No mentions imported yet. Use the API to import mentions.</p>
        ) : (
          <div className="space-y-3">
            {mentions.slice(0, 20).map((m) => (
              <div key={m.id} className="border border-gray-100 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-1 bg-gray-100 rounded text-xs font-medium">{m.platform}</span>
                    <span className="text-sm font-medium">{m.author}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {m.sentiment && (
                      <span className={`px-2 py-1 rounded text-xs font-medium ${sentimentColor[m.sentiment] || "bg-gray-100"}`}>
                        {m.sentiment} {m.sentiment_score != null && `(${m.sentiment_score.toFixed(2)})`}
                      </span>
                    )}
                    <span className="text-xs text-gray-400">{new Date(m.published_at).toLocaleDateString()}</span>
                  </div>
                </div>
                <p className="text-sm text-gray-700">{m.content}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
