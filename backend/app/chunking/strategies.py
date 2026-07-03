import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter
import re
import numpy as np
from app.embeddings.embedder import embed_text

def chunk_fixed_size(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Split text into fixed-size chunks measured in tokens, with overlap
    between consecutive chunks.

    Why tokens, not characters or words: LLMs and embedding models
    measure their input limits in tokens, not characters or words, so
    measuring chunk size in tokens keeps us consistent with what the
    model actually "sees."

    Why overlap: a fixed-size cut doesn't know where sentences end, so
    without overlap, a single idea could be split across two chunks
    with neither half being complete. Overlap re-includes the tail of
    the previous chunk at the start of the next one, increasing the
    odds at least one chunk contains the complete idea intact.
    """
    encoding = tiktoken.get_encoding("cl100k_base")  # GPT-3.5/4 tokenizer
    tokens = encoding.encode(text)

    chunks = []
    start = 0
    step = chunk_size - overlap  # how far forward each chunk starts

    while start < len(tokens):
        end = start + chunk_size
        chunk_tokens = tokens[start:end]
        chunk_text = encoding.decode(chunk_tokens)
        chunks.append(chunk_text)

        start += step

    return chunks

def chunk_recursive(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Split text by trying natural boundaries first (paragraphs, then
    lines, then sentences, then words), only falling back to a hard
    character cut if no natural boundary keeps the piece small enough.

    chunk_size/overlap are measured in TOKENS (via tiktoken), matching
    chunk_fixed_size, so the two strategies are directly comparable -
    "500" means the same thing in both, isolating the comparison to
    splitting LOGIC rather than an accidental difference in units.
    """
    encoding = tiktoken.get_encoding("cl100k_base")

    def token_length(text: str) -> int:
        return len(encoding.encode(text))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=token_length,  # count tokens, not characters
    )

    chunks = splitter.split_text(text)
    return chunks

def _split_into_sentences(text: str) -> list[str]:
    """Simple sentence splitter using punctuation as a boundary signal."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Measures how similar two embedding vectors are (1.0 = identical direction, 0 = unrelated)."""
    a = np.array(vec_a)
    b = np.array(vec_b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def chunk_semantic(text: str, similarity_threshold: float = 0.6) -> list[str]:
    """
    Split text into chunks based on topic shifts, detected via embedding
    similarity between consecutive sentences - not punctuation/structure
    rules like the other two strategies.

    Sentences are grouped together as long as consecutive similarity
    stays ABOVE the threshold (same topic). A sharp drop below the
    threshold signals a topic shift, triggering a new chunk boundary.

    NOTE: this makes one embedding API call per sentence - expensive
    and slow compared to fixed/recursive, which are free local logic.
    """
    sentences = _split_into_sentences(text)

    if len(sentences) <= 1:
        return sentences

    sentence_embeddings = [embed_text(s) for s in sentences]

    chunks = []
    current_chunk = [sentences[0]]

    for i in range(1, len(sentences)):
        similarity = _cosine_similarity(sentence_embeddings[i - 1], sentence_embeddings[i])

        if similarity >= similarity_threshold:
            # still on the same topic - keep building this chunk
            current_chunk.append(sentences[i])
        else:
            # topic shift detected - close current chunk, start a new one
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentences[i]]

    chunks.append(" ".join(current_chunk))  # don't forget the last chunk

    return chunks


