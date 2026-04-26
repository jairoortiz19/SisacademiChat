import asyncio
import logging
import math
import re
import time
import unicodedata
import uuid
from typing import AsyncGenerator

from app.config import settings
from app.infrastructure import embedder
from app.repositories import vector_store, log_store
from app.services.llm_client import ollama_client, LLMStats
from app.services.query_cache import query_cache
from app.security import sanitize_query

logger = logging.getLogger(__name__)
QuestionIntent = str

SYSTEM_PROMPT = """Eres un asistente educativo experto. Tu trabajo es responder usando UNICAMENTE el contexto proporcionado de los materiales del curso.

Reglas:
1. Responde solo con informacion sustentada en el contexto.
2. Si el contexto no alcanza para responder con seguridad, dilo claramente.
3. Prioriza los fragmentos mas directos y claros; ignora ruido de OCR o texto confuso.
4. Responde en espanol de forma clara, breve y didactica.
5. Si la pregunta pide una lista, enumera solo los puntos que aparezcan en el contexto.
6. Si la pregunta implica calculos, extrae primero los datos del contexto, aplica la formula adecuada y revisa la cuenta antes de responder.
7. No inventes informacion ni completes vacios con conocimiento externo.
8. Si el contexto contiene fragmentos de cuentos, narrativa o dialogo ficticio, NO los uses para responder preguntas sobre conceptos, definiciones o explicaciones del mundo real; usa esos fragmentos SOLO si la pregunta es sobre el texto literario en si."""

VERIFICATION_PROMPT = """Eres un verificador de respuestas educativas.

Tu tarea:
1. Releer la pregunta, el contexto y el borrador.
2. Detectar cualquier afirmacion no sustentada.
3. Si hay calculos, rehacerlos solo con los datos del contexto.
4. Corregir el borrador si es necesario.
5. No incluyas frases meta como "la respuesta final es", notas sobre el borrador ni comentarios del sistema.
6. Devuelve una respuesta final limpia en espanol, breve y natural.

Devuelve solo la respuesta final correcta, clara y basada en el contexto."""

REWRITE_PROMPT = """Eres editor de respuestas educativas.

Tu tarea:
1. Reescribir el borrador en espanol claro y natural.
2. Mantener solo la informacion sustentada en el contexto.
3. Eliminar frases meta, notas sobre el borrador y cualquier mezcla con otro idioma.
4. Si la pregunta es de orientacion, expresa criterios o ideas del material, no inventes pasos si el contexto no los enumera.

Devuelve solo la respuesta final."""

