import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.1-8b-instant"


def _llm_call(prompt: str) -> str:
    """Single LLM call — all metrics use this."""
    response = _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=1000,
    )
    return response.choices[0].message.content.strip()


def evaluate_faithfulness(answer: str, contexts: list[str]) -> dict:
    """
    Faithfulness (0-1): what fraction of claims in the answer
    are supported by the retrieved context?

    Process:
    1. Extract individual claims from the answer
    2. For each claim, check if context supports it
    3. Score = supported_claims / total_claims

    A score < 1.0 means the answer contains hallucinations —
    claims not grounded in the retrieved context.
    """
    context_str = "\n\n".join(contexts)

    # Step 1: extract claims
    claims_prompt = f"""Break this answer into individual factual claims.
Return ONLY a JSON array of strings, each string being one claim.
No preamble, no explanation, just the JSON array.

Answer: {answer}

Example output format:
["claim 1", "claim 2", "claim 3"]"""

    claims_response = _llm_call(claims_prompt)

    try:
        # strip markdown code fences if present
        clean = claims_response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        claims = json.loads(clean.strip())
    except Exception:
        return {"score": 0.0, "supported": 0, "total": 0, "error": "Could not parse claims"}

    if not claims:
        return {"score": 1.0, "supported": 0, "total": 0}

    # Step 2: check each claim against context
    supported = 0
    claim_results = []

    for claim in claims:
        check_prompt = f"""Given this context, is the following claim supported?
Answer with ONLY "yes" or "no".

Context:
{context_str}

Claim: {claim}

Answer (yes/no):"""

        result = _llm_call(check_prompt).lower().strip()
        is_supported = result.startswith("yes")
        if is_supported:
            supported += 1
        claim_results.append({"claim": claim, "supported": is_supported})

    score = supported / len(claims)

    return {
        "score": round(score, 3),
        "supported": supported,
        "total": len(claims),
        "claims": claim_results
    }


def evaluate_answer_relevancy(question: str, answer: str) -> dict:
    """
    Answer Relevancy (0-1): does the answer actually address
    the question asked?

    Process:
    1. Generate 3 synthetic questions from the answer
       (what question would this answer be responding to?)
    2. Ask LLM to score similarity between each synthetic
       question and the original question (0-1)
    3. Average the similarity scores

    Low score = answer talks about something other than
    what was asked, even if factually correct.
    """
    prompt = f"""Given this answer, generate 3 questions that this answer would be a good response to.
Then score how similar each generated question is to the original question on a scale of 0-1.

Original question: {question}
Answer: {answer}

Return ONLY a JSON object in this exact format:
{{
  "generated_questions": ["q1", "q2", "q3"],
  "similarity_scores": [0.9, 0.8, 0.7]
}}

No preamble, no explanation, just the JSON."""

    response = _llm_call(prompt)

    try:
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean.strip())
        scores = data.get("similarity_scores", [])
        avg_score = sum(scores) / len(scores) if scores else 0.0
    except Exception:
        return {"score": 0.0, "error": "Could not parse response"}

    return {
        "score": round(avg_score, 3),
        "generated_questions": data.get("generated_questions", []),
        "similarity_scores": scores
    }


def evaluate_context_precision(
    question: str,
    contexts: list[str],
    ground_truth: str
) -> dict:
    """
    Context Precision (0-1): of the chunks retrieved,
    how many were actually relevant to answering the question?

    High precision = retrieval is returning useful chunks.
    Low precision = retrieval is pulling in junk/noise.

    Requires ground_truth to judge relevance.
    """
    relevant_count = 0
    chunk_results = []

    for i, ctx in enumerate(contexts):
        prompt = f"""Is this context chunk relevant to answering the question?
Consider the ground truth answer as reference for what information is needed.

Question: {question}
Ground Truth Answer: {ground_truth}
Context Chunk: {ctx}

Answer with ONLY "yes" or "no":"""

        result = _llm_call(prompt).lower().strip()
        is_relevant = result.startswith("yes")
        if is_relevant:
            relevant_count += 1
        chunk_results.append({"chunk_index": i, "relevant": is_relevant})

    score = relevant_count / len(contexts) if contexts else 0.0

    return {
        "score": round(score, 3),
        "relevant_chunks": relevant_count,
        "total_chunks": len(contexts),
        "chunk_results": chunk_results
    }


