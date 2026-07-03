import json
import os
from dotenv import load_dotenv
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_groq import ChatGroq
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from datasets import Dataset

load_dotenv()


def get_ragas_llm():
    """
    RAGAS needs an LLM to compute metrics — it makes several LLM calls
    per evaluation (breaking answers into claims, checking each against
    context, generating synthetic questions for relevance scoring).
    We use Groq/Llama3.3 — same model as generation, keeps stack consistent
    and avoids needing a separate OpenAI key just for evaluation.
    """
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
    )
    return LangchainLLMWrapper(llm)


def get_ragas_embeddings():
    """
    RAGAS needs embeddings for answer relevancy metric — it embeds
    synthetic questions and compares them to the original question.
    We reuse our existing Gemini embeddings for consistency.
    """
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/embedding-001",
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )
    return LangchainEmbeddingsWrapper(embeddings)


def evaluate_single(
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str = None,
) -> dict:
    """
    Run RAGAS evaluation on a single query/answer/context triple.

    Metrics computed:
    - Faithfulness: are all answer claims supported by context?
    - Answer Relevancy: does the answer address the question?
    - Context Precision: of retrieved chunks, how many were relevant?
      (requires ground_truth)
    - Context Recall: did retrieval find all needed information?
      (requires ground_truth)

    Returns dict of metric scores (0-1 scale).
    """
    data = {
        "question": [question],
        "answer": [answer],
        "contexts": [contexts],
    }

    metrics = [faithfulness, answer_relevancy]

    if ground_truth:
        data["ground_truth"] = [ground_truth]
        metrics += [context_precision, context_recall]

    dataset = Dataset.from_dict(data)

    ragas_llm = get_ragas_llm()
    ragas_embeddings = get_ragas_embeddings()

    for metric in metrics:
        metric.llm = ragas_llm
        if hasattr(metric, "embeddings"):
            metric.embeddings = ragas_embeddings

    results = evaluate(dataset, metrics=metrics)
    scores = results.to_pandas().iloc[0].to_dict()

    return {
        "faithfulness": round(float(scores.get("faithfulness", 0)), 3),
        "answer_relevancy": round(float(scores.get("answer_relevancy", 0)), 3),
        "context_precision": round(float(scores.get("context_precision", 0)), 3) if ground_truth else None,
        "context_recall": round(float(scores.get("context_recall", 0)), 3) if ground_truth else None,
    }


def load_eval_set(path: str) -> list[dict]:
    """Load the ground truth eval set from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)