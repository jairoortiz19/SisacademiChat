from fastapi import APIRouter

from app.config import settings
from app.models import HealthResponse
from app.repositories import vector_store, log_store
from app.services.llm_client import ollama_client

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check del servicio. No requiere autenticacion.
    Verifica: Ollama conectado, modelo disponible, estado de DBs.
    """
    ollama_ok = await ollama_client.is_available()
    model_ok = await ollama_client.has_model() if ollama_ok else False

    if ollama_ok and model_ok:
        ollama_status = "connected"
    elif ollama_ok:
        ollama_status = f"connected (modelo '{settings.OLLAMA_MODEL}' no encontrado)"
    else:
        ollama_status = "disconnected"

    stats = vector_store.get_stats()
    pending = log_store.get_pending_count()

    status = "ok" if ollama_ok and model_ok else "degraded"

    return HealthResponse(
        status=status,
        ollama=ollama_status,
        ollama_model=settings.OLLAMA_MODEL,
        knowledge_chunks=stats["total_chunks"],
        knowledge_sources=stats["total_sources"],
        pending_logs=pending,
        device_id=settings.DEVICE_ID,
    )