_NO_INFO_ANSWER = (
    "No encontre informacion suficiente sobre eso en los materiales de estudio disponibles. "
    "Consulta a tu docente o revisa directamente los documentos del curso."
)
_NUMERIC_TOKEN_HINTS = {
    "calcula", "calcular", "cuanto", "cuanta", "cuantos", "cuantas", "longitud",
    "area", "distancia", "hipotenusa", "porcentaje", "promedio", "metros",
    "grados", "radianes", "ecuacion", "resolver", "resultado", "mide",
}
_NUMERIC_PHRASE_HINTS = (
    "cual es el resultado", "cuanto mide", "cuanta mide", "distancia horizontal",
    "aplica pitagoras", "teorema de pitagoras",
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
_NON_SPANISH_ARTIFACTS = (" nao ", " não ", " presão", " laberintos.", " ou ")
_META_PREFIX_RE = re.compile(
    r"^\s*(la respuesta final es|respuesta final|respuesta corregida|version final)\s*:?\s*",
    re.IGNORECASE,
)
_TRAILING_NOTE_RE = re.compile(r"\n+\s*nota\s*:.*$", re.IGNORECASE | re.DOTALL)
_NUMBERED_STEP_RE = re.compile(r"^\s*\d+\.\s", re.MULTILINE)
_TEXT_TOKEN_RE = re.compile(r"[a-z0-9]{4,}")
_STOPWORDS = {
    "como", "para", "entre", "sobre", "desde", "hasta", "donde", "cuando",
    "porque", "quien", "quienes", "cual", "cuales", "estos", "estas", "este",
    "esta", "solo", "segun", "puede", "pueden", "deben", "tiene", "tienen",
    "ellos", "ellas", "todos", "todas", "mucho", "muchos", "mucha", "muchas",
}
_NOISY_SECTION_HINTS = (
    "temas", "objetivo", "unidad", "actividad", "introduccion", "aprend",
    "materiales", "reto", "evaluacion", "competencia",
)
_FACTUAL_INTENTS: frozenset = frozenset({"definition", "list", "comparison", "explanation", "numeric"})
_FICTION_TEXT_MARKERS = (
    "habia una vez", "había una vez", "erase una vez", "érase una vez",
    " dijo:", " respondio:", " respondió:", " le pregunto:", " le preguntó:",
    " contesto:", " contestó:",
)
_DEFINITION_CUES = (
    "estan establecidos", "esta establecido", "se explica", "se refiere",
    "consiste", "significa", "para que existe", "los principales fines",
)
_LIST_CUES = (
    "los principales", "incluye", "incluyen", "se clasifican", "elementos",
    "acciones", "caracteristicas", "fines son",
)
_COMPARISON_TEXT_CUES = (
    "diferencia", "similitud", "mientras", "en cambio", "por otro lado", "ambos",
)
_GUIDANCE_TEXT_CUES = (
    "impacto", "consecuencias", "respeto", "claridad", "limites", "analiza",
    "reflexiona", "considera", "preguntas", "bienestar", "valores",
)
_LIST_HINTS = (
    "que acciones", "qué acciones", "cuales son", "cuáles son", "que fenomenos",
    "qué fenómenos", "que temas", "qué temas", "que elementos", "qué elementos",
)
_DEFINITION_HINTS = (
    "que es", "qué es", "que son", "qué son", "en que consiste", "en qué consiste",
)
_COMPARISON_HINTS = (
    "diferencia entre", "cual es la diferencia", "cuál es la diferencia",
    "relacion existe", "relación existe", "compar", "similitud",
)
_GUIDANCE_HINTS = (
    "como analizar", "cómo analizar", "como decir", "cómo decir", "como actuar",
    "cómo actuar", "como responder", "cómo responder", "como enfrentar", "cómo enfrentar",
    "como manejar", "cómo manejar", "como tomar", "cómo tomar",
)


def _is_fiction_chunk(chunk: dict, patterns: list[str]) -> bool:
    """Detecta si un chunk proviene de una fuente ficticia o narrativa."""
    source = (chunk.get("source_name") or "").lower()
    if patterns and any(p in source for p in patterns):
        return True
    text = (chunk.get("chunk_text") or "").lower()
    return any(marker in text for marker in _FICTION_TEXT_MARKERS)


def _filter_fictional_chunks(chunks: list[dict], intent: QuestionIntent) -> list[dict]:
    """Filtra chunks de fuentes ficticias cuando la pregunta es factual."""
    if intent not in _FACTUAL_INTENTS:
        return chunks
    raw = settings.FICTIONAL_SOURCE_PATTERNS
    patterns = [p.strip().lower() for p in raw.split(",") if p.strip()] if raw else []
    factual = [c for c in chunks if not _is_fiction_chunk(c, patterns)]
    return factual if factual else chunks  # no dejar sin contexto


def _is_numeric_question(question: str) -> bool:
    """Detecta preguntas donde conviene hacer verificacion adicional."""
    normalized = _normalize_text(question)
    if any(hint in normalized for hint in _NUMERIC_PHRASE_HINTS):
        return True

    # Comparar por tokens evita falsos positivos como "tareas" -> "area".
    tokens = set(_TEXT_TOKEN_RE.findall(normalized))
    return bool(tokens & _NUMERIC_TOKEN_HINTS)


def _detect_question_intent(question: str) -> QuestionIntent:
    """Clasifica la intencion de la pregunta para ajustar retrieval y respuesta."""
    lowered = question.lower().replace("¿", "").replace("?", "").strip()
    if _is_numeric_question(question):
        return "numeric"
    if any(hint in lowered for hint in _GUIDANCE_HINTS):
        return "guidance"
    if any(hint in lowered for hint in _COMPARISON_HINTS):
        return "comparison"
    if any(hint in lowered for hint in _LIST_HINTS):
        return "list"
    if any(lowered.startswith(hint) for hint in _DEFINITION_HINTS):
        return "definition"
    if lowered.startswith(("como ", "cómo ")):
        return "explanation"
    return "general"


def _normalize_text(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(stripped.lower().split())


def _extract_query_terms(question: str) -> list[str]:
    seen = set()
    terms = []
    for raw in _TEXT_TOKEN_RE.findall(_normalize_text(question)):
        if raw in _STOPWORDS or raw in seen:
            continue
        seen.add(raw)
        terms.append(raw)
    return terms


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


def _has_non_spanish_artifacts(answer: str) -> bool:
    normalized = f" {answer.lower()} "
    return any(token in normalized for token in _NON_SPANISH_ARTIFACTS)


def _has_meta_artifacts(answer: str) -> bool:
    return bool(_META_PREFIX_RE.search(answer) or _TRAILING_NOTE_RE.search(answer))


def _sanitize_answer_text(answer: str) -> str:
    cleaned = answer.replace("\r", "").strip()
    cleaned = _META_PREFIX_RE.sub("", cleaned)
    cleaned = _TRAILING_NOTE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _answer_needs_revision(answer: str, intent: QuestionIntent, low_confidence: bool) -> bool:
    """Marca borradores debiles o contradictorios para una segunda pasada."""
    cleaned = _sanitize_answer_text(answer)
    normalized = cleaned.lower()
    if len(normalized) < 40:
        return True
    if any(hint in normalized for hint in _UNCERTAIN_ANSWER_HINTS):
        return True
    if _has_non_spanish_artifacts(cleaned):
        return True
    if _has_meta_artifacts(answer):
        return True
    if low_confidence and intent in {"definition", "list", "guidance"}:
        return True
    return False


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


def _chunk_signature(chunk: dict) -> tuple[str | None, int | None, str]:
    return (
        chunk.get("source_name"),
        chunk.get("page_number"),
        _normalize_text(chunk.get("chunk_text", "")),
    )


def _dedupe_chunks(chunks: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen_ids = set()
    seen_signatures = set()
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        signature = _chunk_signature(chunk)
        if chunk_id in seen_ids or signature in seen_signatures:
            continue
        if chunk_id is not None:
            seen_ids.add(chunk_id)
        seen_signatures.add(signature)
        deduped.append(chunk)
    return deduped


def _chunk_content_score(chunk: dict, intent: QuestionIntent, query_terms: list[str]) -> float:
    text = _normalize_text(chunk.get("chunk_text", ""))
    section = _normalize_text(chunk.get("section", ""))
    score = chunk.get("score", 0.0)

    if any(hint in section for hint in _NOISY_SECTION_HINTS):
        score -= 0.08
    if len(text) < 140:
        score -= 0.03

    term_hits = sum(1 for term in query_terms if term in text)
    score += min(term_hits * 0.03, 0.12)

    if intent == "definition" and any(cue in text for cue in _DEFINITION_CUES):
        score += 0.12
    elif intent == "list" and any(cue in text for cue in _LIST_CUES):
        score += 0.08
    elif intent == "comparison" and any(cue in text for cue in _COMPARISON_TEXT_CUES):
        score += 0.08
    elif intent == "guidance" and any(cue in text for cue in _GUIDANCE_TEXT_CUES):
        score += 0.10

    if chunk.get("page_number") is not None:
        score += 0.01
    return score


def _rank_source_candidates(
    primary_chunks: list[dict],
    question: str,
    intent: QuestionIntent,
) -> list[tuple[str, float, list[dict]]]:
    query_terms = _extract_query_terms(question)[:6]
    candidates: list[tuple[str, float, list[dict]]] = []

    for source_name in dict.fromkeys(
        chunk.get("source_name") for chunk in primary_chunks if chunk.get("source_name")
    ):
        seed_chunks = [chunk for chunk in primary_chunks if chunk.get("source_name") == source_name]
        supporting_chunks = vector_store.find_supporting_chunks(source_name, question, limit=3)
        merged = _dedupe_chunks(seed_chunks + supporting_chunks)
        rescored = []
        for chunk in merged:
            rescored_chunk = dict(chunk)
            rescored_chunk["score"] = max(
                chunk.get("score", 0.0),
                _chunk_content_score(chunk, intent, query_terms),
            )
            rescored.append(rescored_chunk)

        rescored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        if not rescored:
            continue

        source_score = sum(item.get("score", 0.0) for item in rescored[:3]) + (0.02 * len(seed_chunks))
        candidates.append((source_name, source_score, rescored))

    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def _should_anchor_to_focus_source(intent: QuestionIntent, chunks: list[dict]) -> bool:
    """Decide si conviene concentrar el contexto en una fuente dominante."""
    if intent not in {"definition", "list", "guidance", "explanation"} or not chunks:
        return False

    scores: dict[str, float] = {}
    counts: dict[str, int] = {}
    for chunk in chunks[:5]:
        source_name = chunk.get("source_name")
        if not source_name:
            continue
        scores[source_name] = scores.get(source_name, 0.0) + chunk.get("score", 0.0)
        counts[source_name] = counts.get(source_name, 0) + 1

    if not scores:
        return False

    ranked = sorted(
        scores.items(),
        key=lambda item: (item[1], counts.get(item[0], 0)),
        reverse=True,
    )
    top_source, top_score = ranked[0]
    total_score = sum(scores.values())
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    top_count = counts.get(top_source, 0)

    return (
        top_count >= 3
        or (total_score > 0 and top_score / total_score >= 0.45)
        or (top_count >= 2 and top_score >= second_score * 1.20)
    )


def _anchor_primary_chunks(
    primary_chunks: list[dict],
    question: str,
    intent: QuestionIntent,
) -> list[dict]:
    """Refuerza una fuente dominante cuando la pregunta parece resolverse mejor alli."""
    if not primary_chunks:
        return primary_chunks

    ranked_sources = _rank_source_candidates(primary_chunks, question, intent)
    if not ranked_sources:
        return primary_chunks

    top_source, top_score, top_chunks = ranked_sources[0]
    second_score = ranked_sources[1][1] if len(ranked_sources) > 1 else 0.0
    should_anchor = _should_anchor_to_focus_source(intent, primary_chunks)
    if not should_anchor:
        should_anchor = (
            top_score >= max(second_score * 1.12, second_score + 0.08)
            or (intent in {"definition", "guidance", "list"} and top_score >= 0.55)
        )

    if not should_anchor:
        return primary_chunks

    anchored = [dict(chunk) for chunk in top_chunks]
    if len({chunk.get("source_name") for chunk in anchored}) == 1:
        focus_page = anchored[0].get("page_number")
        if focus_page is not None and intent in {"definition", "list", "guidance", "explanation"}:
            anchored.sort(
                key=lambda item: (
                    abs((item.get("page_number") or focus_page) - focus_page),
                    -item.get("score", 0.0),
                    item.get("page_number") or focus_page,
                )
            )
        else:
            anchored.sort(
                key=lambda item: (
                    item.get("page_number") is None,
                    item.get("page_number") or 0,
                    -item.get("score", 0.0),
                )
            )
    anchored_limit = 6 if intent in {"definition", "list", "guidance", "comparison"} else 5
    return anchored[:anchored_limit] if len(anchored) >= 2 and top_source else primary_chunks


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


def _build_context(chunks: list[dict], question: str, intent: QuestionIntent) -> str:
    """Construye el bloque de contexto a partir de los chunks encontrados."""
    configured_max_len = max(settings.MAX_CHUNK_LENGTH, 180)
    if intent == "numeric":
        max_len = max(configured_max_len, 500)
    elif intent in {"definition", "list", "guidance"}:
        max_len = configured_max_len
    else:
        max_len = configured_max_len

    ordered_chunks = _dedupe_chunks(chunks)
    if len({chunk.get("source_name") for chunk in ordered_chunks if chunk.get("source_name")}) == 1:
        ordered_chunks = sorted(
            ordered_chunks,
            key=lambda item: (
                item.get("page_number") is None,
                item.get("page_number") or 0,
                -item.get("score", 0.0),
            ),
        )
    else:
        ordered_chunks = sorted(
            ordered_chunks,
            key=lambda item: item.get("score", 0.0),
            reverse=True,
        )

    parts = []
    for chunk in ordered_chunks:
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


def _build_intent_instructions(intent: QuestionIntent) -> str:
    """Reglas especificas de salida segun la intencion de la pregunta."""
    if intent == "definition":
        return (
            "Forma de responder: da primero una definicion directa en 1 o 2 frases. "
            "Si el contexto enumera fines, elementos o funciones, incluyelos todos de forma breve. "
            "No sustituyas la respuesta por el titulo de la unidad ni la reduzcas a uno o dos ejemplos si el material muestra mas."
        )
    if intent == "list":
        return (
            "Forma de responder: devuelve una lista breve y concreta. "
            "Incluye solo elementos explicitamente mencionados o claramente agrupados por el contexto. "
            "No inventes categorias nuevas."
        )
    if intent == "comparison":
        return (
            "Forma de responder: compara solo por los rasgos o funciones que aparecen en el contexto. "
            "No agregues analogias ni diferencias externas."
        )
    if intent == "guidance":
        return (
            "Forma de responder: si el material no da pasos literales, no inventes un metodo rigido ni una lista numerada. "
            "Resume como criterios, preguntas de reflexion o ideas que el material sugiere considerar. "
            "Puedes usar expresiones como 'segun el material' o 'el material sugiere'."
        )
    if intent == "numeric":
        return (
            "Forma de responder: extrae los datos numericos del contexto, muestra la relacion matematica minima necesaria y entrega el resultado final."
        )
    if intent == "explanation":
        return (
            "Forma de responder: explica con lenguaje directo en 1 o 2 parrafos cortos o en 3 puntos maximo. "
            "No uses metaforas, frases literarias ni cierres grandilocuentes."
        )
    return (
        "Forma de responder: explica con lenguaje directo, sin metaforas, sin tono ensayistico y sin convertir ideas generales en pasos si el contexto no lo hace."
    )


def _build_messages(question: str, context: str, intent: QuestionIntent) -> list[dict]:
    """Construye la lista de mensajes para enviar al LLM."""
    intent_instructions = _build_intent_instructions(intent)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Contexto de los materiales de estudio:\n\n"
                f"{context}\n\n---\n\n"
                f"Pregunta del estudiante: {question}\n\n"
                f"{intent_instructions}\n\n"
                "Responde solo con base en el contexto."
            ),
        },
    ]


