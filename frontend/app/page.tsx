"use client";

import { useState, useRef, useEffect } from "react";
import { uploadDocument, queryDocument, UploadResponse, QueryResponse } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: string[];
  chunks?: number;
}

interface Conversation {
  id: number;
  document: UploadResponse;
  messages: Message[];
  createdAt: string;
}

const STORAGE_KEY = "rag_conversations_v2";

export default function Home() {
  const [conversations, setConversations] = useState<Record<number, Conversation>>({});
  const [activeId, setActiveId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Load from localStorage on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        setConversations(parsed.conversations || {});
        setActiveId(parsed.activeId || null);
      }
    } catch {}
    setHydrated(true);
  }, []);

  // Save to localStorage whenever conversations or activeId changes
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ conversations, activeId }));
    } catch {}
  }, [conversations, activeId, hydrated]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversations, activeId, loading]);

  const activeConversation = activeId !== null ? conversations[activeId] : null;
  const activeMessages = activeConversation?.messages || [];

  const addMessage = (msg: Message) => {
    if (activeId === null) return;
    setConversations((prev) => ({
      ...prev,
      [activeId]: {
        ...prev[activeId],
        messages: [...prev[activeId].messages, msg],
      },
    }));
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadProgress("Reading file...");

    const steps = [
      { msg: "Parsing document...", delay: 800 },
      { msg: "Chunking text...", delay: 1800 },
      { msg: "Generating embeddings...", delay: 3000 },
      { msg: "Storing in vector database...", delay: 5000 },
    ];

    const timers: ReturnType<typeof setTimeout>[] = [];
    steps.forEach(({ msg, delay }) => {
      timers.push(setTimeout(() => setUploadProgress(msg), delay));
    });

    try {
      const result = await uploadDocument(file);
      timers.forEach(clearTimeout);

      const newId = result.document_id;
      const welcomeMsg: Message = {
        role: "assistant",
        content: `I've processed **${result.filename}** successfully.\n\n• ${result.text_length.toLocaleString()} characters extracted\n• ${result.chunk_counts["fixed"]} chunks (fixed strategy)\n• ${result.chunk_counts["recursive"]} chunks (recursive strategy)\n\nYou can now ask me anything about this document.`,
      };

      // Create new conversation — fresh messages, don't touch existing ones
      setConversations((prev) => ({
        ...prev,
        [newId]: {
          id: newId,
          document: result,
          messages: [welcomeMsg],
          createdAt: new Date().toISOString(),
        },
      }));

      setActiveId(newId);
    } catch (err: unknown) {
      timers.forEach(clearTimeout);
      if (activeId !== null) {
        addMessage({ role: "assistant", content: `Upload failed: ${err instanceof Error ? err.message : "Unknown error"}` });
      }
    } finally {
      setUploading(false);
      setUploadProgress("");
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleSend = async () => {
    if (!input.trim() || loading || activeId === null) return;
    const question = input.trim();
    setInput("");
    addMessage({ role: "user", content: question });
    setLoading(true);
    try {
      const result: QueryResponse = await queryDocument(question);
      addMessage({ role: "assistant", content: result.answer, sources: result.sources, chunks: result.chunks_used });
    } catch {
      addMessage({ role: "assistant", content: "I couldn't answer that. Make sure the backend is running at localhost:8000." });
    } finally {
      setLoading(false);
    }
  };

  const deleteConversation = (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setConversations((prev) => {
      const updated = { ...prev };
      delete updated[id];
      return updated;
    });
    if (activeId === id) {
      const remaining = Object.keys(conversations).filter((k) => Number(k) !== id);
      setActiveId(remaining.length > 0 ? Number(remaining[0]) : null);
    }
  };

  const sortedConversations = Object.values(conversations).sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );

  if (!hydrated) return null;

  return (
    <div style={{ display: "flex", height: "100vh", background: "#0a0a0a", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", color: "#e5e5e5" }}>

      {/* Sidebar */}
      <div style={{ width: 248, background: "#111", borderRight: "1px solid #1f1f1f", display: "flex", flexDirection: "column", padding: "16px 12px", flexShrink: 0 }}>

        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 8px", marginBottom: 20 }}>
          <div style={{ width: 28, height: 28, background: "linear-gradient(135deg, #6366f1, #8b5cf6)", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <i className="ti ti-brain" style={{ color: "white", fontSize: 15 }} />
          </div>
          <span style={{ fontSize: 14, fontWeight: 600, color: "#f5f5f5" }}>Veridoc</span>
        </div>

        {/* Nav */}
        <a href="/" style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 8, color: "#f5f5f5", background: "#1f1f1f", fontSize: 13, textDecoration: "none", marginBottom: 2 }}>
          <i className="ti ti-message-2" style={{ fontSize: 15 }} /> Chat
        </a>
        <a href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 8, color: "#888", fontSize: 13, textDecoration: "none", marginBottom: 16 }}>
          <i className="ti ti-chart-bar" style={{ fontSize: 15 }} /> Dashboard
        </a>

        {/* Upload button — prominent at top */}
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, padding: "9px 12px", borderRadius: 8, border: "1px solid #2f2f2f", color: uploading ? "#555" : "#e5e5e5", fontSize: 12, cursor: uploading ? "not-allowed" : "pointer", background: uploading ? "transparent" : "#1a1a1a", width: "100%", marginBottom: 16, fontWeight: 500 }}
        >
          <i className="ti ti-plus" style={{ fontSize: 14 }} />
          {uploading ? uploadProgress || "Processing..." : "New document"}
        </button>
        <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" onChange={handleUpload} style={{ display: "none" }} />

        {/* Upload progress indicator */}
        {uploading && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: 8, background: "#1a1a2e", border: "1px solid #2d2d5c", marginBottom: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#6366f1", flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: "#a5b4fc" }}>{uploadProgress || "Uploading..."}</span>
          </div>
        )}

        {/* Conversations label */}
        <div style={{ fontSize: 10, color: "#555", padding: "0 8px 8px", letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 500 }}>
          Conversations ({sortedConversations.length})
        </div>

        {/* Conversation list */}
        <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
          {sortedConversations.length === 0 && (
            <div style={{ fontSize: 12, color: "#555", padding: "4px 10px" }}>
              No conversations yet
            </div>
          )}

          {sortedConversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => setActiveId(conv.id)}
              style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: 8, cursor: "pointer", background: activeId === conv.id ? "#1f1f1f" : "transparent", border: activeId === conv.id ? "1px solid #2f2f2f" : "1px solid transparent", group: "true" } as React.CSSProperties}
            >
              <i className="ti ti-file-type-pdf" style={{ fontSize: 14, color: "#f87171", flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, color: activeId === conv.id ? "#e5e5e5" : "#888", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {conv.document.filename}
                </div>
                <div style={{ fontSize: 10, color: "#555", marginTop: 1 }}>
                  {conv.messages.length - 1} messages
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
                {activeId === conv.id && (
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e" }} />
                )}
                <button
                  onClick={(e) => deleteConversation(conv.id, e)}
                  style={{ width: 20, height: 20, borderRadius: 4, border: "none", background: "transparent", color: "#555", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, opacity: activeId === conv.id ? 1 : 0 }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = "#f87171")}
                  onMouseLeave={(e) => (e.currentTarget.style.color = "#555")}
                >
                  <i className="ti ti-trash" style={{ fontSize: 12 }} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>

        {/* Topbar */}
        <div style={{ padding: "12px 24px", borderBottom: "1px solid #1f1f1f", display: "flex", alignItems: "center", justifyContent: "space-between", background: "#0a0a0a" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 500, color: "#e5e5e5" }}>
              {activeConversation ? activeConversation.document.filename : "Veridoc"}
            </span>
            {activeConversation && (
              <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 99, background: "#14532d", color: "#86efac", border: "1px solid #166534" }}>
                {activeConversation.document.chunk_counts["fixed"]} chunks
              </span>
            )}
          </div>
          <a href="/dashboard" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#6366f1", textDecoration: "none" }}>
            <i className="ti ti-chart-bar" style={{ fontSize: 14 }} />
            Eval dashboard
          </a>
        </div>

        {/* Chat area */}
        <div style={{ flex: 1, overflowY: "auto", padding: "32px 24px", display: "flex", flexDirection: "column", gap: 24 }}>

          {/* Empty state */}
          {!activeConversation && (
            <div style={{ margin: "auto", textAlign: "center", maxWidth: 420 }}>
              <div style={{ width: 56, height: 56, background: "#111", border: "1px solid #1f1f1f", borderRadius: 16, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px" }}>
                <i className="ti ti-file-search" style={{ fontSize: 28, color: "#555" }} />
              </div>
              <p style={{ fontSize: 17, fontWeight: 500, color: "#e5e5e5", marginBottom: 10 }}>
                Upload a document to get started
              </p>
              <p style={{ fontSize: 13, color: "#666", lineHeight: 1.7, marginBottom: 20 }}>
                Each document gets its own conversation. Switch between documents using the sidebar — your chat history is saved automatically.
              </p>
              <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                {["PDF", "DOCX", "TXT"].map((t) => (
                  <span key={t} style={{ fontSize: 11, padding: "4px 12px", borderRadius: 6, background: "#111", border: "1px solid #1f1f1f", color: "#555" }}>{t}</span>
                ))}
              </div>
              <button
                onClick={() => fileRef.current?.click()}
                style={{ marginTop: 24, padding: "10px 20px", borderRadius: 8, background: "linear-gradient(135deg, #6366f1, #8b5cf6)", border: "none", color: "white", fontSize: 13, fontWeight: 500, cursor: "pointer", display: "flex", alignItems: "center", gap: 8, margin: "24px auto 0" }}
              >
                <i className="ti ti-upload" style={{ fontSize: 15 }} />
                Upload your first document
              </button>
            </div>
          )}

          {/* Messages */}
          {activeMessages.map((msg, i) => (
            <div key={i} style={{ display: "flex", gap: 14, flexDirection: msg.role === "user" ? "row-reverse" : "row", alignItems: "flex-start" }}>
              <div style={{ width: 28, height: 28, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontSize: 11, fontWeight: 600, background: msg.role === "user" ? "#1f1f1f" : "linear-gradient(135deg, #6366f1, #8b5cf6)", color: msg.role === "user" ? "#888" : "white", border: msg.role === "user" ? "1px solid #2f2f2f" : "none" }}>
                {msg.role === "user" ? "Y" : "AI"}
              </div>
              <div style={{ maxWidth: "72%", display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ padding: "12px 16px", borderRadius: msg.role === "user" ? "18px 4px 18px 18px" : "4px 18px 18px 18px", fontSize: 13, lineHeight: 1.75, background: msg.role === "user" ? "#1f1f1f" : "#161616", color: "#e5e5e5", border: `1px solid ${msg.role === "user" ? "#2f2f2f" : "#1f1f1f"}`, whiteSpace: "pre-wrap" }}>
                  {msg.content}
                </div>
                {msg.sources && msg.sources.length > 0 && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {msg.sources.map((src, j) => (
                      <span key={j} style={{ display: "flex", alignItems: "center", gap: 5, padding: "3px 10px", borderRadius: 99, border: "1px solid #1f1f1f", fontSize: 11, color: "#666", background: "#0f0f0f" }}>
                        <i className="ti ti-file" style={{ fontSize: 11, color: "#6366f1" }} />
                        {src} · {msg.chunks} chunks
                      </span>
                    ))}
                    <span style={{ display: "flex", alignItems: "center", gap: 5, padding: "3px 10px", borderRadius: 99, fontSize: 11, color: "#22c55e", background: "#0f1f0f", border: "1px solid #14532d" }}>
                      <i className="ti ti-shield-check" style={{ fontSize: 11 }} />
                      Eval running
                    </span>
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {loading && (
            <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
              <div style={{ width: 28, height: 28, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", background: "linear-gradient(135deg, #6366f1, #8b5cf6)" }}>
                <i className="ti ti-brain" style={{ color: "white", fontSize: 13 }} />
              </div>
              <div style={{ padding: "12px 16px", borderRadius: "4px 18px 18px 18px", background: "#161616", border: "1px solid #1f1f1f", display: "flex", gap: 6, alignItems: "center" }}>
                {[0, 0.2, 0.4].map((delay, i) => (
                  <span key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: "#6366f1", display: "inline-block", animation: `bounce 1s infinite ${delay}s` }} />
                ))}
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={{ padding: "16px 24px", borderTop: "1px solid #1f1f1f", background: "#0a0a0a" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", background: "#111", border: "1px solid #2f2f2f", borderRadius: 12, padding: "10px 14px" }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
              placeholder={!activeConversation ? "Upload a document first..." : "Ask anything about your document..."}
              disabled={loading || !activeConversation}
              style={{ flex: 1, border: "none", background: "transparent", fontSize: 13, color: "#e5e5e5", outline: "none" }}
            />
            <button
              onClick={handleSend}
              disabled={loading || !input.trim() || !activeConversation}
              style={{ width: 32, height: 32, borderRadius: 8, background: input.trim() && !loading && activeConversation ? "linear-gradient(135deg, #6366f1, #8b5cf6)" : "#1f1f1f", border: "none", display: "flex", alignItems: "center", justifyContent: "center", cursor: input.trim() && !loading && activeConversation ? "pointer" : "not-allowed", flexShrink: 0 }}
            >
              <i className="ti ti-send" style={{ color: input.trim() && !loading && activeConversation ? "white" : "#555", fontSize: 15 }} />
            </button>
          </div>
          <p style={{ fontSize: 11, color: "#333", textAlign: "center", marginTop: 8 }}>
            Hybrid retrieval · BM25 + Dense + RRF · Cross-encoder reranking
          </p>
        </div>
      </div>

      <style>{`
        @keyframes bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #2f2f2f; border-radius: 99px; }
      `}</style>
    </div>
  );
}
