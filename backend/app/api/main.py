import os
import shutil
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from app.ingestion.parsers import parse_pdf, parse_docx, parse_txt
from app.chunking.strategies import chunk_fixed_size, chunk_recursive, chunk_semantic
from app.embeddings.embedder import embed_text
from app.db.vector_store import add_document, store_chunks, get_connection
from app.retrieval.hybrid import hybrid_search_reranked
from app.generation.generator import generate_answer
from app.evaluation.async_eval import run_eval_async

load_dotenv()

app = FastAPI(
    title="RAG Eval System",
    description="Document Q&A with hybrid retrieval and evaluation pipeline",
    version="1.0.0"
)

# CORS middleware — allows the Next.js frontend (running on a different
# port/domain) to make requests to this API. Without this, browsers
# block cross-origin requests by default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response models ──────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    document_id: int = None
    strategy: str = "fixed"


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
    chunks_used: int


# ── Endpoints ────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """
    Check system health — DB connection + basic availability.
    Used by Railway deployment to verify the service is running.
    """
    try:
        conn = get_connection()
        conn.close()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "ok",
        "database": db_status,
        "version": "1.0.0"
    }


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    Upload and process a document:
    1. Save uploaded file to a temp location
    2. Parse text based on file type
    3. Chunk using all 3 strategies
    4. Embed + store each strategy's chunks in pgvector
    5. Return document_id and chunk counts

    We store all 3 chunking strategies so the eval dashboard
    can compare retrieval quality across strategies later.
    """
    # validate file type
    allowed_types = {
        "application/pdf": ("pdf", parse_pdf),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("docx", parse_docx),
        "text/plain": ("txt", parse_txt),
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Supported: PDF, DOCX, TXT"
        )

    file_type, parser_fn = allowed_types[file.content_type]

    # save to temp file — parsers need a file path, not raw bytes
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=f".{file_type}"
    ) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        # parse
        text = parser_fn(tmp_path)
        if not text.strip():
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from document. File may be a scanned image."
            )

        # store document record
        doc_id = add_document(file.filename, file_type)

        # chunk with all 3 strategies + store
        chunk_counts = {}

        fixed_chunks = chunk_fixed_size(text, chunk_size=500, overlap=50)
        store_chunks(doc_id, fixed_chunks, strategy="fixed")
        chunk_counts["fixed"] = len(fixed_chunks)

        recursive_chunks = chunk_recursive(text, chunk_size=500, overlap=50)
        store_chunks(doc_id, recursive_chunks, strategy="recursive")
        chunk_counts["recursive"] = len(recursive_chunks)

        # semantic chunking is slow — only do it for smaller documents
        if len(text) < 10000:
            semantic_chunks = chunk_semantic(text, similarity_threshold=0.6)
            store_chunks(doc_id, semantic_chunks, strategy="semantic")
            chunk_counts["semantic"] = len(semantic_chunks)
        else:
            chunk_counts["semantic"] = "skipped (document too large for real-time semantic chunking)"

        return {
            "document_id": doc_id,
            "filename": file.filename,
            "file_type": file_type,
            "text_length": len(text),
            "chunk_counts": chunk_counts,
            "message": "Document processed successfully"
        }

    finally:
        # always clean up temp file
        os.unlink(tmp_path)


@app.post("/query", response_model=QueryResponse)
async def query_document(request: QueryRequest):
    """
    Answer a question using the RAG pipeline:
    1. Hybrid retrieval (BM25 + dense + RRF)
    2. Cross-encoder reranking
    3. LLM generation with citations
    4. Async evaluation (runs in background, doesn't block response)

    Returns answer immediately — evaluation runs silently in background
    and stores results to eval_results table.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # retrieve + rerank
    chunks = hybrid_search_reranked(
        request.question,
        top_k=3,
        strategy=request.strategy if request.strategy != "all" else None
    )

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail="No relevant documents found. Please upload a document first."
        )

    # generate answer
    result = generate_answer(request.question, chunks)

    # kick off async evaluation — doesn't block the response
    run_eval_async(
        question=request.question,
        answer=result["answer"],
        contexts=result["context"],
    )

    return QueryResponse(
        answer=result["answer"],
        sources=result["sources"],
        chunks_used=len(chunks)
    )


@app.get("/eval-results")
def get_eval_results(limit: int = 20):
    """
    Fetch recent evaluation results from PostgreSQL.
    Used by the frontend eval dashboard to display metric scores.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT question, answer, faithfulness, answer_relevancy,
               context_precision, context_recall,
               has_hallucination, hallucination_explanation,
               created_at
        FROM eval_results
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,)
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "question": row[0],
            "answer": row[1],
            "faithfulness": row[2],
            "answer_relevancy": row[3],
            "context_precision": row[4],
            "context_recall": row[5],
            "has_hallucination": row[6],
            "hallucination_explanation": row[7],
            "created_at": str(row[8]),
        }
        for row in rows
    ]


@app.get("/documents")
def list_documents():
    """List all uploaded documents."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, filename, file_type, uploaded_at FROM documents ORDER BY uploaded_at DESC"
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "id": row[0],
            "filename": row[1],
            "file_type": row[2],
            "uploaded_at": str(row[3]),
        }
        for row in rows
    ]