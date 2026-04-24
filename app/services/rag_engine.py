import asyncio
import logging
import math
import re
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

SYSTEM_PROMPT = """Eres un asistente educativo experto. Tu trabajo es responder usando UNICAMENTE el contexto proporcionado de los materiales del curso.

Reglas:
1. Responde solo con informacion sustentada en el contexto.
2. Si el contexto no alcanza para responder con seguridad, dilo claramente.
3. Prioriza los fragmentos mas directos y claros; ignora ruido de OCR o texto confuso.
4. Responde en espanol de forma clara, breve y didactica.
5. Si la pregunta pide una lista, enumera solo los puntos que aparezcan en el contexto.
6. Si la pregunta implica calculos, extrae primero los datos del contexto, aplica la formula adecuada y revisa la cuenta antes de responder.
7. No inventes informacion ni completes vacios con conocimiento externo."""

VERIFICATION_PROMPT = """Eres un verificador de respuestas educativas.

Tu tarea:
1. Releer la pregunta, el contexto y el borrador.
2. Detectar cualquier afirmacion no sustentada.
3. Si hay calculos, rehacerlos solo con los datos del contexto.
4. Corregir el borrador si es necesario.

Devuelve solo la respuesta final correcta, clara y basada en el contexto."""

_NO_INFO_ANSWER = (
    "No encontre informacion suficiente sobre eso en los materiales de estudio disponibles. "
    "Consulta a tu docente o revisa directamente los documentos del curso."
)
_NUMERIC_HINTS = (
    "calcula", "calcular", "cuanto", "cuánto", "longitud", "area", "área", "distancia",
    "hipotenusa", "porcentaje", "promedio", "metros", "grados", "radianes", "ecuacion",
    "ecuación", "resolver", "cuál es el resultado", "cuanto mide",
)
_UNCERTAIN_ANSWER_HINTS = (
    "no encontre informacion",
    "no encontré información",
    "no hay informacion",
    "no hay información",
    "no se menciona",
    "no se indica",
    "no puedo determinar",
)
_SMART_MODEL_CANDIDATES = ("llama3.1:8b",)
_resolved_smart_model: str | None = None
_resolved_smart_model_checked = False
_CABLE_HEIGHT_RE = re.compile(r"poste de\s+(\d+(?:[.,]\d+)?)\s+metros?\s+de\s+altura", re.IGNORECASE)
_CABLE_HORIZONTAL_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s+metros?\s+de\s+distancia horizontal", re.IGNORECASE)
_CABLE_DEPTH_RE = re.compile(r"profundidad de\s+(\d+(?:[.,]\d+)?)\s+metros?", re.IGNORECASE)


def _is_numeric_question(question: str) -> bool:
    """Detecta preguntas donde conviene hacer verificacion adicional."""
    lowered = question.lower()
    return any(hint in lowered for hint in _NUMERIC_HINTS)


def _effective_min_score() -> float:
    """Usa un umbral minimo sensato aunque la config local sea demasiado permisiva."""
    return max(settings.MIN_RELEVANCE_SCORE, 0.10)


def _is_low_confidence(chunks: list[dict], requested_top_k: int) -> bool:
    """Detecta retrieval debil para activar una pasada mas cuidadosa."""
    if not chunks:
        return True

    expected = min(max(requested_top_k, 1), 3)
    top_scores = [chunk.get("score", 0.0) for chunk in chunks[:3]]
    max_score = max(top_scores)
    avg_score = sum(top_scores) / len(top_scores)

    return len(chunks) < expected or max_score < 0.20 or avg_score < 0.18


def _answer_needs_revision(answer: str) -> bool:
    """Marca borradores debiles o contradictorios para una segunda pasada."""
    normalized = answer.strip().lower()
    if len(normalized) < 40:
        return True
    return any(hint in normalized for hint in _UNCERTAIN_ANSWER_HINTS)


def _select_focus_source(chunks: list[dict]) -> str | None:
    """Escoge la fuente dominante entre los mejores resultados."""
    if not chunks:
        return None

    scores: dict[str, float] = {}
    for chunk in chunks[:5]:
        source_name = chunk.get("source_name")
        if not source_name:
            continue
        scores[source_name] = scores.get(source_name, 0.0) + chunk.get("score", 0.0)
    if not scores:
        return None
    return max(scores.items(), key=lambda item: item[1])[0]


def _parse_decimal(value: str) -> float:
    return float(value.replace(",", "."))


