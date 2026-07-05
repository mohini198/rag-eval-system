
# Load the cross-encoder model once at module level — not inside the function.
# Loading a model is expensive (reads weights from disk, initializes layers).
# If we loaded inside the function, every single rerank call would reload
# the entire model from scratch — very slow. Loading once at import time
# means the model stays in memory and rerank() calls are fast.
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    return _model

def rerank(query: str, chunks: list[dict], top_k: int = 3) -> list[dict]:
    if not chunks:
        return []
    
    model = _get_model()
    pairs = [[query, chunk["content"]] for chunk in chunks]
    scores = model.predict(pairs)
    
    scored_chunks = sorted(
        zip(chunks, scores),
        key=lambda x: x[1],
        reverse=True
    )
    
    return [
        {**chunk, "rerank_score": float(score)}
        for chunk, score in scored_chunks[:top_k]
    ]

