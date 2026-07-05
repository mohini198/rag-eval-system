# Veridoc

**Verified answers from your documents.**

Veridoc is a production-grade RAG (Retrieval-Augmented Generation) system that lets you upload documents and ask questions — getting grounded, cited answers backed by a custom evaluation pipeline that measures hallucination in real time.

> Built as a portfolio project to demonstrate that RAG systems can be both **accurate** and **measurable**. Anyone can wire up a vector database and call it RAG. Veridoc proves its answers don't hallucinate — with actual numbers.

---

## Live Demo

- **Frontend:** [https://rag-eval-system-lovat.vercel.app](https://rag-eval-system-lovat.vercel.app)
- **API Docs:** [https://mohini198-rag-backend.hf.space/docs](https://mohini198-rag-backend.hf.space/docs)

---

## Evaluation Results

Tested against a 16-question ground truth eval set manually created from real documents:

| Metric | Score | What it measures |
|---|---|---|
| **Faithfulness** | TBD | Are all answer claims supported by retrieved context? |
| **Answer Relevancy** | TBD | Does the answer address the question asked? |
| **Context Precision** | TBD | Of retrieved chunks, how many were actually relevant? |
| **Context Recall** | TBD | Did retrieval find all information needed? |
| **Hallucination Rate** | TBD | % of answers containing at least one unsupported claim |

> Evaluation runs asynchronously after every query — scores are stored in PostgreSQL and visible in the live dashboard.

---

## Architecture

```
Document Upload
      │
      ├── Parsing (PDF / DOCX / TXT)
      │     ├── pypdf (text-layer PDFs)
      │     ├── python-docx (Word documents)
      │     └── charset-normalizer (encoding detection for TXT)
      │
      ├── Chunking Pipeline
      │     ├── Strategy A: Fixed-size (500 tokens, 50 overlap)
      │     ├── Strategy B: Recursive character splitting
      │     └── Strategy C: Semantic chunking (embedding-based breaks)
      │
      ├── Embedding (Google Gemini text-embedding-001, 768 dimensions)
      └── Vector Store (pgvector + HNSW index)

Query Flow
      │
      ├── Hybrid Retrieval
      │     ├── Dense: vector similarity search (top 10)
      │     ├── Sparse: BM25 keyword search (top 10)
      │     └── Reciprocal Rank Fusion → merged top 5
      │
      ├── Reranking (cross-encoder/ms-marco-MiniLM-L-6-v2) → top 3
      │
      ├── LLM Generation (Groq Llama 3.3 70B) with citations
      │
      └── Evaluation Pipeline (async, non-blocking)
            ├── Faithfulness Score
            ├── Answer Relevancy
            ├── Context Precision
            ├── Context Recall
            └── LLM-as-judge Hallucination Check
```

---

## Why Hybrid Retrieval?

Neither dense vector search nor BM25 alone handles all query types well:

| Query type | Dense search | BM25 |
|---|---|---|
| Semantic/conceptual | ✅ Wins | ❌ Misses |
| Exact rare terms, names, codes | ❌ Misses | ✅ Wins |

**Tested on real data:** searching for author name "Conor Lastowka" — BM25 scored the correct chunk at **5.804** vs. **0.000** for irrelevant chunks (decisive). Dense search scored **0.618** vs **0.564** (much smaller gap). Hybrid retrieval with RRF combines both, consistently outperforming either alone.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Parsing** | pypdf, python-docx, charset-normalizer | Format-specific parsing; encoding detection instead of assuming UTF-8 |
| **Chunking** | tiktoken, LangChain, custom semantic | 3 strategies compared in eval dashboard |
| **Embeddings** | Google Gemini text-embedding-001 (768d) | Free tier; 768d fits pgvector HNSW 2000-dim limit |
| **Vector DB** | pgvector (PostgreSQL) | One less service vs Pinecone; HNSW index for sub-linear search |
| **Retrieval** | BM25Okapi + pgvector + RRF | Hybrid covers semantic + exact-match queries |
| **Reranking** | cross-encoder/ms-marco-MiniLM-L-6-v2 | Local cross-encoder; no API key, no rate limits in eval pipeline |
| **Generation** | Groq Llama 3.3 70B | Free tier, fast inference; temperature=0.1 for grounded answers |
| **Evaluation** | Custom LLM-as-judge (5 metrics) | Built from scratch after RAGAS had breaking dependency conflicts |
| **Backend** | FastAPI + PostgreSQL + psycopg2 | Async support; automatic /docs; production-standard Python API |
| **Frontend** | Next.js 14 + Tailwind + Recharts | Multi-conversation UI with localStorage persistence |
| **Deployment** | Railway (backend) + Vercel (frontend) | Standard free-tier deployment stack |

---

## Key Technical Decisions

Full reasoning for every architectural decision is documented in [`DECISIONS.md`](./DECISIONS.md).

Highlights:
- **pgvector over Pinecone** — one less external service, same SQL connection already used for metadata, HNSW index gives logarithmic search time
- **768 embedding dimensions** — pgvector's HNSW index has a hard 2000-dimension ceiling; Gemini's default 3072 exceeded it
- **Local cross-encoder over Cohere Rerank API** — no rate limits during eval pipeline runs (which make 7-9 LLM calls per query)
- **Custom eval metrics over RAGAS** — RAGAS had breaking `langchain_community` dependency conflicts; rebuilding from scratch produced more understandable, debuggable code
- **RRF over score-based merging** — BM25 and cosine similarity scores are on incomparable scales; rank-based fusion is mathematically correct

---

## Project Structure

```
veridoc/
├── backend/
│   ├── app/
│   │   ├── ingestion/      # PDF/DOCX/TXT parsers
│   │   ├── chunking/       # 3 chunking strategies
│   │   ├── embeddings/     # Gemini embedding client
│   │   ├── retrieval/      # BM25, dense search, RRF, reranker
│   │   ├── generation/     # Groq LLM + prompt engineering
│   │   ├── evaluation/     # 5 custom eval metrics + async pipeline
│   │   ├── db/             # pgvector store + PostgreSQL connection
│   │   └── api/            # FastAPI endpoints
│   └── init.sql            # Database schema (auto-runs on Docker start)
├── frontend/
│   ├── app/
│   │   ├── page.tsx        # Multi-conversation chat UI
│   │   └── dashboard/      # Eval metrics dashboard (Recharts)
│   └── lib/
│       └── api.ts          # Typed API client
├── data/
│   └── eval_set.json       # 16-question ground truth eval set
└── DECISIONS.md            # Full architectural decision log
```

---

## Running Locally

### Prerequisites
- Python 3.10+
- Node.js 18+
- Docker Desktop

### 1. Clone and set up

```bash
git clone https://github.com/mohini198/rag-eval-system.git
cd rag-eval-system
```

### 2. Start the database

```bash
docker run -d \
  --name rag-postgres \
  -e POSTGRES_PASSWORD=postgres123 \
  -e POSTGRES_DB=rag_eval \
  -p 5433:5432 \
  -v pgdata:/var/lib/postgresql/data \
  -v $(pwd)/backend/init.sql:/docker-entrypoint-initdb.d/init.sql \
  pgvector/pgvector:pg16
```

### 3. Set up backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env`:
```
GOOGLE_API_KEY=your_google_api_key
GROQ_API_KEY=your_groq_api_key
DB_PASSWORD=postgres123
DB_PORT=5433
```

```bash
uvicorn app.api.main:app --reload --port 8000
```

### 4. Set up frontend

```bash
cd frontend
npm install
npm run dev
```

### 5. Open in browser

- Chat: http://localhost:3000
- Eval Dashboard: http://localhost:3000/dashboard
- API Docs: http://localhost:8000/docs

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | System health check (DB + API status) |
| `POST` | `/upload` | Upload PDF/DOCX/TXT → parse, chunk, embed, store |
| `POST` | `/query` | Ask a question → hybrid retrieval + reranking + generation |
| `GET` | `/eval-results` | Fetch evaluation scores from PostgreSQL |
| `GET` | `/documents` | List all uploaded documents |

---

## Known Limitations

- **Scanned PDFs:** text extraction requires a real text layer. Scanned image PDFs return empty text. OCR support via Tesseract is planned.
- **Groq free tier:** 100,000 tokens/day limit. The eval pipeline makes 7-9 LLM calls per query — on high traffic, eval calls may hit rate limits (generation still works; eval silently skips).
- **In-memory BM25:** BM25 index is rebuilt from the database on every query. Sufficient at portfolio scale; production would use Elasticsearch for a persistent BM25 index.
- **Semantic chunking on large docs:** skipped for documents >10,000 characters (one API call per sentence makes it too slow for synchronous upload requests).

---

## What I Learned

This project taught me that **evaluation is the hardest part of RAG, not retrieval.** Building hybrid retrieval with RRF and cross-encoder reranking is well-documented. Measuring whether the system actually works — with metrics that catch subtle hallucinations, not just obvious ones — required understanding the difference between faithfulness vs. answer relevancy, context precision vs. context recall, and why a system can score 0.929 faithfulness while still hallucinating in 28% of individual queries.

The DECISIONS.md file documents every real tradeoff made during the build — unit mismatches between chunking strategies, the pgvector HNSW dimension limit, why RAGAS was replaced with custom metrics, why RRF beats score-based merging. These aren't things you learn from tutorials.

---

*Built by Mohini chauhan | [GitHub](https://github.com/mohini198)*
