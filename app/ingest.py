import time
import tiktoken
import fitz
from chromadb import Collection
from chromadb.api.types import Metadata

from app.config import settings

tokenizer = tiktoken.get_encoding("cl100k_base")
OCR_MIN_CHARS = 50


def _try_tables(pdf_path: str) -> dict[int, str]:
    """Extract tables from each page via pdfplumber. Returns {page_num: formatted_tables}."""
    try:
        import pdfplumber
    except ImportError:
        return {}

    result = {}
    try:
        with pdfplumber.open(pdf_path) as doc:
            for page_num, page in enumerate(doc.pages, start=1):
                tables = page.extract_tables()
                if not tables:
                    continue
                lines = ["\n--- TABLES ---"]
                for t_idx, table in enumerate(tables, start=1):
                    if not table or not table[0]:
                        continue
                    col_count = len(table[0])
                    lines.append(f"\nTable {t_idx}:")
                    for row in table:
                        cells = [str(c) if c else "" for c in (row or [])]
                        while len(cells) < col_count:
                            cells.append("")
                        lines.append("| " + " | ".join(cells) + " |")
                result[page_num] = "\n".join(lines)
    except Exception:
        pass
    return result


def _try_ocr(pdf_path: str, page_num: int) -> str:
    """Run OCR on a single page. Returns empty string on failure."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        return ""
    try:
        images = convert_from_path(pdf_path, first_page=page_num, last_page=page_num, dpi=200)
        if images:
            return pytesseract.image_to_string(images[0]).strip()
    except Exception:
        pass
    return ""


def extract_text_from_pdf(path: str) -> list[dict]:
    """Extract page text with three strategies:
    1. PyMuPDF for standard text PDFs
    2. pdfplumber for table extraction (appended as structured text)
    3. Tesseract OCR fallback for scanned/image pages
    """
    table_content = _try_tables(path)
    doc = fitz.open(path)
    pages = []
    for page_num in range(doc.page_count):
        pn = page_num + 1
        page = doc.load_page(page_num)
        text = page.get_text().strip()

        # Append tables if found
        extra = table_content.get(pn, "")
        if extra:
            text = text + "\n" + extra if text else extra

        # OCR fallback for image-based pages
        if len(text) < OCR_MIN_CHARS:
            ocr = _try_ocr(path, pn)
            if ocr:
                text = ocr

        pages.append({"page_number": pn, "text": text})
    doc.close()
    return [p for p in pages if p["text"]]


def chunk_page(page_text: str, page_number: int, filename: str, session_id: str = "") -> list[dict]:
    """Split page text into overlapping chunks of ~chunk_size tokens."""
    chunks = []
    tokens = tokenizer.encode(page_text, disallowed_special=())
    start = 0
    chunk_id = 0
    while start < len(tokens):
        end = start + settings.chunk_size
        chunk_tokens = tokens[start:end]
        chunk_text = tokenizer.decode(chunk_tokens)
        chunks.append({
            "chunk_id": f"{filename}_p{page_number}_c{chunk_id}",
            "filename": filename,
            "page_number": page_number,
            "text": chunk_text,
            "session_id": session_id,
        })
        chunk_id += 1
        if end >= len(tokens):
            break
        start += settings.chunk_size - settings.chunk_overlap
    return chunks


def ingest_pdf(
    path: str,
    filename: str,
    collection: Collection,
    embedder,
    session_id: str = "",
) -> dict:
    """Full pipeline: extract → chunk → embed → upsert to ChromaDB."""
    start = time.perf_counter()

    pages = extract_text_from_pdf(path)
    if not pages:
        raise ValueError(f"No extractable text found in {filename}")

    all_chunks = []
    for page in pages:
        page_chunks = chunk_page(page["text"], page["page_number"], filename, session_id)
        all_chunks.extend(page_chunks)

    ids = [ch["chunk_id"] for ch in all_chunks]
    texts = [ch["text"] for ch in all_chunks]
    metadatas: list[Metadata] = [
        {"filename": ch["filename"], "page_number": ch["page_number"], "chunk_id": ch["chunk_id"], "session_id": ch["session_id"]}
        for ch in all_chunks
    ]

    embeddings = embedder.encode(texts, show_progress_bar=False).tolist()

    collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    elapsed = time.perf_counter() - start
    return {
        "filename": filename,
        "pages": len(pages),
        "chunks": len(all_chunks),
        "time_taken": round(elapsed, 2),
    }
