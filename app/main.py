import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from chromadb import PersistentClient
from sentence_transformers import SentenceTransformer

from app.config import settings
from app.models import (
    ChatRequest,
    ChatResponse,
    UploadResponse,
    HealthResponse,
    ErrorResponse,
)
from app.ingest import ingest_pdf
from app.rag import RAGEngine


collection = None
embedder = None
rag_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global collection, embedder, rag_engine
    chroma_client = PersistentClient(path=settings.chroma_path)
    collection = chroma_client.get_or_create_collection(
        name="docchat",
        metadata={"hnsw:space": "cosine"},
    )
    embedder = SentenceTransformer(settings.embed_model)
    rag_engine = RAGEngine(collection, embedder)
    yield
    chroma_client._system.stop()


app = FastAPI(
    title="DocChat",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health(session_id: str = ""):
    docs = rag_engine.get_indexed_docs(session_id) if rag_engine else []
    count = rag_engine.get_chunk_count(session_id) if rag_engine else 0
    return HealthResponse(status="ok", chunks_indexed=count, docs_ingested=docs)


@app.post("/upload", response_model=UploadResponse, responses={422: {"model": ErrorResponse}})
async def upload(
    files: list[UploadFile] = File(...),
    session_id: str = "",
):
    if len(files) < 1 or len(files) > 5:
        raise HTTPException(status_code=422, detail="Upload between 1 and 5 PDFs")

    results = []
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=422, detail=f"{file.filename} is not a PDF")

        contents = await file.read()
        if len(contents) > 20 * 1024 * 1024:
            raise HTTPException(status_code=422, detail=f"{file.filename} exceeds 20MB limit")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        try:
            result = ingest_pdf(tmp_path, file.filename, collection, embedder, session_id)
            results.append(result)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        finally:
            os.unlink(tmp_path)

    total = {
        "filename": ", ".join(r["filename"] for r in results),
        "pages": sum(r["pages"] for r in results),
        "chunks": sum(r["chunks"] for r in results),
        "time_taken": round(sum(r["time_taken"] for r in results), 2),
    }
    return UploadResponse(**total)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    return rag_engine.answer(req.question, req.session_id)


@app.post("/clear")
async def clear(session_id: str = ""):
    if session_id:
        rag_engine.clear_session(session_id)
    return {"status": "ok"}


@app.post("/reset")
async def reset(session_id: str = ""):
    rag_engine.reset_collection(session_id)
    msg = f"Documents cleared for session {session_id}" if session_id else "All documents cleared"
    return {"status": "ok", "message": msg}
