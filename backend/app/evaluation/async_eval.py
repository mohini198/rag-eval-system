import threading
from app.evaluation.evaluator import evaluate_all
from app.db.vector_store import get_connection


def store_eval_results(question: str, answer: str, scores: dict) -> None:
    """Store evaluation scores in PostgreSQL."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO eval_results (
            question, answer, faithfulness, answer_relevancy,
            context_precision, context_recall,
            has_hallucination, hallucination_explanation
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            question,
            answer,
            scores.get("faithfulness", {}).get("score"),
            scores.get("answer_relevancy", {}).get("score"),
            scores.get("context_precision", {}).get("score") if scores.get("context_precision") else None,
            scores.get("context_recall", {}).get("score") if scores.get("context_recall") else None,
            scores.get("hallucination", {}).get("has_hallucination"),
            scores.get("hallucination", {}).get("explanation"),
        )
    )

    conn.commit()
    cur.close()
    conn.close()
    print(f"[eval] Scores stored for: '{question[:50]}...'")


def run_eval_async(
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str = None,
) -> None:
    """
    Run evaluation in a background thread — non-blocking.
    User gets answer immediately while eval runs silently
    in background and stores results to PostgreSQL.
    """
    def _eval_worker():
        try:
            print(f"[eval] Starting background evaluation...")
            scores = evaluate_all(
                question=question,
                answer=answer,
                contexts=contexts,
                ground_truth=ground_truth,
            )
            store_eval_results(question, answer, scores)
            print(f"[eval] Background evaluation complete.")
        except Exception as e:
            print(f"[eval] Evaluation error: {e}")

    thread = threading.Thread(target=_eval_worker, daemon=True)
    thread.start()
    print(f"[eval] Evaluation started in background (thread: {thread.name})")