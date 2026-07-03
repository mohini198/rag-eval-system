# Project Decisions Log

This file tracks every meaningful technical decision made during the build,
along with the reasoning behind it and any real bugs encountered. Purpose:
interview prep — being able to explain *why*, not just *what*.

---

## Day 1 — Document Ingestion

### Decision: Separate parser functions per file type (TXT, DOCX, PDF)
**Why:** Each format stores text fundamentally differently, so one generic
parser isn't possible:
- **TXT** — raw bytes, no structure. Reading the file IS the whole job.
- **DOCX** — a zip archive containing structured XML (`document.xml`).
  Requires unzipping, then walking the XML tree (paragraphs → runs) in
  document order to extract text.
- **PDF** — no real text structure at all. A PDF is drawing instructions
  (place character X at coordinate Y). Text has to be reconstructed from
  positional data, which is why PDF parsing is the most fragile of the three.

### Decision: Used `pypdf` instead of `PyPDF2`
**Why:** `PyPDF2` is deprecated; `pypdf` is the actively maintained fork with
the same core API.

### Decision: Used `charset_normalizer` for TXT encoding detection
**Why:** Initially assumed UTF-8 for all text files. Hit a real bug (see
below) that proved this assumption unsafe. Switched to detecting encoding
from raw bytes rather than assuming a fixed one.

---

