import asyncio
import logging
import time
import uuid
from typing import AsyncGenerator

from app.config import settings
from app.infrastructure import embedder
from app.repositories import vector_store, log_store
from app.services.llm_client import ollama_client, LLMStats
from app.services.query_cache import query_cache
from app.security import sanitize_query

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un asistente educativo experto. Tu trabajo es responder las preguntas de los estudiantes basandote UNICAMENTE en el contexto proporcionado de sus materiales de curso.

Reglas:
1. Responde SOLO con informacion del contexto proporcionado.
2. Si el contexto no contiene informacion suficiente para responder, dilo claramente.
3. Cita la fuente (nombre del documento y pagina) cuando sea relevante.
4. Responde en espanol de forma clara y didactica.
5. Si la pregunta es ambigua, pide aclaracion.
6. No inventes informacion que no este en el contexto."""

_NO_INFO_ANSWER = (
    "No encontre informacion sobre eso en los materiales de estudio disponibles. "
    "Consulta a tu docente o revisa directamente los documentos del curso."
)


def _build_context(chunks: list[dict]) -> str:
    """Construye el bloque de contexto a partir de los chunks encontrados."""
    max_len = settings.MAX_CHUNK_LENGTH
    parts = []
    for chunk in chunks:
        header = f"[Fuente: {chunk['source_name']}"
        if chunk.get("page_number"):
            header += f", Pagina {chunk['page_number']}"
        if chunk.get("section"):
            header += f", Seccion: {chunk['section']}"
        header += "]"
        text = chunk["chunk_text"]
        if len(text) > max_len:
            text = text[:max_len] + "..."
        parts.append(f"{header}\n{text}")
    return "\n\n---\n\n".join(parts)


def _build_messages(question: str, context: str) -> list[dict]:
    """Construye la lista de mensajes para enviar al LLM."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Contexto de los materiales de estudio:\n\n{context}\n\n---\n\nPregunta del estudiante: {question}",
        },
    ]


async def query(
    message: str,
    conversation_id: str | None = None,
    top_k: int | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Procesa una consulta RAG completa con streaming.

    Yields dicts con tipos:
        {"type": "sources", "sources": [...]}
        {"type": "token", "content": "..."}
        {"type": "done", "stats": {...}}
        {"type": "error", "error": "..."}
    """
    start_time = time.time()
    top_k = top_k or settings.TOP_K
    conversation_id = conversation_id or str(uuid.uuid4())

    # 1. Sanitizar input
    clean_message = sanitize_query(message)

    # 2. Verificar cache (antes de embedear o llamar al LLM)
    cached = query_cache.get(clean_message, top_k)
    if cached:
        logger.info("Respondiendo desde cache para: %.60s", clean_message)
        yield {
            "type": "sources",
            "sources": cached["sources"],
            "conversation_id": conversation_id,
        }
        yield {"type": "token", "content": cached["answer"]}
        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": int((time.time() - start_time) * 1000),
            "from_cache": True,
        }
        return

    # 3. Generar embedding (en thread pool, no bloquea el event loop)
    try:
        query_embedding = await embedder.embed_query_async(clean_message)
    except Exception as e:
        logger.error("Error generando embedding: %s", e)
        yield {"type": "error", "error": "Error procesando la consulta"}
        return

    # 4. Buscar chunks relevantes
    try:
        chunks = vector_store.search(query_embedding, top_k=top_k)
    except Exception as e:
        logger.error("Error en busqueda vectorial: %s", e)
        yield {"type": "error", "error": "Error buscando en la base de conocimiento"}
        return

    # 4.5 Filtrar por score minimo
    min_score = settings.MIN_RELEVANCE_SCORE
    filtered = [c for c in chunks if c["score"] >= min_score]
    if len(filtered) < len(chunks):
        logger.info(
            "Filtrados %d/%d chunks por score < %.2f",
            len(chunks) - len(filtered), len(chunks), min_score,
        )
    chunks = filtered

    # 5. Early exit: si no hay chunks relevantes, responder sin llamar al LLM
    if not chunks:
        logger.info("No hay chunks relevantes. Respondiendo sin LLM.")
        yield {"type": "sources", "sources": [], "conversation_id": conversation_id}
        yield {"type": "token", "content": _NO_INFO_ANSWER}
        latency_ms = int((time.time() - start_time) * 1000)
        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": latency_ms,
        }
        asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _safe_log(conversation_id, clean_message, _NO_INFO_ANSWER, [], 0, 0, latency_ms),
        )
        return

    # 6. Enviar fuentes al cliente
    sources_data = [
        {
            "source_name": c["source_name"],
            "chunk_text": c["chunk_text"][:200] + "..." if len(c["chunk_text"]) > 200 else c["chunk_text"],
            "page_number": c.get("page_number"),
            "section": c.get("section"),
            "score": round(c["score"], 3),
        }
        for c in chunks
    ]
    yield {"type": "sources", "sources": sources_data, "conversation_id": conversation_id}

    # 7. Construir contexto y mensajes
    context = _build_context(chunks)
    messages = _build_messages(clean_message, context)

    # 8. Stream desde Ollama
    full_answer: list[str] = []
    stats = LLMStats()

    try:
        async for token, token_stats in ollama_client.stream_chat(messages):
            if token_stats:
                stats = token_stats
            if token:
                full_answer.append(token)
                yield {"type": "token", "content": token}
    except ConnectionError as e:
        logger.error("Ollama no disponible: %s", e)
        yield {"type": "error", "error": str(e)}
        return
    except Exception as e:
        logger.error("Error en streaming LLM: %s", e)
        yield {"type": "error", "error": "Error generando respuesta"}
        return

    # 9. Calcular metricas
    latency_ms = int((time.time() - start_time) * 1000)
    answer_text = "".join(full_answer)
    source_names = list({c["source_name"] for c in chunks})

    # 10. Guardar en cache para proximas consultas identicas
    query_cache.set(clean_message, top_k, {"sources": sources_data, "answer": answer_text})

    # 11. Registrar log en background (no retrasa la respuesta)
    asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _safe_log(
            conversation_id, clean_message, answer_text,
            source_names, stats.tokens_in, stats.tokens_out, latency_ms,
        ),
    )

    yield {
        "type": "done",
        "conversation_id": conversation_id,
        "tokens_in": stats.tokens_in,
        "tokens_out": stats.tokens_out,
        "latency_ms": latency_ms,
    }


def _safe_log(
    conversation_id: str,
    question: str,
    answer: str,
    sources_used: list[str],
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
) -> None:
    try:
        log_store.log_usage(
            conversation_id=conversation_id,
            question=question,
            answer=answer,
            sources_used=sources_used,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.error("Error registrando log de uso: %s", e)