def _solve_special_numeric_case(question: str, context: str) -> str | None:
    """Resuelve de forma deterministica algunos problemas geometricos frecuentes."""
    lowered = question.lower()
    if "cable" not in lowered or "poste" not in lowered or "subterr" not in lowered:
        return None

    height_match = _CABLE_HEIGHT_RE.search(context)
    horizontal_match = _CABLE_HORIZONTAL_RE.search(context)
    depth_match = _CABLE_DEPTH_RE.search(context)
    if not (height_match and horizontal_match and depth_match):
        return None

    height = _parse_decimal(height_match.group(1))
    horizontal = _parse_decimal(horizontal_match.group(1))
    depth = _parse_decimal(depth_match.group(1))
    vertical = height + depth
    cable = math.sqrt((vertical ** 2) + (horizontal ** 2))

    return (
        "La longitud total del cable es aproximadamente "
        f"{cable:.2f} metros, porque la distancia vertical total es {height:g} + {depth:g} = {vertical:g} metros "
        f"y se aplica Pitagoras: sqrt({vertical:g}^2 + {horizontal:g}^2)."
    )


async def _resolve_smart_model() -> str:
    """Elige un modelo mas fuerte cuando este disponible localmente."""
    global _resolved_smart_model
    global _resolved_smart_model_checked

    configured = settings.OLLAMA_MODEL_SMART
    if configured and configured != settings.OLLAMA_MODEL_FAST:
        return configured

    if _resolved_smart_model_checked:
        return _resolved_smart_model or settings.OLLAMA_MODEL_FAST

    _resolved_smart_model_checked = True
    try:
        available, installed = await ollama_client.check_models_status()
        if available:
            for candidate in _SMART_MODEL_CANDIDATES:
                if candidate in installed:
                    _resolved_smart_model = candidate
                    break
    except Exception:
        _resolved_smart_model = None

    return _resolved_smart_model or settings.OLLAMA_MODEL_FAST


def _build_context(chunks: list[dict], question: str) -> str:
    """Construye el bloque de contexto a partir de los chunks encontrados."""
    max_len = max(settings.MAX_CHUNK_LENGTH, 750) if _is_numeric_question(question) else settings.MAX_CHUNK_LENGTH
    parts = []
    for chunk in chunks:
        header = f"[Fuente: {chunk['source_name']}"
        if chunk.get("page_number"):
            header += f", Pagina {chunk['page_number']}"
        if chunk.get("section"):
            header += f", Seccion: {chunk['section']}"
        header += f", Relevancia: {chunk.get('score', 0.0):.3f}]"

        text = chunk["chunk_text"]
        if len(text) > max_len:
            text = text[:max_len].rstrip() + "..."
        parts.append(f"{header}\n{text}")
    return "\n\n---\n\n".join(parts)


