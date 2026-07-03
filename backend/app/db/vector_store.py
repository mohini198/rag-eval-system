import os
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from app.embeddings.embedder import embed_text, embed_batch

load_dotenv()

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "database": "rag_eval",
    "user": "postgres",
    "password": os.getenv("DB_PASSWORD", "postgres123"),
}


def get_connection():
    """Get a connection to the Docker PostgreSQL instance."""
    return psycopg2.connect(**DB_CONFIG)


def add_document(filename: str, file_type: str) -> int:
    """
    Insert a document record and return its ID.
    Every chunk we store will reference this document_id,
    which is how we track which document each chunk came from
    (needed for citations later).
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO documents (filename, file_type) VALUES (%s, %s) RETURNING id",
        (filename, file_type)
    )
    document_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return document_id


def store_chunks(document_id: int, chunks: list[str], strategy: str) -> None:
    """
    Embed each chunk and store it in the vector database.

    Each row stores:
    - The chunk text (for returning to the LLM as context)
    - The embedding vector (for similarity search)
    - The strategy used (for eval comparison later)
    - The document_id (for citations)
    """
    print(f"Embedding {len(chunks)} chunks using strategy '{strategy}'...")
    embeddings = embed_batch(chunks)

    conn = get_connection()
    cur = conn.cursor()

    rows = [
        (document_id, i, chunk, strategy, embedding)
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]

    execute_values(
        cur,
        """
        INSERT INTO chunks (document_id, chunk_index, content, chunk_strategy, embedding)
        VALUES %s
        """,
        rows,
        template="(%s, %s, %s, %s, %s::vector)"
    )

    conn.commit()
    cur.close()
    conn.close()
    print(f"Stored {len(chunks)} chunks successfully.")


def search_chunks(query: str, top_k: int = 5, strategy: str = None) -> list[dict]:
    """
    Embed the query and find the most similar chunks using
    cosine similarity via the HNSW index.

    Returns the top_k most relevant chunks with their content
    and similarity scores — these become the context for the LLM.
    """
    query_embedding = embed_text(query)

    conn = get_connection()
    cur = conn.cursor()

    if strategy:
        cur.execute(
            """
            SELECT c.id, c.content, c.chunk_strategy, d.filename,
                   1 - (c.embedding <=> %s::vector) AS similarity
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.chunk_strategy = %s
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
            """,
            (query_embedding, strategy, query_embedding, top_k)
        )
    else:
        cur.execute(
            """
            SELECT c.id, c.content, c.chunk_strategy, d.filename,
                   1 - (c.embedding <=> %s::vector) AS similarity
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
            """,
            (query_embedding, query_embedding, top_k)
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "id": row[0],
            "content": row[1],
            "strategy": row[2],
            "filename": row[3],
            "similarity": float(row[4]),
        }
        for row in rows
    ]