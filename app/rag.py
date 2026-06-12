import re
import time
import hashlib
from functools import lru_cache
from collections import OrderedDict

from groq import Groq
from chromadb import Collection
from sentence_transformers.SentenceTransformer import SentenceTransformer
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.models import ChatResponse, Citation


SYSTEM_PROMPT = (
    "You are DocChat, a precise document assistant. "
    "Answer the question using ONLY the provided context below. "
    "If the answer is NOT in the context, say EXACTLY: "
    '"I can\'t find this in the uploaded documents." '
    "Cite sources inline using [1], [2], etc. corresponding to each context chunk. "
    "Do NOT use any external knowledge or prior training data."
)


class LRUCache:
    def __init__(self, capacity: int = 100):
        self.cache = OrderedDict()
        self.capacity = capacity

    def get(self, key: str):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def put(self, key: str, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)


class RateLimiter:
    def __init__(self, min_interval: float = 2.0):
        self.min_interval = min_interval
        self.last_call = 0.0

    def wait(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()


def build_context(chunks: list[dict]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk["metadata"]
        snippet = chunk["document"]
        lines.append(f"[{i}] ({meta['filename']}, page {meta['page_number']}): {snippet}")
    return "\n\n".join(lines)


def build_prompt(question: str, context: str, history: list[dict]) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        messages.append({
            "role": "system",
            "content": f"Previous conversation:\n{_format_history(history)}",
        })

    messages.append({"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"})
    return messages


def _format_history(history: list[dict]) -> str:
    lines = []
    for msg in history[-6:]:
        role = msg["role"].capitalize()
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def parse_citations(answer: str, chunks: list[dict]) -> tuple[str, list[Citation]]:
    citations = []
    refs = set(int(m) for m in re.findall(r"\[(\d+)\]", answer))

    for ref in refs:
        if 1 <= ref <= len(chunks):
            chunk = chunks[ref - 1]
            meta = chunk["metadata"]
            citations.append(Citation(
                chunk_id=meta["chunk_id"],
                filename=meta["filename"],
                page=meta["page_number"],
                snippet=chunk["document"][:200],
            ))

    return answer, citations


class RAGEngine:
    def __init__(self, collection: Collection, embedder: SentenceTransformer):
        self.collection = collection
        self.embedder = embedder
        self.client = Groq(api_key=settings.groq_api_key)
        self.sessions: dict[str, list[dict]] = {}
        self.cache = LRUCache(capacity=50)
        self.rate_limiter = RateLimiter(min_interval=2.0)

    def retrieve(self, query: str, session_id: str = "") -> list[dict]:
        query_emb = self.embedder.encode(query).tolist()
        where_filter = {"session_id": session_id} if session_id else None
        results = self.collection.query(
            query_embeddings=[query_emb],
            n_results=settings.top_k,
            where=where_filter,
        )
        chunks = []
        for i in range(len(results["ids"][0])):
            chunks.append({
                "id": results["ids"][0][i],
                "metadata": results["metadatas"][0][i],
                "document": results["documents"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else 0,
            })
        return chunks

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=60),
    )
    def _call_llm(self, messages: list[dict]) -> str:
        self.rate_limiter.wait()
        resp = self.client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=0,
            max_tokens=1024,
        )
        return resp.choices[0].message.content

    def answer(self, question: str, session_id: str) -> ChatResponse:
        if session_id not in self.sessions:
            self.sessions[session_id] = []

        chunks = self.retrieve(question, session_id)

        if not chunks:
            return ChatResponse(
                answer="No documents have been uploaded yet. Please upload a PDF first.",
                citations=[],
            )

        cache_key = hashlib.md5(
            f"{session_id}:{question}".encode()
        ).hexdigest()

        cached = self.cache.get(cache_key)
        if cached:
            return cached

        context = build_context(chunks)
        history = self.sessions[session_id]
        messages = build_prompt(question, context, history)

        try:
            answer_text = self._call_llm(messages)
        except Exception:
            return ChatResponse(
                answer="The AI backend is temporarily unavailable (rate limit reached). "
                       "Please try again later or check your GROQ_API_KEY quota.",
                citations=[],
            )

        answer_text, citations = parse_citations(answer_text, chunks)

        self.sessions[session_id].append({"role": "user", "content": question})
        self.sessions[session_id].append({"role": "assistant", "content": answer_text})
        if len(self.sessions[session_id]) > 12:
            self.sessions[session_id] = self.sessions[session_id][-12:]

        response = ChatResponse(answer=answer_text, citations=citations)
        self.cache.put(cache_key, response)
        return response

    def clear_session(self, session_id: str):
        self.sessions.pop(session_id, None)

    def get_indexed_docs(self, session_id: str = "") -> list[str]:
        where_filter = {"session_id": session_id} if session_id else None
        all_meta = self.collection.get(limit=1000, where=where_filter)["metadatas"]
        filenames = sorted(set(m["filename"] for m in all_meta if m))
        return filenames

    def get_chunk_count(self, session_id: str = "") -> int:
        where_filter = {"session_id": session_id} if session_id else None
        return len(self.collection.get(where=where_filter, limit=10000)["ids"])

    def reset_collection(self, session_id: str = ""):
        where_filter = {"session_id": session_id} if session_id else None
        ids = self.collection.get(where=where_filter)["ids"]
        if ids:
            self.collection.delete(ids=ids)