def _build_messages(question: str, context: str) -> list[dict]:
    """Construye la lista de mensajes para enviar al LLM."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Contexto de los materiales de estudio:\n\n"
                f"{context}\n\n---\n\n"
                f"Pregunta del estudiante: {question}\n\n"
                "Responde solo con base en el contexto."
            ),
        },
    ]


def _build_verification_messages(question: str, context: str, draft_answer: str) -> list[dict]:
    """Mensajes para una segunda pasada de verificacion."""
    return [
        {"role": "system", "content": VERIFICATION_PROMPT},
        {
            "role": "user",
            "content": (
                f"Pregunta:\n{question}\n\n"
                f"Contexto:\n{context}\n\n"
                f"Borrador a verificar:\n{draft_answer}\n\n"
                "Corrige cualquier error y devuelve la respuesta final."
            ),
        },
    ]


def _stream_text(text: str, chunk_size: int = 140):
    """Divide texto final en trozos para mantener la interfaz de streaming."""
    remaining = text.strip()
    while remaining:
        if len(remaining) <= chunk_size:
            yield remaining
            break
        split_at = remaining.rfind(" ", 0, chunk_size)
        if split_at <= 0:
            split_at = chunk_size
        piece = remaining[:split_at]
        yield piece
        remaining = remaining[split_at:].lstrip()


async def _collect_model_response(messages: list[dict], model: str) -> tuple[str, LLMStats]:
    """Consume el stream completo de Ollama y retorna texto + stats."""
    parts: list[str] = []
    stats = LLMStats()
    async for token, token_stats in ollama_client.stream_chat(messages, model=model):
        if token_stats:
            stats = token_stats
        if token:
            parts.append(token)
    return "".join(parts).strip(), stats


def _build_sources_payload(chunks: list[dict]) -> list[dict]:
    """Normaliza las fuentes para la respuesta API."""
    return [
        {
            "source_name": chunk["source_name"],
            "chunk_text": chunk["chunk_text"][:200] + "..." if len(chunk["chunk_text"]) > 200 else chunk["chunk_text"],
            "page_number": chunk.get("page_number"),
            "section": chunk.get("section"),
            "score": round(chunk.get("score", 0.0), 3),
        }
        for chunk in chunks
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

    clean_message = sanitize_query(message)

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

    try:
        query_embedding = await embedder.embed_query_async(clean_message)
    except Exception as e:
        logger.error("Error generando embedding: %s", e)
        yield {"type": "error", "error": "Error procesando la consulta"}
        return

    try:
        chunks = vector_store.search(query_embedding, query_text=clean_message, top_k=top_k)
        if not chunks and top_k < 8:
            chunks = vector_store.search(query_embedding, query_text=clean_message, top_k=8)
    except Exception as e:
        logger.error("Error en busqueda de conocimiento: %s", e)
        yield {"type": "error", "error": "Error buscando en la base de conocimiento"}
        return

    min_score = _effective_min_score()
    filtered = [chunk for chunk in chunks if chunk.get("score", 0.0) >= min_score]
    if filtered:
        chunks = filtered

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

    numeric_question = _is_numeric_question(clean_message)
    primary_chunks = chunks[: max(top_k, 1)]
    low_confidence = _is_low_confidence(primary_chunks, top_k)
    if not numeric_question and low_confidence:
        focus_source = _select_focus_source(primary_chunks)
        if focus_source:
            supporting_chunks = vector_store.find_supporting_chunks(
                focus_source,
                clean_message,
                limit=2,
            )
            seen = {chunk["chunk_id"] for chunk in primary_chunks}
            for chunk in supporting_chunks:
                if chunk["chunk_id"] not in seen:
                    primary_chunks.append(chunk)
                    seen.add(chunk["chunk_id"])
            primary_chunks.sort(key=lambda item: item.get("score", 0.0), reverse=True)

    if numeric_question:
        chunks = vector_store.expand_with_neighbors(
            primary_chunks[:1],
            limit=1,
            max_chunks=3,
        )
    else:
        chunks = vector_store.expand_with_neighbors(
            primary_chunks,
            limit=1,
            max_chunks=max(top_k + 2, 6),
        )

    sources_data = _build_sources_payload(chunks)
    yield {"type": "sources", "sources": sources_data, "conversation_id": conversation_id}

    context = _build_context(chunks, clean_message)
    messages = _build_messages(clean_message, context)
    source_names = list({chunk["source_name"] for chunk in chunks})

    deliberate_mode = numeric_question or low_confidence
    smart_model = await _resolve_smart_model() if deliberate_mode else settings.OLLAMA_MODEL_FAST
    total_tokens_in = 0
    total_tokens_out = 0

    try:
        if deliberate_mode:
            deterministic_answer = _solve_special_numeric_case(clean_message, context) if numeric_question else None
            if deterministic_answer:
                answer_text = deterministic_answer
                for piece in _stream_text(answer_text):
                    yield {"type": "token", "content": piece}
                latency_ms = int((time.time() - start_time) * 1000)
                query_cache.set(clean_message, top_k, {"sources": sources_data, "answer": answer_text})
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _safe_log(
                        conversation_id,
                        clean_message,
                        answer_text,
                        source_names,
                        total_tokens_in,
                        total_tokens_out,
                        latency_ms,
                    ),
                )
                yield {
                    "type": "done",
                    "conversation_id": conversation_id,
                    "tokens_in": total_tokens_in,
                    "tokens_out": total_tokens_out,
                    "latency_ms": latency_ms,
                }
                return

            draft_answer, draft_stats = await _collect_model_response(
                messages,
                settings.OLLAMA_MODEL_FAST,
            )
            total_tokens_in += draft_stats.tokens_in
            total_tokens_out += draft_stats.tokens_out

            answer_text = draft_answer
            if numeric_question or _answer_needs_revision(draft_answer):
                verification_messages = _build_verification_messages(clean_message, context, draft_answer)
                final_answer, verify_stats = await _collect_model_response(
                    verification_messages,
                    smart_model,
                )
                total_tokens_in += verify_stats.tokens_in
                total_tokens_out += verify_stats.tokens_out
                answer_text = final_answer or draft_answer

            for piece in _stream_text(answer_text):
                yield {"type": "token", "content": piece}
        else:
            answer_parts: list[str] = []
            stats = LLMStats()
            async for token, token_stats in ollama_client.stream_chat(
                messages,
                model=settings.OLLAMA_MODEL_FAST,
            ):
                if token_stats:
                    stats = token_stats
                if token:
                    answer_parts.append(token)
                    yield {"type": "token", "content": token}
            total_tokens_in += stats.tokens_in
            total_tokens_out += stats.tokens_out
            answer_text = "".join(answer_parts).strip()
    except ConnectionError as e:
        logger.error("Ollama no disponible: %s", e)
        yield {"type": "error", "error": str(e)}
        return
    except Exception as e:
        logger.exception("Error generando respuesta")
        yield {"type": "error", "error": "Error generando respuesta"}
        return

    latency_ms = int((time.time() - start_time) * 1000)
    query_cache.set(clean_message, top_k, {"sources": sources_data, "answer": answer_text})

    asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _safe_log(
            conversation_id,
            clean_message,
            answer_text,
            source_names,
            total_tokens_in,
            total_tokens_out,
            latency_ms,
        ),
    )

    yield {
        "type": "done",
        "conversation_id": conversation_id,
        "tokens_in": total_tokens_in,
        "tokens_out": total_tokens_out,
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
