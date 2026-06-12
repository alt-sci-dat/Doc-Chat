from pydantic import BaseModel, Field
from typing import Optional


class UploadResponse(BaseModel):
    filename: str
    pages: int
    chunks: int
    time_taken: float


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=0, max_length=4096)
    session_id: str


class Citation(BaseModel):
    chunk_id: str
    filename: str
    page: int
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]


class HealthResponse(BaseModel):
    status: str = "ok"
    chunks_indexed: int
    docs_ingested: list[str]


class ErrorResponse(BaseModel):
    detail: str
