from rank_bm25 import BM25Okapi
from app.db.vector_store import search_chunks, get_connection
from app.embeddings.embedder import embed_text
from app.retrieval.reranker import rerank

def get_all_chunks(strategy: str = None) -> list[dict]:
    """
    Load all chunks from the database into memory for BM25 indexing.
    BM25 has no pre-computed index stored in the DB — it needs raw text
    to build its term frequency index at search time.
    """
    conn = get_connection()
    cur = conn.cursor()

    if strategy:
        cur.execute(
            """
            SELECT c.id, c.content, c.chunk_strategy, d.filename
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.chunk_strategy = %s
            """,
            (strategy,)
        )
    else:
        cur.execute(
            """
            SELECT c.id, c.content, c.chunk_strategy, d.filename
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            """
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
        }
        for row in rows
    ]


def bm25_search(query: str, top_k: int = 10, strategy: str = None) -> list[dict]:
    """
    Keyword search using BM25 over all stored chunks.

    Loads chunks from DB into memory, tokenizes them, builds a BM25
    index, then scores the query against every chunk. Returns top_k
    results with their BM25 scores.

    Weakness: misses semantic meaning — "car" won't match "automobile"
    unless both words appear in the same chunk.
    Strength: exact rare terms (function names, codes, proper nouns)
    score high even if the embedding model has never seen them.
    """
    all_chunks = get_all_chunks(strategy)

    if not all_chunks:
        return []

    # tokenize: lowercase + split on whitespace
    # simple but sufficient — a production system might use a proper
    # tokenizer with stemming/lemmatization
    tokenized_chunks = [chunk["content"].lower().split() for chunk in all_chunks]
    tokenized_query = query.lower().split()

    bm25 = BM25Okapi(tokenized_chunks)
    scores = bm25.get_scores(tokenized_query)

    # pair each chunk with its score and sort descending
    scored = sorted(
        zip(all_chunks, scores),
        key=lambda x: x[1],
        reverse=True
    )

    return [
        {**chunk, "bm25_score": float(score)}
        for chunk, score in scored[:top_k]
    ]


def reciprocal_rank_fusion(
    dense_results: list[dict],
    bm25_results: list[dict],
    k: int = 60,
    top_k: int = 5
) -> list[dict]:
    """
    Merge dense and BM25 result lists using Reciprocal Rank Fusion.

    RRF ignores raw scores (which are on incomparable scales) and
    uses only rank position. A chunk appearing in both lists gets
    contributions from both, naturally surfacing results that multiple
    retrieval methods independently agree on.

    Formula: RRF_score = 1/(k + rank_dense) + 1/(k + rank_bm25)
    k=60 is the standard constant that prevents rank-1 results from
    having disproportionate influence over the merged ranking.
    """
    rrf_scores = {}

    # score from dense results
    for rank, result in enumerate(dense_results, start=1):
        chunk_id = result["id"]
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (k + rank)

    # score from BM25 results
    for rank, result in enumerate(bm25_results, start=1):
        chunk_id = result["id"]
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (k + rank)

    # build a lookup of all results by chunk_id
    all_results = {r["id"]: r for r in dense_results + bm25_results}

    # sort by RRF score descending
    sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)

    return [
        {**all_results[chunk_id], "rrf_score": rrf_scores[chunk_id]}
        for chunk_id in sorted_ids[:top_k]
    ]


def hybrid_search(query: str, top_k: int = 5, strategy: str = None) -> list[dict]:
    """
    Full hybrid retrieval pipeline:
    1. Dense search (top 10) — semantic similarity via embeddings
    2. BM25 search (top 10) — keyword matching
    3. RRF fusion → merged top_k results

    This is the main retrieval function the rest of the system uses.
    """
    print(f"Running hybrid search for: '{query}'")

    dense_results = search_chunks(query, top_k=10, strategy=strategy)
    print(f"Dense results: {len(dense_results)}")

    bm25_results = bm25_search(query, top_k=10, strategy=strategy)
    print(f"BM25 results: {len(bm25_results)}")

    fused_results = reciprocal_rank_fusion(dense_results, bm25_results, top_k=top_k)
    print(f"Fused results: {len(fused_results)}")

    return fused_results

def hybrid_search_reranked(query: str, top_k: int = 3, strategy: str = None) -> list[dict]:
    """
    Full retrieval pipeline with reranking:
    1. Dense search (top 10)
    2. BM25 search (top 10)
    3. RRF fusion → top 5
    4. Cross-encoder reranking → top 3

    This is the production-quality retrieval function used for
    answer generation — reranking adds precision on the final
    shortlist that bi-encoder retrieval can't provide.
    """
    # Step 1-3: hybrid retrieval
    candidates = hybrid_search(query, top_k=5, strategy=strategy)
    print(f"Candidates before reranking: {len(candidates)}")

    # Step 4: rerank the shortlist
    reranked = rerank(query, candidates, top_k=top_k)
    print(f"Results after reranking: {len(reranked)}")

    return reranked
