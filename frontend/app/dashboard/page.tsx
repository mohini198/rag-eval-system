"use client";

import { useState, useEffect } from "react";
import { getEvalResults, EvalResult } from "@/lib/api";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function Dashboard() {
  const [results, setResults] = useState<EvalResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getEvalResults(20)
      .then(setResults)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const validResults = results.filter((r) => r.faithfulness !== null);

  const avgScore = (key: keyof EvalResult) => {
    const vals = validResults
      .map((r) => r[key] as number | null)
      .filter((v): v is number => v !== null);
    return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };

  const chartData = [
    { metric: "Faithfulness", score: avgScore("faithfulness") },
    { metric: "Relevancy", score: avgScore("answer_relevancy") },
    { metric: "Precision", score: avgScore("context_precision") },
    { metric: "Recall", score: avgScore("context_recall") },
  ].filter((d) => d.score !== null);

  const hallucinationRate =
    validResults.length > 0
      ? (validResults.filter((r) => r.has_hallucination).length / validResults.length) * 100
      : 0;

  const summaryCards = [
    { label: "Faithfulness", value: avgScore("faithfulness"), good: true },
    { label: "Answer Relevancy", value: avgScore("answer_relevancy"), good: true },
    { label: "Context Precision", value: avgScore("context_precision"), good: true },
    { label: "Context Recall", value: avgScore("context_recall"), good: true },
    { label: "Hallucination Rate", value: hallucinationRate / 100, good: false },
  ];

  return (
    <div style={{ display: "flex", height: "100vh", background: "var(--surface-0)", fontFamily: "var(--font-sans)" }}>

      {/* Sidebar */}
      <div style={{ width: 240, background: "var(--surface-1)", borderRight: "0.5px solid var(--border)", display: "flex", flexDirection: "column", padding: "16px 12px", gap: 4, flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 8px", marginBottom: 16 }}>
          <div style={{ width: 30, height: 30, background: "var(--fill-accent)", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <i className="ti ti-brain" style={{ color: "var(--on-accent)", fontSize: 16 }} aria-hidden="true" />
          </div>
          <span style={{ fontSize: 15, fontWeight: 500, color: "var(--text-primary)" }}>Veridoc</span>
        </div>

        <a href="/" style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: "var(--radius)", color: "var(--text-secondary)", fontSize: 13, textDecoration: "none" }}>
          <i className="ti ti-message-2" style={{ fontSize: 16 }} aria-hidden="true" /> Chat
        </a>
        <a href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: "var(--radius)", color: "var(--text-accent)", background: "var(--bg-accent)", fontSize: 13, textDecoration: "none" }}>
          <i className="ti ti-chart-bar" style={{ fontSize: 16 }} aria-hidden="true" /> Dashboard
        </a>

        <div style={{ marginTop: "auto", padding: "8px 10px", borderRadius: "var(--radius)", background: "var(--surface-2)", border: "0.5px solid var(--border)" }}>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>Total evaluations</p>
          <p style={{ fontSize: 22, fontWeight: 600, color: "var(--text-primary)" }}>{validResults.length}</p>
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflowY: "auto" }}>

        {/* Topbar */}
        <div style={{ padding: "16px 24px", borderBottom: "0.5px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", position: "sticky", top: 0, background: "var(--surface-0)", zIndex: 10 }}>
          <div>
            <h1 style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)" }}>Evaluation Dashboard</h1>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>Real-time RAG pipeline quality metrics</p>
          </div>
          <button
            onClick={() => { setLoading(true); getEvalResults(20).then(setResults).finally(() => setLoading(false)); }}
            style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 12px", borderRadius: "var(--radius)", border: "0.5px solid var(--border)", background: "transparent", color: "var(--text-secondary)", fontSize: 12, cursor: "pointer" }}
          >
            <i className="ti ti-refresh" style={{ fontSize: 14 }} aria-hidden="true" /> Refresh
          </button>
        </div>

        <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: 24 }}>

          {loading && (
            <div style={{ textAlign: "center", padding: "60px 0", color: "var(--text-muted)", fontSize: 14 }}>
              Loading evaluation results...
            </div>
          )}

          {error && (
            <div style={{ padding: "12px 16px", borderRadius: "var(--radius)", background: "var(--bg-danger)", border: "0.5px solid var(--border-danger)", color: "var(--text-danger)", fontSize: 13 }}>
              {error} — Make sure the backend is running at localhost:8000
            </div>
          )}

          {!loading && !error && validResults.length === 0 && (
            <div style={{ textAlign: "center", padding: "60px 0", color: "var(--text-muted)" }}>
              <i className="ti ti-chart-bar" style={{ fontSize: 40, display: "block", marginBottom: 12 }} aria-hidden="true" />
              <p style={{ fontSize: 14, fontWeight: 500, color: "var(--text-secondary)", marginBottom: 6 }}>No evaluation results yet</p>
              <p style={{ fontSize: 13 }}>Ask some questions in the chat and results will appear here</p>
            </div>
          )}

          {!loading && validResults.length > 0 && (
            <>
              {/* Summary cards */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
                {summaryCards.map((card) => (
                  <div key={card.label} style={{ background: "var(--surface-1)", border: "0.5px solid var(--border)", borderRadius: "var(--radius)", padding: "16px", textAlign: "center" }}>
                    <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>{card.label}</p>
                    <p style={{ fontSize: 24, fontWeight: 700, color: card.value === null ? "var(--text-muted)" : card.good ? (card.value >= 0.8 ? "var(--text-success)" : card.value >= 0.6 ? "var(--text-warning)" : "var(--text-danger)") : (card.value <= 0.2 ? "var(--text-success)" : card.value <= 0.4 ? "var(--text-warning)" : "var(--text-danger)") }}>
                      {card.value === null ? "N/A" : card.label === "Hallucination Rate" ? `${(card.value * 100).toFixed(0)}%` : card.value.toFixed(2)}
                    </p>
                  </div>
                ))}
              </div>

              {/* Chart */}
              <div style={{ background: "var(--surface-1)", border: "0.5px solid var(--border)", borderRadius: "var(--radius)", padding: "20px" }}>
                <h2 style={{ fontSize: 14, fontWeight: 500, color: "var(--text-primary)", marginBottom: 20 }}>Average Metric Scores (0–1 scale)</h2>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={chartData} barSize={40}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="metric" tick={{ fontSize: 12, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
                    <YAxis domain={[0, 1]} tick={{ fontSize: 12, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: "var(--surface-2)", border: "0.5px solid var(--border)" }}
                      formatter={(value: any) => {
                        if (typeof value === 'number') return [value.toFixed(3), "Score"];
                        return [Number(value || 0).toFixed(3), "Score"];
                      }}
                    />
                    <Bar dataKey="score" fill="var(--fill-accent)" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Table */}
              <div style={{ background: "var(--surface-1)", border: "0.5px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
                <div style={{ padding: "16px 20px", borderBottom: "0.5px solid var(--border)" }}>
                  <h2 style={{ fontSize: 14, fontWeight: 500, color: "var(--text-primary)" }}>
                    Recent Evaluations
                  </h2>
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                    <thead>
                      <tr style={{ background: "var(--surface-0)" }}>
                        {["Question", "Faithfulness", "Relevancy", "Precision", "Recall", "Hallucination"].map((h) => (
                          <th key={h} style={{ padding: "10px 16px", textAlign: h === "Question" ? "left" : "center", color: "var(--text-muted)", fontWeight: 500, whiteSpace: "nowrap" }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {results.slice(0, 10).map((r, i) => (
                        <tr key={i} style={{ borderTop: "0.5px solid var(--border)" }}>
                          <td style={{ padding: "10px 16px", color: "var(--text-primary)", maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.question}</td>
                          <td style={{ padding: "10px 16px", textAlign: "center" }}><Score v={r.faithfulness} /></td>
                          <td style={{ padding: "10px 16px", textAlign: "center" }}><Score v={r.answer_relevancy} /></td>
                          <td style={{ padding: "10px 16px", textAlign: "center" }}><Score v={r.context_precision} /></td>
                          <td style={{ padding: "10px 16px", textAlign: "center" }}><Score v={r.context_recall} /></td>
                          <td style={{ padding: "10px 16px", textAlign: "center" }}>
                            {r.has_hallucination === null
                              ? <span style={{ color: "var(--text-muted)" }}>—</span>
                              : r.has_hallucination
                              ? <span style={{ color: "var(--text-danger)", fontWeight: 500 }}>Yes</span>
                              : <span style={{ color: "var(--text-success)", fontWeight: 500 }}>No</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Score({ v }: { v: number | null }) {
  if (v === null) return <span style={{ color: "var(--text-muted)" }}>—</span>;
  const color = v >= 0.8 ? "var(--text-success)" : v >= 0.6 ? "var(--text-warning)" : "var(--text-danger)";
  return <span style={{ color, fontWeight: 500 }}>{v.toFixed(2)}</span>;
}
