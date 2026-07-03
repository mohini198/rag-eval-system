CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    uploaded_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    chunk_strategy TEXT NOT NULL,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx 
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS eval_results (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    faithfulness FLOAT,
    answer_relevancy FLOAT,
    context_precision FLOAT,
    context_recall FLOAT,
    has_hallucination BOOLEAN,
    hallucination_explanation TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);