def _build_verification_messages(
    question: str,
    context: str,
    draft_answer: str,
    intent: QuestionIntent,
) -> list[dict]:
    """Mensajes para una segunda pasada de verificacion."""
    return [
        {"role": "system", "content": VERIFICATION_PROMPT},
        {
            "role": "user",
            "content": (
                f"Pregunta:\n{question}\n\n"
                f"Contexto:\n{context}\n\n"
                f"Borrador a verificar:\n{draft_answer}\n\n"
                f"{_build_intent_instructions(intent)}\n\n"
                "Corrige cualquier error y devuelve la respuesta final."
            ),
        },
    ]


def _build_rewrite_messages(
    question: str,
    context: str,
    draft_answer: str,
    intent: QuestionIntent,
) -> list[dict]:
    """Mensajes para una pasada ligera de limpieza y reescritura."""
    return [
        {"role": "system", "content": REWRITE_PROMPT},
        {
            "role": "user",
            "content": (
                f"Pregunta:\n{question}\n\n"
                f"Contexto:\n{context}\n\n"
                f"Borrador a reescribir:\n{draft_answer}\n\n"
                f"{_build_intent_instructions(intent)}\n\n"
                "Reescribe y devuelve solo la respuesta final."
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
    unique_chunks = _dedupe_chunks(chunks)
    return [
        {
            "source_name": chunk["source_name"],
            "chunk_text": chunk["chunk_text"][:200] + "..." if len(chunk["chunk_text"]) > 200 else chunk["chunk_text"],
            "page_number": chunk.get("page_number"),
            "section": chunk.get("section"),
            "score": round(chunk.get("score", 0.0), 3),
        }
        for chunk in unique_chunks
    ]


def _answer_quality_score(answer: str, intent: QuestionIntent) -> float:
    cleaned = _sanitize_answer_text(answer)
    normalized = _normalize_text(cleaned)
    score = 0.0

    score += min(len(cleaned), 450) / 450.0
    if not _has_non_spanish_artifacts(cleaned):
        score += 0.35
    if not _has_meta_artifacts(answer):
        score += 0.25
    if intent in {"guidance", "explanation"} and not _NUMBERED_STEP_RE.search(cleaned):
        score += 0.10
    if intent == "definition" and any(cue in normalized for cue in _DEFINITION_CUES):
        score += 0.10
    if intent == "list" and ("\n" in cleaned or ":" in cleaned):
        score += 0.05
    return score


def _choose_best_answer(draft_answer: str, reviewed_answer: str, intent: QuestionIntent) -> str:
    draft_clean = _sanitize_answer_text(draft_answer)
    reviewed_clean = _sanitize_answer_text(reviewed_answer)
    if not reviewed_clean:
        return draft_clean

    reviewed_score = _answer_quality_score(reviewed_clean, intent)
    draft_score = _answer_quality_score(draft_clean, intent)
    if reviewed_score + 0.05 >= draft_score:
        return reviewed_clean
    return draft_clean


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
    question_intent = _detect_question_intent(clean_message)

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

    # Filtrar fuentes ficticias / narrativas para preguntas factuales
    chunks = _filter_fictional_chunks(chunks, question_intent)

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

    numeric_question = question_intent == "numeric"

    # Chequear confianza del retrieval ANTES del anchoring (los scores post-anchor son recalculados
    # y no reflejan que tan bien el vector search encontro la pregunta).
    retrieval_top_score = max((c.get("score", 0.0) for c in chunks[: max(top_k, 1)]), default=0.0)
    if not numeric_question and retrieval_top_score < settings.MIN_TOP_SCORE_TO_ANSWER:
        logger.info("Retrieval debil (top_score=%.3f < %.3f). Respondiendo NO_INFO sin LLM.",
                    retrieval_top_score, settings.MIN_TOP_SCORE_TO_ANSWER)
        primary_chunks = chunks[: max(top_k, 1)]
        sources_data = _build_sources_payload(primary_chunks)
        yield {"type": "sources", "sources": sources_data, "conversation_id": conversation_id}
        yield {"type": "token", "content": _NO_INFO_ANSWER}
        latency_ms = int((time.time() - start_time) * 1000)
        query_cache.set(clean_message, top_k, {"sources": sources_data, "answer": _NO_INFO_ANSWER})
        asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _safe_log(conversation_id, clean_message, _NO_INFO_ANSWER,
                              [c["source_name"] for c in primary_chunks], 0, 0, latency_ms),
        )
        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": latency_ms,
        }
        return

    primary_chunks = chunks[: max(top_k, 1)]
    primary_chunks = _anchor_primary_chunks(primary_chunks, clean_message, question_intent)
    low_confidence = _is_low_confidence(primary_chunks, top_k)

    if numeric_question:
        chunks = vector_store.expand_with_neighbors(
            primary_chunks[:1],
            limit=1,
            max_chunks=min(max(settings.MAX_CONTEXT_CHUNKS, 2), 3),
        )
    else:
        neighbor_limit = 1
        context_budget = max(settings.MAX_CONTEXT_CHUNKS, 2)
        if question_intent in {"definition", "list", "comparison"}:
            max_chunks = min(context_budget, max(top_k + 1, 4))
        else:
            max_chunks = min(context_budget, max(top_k + 1, 3))
        chunks = vector_store.expand_with_neighbors(
            primary_chunks,
            limit=neighbor_limit,
            max_chunks=max_chunks,
        )

    sources_data = _build_sources_payload(chunks)
    yield {"type": "sources", "sources": sources_data, "conversation_id": conversation_id}

    context = _build_context(chunks, clean_message, question_intent)
    messages = _build_messages(clean_message, context, question_intent)
    source_names = list({chunk["source_name"] for chunk in chunks})

    deliberate_mode = numeric_question or (
        low_confidence and question_intent in {"definition", "list", "comparison"}
    )
    # Siempre usar FAST. El escalado a MEDIUM lo hacia muy lento (>90s) y no
    # mejoraba calidad consistentemente. Mejor bloquear con NO_INFO cuando
    # el retrieval es pesimo (MIN_TOP_SCORE_TO_ANSWER).
    active_model = settings.OLLAMA_MODEL_FAST
    smart_model = settings.OLLAMA_MODEL_FAST
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
                active_model,
            )
            total_tokens_in += draft_stats.tokens_in
            total_tokens_out += draft_stats.tokens_out

            draft_answer = _sanitize_answer_text(draft_answer)
            answer_text = draft_answer
            if numeric_question or _answer_needs_revision(draft_answer, question_intent, low_confidence):
                if numeric_question or question_intent in {"definition", "list", "comparison"}:
                    smart_model = await _resolve_smart_model()
                    review_messages = _build_verification_messages(
                        clean_message,
                        context,
                        draft_answer,
                        question_intent,
                    )
                    review_model = smart_model
                else:
                    review_messages = _build_rewrite_messages(
                        clean_message,
                        context,
                        draft_answer,
                        question_intent,
                    )
                    review_model = active_model

                reviewed_answer, review_stats = await _collect_model_response(
                    review_messages,
                    review_model,
                )
                total_tokens_in += review_stats.tokens_in
                total_tokens_out += review_stats.tokens_out
                answer_text = _choose_best_answer(draft_answer, reviewed_answer, question_intent)

            for piece in _stream_text(answer_text):
                yield {"type": "token", "content": piece}
        else:
            answer_parts: list[str] = []
            stats = LLMStats()
            async for token, token_stats in ollama_client.stream_chat(
                messages,
                model=active_model,
            ):
                if token_stats:
                    stats = token_stats
                if token:
                    answer_parts.append(token)
                    yield {"type": "token", "content": token}
            total_tokens_in += stats.tokens_in
            total_tokens_out += stats.tokens_out
            answer_text = _sanitize_answer_text("".join(answer_parts).strip())
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
