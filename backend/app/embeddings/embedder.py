import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768  # reduced from 3072 to fit pgvector's HNSW 2000-dim limit


def embed_text(text: str) -> list[float]:
    """
    Convert text into a 768-dimensional embedding vector.

    We request 768 dimensions explicitly (Gemini supports output_dimensionality
    parameter) rather than the default 3072, because pgvector's HNSW index has
    a hard 2000-dimension ceiling. 768 is standard for many production RAG
    systems and sufficient for high-quality semantic retrieval.
    """
    result = _client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config={"output_dimensionality": EMBEDDING_DIMENSIONS},
    )
    return result.embeddings[0].values


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed multiple texts, one at a time with a small delay to avoid
    hitting API rate limits during bulk document ingestion.

    In production this would use a proper batch API or async calls,
    but sequential with rate limiting is sufficient for a portfolio project
    where documents are ingested one at a time, not in bulk pipelines.
    """
    import time
    embeddings = []
    for i, text in enumerate(texts):
        embedding = embed_text(text)
        embeddings.append(embedding)
        if i % 10 == 9:  # small pause every 10 calls
            time.sleep(1)
    return embeddings
