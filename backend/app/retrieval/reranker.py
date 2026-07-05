from sentence_transformers import CrossEncoder

# Load the cross-encoder model once at module level — not inside the function.
# Loading a model is expensive (reads weights from disk, initializes layers).
# If we loaded inside the function, every single rerank call would reload
# the entire model from scratch — very slow. Loading once at import time
# means the model stays in memory and rerank() calls are fast.
_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")


def rerank(query: str, chunks: list[dict], top_k: int = 3) -> list[dict]:
    """
    Re-score a shortlist of candidate chunks using a cross-encoder.

    Unlike bi-encoders (used in retrieval) which embed query and chunk
    separately, a cross-encoder reads [query] + [chunk] together as one
    input — this lets it directly attend to the interaction between
    question and passage, producing more accurate relevance scores.

    Tradeoff: can't pre-compute anything (query and chunk must be seen
    together), so only viable on a small shortlist (5-10 chunks), not
    the full chunk collection. That's why retrieval runs first to narrow
    down candidates before reranking.

    Model: cross-encoder/ms-marco-MiniLM-L-6-v2
    - Trained on MS MARCO (Microsoft's large-scale passage ranking dataset)
    - "MiniLM" = lightweight, runs on CPU in reasonable time
    - Outputs a raw relevance score (not 0-1, just higher = more relevant)
    """
    if not chunks:
        return []

    # build pairs: [[query, chunk1_content], [query, chunk2_content], ...]
    pairs = [[query, chunk["content"]] for chunk in chunks]

    # cross-encoder scores each pair — returns list of raw scores
    scores = _model.predict(pairs)

    # attach scores to chunks and sort descending
    scored_chunks = sorted(
        zip(chunks, scores),
        key=lambda x: x[1],
        reverse=True
    )

    return [
        {**chunk, "rerank_score": float(score)}
        for chunk, score in scored_chunks[:top_k]
    ]
