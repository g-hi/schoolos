"use client";

import { useEffect, useState } from "react";
import { api, apiPost } from "@/lib/api";
import StatCard from "@/components/stat-card";

interface Mention {
  id: string;
  platform: string;
  author: string;
  text: string;
  url: string | null;
  posted_at: string;
  sentiment: string | null;
  sentiment_score: number | null;
  topics: string[] | null;
  is_competitor: boolean;
  engagement: number;
  processed: boolean;
}

interface SchoolReport {
  total_mentions: number;
  sentiment: Record<string, number>;
  avg_sentiment_score: number | null;
  by_platform: Record<string, number>;
  top_topics: { topic: string; count: number }[];
  top_posts: { platform: string; text: string; author: string; engagement: number; sentiment: string; posted_at: string }[];
}

interface CompetitorReport {
  total_mentions: number;
  avg_sentiment_score: number | null;
  top_posts: { competitor: string; platform: string; text: string; engagement: number; sentiment: string }[];
}

interface DailyTrend {
  date: string;
  mentions: number;
  avg_sentiment: number | null;
  negative_count: number;
}

interface Report {
  period: string;
  our_school: SchoolReport;
  competitors: CompetitorReport;
  daily_trend: DailyTrend[];
}

export default function SocialPage() {
  const [mentions, setMentions] = useState<Mention[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [tab, setTab] = useState<"overview" | "mentions" | "competitors">("overview");

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

  const tabs = [
    { id: "overview" as const, label: "Overview" },
    { id: "mentions" as const, label: "Mentions" },
    { id: "competitors" as const, label: "Competitors" },
  ];

  const school = report?.our_school;
  const competitors = report?.competitors;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Social Media Analytics</h1>
        <div className="flex gap-3">
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
      </div>

      {result && (
        <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-xs overflow-auto max-h-40">
          {result}
        </pre>
      )}

      {/* Tabs */}
      <div className="flex gap-4 border-b border-gray-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`pb-2 text-sm font-medium transition-colors ${
              tab === t.id ? "border-b-2 border-indigo-600 text-indigo-600" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {tab === "overview" && (
        <>
          {school && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <StatCard title="Total Mentions" value={school.total_mentions} />
                <StatCard
                  title="Positive"
                  value={school.sentiment?.positive ?? 0}
                  color="green"
                />
                <StatCard
                  title="Negative"
                  value={school.sentiment?.negative ?? 0}
                  color="red"
                />
                <StatCard
                  title="Avg Sentiment"
                  value={school.avg_sentiment_score != null ? school.avg_sentiment_score.toFixed(2) : "N/A"}
                  color={school.avg_sentiment_score != null && school.avg_sentiment_score >= 0.5 ? "green" : "amber"}
                />
              </div>

              {/* Platform Breakdown */}
              {school.by_platform && Object.keys(school.by_platform).length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-6">
                  <h3 className="font-semibold mb-3">By Platform</h3>
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(school.by_platform).map(([platform, count]) => (
                      <div key={platform} className="px-4 py-2 bg-indigo-50 rounded-lg text-sm">
                        <span className="font-medium text-indigo-700">{platform}</span>
                        <span className="ml-2 text-gray-500">{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Top Topics */}
              {school.top_topics && school.top_topics.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-6">
                  <h3 className="font-semibold mb-3">Top Topics</h3>
                  <div className="flex flex-wrap gap-2">
                    {school.top_topics.map((t) => (
                      <span key={t.topic} className="px-3 py-1 bg-gray-100 rounded-full text-sm">
                        {t.topic} <span className="text-gray-400">({t.count})</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Daily Trend */}
              {report.daily_trend && report.daily_trend.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-6">
                  <h3 className="font-semibold mb-3">Daily Trend (Last 7 days)</h3>
                  <div className="grid grid-cols-7 gap-2">
                    {report.daily_trend.slice(-7).map((d) => (
                      <div key={d.date} className="text-center">
                        <div className="text-xs text-gray-400 mb-1">{d.date.slice(5)}</div>
                        <div className="text-sm font-medium">{d.mentions}</div>
                        {d.negative_count > 0 && (
                          <div className="text-xs text-red-500">{d.negative_count} neg</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
          {!school && (
            <p className="text-gray-500 text-sm py-8 text-center">No report data yet. Run AI Analysis to generate.</p>
          )}
        </>
      )}

      {/* Mentions Tab */}
      {tab === "mentions" && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Recent Mentions</h2>
            <button onClick={loadMentions} className="text-sm text-indigo-600 hover:underline">Refresh</button>
          </div>
          {mentions.length === 0 ? (
            <p className="text-gray-500 text-sm py-8 text-center">No mentions imported yet. Use the API to import mentions.</p>
          ) : (
            <div className="space-y-3">
              {mentions.filter((m) => !m.is_competitor).slice(0, 30).map((m) => (
                <div key={m.id} className="border border-gray-100 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-1 bg-gray-100 rounded text-xs font-medium">{m.platform}</span>
                      <span className="text-sm font-medium">{m.author}</span>
                      {m.engagement > 0 && (
                        <span className="text-xs text-gray-400">⚡ {m.engagement}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {m.sentiment && (
                        <span className={`px-2 py-1 rounded text-xs font-medium ${sentimentColor[m.sentiment] || "bg-gray-100"}`}>
                          {m.sentiment} {m.sentiment_score != null && `(${m.sentiment_score.toFixed(2)})`}
                        </span>
                      )}
                      <span className="text-xs text-gray-400">{new Date(m.posted_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                  <p className="text-sm text-gray-700">{m.text}</p>
                  {m.topics && m.topics.length > 0 && (
                    <div className="flex gap-1 mt-2">
                      {m.topics.map((topic) => (
                        <span key={topic} className="px-2 py-0.5 bg-indigo-50 text-indigo-600 rounded text-xs">{topic}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Competitors Tab */}
      {tab === "competitors" && (
        <>
          {competitors && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <StatCard title="Competitor Mentions" value={competitors.total_mentions} />
                <StatCard
                  title="Competitor Avg Sentiment"
                  value={competitors.avg_sentiment_score != null ? competitors.avg_sentiment_score.toFixed(2) : "N/A"}
                  color="gray"
                />
              </div>
              {competitors.top_posts && competitors.top_posts.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-6">
                  <h3 className="font-semibold mb-3">Top Competitor Posts</h3>
                  <div className="space-y-3">
                    {competitors.top_posts.map((p, i) => (
                      <div key={i} className="border border-gray-100 rounded-lg p-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="px-2 py-1 bg-amber-50 text-amber-700 rounded text-xs font-medium">{p.competitor}</span>
                          <span className="px-2 py-1 bg-gray-100 rounded text-xs">{p.platform}</span>
                          {p.sentiment && (
                            <span className={`px-2 py-1 rounded text-xs font-medium ${sentimentColor[p.sentiment] || "bg-gray-100"}`}>
                              {p.sentiment}
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-gray-700">{p.text}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
          {!competitors && (
            <p className="text-gray-500 text-sm py-8 text-center">No competitor data yet.</p>
          )}
        </>
      )}
    </div>
  );
}