def evaluate_context_recall(
    contexts: list[str],
    ground_truth: str
) -> dict:
    """
    Context Recall (0-1): did retrieval find all the information
    needed to produce the ground truth answer?

    Process:
    1. Break ground truth into individual statements
    2. For each statement, check if it's present in the retrieved context
    3. Score = statements_found / total_statements

    Low recall = retrieval missed important information that
    would be needed to answer correctly.
    """
    context_str = "\n\n".join(contexts)

    # Step 1: extract statements from ground truth
    statements_prompt = f"""Break this ground truth answer into individual statements.
Return ONLY a JSON array of strings.
No preamble, no explanation.

Ground truth: {ground_truth}

Example: ["statement 1", "statement 2"]"""

    statements_response = _llm_call(statements_prompt)

    try:
        clean = statements_response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        statements = json.loads(clean.strip())
    except Exception:
        return {"score": 0.0, "error": "Could not parse statements"}

    if not statements:
        return {"score": 1.0, "found": 0, "total": 0}

    # Step 2: check each statement against context
    found = 0
    statement_results = []

    for statement in statements:
        prompt = f"""Is this statement supported by the context?
Answer with ONLY "yes" or "no".

Context:
{context_str}

Statement: {statement}

Answer (yes/no):"""

        result = _llm_call(prompt).lower().strip()
        is_found = result.startswith("yes")
        if is_found:
            found += 1
        statement_results.append({"statement": statement, "found": is_found})

    score = found / len(statements)

    return {
        "score": round(score, 3),
        "found": found,
        "total": len(statements),
        "statement_results": statement_results
    }


def evaluate_hallucination(answer: str, contexts: list[str]) -> dict:
    """
    Hallucination Check (binary + explanation):
    LLM-as-judge reads the answer and context together and
    identifies any claims NOT supported by the context.

    Unlike faithfulness (which gives a 0-1 score), this gives
    an EXPLANATION — auditable, human-readable hallucination
    detection, not just a number.

    This is the metric that makes your eval suite defensible
    in an interview: you can show exactly which claims were
    flagged and why.
    """
    context_str = "\n\n".join(contexts)

    prompt = f"""You are an expert fact-checker. 
Given the context and answer below, identify any claims in the answer 
that are NOT supported by the context.

Context:
{context_str}

Answer:
{answer}

Return ONLY a JSON object in this format:
{{
  "has_hallucination": true or false,
  "unsupported_claims": ["claim 1", "claim 2"],
  "explanation": "brief explanation"
}}

If all claims are supported, return:
{{
  "has_hallucination": false,
  "unsupported_claims": [],
  "explanation": "All claims are supported by the context"
}}

No preamble, just the JSON:"""

    response = _llm_call(prompt)

    try:
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean.strip())
    except Exception:
        return {
            "has_hallucination": None,
            "error": "Could not parse response",
            "raw": response
        }

    return data


def evaluate_all(
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str = None,
) -> dict:
    """
    Run all 5 evaluation metrics on a single query/answer pair.
    Returns a complete evaluation report.
    """
    print(f"Evaluating: '{question[:50]}...'")

    results = {}

    print("  Running faithfulness...")
    results["faithfulness"] = evaluate_faithfulness(answer, contexts)

    print("  Running answer relevancy...")
    results["answer_relevancy"] = evaluate_answer_relevancy(question, answer)

    print("  Running hallucination check...")
    results["hallucination"] = evaluate_hallucination(answer, contexts)

    if ground_truth:
        print("  Running context precision...")
        results["context_precision"] = evaluate_context_precision(
            question, contexts, ground_truth
        )

        print("  Running context recall...")
        results["context_recall"] = evaluate_context_recall(
            contexts, ground_truth
        )

    return results