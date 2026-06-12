import time
import tiktoken
import fitz
from chromadb import Collection
from chromadb.api.types import Metadata

from app.config import settings


tokenizer = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(tokenizer.encode(text, disallowed_special=()))


def extract_text_from_pdf(path: str) -> list[dict]:
    """Extract text page-by-page from a PDF. Returns list of {page_number, text}."""
    doc = fitz.open(path)
    pages = []
    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        text = page.get_text().strip()
        if text:
            pages.append({"page_number": page_num + 1, "text": text})
    doc.close()
    return pages


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
