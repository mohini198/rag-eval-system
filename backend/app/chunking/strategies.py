import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter


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

