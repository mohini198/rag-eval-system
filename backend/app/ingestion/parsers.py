from pathlib import Path
from charset_normalizer import from_path
from docx import Document
from pypdf import PdfReader



def parse_txt(file_path: str) -> str:
    """
    Read a plain text file and return its contents as a string.
    
    We don't assume UTF-8 because uploaded files can come from any
    system/locale - Windows tools especially love UTF-16 with a BOM.
    charset_normalizer inspects the raw bytes and detects the actual
    encoding before we decode, rather than guessing wrong and crashing.
    """
    path = Path(file_path)
    
    result = from_path(path).best()
    
    if result is None:
        raise ValueError(f"Could not detect encoding for {file_path}")
    
    return str(result)

def parse_docx(file_path: str) -> str:
    """
    Extract text from a DOCX file.
    
    python-docx handles the unzip + XML parsing internally. We walk
    the document's paragraphs in order and join their text, since
    paragraph order in the object model matches reading order in
    the original document.
    """
    doc = Document(file_path)
    
    paragraphs = [para.text for para in doc.paragraphs]
    
    # Filter out empty paragraphs (blank lines between sections)
    # but keep them as newlines so we don't accidentally merge
    # unrelated sections into one block of text
    full_text = "\n".join(paragraphs)
    
    return full_text

def parse_pdf(file_path: str) -> str:
    """
    Extract text from a PDF file.
    
    Unlike DOCX (structured XML) or TXT (raw text), a PDF has no
    real text structure - it's drawing instructions (characters
    placed at x/y coordinates). pypdf reconstructs reading order
    from those coordinates page by page.
    
    NOTE: if a PDF is a scanned image (no real text layer), this
    will return an empty string with no error - that's a silent
    failure mode to watch for, not something this function alone
    can fix. OCR would be needed for scanned documents.
    """
    reader = PdfReader(file_path)
    
    pages_text = []
    for page in reader.pages:
        pages_text.append(page.extract_text())
    
    full_text = "\n".join(pages_text)
    
    return full_text

