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

## Day 2 — (not yet started)