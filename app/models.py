from typing import Optional

from pydantic import BaseModel, Field


# --- Chat ---

class ChatTurn(BaseModel):
    """Un turno previo de la conversacion (para mantener continuidad)."""
    question: str = Field(..., max_length=500)
    answer: str = Field(..., max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    conversation_id: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=20)  # None = usar TOP_K de config.env
    # Historial opcional: el cliente envia los ultimos turnos (max 2-3). Si se omite,
    # el servidor lo reconstruye desde los logs usando el conversation_id.
    history: Optional[list[ChatTurn]] = Field(default=None, max_length=4)


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
