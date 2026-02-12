from typing import Optional

from pydantic import BaseModel, Field


# --- Chat ---

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    conversation_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)


class SourceRef(BaseModel):
    source_name: str
    chunk_text: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    score: float = 0.0


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceRef]
    conversation_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


# --- Sources ---

class SourceInfo(BaseModel):
    source_name: str
    chunk_count: int
    ingested_at: str


# --- Sync ---

class SyncStatusResponse(BaseModel):
    pending_logs: int
    last_sync_at: Optional[str] = None
    last_sync_result: Optional[str] = None
    records_synced: int = 0


class SyncResult(BaseModel):
    synced: int
    failed: int
    message: str


# --- Health ---

class HealthResponse(BaseModel):
    status: str
    ollama: str
    ollama_model: str
    knowledge_chunks: int
    knowledge_sources: int
    pending_logs: int
    device_id: str


# --- Stats ---

class StatsResponse(BaseModel):
    total_sources: int
    total_chunks: int
    total_queries: int
    pending_sync_logs: int
    device_id: str


# --- Errors ---

class ErrorResponse(BaseModel):
    error: str
    code: str
