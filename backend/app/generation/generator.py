import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MODEL = "llama-3.3-70b-versatile"


def build_prompt(query: str, chunks: list[dict]) -> str:
    """
    Build the prompt that gets sent to the LLM.

    The prompt structure matters a lot for RAG quality:
    1. Clear instruction to answer ONLY from provided context
       — this is what makes the system grounded, not just a chatbot
    2. Numbered context chunks with source filenames
       — enables citations in the answer
    3. Explicit instruction to cite sources
       — forces the model to reference which chunk supports each claim
    4. Instruction to say "I don't know" if context doesn't help
       — reduces hallucination when retrieved chunks are irrelevant
    """
    context_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        filename = chunk.get("filename", "unknown")
        content = chunk["content"].strip()
        context_blocks.append(f"[{i}] Source: {filename}\n{content}")

    context_str = "\n\n".join(context_blocks)

    prompt = f"""You are a helpful assistant that answers questions based strictly on the provided context.

CONTEXT:
{context_str}

INSTRUCTIONS:
- Answer the question using ONLY the information in the context above
- Cite your sources using [1], [2], [3] notation matching the context numbers
- If the context does not contain enough information to answer the question, say "I don't have enough information in the provided documents to answer this question"
- Do not use any knowledge outside of the provided context
- Be concise and direct

QUESTION: {query}

ANSWER:"""

    return prompt


def generate_answer(query: str, chunks: list[dict]) -> dict:
    """
    Generate an answer to the query using the retrieved chunks as context.

    Returns a dict with:
    - answer: the generated text
    - query: original question
    - sources: list of source filenames used
    - context: the chunks that were used (needed for eval pipeline later)
    """
    if not chunks:
        return {
            "answer": "No relevant documents found to answer this question.",
            "query": query,
            "sources": [],
            "context": []
        }

    prompt = build_prompt(query, chunks)

    response = _client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a precise document Q&A assistant. Answer only from the provided context."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.1,  # low temperature = more deterministic, less creative
                          # important for factual Q&A — we want consistent,
                          # grounded answers, not creative paraphrasing
        max_tokens=500,
    )

    answer = response.choices[0].message.content

    return {
        "answer": answer,
        "query": query,
        "sources": list(set(chunk.get("filename", "unknown") for chunk in chunks)),
        "context": [chunk["content"] for chunk in chunks]
    }