const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface QueryResponse {
  answer: string;
  sources: string[];
  chunks_used: number;
}

export interface UploadResponse {
  document_id: number;
  filename: string;
  file_type: string;
  text_length: number;
  chunk_counts: Record<string, number | string>;
  message: string;
}

export interface EvalResult {
  question: string;
  answer: string;
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  has_hallucination: boolean | null;
  hallucination_explanation: string | null;
  created_at: string;
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Upload failed");
  }

  return response.json();
}

export async function queryDocument(
  question: string,
  strategy: string = "fixed"
): Promise<QueryResponse> {
  const response = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, strategy }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Query failed");
  }

  return response.json();
}

export async function getEvalResults(limit: number = 20): Promise<EvalResult[]> {
  const response = await fetch(`${API_BASE}/eval-results?limit=${limit}`);

  if (!response.ok) {
    throw new Error("Failed to fetch eval results");
  }

  return response.json();
}