### Bug #1: UnicodeDecodeError on TXT parsing
**What happened:** `parse_txt` hardcoded `encoding='utf-8'`. A test file
created via PowerShell's `echo "..." > file.txt` was actually written in
UTF-16 (PowerShell's default redirect encoding on Windows), causing:
```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0
```
**Root cause:** Assumed a fixed encoding instead of verifying it. The `0xff`
byte was the start of a UTF-16 byte-order-mark (BOM), invalid as UTF-8.

**Fix:** Replaced manual `open(..., encoding='utf-8')` with
`charset_normalizer.from_path(...).best()`, which inspects the raw bytes
statistically and detects the actual encoding before decoding.

**Lesson:** Never assume a file's encoding — uploaded files can come from
any system/locale. Detect, don't assume. (This became a repeated theme —
see Bug #2.)

---

### Bug #2: PackageNotFoundError on DOCX parsing
**What happened:** Created a test "DOCX" by renaming a plain `.txt` file to
`.docx`. `python-docx` failed with:
```
docx.opc.exceptions.PackageNotFoundError: Package not found at '...'
```
**Root cause:** A `.docx` file is a zip archive containing XML. Renaming a
file only changes its filesystem label (the name) — it does NOT change the
actual bytes inside. The renamed file still contained plain text bytes, not
a valid zip structure, so `python-docx` couldn't unzip it.

**Fix:** Created a genuine `.docx` using actual Word, which produces real
zip-compressed XML content.

**Lesson:** A file extension is a label/hint, not a guarantee of internal
format. Parsers validate by checking actual file structure/content, not by
trusting the extension. This matters directly for a future production
concern: a document upload API must validate file *content*, not just trust
the extension a user provides.

---

### Bug #3: ModuleNotFoundError for `docx` despite being installed
**What happened:**
```
ModuleNotFoundError: No module named 'docx'
```
even though `pip install python-docx` had succeeded earlier.

**Root cause:** The venv had been deactivated (e.g. a new terminal/session
was opened without re-running `venv\Scripts\activate`), so Python fell back
to a system-wide interpreter that never had `python-docx` installed in it.
Packages installed via `pip` only exist inside the *currently active*
virtual environment.

**Fix:** Re-activated the venv (`venv\Scripts\activate`, confirmed by the
`(venv)` prefix in the prompt) before re-running the script.

**Lesson:** Don't assume the active Python environment — verify it,
especially after switching terminals/sessions.

---

### Known limitation: PDF text extraction quality
**Observed:** Real PDF extraction output contained inconsistent spacing and
mid-word line breaks (e.g. "depar / tment"), because pypdf reconstructs
reading order from x/y character coordinates rather than true paragraph
structure.
**Implication:** A normalization/cleanup step before chunking is likely
needed to avoid feeding noisy text into the chunking pipeline.
**Status:** Not yet fixed — flagged for a later cleanup step.

### Known limitation: Scanned PDFs produce silent empty extraction
**Risk:** If a PDF is a scanned image rather than real embedded text,
`parse_pdf` will not error — it will silently return an empty string, since
there is no text layer to extract, only pixel data that visually resembles
text.
**Implication:** This is more dangerous than a crash, since nothing signals
the failure. A real pipeline should check for empty/near-empty extraction
results and flag them, or fall back to OCR.
**Status:** Not handled yet — OCR fallback is a possible future addition,
not built in the current scope.

---

## Day 2 — 
## Day 2 — Chunking Strategies

### Why chunking exists at all
Embedding and storing an entire document as one vector has two critical failure modes:
1. **Retrieval imprecision**: a single vector representing 50 pages of content is a
   "blended average" of all topics — too diluted to match sharply against a specific
   narrow question. Vector similarity search loses precision.
2. **Context stuffing / "lost in the middle"**: stuffing an entire long document into
   the LLM's prompt buries relevant content in irrelevant noise. LLMs are measurably
   worse at using information in the middle of long contexts (well-documented phenomenon).
   Chunking means only the relevant piece gets passed to the LLM, not everything.

Chunking is what makes retrieval *precise* rather than *vague*.

---

### Strategy A: Fixed-size chunking (chunk_fixed_size)
**What it does:** cuts text at every N tokens, with M tokens of overlap between
consecutive chunks. No awareness of sentence or paragraph structure.

**Why tokens, not characters or words:** LLMs and embedding models measure input
limits in tokens, so measuring chunk size in tokens keeps us consistent with what
the model actually "sees."

**Why overlap:** a fixed token-count cut doesn't know where sentences end. Without
overlap, a single idea could be permanently split across two chunks with neither
half being complete. Overlap re-includes the tail of the previous chunk at the
start of the next one — insurance against hard boundary cuts, not a structural fix.

**Limitation:** overlap is a band-aid, not a real solution. The root problem
(blind cuts) remains — overlap just reduces the damage.

---

### Strategy B: Recursive character splitting (chunk_recursive)
**What it does:** tries natural boundaries in order of preference:
  paragraphs (\n\n) → line breaks (\n) → sentence ends (". ") → words (" ") → characters ("")
Only falls back to a cruder cut if the piece is still too big after trying the
preferred separator. Same function called recursively on oversized pieces — that's
why it's called "recursive."

**Key advantage over fixed-size:** prefers cutting at real structural boundaries
(paragraphs, sentences) instead of arbitrary token counts. Sentences stay intact
more often; overlap matters less as a result.

**Limitation:** still uses structural heuristics (punctuation) as a *proxy* for
meaning — doesn't actually understand whether two sentences are about the same
topic. A document with poor formatting (bad OCR, broken paragraph structure) still
produces poor cuts.

### Bug: token vs character unit mismatch
**What happened:** both chunk_fixed_size and chunk_recursive accepted chunk_size=500,
but fixed-size measured in TOKENS (via tiktoken) while recursive measured in
CHARACTERS (LangChain's default). Since 1 token ≈ 4 characters, calling both with
chunk_size=500 was actually:
  - Fixed-size: 500 tokens ≈ 2000 characters per chunk
  - Recursive: 500 characters ≈ 125 tokens per chunk
Result: recursive produced ~4x more chunks (59 vs 15) on the same document —
not because of any meaningful algorithmic difference, but purely due to the unit
mismatch. This would have made any eval comparison between strategies misleading.

**Fix:** added a custom length_function=token_length to RecursiveCharacterTextSplitter,
using tiktoken to count tokens instead of characters. After the fix: 15 vs 16 chunks —
now a fair, directly comparable result.

**Lesson:** when comparing systems, make sure you're comparing on equal footing.
A performance difference that's actually just a unit mismatch is not a real finding.

---

### Strategy C: Semantic chunking (chunk_semantic)
**What it does:** embeds every sentence individually, then walks through consecutive
sentence pairs measuring cosine similarity. Sentences are grouped together as long as
similarity stays above the threshold (same topic). A sharp drop below the threshold
signals a topic shift → new chunk boundary.

**Key advantage over both other strategies:** the only strategy that actually *measures*
meaning directly (via embeddings) rather than approximating it through structure/punctuation.
Works even on poorly-formatted documents where paragraph/sentence heuristics break down.

**Real cost:** one embedding API call per sentence. On a 100-sentence document,
that's 100 API calls just to decide where to cut — before the main retrieval pipeline
even starts. Slow and expensive compared to fixed/recursive (pure local Python logic,
zero API calls, effectively instant).

**Embedding model used:** models/gemini-embedding-001 (Google AI Studio free tier)
Produces 3072-dimensional vectors.

**Why this model:** google-generativeai package was deprecated mid-build; switched
to google-genai (newer SDK). Discovered available models by querying the API directly
(client.models.list()) rather than trusting potentially stale documentation — model
names change, always verify against what the API actually serves.

### Threshold tuning — evidence-based, not guessing
Initial threshold of 0.75 → 11 chunks from a 2000-char excerpt (way too fragmented).
Threshold of 0.50 → 1 chunk (way too merged — nothing ever triggered a cut).

Rather than keep guessing, measured actual cosine similarity scores between every
consecutive sentence pair in the test excerpt:
  - Related sentences within same section: scored 0.610 – 0.741
  - One genuine topic shift (legal boilerplate → "Introduction" section): scored 0.573

The real topic shift sat clearly below the lowest "still related" score (0.573 vs 0.610),
giving a natural gap to place the threshold in. Set threshold=0.60 based on this
observed gap — not an arbitrary default.

**Known limitation:** this threshold was tuned on one excerpt from one document
with one embedding model. It may not generalize to all document types/styles.
A more rigorous approach would test across multiple varied documents, or make the
threshold adaptive. Flagged as future improvement, not built in current scope.

---

### Decision: lib choices for chunking
- tiktoken: OpenAI's tokenizer, used by GPT-3.5/4/embedding models. Ensures our
  token counts match what the actual models will see.
- langchain-text-splitters: production-grade RecursiveCharacterTextSplitter
  implementation. No value in reimplementing a well-tested algorithm from scratch.
- numpy: cosine similarity math for semantic chunking. Standard scientific computing
  library, no need for a heavier ML framework just for dot products.

---

## Day 3 — 
## Day 3 — Embeddings Pipeline + Vector Store (pgvector)

### Connection to previous days
Day 1 output: clean text strings from parsed files.
Day 2 output: list of smaller chunk strings from those texts.
Day 3 job: convert each chunk into a vector (embedding) and store it
permanently in a database so it can be searched later without re-embedding.
Without Day 3, chunks only exist in memory during the Python session —
they're gone the moment the program exits, and retrieval is impossible.

---

### Decision: 768 dimensions instead of default 3072
**Why:** pgvector's HNSW index has a hard ceiling of 2000 dimensions.
Gemini's `gemini-embedding-001` model defaults to 3072 dimensions, which
exceeds this limit. Hit this as a real error:
```
ERROR: column cannot have more than 2000 dimensions for hnsw index
```
**Fix:** Gemini supports an `output_dimensionality` parameter — we request
768 dimensions explicitly instead of accepting the 3072 default.

**Tradeoff:** 768-dimensional embeddings are slightly less information-rich
than 3072-dimensional ones. In practice, 768 dimensions is standard for many
production RAG systems (OpenAI's text-embedding-3-small defaults to 1536,
many sentence-transformer models use 768) and more than sufficient for
high-quality semantic retrieval at our scale.

**Interview answer:** "I reduced embedding dimensions from 3072 to 768 to
stay within pgvector's HNSW index limit. 768 is a production-standard
dimensionality — the tradeoff in retrieval quality is minimal, and I kept
the HNSW index which gives logarithmic search time instead of linear."

---

### Decision: Docker for PostgreSQL + pgvector
**Why:** pgvector requires a separate installation step on top of PostgreSQL.
On Windows with PostgreSQL 18, no working prebuilt binary was available —
the official method requires Visual Studio Build Tools and compiling from
source, which is complex and error-prone.

**Fix:** Switched to Docker using the official `pgvector/pgvector:pg16` image,
which ships with pgvector pre-installed. One command to start a fully
configured PostgreSQL + pgvector instance.

**Additional issue discovered:** local PostgreSQL 18 and Docker PostgreSQL 16
both tried to use port 5432, causing Python to connect to the wrong instance
(no pgvector, no schema). Fix: stopped the local PostgreSQL service
(`net stop postgresql-x64-18`) so Docker's container is the only listener
on port 5432.

**Interview answer:** "I used Docker for the local dev database because
pgvector's Windows installation requires compiling from source with Visual
Studio, which adds unnecessary complexity. The official pgvector Docker image
gives a clean, reproducible environment that matches what you'd run in
production on Linux. This is also a more realistic setup — most teams
run their local dev databases in Docker for exactly this reason."

---

### Decision: HNSW index over IVFFlat
**Why:** pgvector supports two approximate nearest neighbor index types:
- **IVFFlat:** requires a training step (needs data before you can build
  the index), faster to build, slightly less accurate at query time.
- **HNSW (Hierarchical Navigable Small World):** no training step needed
  (can be created on an empty table), better query performance (speed vs
  recall tradeoff), higher memory usage.

For a portfolio project where we're inserting documents incrementally
(not bulk-loading a pre-existing dataset), HNSW is the right choice —
IVFFlat's training requirement would mean rebuilding the index every time
we add enough new data to shift the cluster centroids.

**What HNSW does:** builds a multilayer graph over the vectors during insert.
At query time, navigates the graph to find approximate nearest neighbors
in O(log n) time instead of O(n) for a full table scan. Trades a small,
controllable amount of recall accuracy for dramatically faster search.

---

### Schema design decisions

**Two-table design: `documents` + `chunks`**
- `documents` stores file-level metadata (filename, type, upload time).
- `chunks` stores individual chunk content, embedding vector, chunking
  strategy used, and a foreign key back to `documents`.

**Why the foreign key (`chunks.document_id → documents.id`) matters:**
Every chunk knows which document it came from. This enables citations in
the frontend — when the LLM answers a question using chunk content, the
system can tell the user "this answer came from filename X" by joining
chunks back to documents. Without this relationship, answers would have
no traceable source.

**Why store `chunk_strategy` on each chunk:**
Allows filtering retrieval by strategy (e.g. "search only fixed-size chunks")
and enables the evaluation dashboard to compare retrieval quality across
strategies on the same document. This is a core feature of the eval suite.

---

### Key concept: `<=>` is cosine DISTANCE, not similarity
pgvector's `<=>` operator computes **cosine distance** (range: 0 to 2),
where 0 = identical vectors and 2 = completely opposite.

In `search_chunks`, we use:
- `ORDER BY embedding <=> query` — ascending distance = closest first (correct)
- `1 - (embedding <=> query)` AS similarity — converts distance to similarity
  so returned scores are intuitive (0.95 = very similar, not 0.05)

This distinction matters: returning raw `<=>` scores to users would show
lower numbers for better matches, which is confusing. The `1 - x` conversion
makes scores human-readable.

---

### Real pipeline test results (Day 3 end-to-end)
Parsed `test.pdf` (26,764 chars) → 15 fixed-size chunks → embedded at 768
dimensions → stored in Docker pgvector → searched with "formula for variance."

Top results scored ~0.47-0.48 similarity — correctly LOW, since the document
is a book about bad Wikipedia writing with zero statistics content. This
confirmed the pipeline works correctly and revealed an important lesson:

**Similarity scores are relative, not absolute.** A score of 0.48 doesn't
mean "good match" — it means "best available match in this collection,"
which may still be completely irrelevant. This is exactly why the project's
evaluation suite includes faithfulness scoring and a hallucination judge —
because high retrieval similarity doesn't guarantee the retrieved content
actually answers the question. A system retrieving the "least bad" irrelevant
chunk and hallucinating an answer would score high on retrieval but low on
faithfulness. The eval suite is designed to catch exactly this gap.

---

### Known issues / future improvements
- Docker container data is ephemeral by default — if the container is removed,
  all stored chunks/embeddings are lost. For persistence across restarts,
  add a Docker volume: `-v pgdata:/var/lib/postgresql/data`. Not done yet —
  flagged for before deployment.
- `embed_batch` makes sequential API calls with a simple rate-limit pause.
  A production system would use async calls or the batch API endpoint for
  much higher throughput. Sufficient for portfolio scale.

---

## Day 4 — 
## Day 4 — Hybrid Retrieval (BM25 + Dense + RRF)

### Connection to previous days
Day 3 gave us dense vector search — embed a question, find closest chunk
vectors via HNSW index. Day 4 adds a second, completely different retrieval
method (BM25 keyword search) and merges both using Reciprocal Rank Fusion.
The output of Day 4 — a ranked list of the most relevant chunks — becomes
the context fed to the LLM in Day 5/6.

---

### Why hybrid retrieval — the core problem with single-method search

**Dense search failure mode:** specific rare terms (function names, error
codes, proper nouns) may not score high on semantic similarity because the
embedding model has no strong semantic representation for strings it hasn't
seen in context. A chunk containing the exact rare term may score only
moderately higher than unrelated chunks.

**BM25 failure mode:** conceptual/semantic queries ("what causes inflation",
"how does authentication work") won't match chunks that discuss the same
topic using different words. BM25 only counts exact term frequency — "car"
won't match "automobile" unless both words appear in the same chunk.

**Evidence from real testing on this project:**
Query: "Wikipedia editing rules"
- Dense top result: Introduction/Wikipedia chunk (similarity 0.634)
  — correctly semantic, understood the query's meaning
- BM25 top result: Dr. Dre chunk (score 2.289)
  — wrong, matched "Wikipedia" keyword without understanding "editing rules"

Query: "Conor Lastowka" (rare proper noun — book author)
- Dense top result: credits chunk (similarity 0.618), rank 2 at 0.564
  — found it, but small gap between right and wrong chunks
- BM25 top result: credits chunk (score 5.804), rank 3 at 0.000
  — decisive, enormous gap, correctly gave zero to chunks without the name

**Conclusion:** neither method dominates across all query types. Dense wins
on semantic/conceptual queries; BM25 wins on exact rare terms. Hybrid
retrieval covers both — and the real test results above are the evidence,
not just a theoretical claim.

---

### Decision: BM25 via rank_bm25 (in-memory), not Elasticsearch

**Why in-memory:** BM25 has no pre-computed index to store — it needs raw
text to build its term frequency index at search time. All chunks are loaded
from the DB into memory, BM25 index is built, query is scored, results
returned. Simple, no extra infrastructure.

**Known limitation:** this gets slower as chunk collection grows, since
you're loading more text into memory and rebuilding the index on every query.
At millions of chunks, a dedicated search engine (Elasticsearch, OpenSearch)
that maintains a persistent BM25 index would be necessary.

**Why acceptable for this project:** portfolio-scale document collections
(tens to hundreds of documents) won't hit this limitation. The architectural
decision is explicitly noted and defensible: "I used in-memory BM25 for
simplicity at portfolio scale — in production I'd move to Elasticsearch for
a persistent, incrementally-updated BM25 index."

---

### Decision: Reciprocal Rank Fusion over score-based merging

**Why not just add scores:** dense search returns cosine similarity (0 to 1).
BM25 returns term frequency scores with no fixed range — could be 0.5 or
500 depending on document length and term frequency. Adding these directly
means BM25's larger numbers completely dominate the merge — dense search
becomes invisible. The merged result is effectively just BM25 with a
negligible cosine similarity nudge.

**What RRF does instead:** ignores raw scores entirely, uses only rank
position.

Formula: RRF_score = 1/(k + rank_dense) + 1/(k + rank_bm25)

A chunk appearing in both lists gets contributions from both terms — a chunk
at rank 3 in both lists scores:
  1/(60+3) + 1/(60+3) = 0.03174

A chunk appearing only in dense at rank 3 scores:
  1/(60+3) + 0 = 0.01587

Exactly 2x lower — not because it's penalized, but because it misses the
"both methods independently agree" bonus. Independent agreement between two
completely different retrieval approaches is a stronger relevance signal than
either method's confidence alone.

**k=60:** standard constant from the original RRF paper. Prevents rank-1
results from having disproportionate influence — smooths the scoring curve
so the difference between rank 1 and rank 2 isn't enormous.

---

### Key concepts cemented on Day 4

**BM25's three smart adjustments over naive word counting:**
1. Term frequency saturation — relevance increases logarithmically with
   frequency, not linearly. A word appearing 10x isn't 10x more relevant.
2. Inverse document frequency — rare words across the corpus are weighted
   higher than common words (downweights "the", "is", upweights rare terms).
3. Document length normalization — longer chunks don't get unfair advantage
   for having more words overall.

**Why this matters for the eval suite:** the evaluation dashboard will show
retrieval quality per method (dense vs BM25 vs hybrid) — Day 4's architecture
is what makes that comparison possible, since each method is independently
callable and their results are traceable back to specific chunks and scores.

---

## ## Day 5 — Reranking (Cross-Encoder)

### Connection to previous days
Day 4 output: top 5 chunks from hybrid retrieval (BM25 + dense + RRF).
Day 5 job: re-score those 5 candidates with a more precise model and
return the best 3 to pass to the LLM for answer generation (Day 6).
Reranking sits between retrieval and generation — it's the final quality
filter before context reaches the LLM.

---

### Why reranking exists — retrieval vs precision tradeoff

**Retrieval (Day 4) optimizes for recall and speed:**
- Must search across thousands of chunks quickly
- Uses approximate methods (HNSW ANN, in-memory BM25)
- Goal: don't miss anything relevant — cast a wide net
- Tradeoff: some irrelevant chunks slip through (e.g. Dr. Dre chunk
  boosted by BM25 keyword match despite being irrelevant to the query)

**Reranking (Day 5) optimizes for precision:**
- Only sees the small shortlist (5 chunks) retrieval already filtered to
- Can afford to be slower and more thorough
- Goal: from these 5 candidates, pick the 3 that actually best answer
  this specific question
- Catches retrieval errors that neither BM25 nor dense search could catch

**Real evidence from testing:**
Query: "Wikipedia editing rules"
- RRF rank 2: Dr. Dre chunk (BM25 incorrectly boosted for "Wikipedia" keyword)
- After reranking: Dr. Dre chunk dropped out of top 3 entirely
- Cross-encoder correctly judged it irrelevant by reading query + chunk together

RRF combines rankings but doesn't re-evaluate relevance — if both BM25 and
dense independently rank a wrong chunk highly, RRF will too. Only the
cross-encoder, reading question + chunk together as one input, can catch
this class of retrieval error.

---

### Decision: local cross-encoder over Cohere Rerank API

**Options considered:**
1. Cohere Rerank API — hosted, state-of-the-art reranker, requires API key
2. Local cross-encoder (sentence-transformers) — runs on CPU, no API key

**Why local:**
- No API key needed — one less dependency, one less rate limit to hit
- Works fully offline — eval pipeline fires many reranking calls (one per
  evaluated query); rate limits on a hosted API would throttle this badly
- Same interface — the rerank() function can swap in Cohere later with
  minimal code change (same input/output contract)
- Defensible interview answer: "I used a local cross-encoder to avoid
  external dependencies in the hot path and rate limits during eval runs,
  with the architecture designed to swap in Cohere via the same interface"

**Model: cross-encoder/ms-marco-MiniLM-L-6-v2**
- Trained on MS MARCO (Microsoft's large-scale passage ranking dataset —
  real search queries + human-judged relevant passages)
- "MiniLM" = lightweight distilled model, runs on CPU in reasonable time
- ~90MB download, cached locally after first use
- Output: raw relevance scores (no fixed range — higher = more relevant)

---

### Bi-encoder vs cross-encoder — the core architectural distinction

**Bi-encoder (used in retrieval):**
- Query and chunk are embedded SEPARATELY into independent vectors
- Similarity computed by comparing pre-computed vectors (cosine similarity)
- Fast: chunk embeddings pre-computed and stored; only query needs embedding
  at search time; HNSW index makes comparison sub-linear
- Weakness: model never sees query and chunk together — infers similarity
  from independent representations, which is less accurate

**Cross-encoder (used in reranking):**
- Query and chunk fed TOGETHER as one input: [query] [SEP] [chunk]
- Model reads both simultaneously, outputs single relevance score
- More accurate: directly attends to interaction between question and passage
- Slow: can't pre-compute anything — every query-chunk pair requires a
  full transformer forward pass
- Would be unusable for full collection search: 100,000 chunks × 10ms per
  pass = 1,000 seconds per query. Only viable on a small shortlist (5-10).

**Why the two-stage architecture:**
Use bi-encoder where speed matters (full collection search), use
cross-encoder where accuracy matters (small shortlist re-scoring).
Each tool used where its tradeoffs are acceptable.

---

### Key concept: raw scores are fine for reranking

Cross-encoder outputs raw scores with no fixed range (e.g. -3.1, -6.6).
This is not a problem because reranking only needs relative ordering —
we sort by score descending and take top k. Whether the best chunk scores
-3.1 or 0.95 is irrelevant; only that it scores higher than the others.

Contrast with retrieval similarity scores (0-1 cosine similarity), which
are sometimes compared against thresholds to filter low-quality results.
Reranking never uses thresholds — pure sorting.

---

### Known limitation
Cross-encoder runs on CPU — inference is slower than GPU would allow.
On a shortlist of 5 chunks with a lightweight MiniLM model, this is
acceptable (sub-second). On a larger shortlist or a bigger model, this
would become a bottleneck. GPU inference or a hosted API would be the
production fix.

---

## Day 6 — LLM Generation with Citations

### Connection to previous days
Day 5 output: top 3 reranked chunks most relevant to the user's question.
Day 6 job: send those chunks + the question to an LLM with strict
instructions to answer only from the provided context and cite sources.
This is the final stage of the query pipeline — everything before this
was about finding the right information; Day 6 is about presenting it.

---

### Why Approach B (retrieval-augmented) over Approach A (LLM from memory)

**Approach A — send just the question to the LLM:**
- LLM answers from training knowledge only
- Fails completely on private/custom documents (company policies, internal
  docs, uploaded PDFs) — LLM has never seen them
- Even for known topics, claims can't be traced to a source document
- Citations are impossible — answer didn't come from any specific document
- Hallucination risk: LLM confidently generates plausible-sounding but
  wrong answers when it doesn't know something

**Approach B — send question + retrieved chunks (RAG):**
- Answer grounded in actual document content placed in the prompt
- Works on any private document — content is in the context, not training
- Every claim traceable to a specific chunk and source file
- Citations are meaningful — [1] maps to a real chunk from a real document
- Hallucination still possible (LLM can add claims beyond the chunks)
  but measurable — that's exactly what the faithfulness score catches

**The key insight:** RAG doesn't eliminate hallucination, it makes it
*detectable and measurable* — which is why Days 7-8 (evaluation) matter.

---

### Decision: Groq + Llama 3.3 (70b-versatile) over GPT-4o-mini

**Why Groq:**
- Free tier with generous rate limits
- Extremely fast inference (Groq's custom LPU hardware) — important because
  RAGAS evaluation pipeline makes multiple LLM calls per query; slow
  inference would make eval runs painfully long
- Llama 3.3 70b is a strong open-weight model — competitive with GPT-4o-mini
  on instruction following and factual Q&A tasks

**Interview answer:** "I chose Groq for low-latency inference so the async
eval pipeline wouldn't bottleneck the user-facing response. The same model
handles both generation and RAGAS judge calls, keeping the stack consistent
and avoiding multiple LLM provider dependencies."

---

### Decision: temperature=0.1 (near-deterministic)

**Why low temperature for RAG:**
Temperature controls randomness in token selection. Higher temperature =
more creative/varied output. Lower temperature = more deterministic, sticks
closer to most likely tokens.

For a document Q&A system, we want the LLM to faithfully report what the
context says — not creatively rephrase, embellish, or drift from source
material. Low temperature reduces the chance the model introduces claims
beyond what the retrieved chunks contain (hallucination).

This is the opposite of creative writing (where temperature ~0.7-1.0
produces interesting variation) — RAG prioritizes faithfulness over variety.

**Tradeoff:** very low temperature (0.0) can make answers feel robotic and
repetitive. 0.1 gives slight variation while staying close to deterministic.

---

### Prompt engineering decisions

**"Answer ONLY from the provided context"** — explicit grounding instruction.
Without this, LLMs default to mixing context with training knowledge, making
it impossible to measure faithfulness accurately.

**Numbered context blocks with source filenames** — enables [1][2][3]
citation notation. Each chunk is labeled with its source file, so the LLM
can reference both the chunk number and the filename.

**"Say 'I don't have enough information' if context doesn't help"** — reduces
hallucination when retrieved chunks are irrelevant to the query. Without
this, LLMs tend to answer anyway using training knowledge, silently violating
the grounding constraint.

**System prompt as "precise document Q&A assistant"** — sets the behavioral
frame before the user prompt. Reinforces the grounding constraint at the
system level, not just in the user message.

---

### Real generation test results (Day 6)

Query: "What is Wikipedia and why do people edit it?"
Retrieved chunks: 3 (Introduction chunk ranked #1 by reranker)
Answer quality: grounded, accurate, all claims cited with [1]

Manual faithfulness check:
- "allows anyone to edit" ✅ — present in chunk 1
- "settle arguments" ✅ — explicitly in chunk 1
- "poorly written articles" ✅ — implied by book's premise in chunk 1
- "pro wrestling" ✅ — mentioned in Introduction chunk

No hallucinations detected on manual inspection — consistent with what
a faithfulness score of ~1.0 would show. This will be formally measured
in Days 7-8 using RAGAS.

**Key observation:** all citations pointed to [1] — the Introduction chunk
was most relevant and contained most of the answerable content. Chunks [2]
and [3] were in the context but the LLM correctly ignored them, showing the
model can distinguish relevant from less-relevant context even when all
chunks are provided together.

---

### Known limitations

**Context window budget:** we pass top 3 chunks to the LLM. For very long
chunks or complex questions requiring many sources, 3 chunks may not be
enough. A production system might dynamically adjust top_k based on query
complexity or available context window budget.

**Citation accuracy:** the LLM cites [1][2][3] based on position in the
prompt, not semantic matching. If the prompt order changes, citations change.
A more robust system would verify that cited chunk actually contains the
claimed information — which is exactly what the faithfulness score measures.

**Temperature 0.1 ≠ 0:** slight randomness remains, meaning the same query
run twice may produce slightly different wording. For reproducible eval
results, temperature=0 would be more consistent but risks degenerate
repetitive outputs on some models.

---

## Day 7-8 — Custom Evaluation Pipeline (5 Metrics)

### Why evaluation is the differentiator
Anyone can wire up a vector database and call it RAG. What gets you hired
is proving — with actual numbers — that your system doesn't hallucinate.
The evaluation suite is what separates "I built a RAG chatbot" from "I
built a RAG system and measured its faithfulness, relevancy, precision,
recall, and hallucination rate across 16 real test questions."

---

### Decision: custom LLM-as-judge metrics over RAGAS library

**What we tried first:** RAGAS library (pip install ragas)
**What happened:** RAGAS had a broken dependency on
`langchain_community.chat_models.vertexai` — a module that moved in newer
versions of langchain_community. Attempting to fix by pinning to older
RAGAS version (0.1.21) caused cascading dependency conflicts with
langchain-core, langchain-text-splitters, and openai, breaking the
environment.

**Decision:** uninstall RAGAS entirely and implement all 5 metrics from
scratch using direct Groq API calls.

**Why this is actually better for a portfolio project:**
- You understand every line — can explain exactly how each metric works
- "I implemented custom evaluation metrics using LLM-as-judge" is a
  stronger interview story than "I used RAGAS"
- No fragile dependency chain — the evaluator only needs groq + dotenv
- Completely debuggable — you can read the exact prompts the judge uses
- Metrics are tunable — you can adjust prompts, models, thresholds

---

### The 5 metrics implemented

**1. Faithfulness (0-1)**
Question: does the answer contain ONLY claims supported by the context?
Process:
  Step 1 — LLM breaks answer into individual atomic claims
  Step 2 — For each claim, LLM checks: "is this in the context? yes/no"
  Score = supported_claims / total_claims
A score < 1.0 = hallucination present.
Does NOT require ground truth.

**2. Answer Relevancy (0-1)**
Question: does the answer actually address the question asked?
Process:
  Step 1 — LLM generates 3 synthetic questions from the answer
           ("what question would this answer be responding to?")
  Step 2 — LLM scores similarity between each synthetic question
           and the original question
  Score = average similarity across 3 synthetic questions
Low score = answer talks about something other than what was asked,
even if factually correct.
Does NOT require ground truth.

**3. Context Precision (0-1)**
Question: of the chunks retrieved, how many were actually relevant?
Process:
  For each retrieved chunk, LLM checks: "is this relevant to answering
  the question, given the ground truth?" yes/no
  Score = relevant_chunks / total_chunks
Low precision = retrieval is pulling noise/junk into the context window.
REQUIRES ground truth.

**4. Context Recall (0-1)**
Question: did retrieval find ALL the information needed to answer?
Process:
  Step 1 — LLM breaks ground truth into individual statements
  Step 2 — For each statement, checks if it's present in retrieved context
  Score = statements_found_in_context / total_statements
Low recall = retrieval missed important information.
REQUIRES ground truth.

**5. Hallucination Check (binary + explanation)**
Question: does the answer contain any unsupported claims?
Process:
  Single LLM call reads answer + context together and lists any claims
  NOT supported by context, with a human-readable explanation.
Unlike faithfulness (0-1 score), this gives an EXPLANATION —
auditable, human-readable hallucination detection. More useful for
debugging than a number alone.
Does NOT require ground truth.

---

### Faithfulness vs Answer Relevancy — the key distinction

Most commonly confused pair in interviews. They measure different failure modes:

**Faithfulness failure:** answer adds claims beyond the context.
Example: question "who wrote the book?", context says "written by John Smith",
answer says "written by John Smith, a Harvard graduate" — Harvard claim
not in context → faithfulness < 1.0 even though answer is mostly correct.

**Answer Relevancy failure:** answer doesn't address the question.
Example: question "when was Wikipedia founded?", answer talks about
Wikipedia's editing rules instead — perfectly accurate information,
but doesn't answer what was asked → low relevancy score.

An answer can be faithful but irrelevant, or relevant but unfaithful.
They are independent measurements of independent failure modes.

---

### Context Precision vs Context Recall — the key distinction

Same confusion as precision/recall in any ML context:

**Precision = quality of what you retrieved**
"Of the chunks you retrieved, how many were actually useful?"
If you retrieve 3 chunks and only 1 was relevant: precision = 0.333

**Recall = coverage of what you retrieved**
"Of all the information needed, how much did you find?"
If the correct answer requires info from 3 chunks and you found all 3: recall = 1.0

Both can be low simultaneously — you can retrieve wrong chunks AND miss
the right ones. Optimizing one often hurts the other (retrieving more
chunks improves recall but hurts precision).

---

### Real evaluation results (7/16 questions — partial due to rate limit)

```
Faithfulness:       0.929
Answer Relevancy:   0.825
Context Precision:  0.333
Context Recall:     1.000
Hallucination Rate: 28.6%
```

**What these numbers mean:**

Faithfulness 0.929 — strong. 92.9% of claims grounded in context.
The system rarely adds unsupported information.

Answer Relevancy 0.825 — good. Answers address questions well, with
some drift. Room for improvement in prompt engineering.

Context Precision 0.333 — low. Only 1 in 3 retrieved chunks was
typically relevant to the specific question. This is the clearest
signal for improvement — retrieval is pulling in noise alongside
the right chunk. Better reranking or higher top_k filtering could help.

Context Recall 1.000 — perfect. Retrieval consistently found all
information needed. Nothing important was missed. This confirms
hybrid retrieval (BM25 + dense + RRF) provides good coverage.

Hallucination Rate 28.6% — concerning. 2 of 7 questions had at least
one unsupported claim. This is what makes the eval suite valuable:
faithfulness of 0.929 (per-claim score) can coexist with a 28.6%
question-level hallucination rate because even one unsupported claim
per answer counts as a hallucination at the question level.

**The coherent story these numbers tell:**
Retrieval has high recall (finds everything) but low precision (also
pulls junk). Generation is mostly faithful but occasionally adds claims
beyond context. The hallucination rate is the most actionable finding —
reranking alone isn't sufficient to guarantee clean answers. Improving
context precision (better retrieval filtering) would likely reduce
hallucination rate since the LLM would have less noise to potentially
misuse.

---

### Rate limit issue and fix

**Problem:** Groq free tier has 100,000 tokens/day limit. Each evaluation
question makes 7-9 LLM calls (generation + 5 eval metrics, each with
multiple steps). 16 questions × ~7 calls × ~700 tokens = ~78,400 tokens
just for eval, plus generation calls. Hit the daily limit at question 8.

**Fix:**
1. Switched eval model from llama-3.3-70b-versatile to llama-3.1-8b-instant
   — smaller model uses fewer tokens, has separate rate limit bucket
2. Added time.sleep(3) between questions — spaces out calls to avoid
   per-minute rate limits
3. Keep llama-3.3-70b-versatile for answer generation where quality matters

**Interview answer:** "I used a smaller model for evaluation calls and
a larger model for generation — evaluation metrics are about detecting
patterns (yes/no claims checking) which smaller models handle well,
while generation quality benefits from the larger model's reasoning."

---

### Ground truth eval set creation

16 question/answer pairs manually created from the test document.

Key lesson: ground truth must come from actually reading the document —
AI-generated ground truth from PDF metadata is useless since it doesn't
match the text your parser extracts. This was learned directly (twice)
when generated eval sets contained metadata questions that had no answers
in any chunk.

**Spot-check method used:** verified 3 answers appear in parsed text
using `"answer_text" in parse_pdf(path)` before finalizing the eval set.
This confirms ground truth is grounded in real chunk content.

---

## Day 9 — FastAPI Backend

### Why a backend API is necessary
Before Day 9, the entire RAG pipeline existed as Python functions
callable only from a Jupyter notebook — only usable by the developer,
on their own machine, with no way for any frontend or external service
to interact with it. FastAPI wraps every pipeline function behind HTTP
endpoints, turning a collection of scripts into a real deployable
application that any frontend, mobile app, or external service can call.

Without the API:
- No frontend can talk to the pipeline
- Can't deploy to Railway (deploys a server, not a notebook)
- Can't demonstrate the project to anyone without sharing your machine

---

### Decision: FastAPI over Flask or Django

**Flask:** simpler, but no built-in request validation, no automatic
docs, no async support by default. Would require more boilerplate.

**Django:** full-stack framework with ORM, admin panel, templating —
massive overkill for a pure API backend that already has its own
database layer (psycopg2 + pgvector).

**FastAPI:**
- Automatic interactive API documentation at /docs (Swagger UI) —
  every endpoint testable in the browser with zero extra code
- Pydantic models for automatic request/response validation —
  type errors caught before they reach pipeline code
- Native async support — matches our non-blocking eval pipeline
- One of the fastest Python web frameworks (comparable to NodeJS)
- Industry standard for Python ML/AI APIs — realistic choice

**Interview answer:** "I chose FastAPI because it generates interactive
docs automatically, which made testing and demonstrating the API trivial,
and because its async support matched the non-blocking evaluation pipeline
I'd already designed."

---

### Decision: CORS middleware configuration

Added CORSMiddleware allowing requests from:
- http://localhost:3000 (Next.js dev server)
- https://*.vercel.app (deployed frontend)

Without CORS headers, browsers block all cross-origin requests by
default — the frontend running on port 3000 cannot call the API on
port 8000 without explicit CORS permission. This is a browser security
feature (Same-Origin Policy), not a server restriction.

**Why not allow_origins=["*"] (allow all origins):**
Wildcards allow any website to call your API, which is a security risk
for APIs with write operations (upload, query). Whitelisting specific
origins is the correct production approach.

---

### The 4 endpoints and their design decisions

**GET /health**
Returns database connection status and version.
Why it exists: Railway (and most deployment platforms) ping /health
periodically to verify the service is running. If it returns non-200,
the platform marks the service as unhealthy and restarts it. Without
this endpoint, deployment monitoring is blind.

**POST /upload**
Accepts multipart/form-data file upload.
Key decisions:
- File type validation by content_type, not extension — consistent
  with the Day 1 lesson that extensions lie
- Saves to tempfile before parsing — parsers need a file path, not
  raw bytes; tempfile ensures cleanup even if parsing fails (try/finally)
- Stores all 3 chunking strategies — enables eval dashboard to compare
  retrieval quality across strategies on the same document
- Skips semantic chunking for large documents (>10,000 chars) — semantic
  chunking makes one API call per sentence, which would timeout on large
  documents in a synchronous HTTP request

**POST /query**
Returns answer immediately, kicks off async eval in background.
Key decisions:
- response_model=QueryResponse enforces the response shape — FastAPI
  validates the return value matches the Pydantic model before sending
- run_eval_async() called after generate_answer() — user never waits
  for evaluation. Response time = retrieval + generation only (~2-3s),
  not retrieval + generation + 7 eval LLM calls (~30s+)
- temperature=0.1 in generation (carried from Day 6) — low randomness
  for grounded, faithful answers

**GET /eval-results**
Fetches from eval_results table, ordered by most recent first.
Accepts limit parameter (default 20) — prevents returning thousands
of rows to the frontend on a busy system.

---

### uvicorn --reload flag

Used during development: watches code files and automatically restarts
the server on save. Equivalent to nodemon in Node.js development.

NOT used in production because:
- Adds file-watching overhead
- Can restart mid-request, dropping active connections
- Production deployments should be deliberate, not automatic

Production command: uvicorn app.api.main:app --host 0.0.0.0 --port 8000
(no --reload, explicit host binding for Docker/Railway)

---

### Verified working endpoints (Day 9 test results)

GET /health:
{
  "status": "ok",
  "database": "connected",
  "version": "1.0.0"
}

POST /upload (test.pdf):
{
  "document_id": 3,
  "filename": "test.pdf",
  "file_type": "pdf",
  "text_length": 26764,
  "chunk_counts": {"fixed": 15, "recursive": 16, "semantic": "skipped"}
}

POST /query ("Who are the authors of Citation Needed?"):
{
  "answer": "The authors of Citation Needed are Conor Lastowka and Josh Fruhlinger [3].",
  "sources": ["test.pdf"],
  "chunks_used": 3
}

All three endpoints returned correct results. Async eval confirmed
starting in background (visible in server terminal logs) without
blocking the query response.

---

## Day 10 — (not yet started)
