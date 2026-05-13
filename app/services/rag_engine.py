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
AnswerLanguage = str

SYSTEM_PROMPT = """Eres un asistente educativo. SOLO puedes usar la informacion del contexto entregado (materiales del curso). No tienes acceso a ningun otro conocimiento.

REGLAS ABSOLUTAS:
1. PROHIBIDO inventar datos, ejemplos, definiciones o explicaciones que no esten LITERALMENTE en el contexto.
2. Si el contexto NO contiene la respuesta a la pregunta, responde EXACTAMENTE: "No encontre informacion sobre eso en los materiales de estudio. Consulta a tu docente." y nada mas.
3. PROHIBIDO usar conocimiento general (ej. saber que los colores primarios son rojo/azul/amarillo) si no aparece en el contexto. Si no aparece, di que no hay informacion.
4. Responde SIEMPRE en espanol claro, breve y didactico. NUNCA mezcles ingles.
5. Si la pregunta pide una lista, enumera solo los puntos que aparezcan en el contexto.
6. Si la pregunta implica calculos, extrae los datos del contexto, aplica la formula y revisa la cuenta.
7. Si el contexto trae fragmentos de cuentos o narrativa, NO los uses para preguntas de concepto; usalos solo si la pregunta es sobre el texto literario.
8. Ignora ruido de OCR (caracteres raros, palabras pegadas, simbolos repetidos). Si el contexto se ve corrupto y no es legible, di que no hay informacion.
9. NUNCA termines a media frase. Cierra siempre la idea antes del final."""

SYSTEM_PROMPT_EN = """You are an expert educational assistant. Your job is to answer using ONLY the provided course-material context.

Rules:
1. Answer only with information supported by the context.
2. If the context is not enough to answer safely, say so clearly.
3. Prioritize the most direct and clear fragments; ignore OCR noise or confusing text.
4. Answer in clear, brief, natural English.
5. If the question asks for a list, list only points that appear in the context.
6. If the question involves calculations, extract the data from the context, apply the appropriate formula, and check the result.
7. Do not invent information or fill gaps with outside knowledge.
8. If the context contains fictional stories, narrative, or dialogue, do NOT use them to answer real-world concept questions; use them only if the question is about the literary text itself."""

VERIFICATION_PROMPT = """Eres un verificador de respuestas educativas.

Tu tarea:
1. Releer la pregunta, el contexto y el borrador.
2. Detectar cualquier afirmacion no sustentada.
3. Si hay calculos, rehacerlos solo con los datos del contexto.
4. Corregir el borrador si es necesario.
5. No incluyas frases meta como "la respuesta final es", notas sobre el borrador ni comentarios del sistema.
6. Devuelve una respuesta final limpia en el idioma indicado, breve y natural.

Devuelve solo la respuesta final correcta, clara y basada en el contexto."""

VERIFICATION_PROMPT_EN = """You are an educational answer verifier.

Your task:
1. Reread the question, context, and draft.
2. Detect any unsupported claim.
3. If there are calculations, redo them using only the context.
4. Correct the draft if needed.
5. Do not include meta phrases, draft notes, or system comments.
6. Return a clean final answer in English, brief and natural.

Return only the final answer, clear and based on the context."""

REWRITE_PROMPT = """Eres editor de respuestas educativas.

Tu tarea:
1. Reescribir el borrador en el idioma indicado, claro y natural.
2. Mantener solo la informacion sustentada en el contexto.
3. Eliminar frases meta, notas sobre el borrador y cualquier mezcla con otro idioma.
4. Si la pregunta es de orientacion, expresa criterios o ideas del material, no inventes pasos si el contexto no los enumera.

Devuelve solo la respuesta final."""

REWRITE_PROMPT_EN = """You are an educational answer editor.

Your task:
1. Rewrite the draft in clear, natural English.
2. Keep only information supported by the context.
3. Remove meta phrases, draft notes, and any unnecessary language mixing.
4. If the question asks for guidance, express criteria or ideas from the material; do not invent rigid steps if the context does not list them.

Return only the final answer."""

_NO_INFO_ANSWERS = {
    "es": (
        "No encontre informacion suficiente sobre eso en los materiales de estudio disponibles. "
        "Consulta a tu docente o revisa directamente los documentos del curso."
    ),
    "en": (
        "I could not find enough information about that in the available study materials. "
        "Ask your teacher or review the course documents directly."
    ),
}
_LANGUAGE_CAPABILITY_ANSWERS = {
    "es": "Si. Puedes hacerme preguntas sobre los materiales de estudio y te respondere en espanol o en ingles.",
    "en": "Yes. Ask me about the study materials, and I will answer in English using only the available course context.",
}
_ENGLISH_TO_SPANISH_RETRIEVAL_ALIASES = {
    "abiotic": "abiotico abioticos factores abioticos",
    "cardinal": "puntos cardinales direcciones cardinales orientacion",
    "citizenship": "ciudadania ciudadano",
    "democracy": "democracia",
    "digestive": "sistema digestivo digestion",
    "directions": "direcciones orientacion ubicacion",
    "ecosystem": "ecosistema",
    "emotions": "emociones",
    "explanatory": "texto explicativo",
    "photosynthesis": "fotosintesis plantas alimento",
    "plants": "plantas reino vegetal",
    "points": "puntos",
    "rights": "derechos",
    "software": "software informatica",
    "windows": "windows sistema operativo informatica",
}
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
_resolved_english_model: str | None = None
_resolved_english_model_checked = False
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
_LANG_TOKEN_RE = re.compile(r"[a-z]{2,}")
_LANGUAGE_DIRECTIVE_RE = re.compile(
    r"\b(answer|respond|reply|please answer|please respond)\s+(in\s+)?(english|spanish)\b"
    r"|\b(in english|english please|in spanish|spanish please)\b"
    r"|\b(responde|contesta|contestame|respondeme)\s+en\s+(ingles|espanol)\b"
    r"|\ben\s+(ingles|espanol)\b",
    re.IGNORECASE,
)
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
# Patrones de preguntas claramente fuera del scope educativo del KB.
# Los detectamos antes de embedding/LLM para devolver NO_INFO instantaneo.
_OFF_TOPIC_PATTERNS = (
    "que tal el clima", "como esta el clima", "el clima de hoy", "weather",
    "cuentame un chiste", "tell me a joke", "dime un chiste", "joke", "chiste",
    "que opinas de", "que piensas de", "what do you think about",
    "hora es", "que hora es", "what time is",
    "como te llamas", "cual es tu nombre", "what is your name", "who are you",
    "quien eres", "que eres",
    "ignora tus instrucciones", "olvida tus instrucciones",
    "ignore your instructions", "forget your instructions",
    "actua como", "pretend you are", "roleplay",
    "presidente de", "president of", "candidato",
    "receta de", "como cocinar", "how to cook", "recipe",
    "futbol", "messi", "ronaldo",
    "pelicula", "movie", "netflix",
    "musica", "cancion de", "song by",
)
# Patrones de jailbreak / prompt injection — bloqueo estricto.
_JAILBREAK_HINTS = (
    "ignora", "ignore", "olvida", "forget",
    "system prompt", "prompt del sistema",
    "actua como", "pretend",
    "responde sin restricciones", "respond without restrictions",
    "no uses el contexto", "without context",
)
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
    "what actions", "what phenomena", "what topics", "what elements", "which are",
    "list",
)
_DEFINITION_HINTS = (
    "que es", "qué es", "que son", "qué son", "en que consiste", "en qué consiste",
    "what is", "what are", "define",
)
_COMPARISON_HINTS = (
    "diferencia entre", "cual es la diferencia", "cuál es la diferencia",
    "relacion existe", "relación existe", "compar", "similitud",
    "difference between", "what is the difference", "relationship between",
    "compare", "similarity",
)
_GUIDANCE_HINTS = (
    "como analizar", "cómo analizar", "como decir", "cómo decir", "como actuar",
    "cómo actuar", "como responder", "cómo responder", "como enfrentar", "cómo enfrentar",
    "como manejar", "cómo manejar", "como tomar", "cómo tomar",
    "how to analyze", "how to say", "how to act", "how to answer",
    "how to handle", "how to decide",
)
_ENGLISH_RESPONSE_HINTS = (
    "answer in english", "respond in english", "reply in english", "in english",
    "english please", "please answer in english", "please respond in english",
    "responde en ingles", "respondeme en ingles", "contestame en ingles",
    "contesta en ingles", "en ingles",
)
_SPANISH_RESPONSE_HINTS = (
    "answer in spanish", "respond in spanish", "reply in spanish", "in spanish",
    "spanish please", "responde en espanol", "respondeme en espanol",
    "contestame en espanol", "contesta en espanol", "en espanol",
)
_LANGUAGE_CAPABILITY_HINTS = (
    "can you speak english", "do you speak english", "can you answer in english",
    "can you respond in english", "speak english", "puedes hablar en ingles",
    "puedes responder en ingles", "puede responder en ingles", "hablas ingles",
    "sabes ingles",
)
_ENGLISH_QUESTION_WORDS = {
    "what", "why", "how", "when", "where", "which", "who", "define", "explain",
    "list", "give", "tell", "according", "material", "course", "study", "does",
    "are", "is", "can", "should",
}
_SPANISH_QUESTION_WORDS = {
    "que", "cual", "cuales", "como", "cuando", "donde", "quien", "quienes",
    "define", "explica", "dame", "segun", "material", "curso", "estudio",
    "puedes", "puede", "son", "esta",
}
_ENGLISH_LANGUAGE_MARKERS = {
    "the", "is", "are", "and", "or", "to", "of", "in", "for", "with",
    "from", "as", "it", "they", "this", "these", "that", "those", "can",
    "must", "should", "because", "according", "context", "means", "refers",
    "includes", "uses", "used", "helps", "allows", "north", "south", "east",
    "west", "not", "information", "available", "study", "materials",
}
_SPANISH_LANGUAGE_MARKERS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "es", "son",
    "ser", "esta", "estan", "este", "estos", "estas", "que", "como", "para",
    "por", "con", "segun", "contexto", "se", "del", "al", "permite",
    "permiten", "puede", "pueden", "debe", "deben", "cuando", "donde",
    "cuales", "tambien", "porque", "sirve", "consiste", "puntos",
    "cardinales", "norte", "sur", "este", "oeste", "fotosintesis",
    "democracia", "ciudadania", "informacion", "materiales", "disponibles",
}
_SPANISH_START_RE = re.compile(
    r"^\s*(los|las|el|la|un|una|segun|de acuerdo con|para|en el|en la)\b",
    re.IGNORECASE,
)
_SPANISH_CHAR_RE = re.compile(r"[\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00bf\u00a1]|\u00c3|\u00c2", re.IGNORECASE)
_COMPASS_TRANSLATION_ARTIFACTS = (
    ("northeast", "(n"),
    ("north-east", "(n"),
    ("southwest", "(s"),
    ("south-west", "(s"),
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


def _detect_answer_language(question: str) -> AnswerLanguage:
    """Detecta si conviene responder en ingles sin cargar librerias extra."""
    # Si el modo estricto esta activo, siempre respondemos en espanol.
    # Razon: los modelos pequenos (qwen2.5:0.5b) mezclan idiomas y rompen continuidad.
    if getattr(settings, "STRICT_SPANISH_ONLY", False):
        return "es"

    normalized = _normalize_text(question)
    if any(hint in normalized for hint in _ENGLISH_RESPONSE_HINTS):
        return "en"
    if any(hint in normalized for hint in _SPANISH_RESPONSE_HINTS):
        return "es"

    tokens = set(_LANG_TOKEN_RE.findall(normalized))
    english_hits = len(tokens & _ENGLISH_QUESTION_WORDS)
    spanish_hits = len(tokens & _SPANISH_QUESTION_WORDS)
    if english_hits >= 2 and english_hits > spanish_hits:
        return "en"
    if normalized.startswith(("what ", "why ", "how ", "when ", "where ", "which ", "who ")):
        return "en"
    return "es"


def _strip_language_directives(question: str) -> str:
    """Quita instrucciones de idioma antes del retrieval para no contaminar la busqueda."""
    cleaned = _LANGUAGE_DIRECTIVE_RE.sub(" ", question)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:¿?¡!")
    return cleaned or question


def _expand_retrieval_message(question: str, answer_language: AnswerLanguage) -> str:
    """Agrega alias en espanol para consultas en ingles sin usar otro modelo."""
    if answer_language != "en":
        return question

    normalized = _normalize_text(question)
    tokens = set(_LANG_TOKEN_RE.findall(normalized))
    aliases = [
        alias
        for term, alias in _ENGLISH_TO_SPANISH_RETRIEVAL_ALIASES.items()
        if term in tokens
    ]
    if not aliases:
        return question
    return f"{question} {' '.join(aliases)}"


def _system_prompt(answer_language: AnswerLanguage) -> str:
    return SYSTEM_PROMPT_EN if answer_language == "en" else SYSTEM_PROMPT


def _verification_prompt(answer_language: AnswerLanguage) -> str:
    return VERIFICATION_PROMPT_EN if answer_language == "en" else VERIFICATION_PROMPT


def _rewrite_prompt(answer_language: AnswerLanguage) -> str:
    return REWRITE_PROMPT_EN if answer_language == "en" else REWRITE_PROMPT


def _language_instruction(answer_language: AnswerLanguage) -> str:
    if answer_language == "en":
        return (
            "Required answer language: English. The final answer MUST be in English, even if the context is in Spanish. "
            "Do not answer in Spanish. Translate Spanish source content faithfully into English, without changing concepts. "
            "Use North for Norte, South for Sur, East for Este, and West for Oeste. "
            "Keep source-grounding strict and do not add outside knowledge."
        )
    return (
        "Idioma de respuesta: espanol. Responde en espanol claro y natural. "
        "Mantente estrictamente dentro del contexto."
    )


def _no_info_answer(answer_language: AnswerLanguage) -> str:
    return _NO_INFO_ANSWERS.get(answer_language, _NO_INFO_ANSWERS["es"])


def _is_language_capability_request(question: str) -> bool:
    normalized = _normalize_text(question).strip(" ?!._-")
    return any(hint in normalized for hint in _LANGUAGE_CAPABILITY_HINTS)


def _is_off_topic_question(question: str) -> bool:
    """Detecta preguntas claramente fuera del scope educativo del KB.

    Bloquea ANTES de embedding+LLM para ahorrar compute y dar respuesta instantanea.
    """
    normalized = _normalize_text(question)
    if any(pattern in normalized for pattern in _OFF_TOPIC_PATTERNS):
        return True
    # Jailbreak attempts: combinacion de hints sospechosos
    jailbreak_hits = sum(1 for h in _JAILBREAK_HINTS if h in normalized)
    if jailbreak_hits >= 2:
        return True
    return False


def _build_history_block(history: list[dict] | None, answer_language: AnswerLanguage) -> str:
    """Construye un bloque corto con los ultimos turnos de conversacion.

    Devuelve cadena vacia si no hay historia. Limita cada turno para no inflar el prompt.
    """
    if not history:
        return ""
    label_q = "Question" if answer_language == "en" else "Pregunta"
    label_a = "Answer" if answer_language == "en" else "Respuesta"
    parts: list[str] = []
    for turn in history[-2:]:  # Maximo 2 turnos previos
        q = (turn.get("question") or "").strip()[:200]
        a = (turn.get("answer") or "").strip()[:300]
        if not q or not a:
            continue
        parts.append(f"{label_q}: {q}\n{label_a}: {a}")
    if not parts:
        return ""
    header = "Previous turns (for context only — answer the new question):" if answer_language == "en" \
        else "Turnos previos (solo para contexto — responde la pregunta nueva):"
    return f"{header}\n\n" + "\n\n".join(parts) + "\n\n---\n\n"


def _language_capability_answer(answer_language: AnswerLanguage) -> str:
    return _LANGUAGE_CAPABILITY_ANSWERS.get(answer_language, _LANGUAGE_CAPABILITY_ANSWERS["es"])


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


def _language_marker_counts(answer: str) -> tuple[int, int]:
    normalized = _normalize_text(answer)
    tokens = _LANG_TOKEN_RE.findall(normalized)
    english_hits = sum(1 for token in tokens if token in _ENGLISH_LANGUAGE_MARKERS)
    spanish_hits = sum(1 for token in tokens if token in _SPANISH_LANGUAGE_MARKERS)
    if _SPANISH_START_RE.search(normalized):
        spanish_hits += 2
    if _SPANISH_CHAR_RE.search(answer):
        spanish_hits += 1
    return english_hits, spanish_hits


def _answer_language_mismatch(answer: str, answer_language: AnswerLanguage) -> bool:
    """Detecta cuando el borrador quedo en otro idioma, sin llamar otro modelo."""
    cleaned = _sanitize_answer_text(answer)
    if not cleaned:
        return True

    english_hits, spanish_hits = _language_marker_counts(cleaned)
    normalized = _normalize_text(cleaned)

    if answer_language == "en":
        if any(hint in normalized for hint in _UNCERTAIN_ANSWER_HINTS):
            return True
        if spanish_hits >= 4 and spanish_hits > english_hits:
            return True
        if spanish_hits >= 3 and english_hits < 3:
            return True
        return False

    if english_hits >= 6 and english_hits > spanish_hits + 2:
        return True
    return False


def _has_translation_artifacts(answer: str, context: str, answer_language: AnswerLanguage) -> bool:
    """Atrapa errores de traduccion comunes que cambian el concepto."""
    if answer_language != "en":
        return False

    normalized_answer = _normalize_text(answer)
    if not normalized_answer:
        return False

    normalized_context = _normalize_text(context)
    has_compass_context = (
        "norte" in normalized_context
        or "sur" in normalized_context
        or "cardinal" in normalized_answer
        or "direction" in normalized_answer
    )
    return has_compass_context and any(
        word in normalized_answer and marker in normalized_answer
        for word, marker in _COMPASS_TRANSLATION_ARTIFACTS
    )


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


def _solve_special_numeric_case(
    question: str,
    context: str,
    answer_language: AnswerLanguage = "es",
) -> str | None:
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

    if answer_language == "en":
        return (
            "The total cable length is approximately "
            f"{cable:.2f} meters, because the total vertical distance is {height:g} + {depth:g} = {vertical:g} meters "
            f"and the Pythagorean theorem is applied: sqrt({vertical:g}^2 + {horizontal:g}^2)."
        )
    return (
        "La longitud total del cable es aproximadamente "
        f"{cable:.2f} metros, porque la distancia vertical total es {height:g} + {depth:g} = {vertical:g} metros "
        f"y se aplica Pitagoras: sqrt({vertical:g}^2 + {horizontal:g}^2)."
    )


async def _resolve_smart_model() -> str:
    """Devuelve el modelo configurado para verificacion/reescritura.

    Si el usuario configuro OLLAMA_MODEL_SMART (incluso igual a FAST), se respeta.
    Antes esto disparaba un fallback a llama3.1:8b que era 8x mas lento e
    inconsistente con el resto de la pipeline.
    """
    if settings.OLLAMA_MODEL_SMART:
        return settings.OLLAMA_MODEL_SMART
    return settings.OLLAMA_MODEL_FAST


def _model_is_installed(model: str, installed: set[str]) -> bool:
    return model in installed or (":" not in model and f"{model}:latest" in installed)


async def _resolve_answer_model(answer_language: AnswerLanguage) -> str:
    """Usa un modelo dedicado para ingles si esta configurado e instalado."""
    if answer_language != "en":
        return settings.OLLAMA_MODEL_FAST

    configured = settings.OLLAMA_MODEL_ENGLISH
    if not configured or configured == settings.OLLAMA_MODEL_FAST:
        return settings.OLLAMA_MODEL_FAST

    global _resolved_english_model
    global _resolved_english_model_checked

    if _resolved_english_model_checked:
        return _resolved_english_model or settings.OLLAMA_MODEL_FAST

    _resolved_english_model_checked = True
    try:
        available, installed = await ollama_client.check_models_status()
        if available and _model_is_installed(configured, installed):
            _resolved_english_model = configured
        else:
            logger.warning(
                "Modelo de ingles '%s' no encontrado. Se usara '%s'.",
                configured,
                settings.OLLAMA_MODEL_FAST,
            )
    except Exception:
        _resolved_english_model = None

    return _resolved_english_model or settings.OLLAMA_MODEL_FAST


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


def _build_intent_instructions(
    intent: QuestionIntent,
    answer_language: AnswerLanguage = "es",
) -> str:
    """Reglas especificas de salida segun la intencion de la pregunta."""
    if answer_language == "en":
        if intent == "definition":
            return (
                "Answer format: start with a direct definition in 1 or 2 sentences. "
                "If the context lists purposes, elements, or functions, include them briefly. "
                "Do not replace the answer with a unit title or reduce it to examples if the material gives more."
            )
        if intent == "list":
            return (
                "Answer format: give a brief, concrete list. "
                "Include only elements explicitly mentioned or clearly grouped by the context. "
                "Do not invent categories."
            )
        if intent == "comparison":
            return (
                "Answer format: compare only the traits or functions that appear in the context. "
                "Do not add external analogies or differences."
            )
        if intent == "guidance":
            return (
                "Answer format: if the material does not give literal steps, do not invent a rigid method or numbered list. "
                "Summarize the criteria, reflection questions, or ideas suggested by the material."
            )
        if intent == "numeric":
            return (
                "Answer format: extract the numerical data from the context, show the minimal mathematical relation needed, and give the final result."
            )
        if intent == "explanation":
            return (
                "Answer format: explain directly in 1 or 2 short paragraphs or at most 3 points. "
                "Avoid metaphors, literary phrasing, and grand closing statements."
            )
        return (
            "Answer format: explain directly, without metaphors or essay-like tone, and do not turn general ideas into steps unless the context does so."
        )

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


def _build_messages(
    question: str,
    context: str,
    intent: QuestionIntent,
    answer_language: AnswerLanguage,
    history: list[dict] | None = None,
) -> list[dict]:
    """Construye la lista de mensajes para enviar al LLM."""
    intent_instructions = _build_intent_instructions(intent, answer_language)
    language_instruction = _language_instruction(answer_language)
    history_block = _build_history_block(history, answer_language)
    return [
        {"role": "system", "content": _system_prompt(answer_language)},
        {
            "role": "user",
            "content": (
                f"{history_block}"
                f"{'Study-material context' if answer_language == 'en' else 'Contexto de los materiales de estudio'}:\n\n"
                f"{context}\n\n---\n\n"
                f"{'Student question' if answer_language == 'en' else 'Pregunta del estudiante'}: {question}\n\n"
                f"{language_instruction}\n\n"
                f"{intent_instructions}\n\n"
                f"{'Answer only based on the context.' if answer_language == 'en' else 'Responde solo con base en el contexto.'}"
            ),
        },
    ]


def _build_verification_messages(
    question: str,
    context: str,
    draft_answer: str,
    intent: QuestionIntent,
    answer_language: AnswerLanguage,
) -> list[dict]:
    """Mensajes para una segunda pasada de verificacion."""
    if answer_language == "en":
        user_content = (
            f"Student question:\n{question}\n\n"
            f"Study-material context:\n{context}\n\n"
            f"Draft answer to verify:\n{draft_answer}\n\n"
            f"{_language_instruction(answer_language)}\n\n"
            f"{_build_intent_instructions(intent, answer_language)}\n\n"
            "Correct any error and return only the final answer in English."
        )
    else:
        user_content = (
            f"Pregunta:\n{question}\n\n"
            f"Contexto:\n{context}\n\n"
            f"Borrador a verificar:\n{draft_answer}\n\n"
            f"{_language_instruction(answer_language)}\n\n"
            f"{_build_intent_instructions(intent, answer_language)}\n\n"
            "Corrige cualquier error y devuelve la respuesta final."
        )
    return [
        {"role": "system", "content": _verification_prompt(answer_language)},
        {"role": "user", "content": user_content},
    ]


def _build_rewrite_messages(
    question: str,
    context: str,
    draft_answer: str,
    intent: QuestionIntent,
    answer_language: AnswerLanguage,
) -> list[dict]:
    """Mensajes para una pasada ligera de limpieza y reescritura."""
    if answer_language == "en":
        user_content = (
            f"Student question:\n{question}\n\n"
            f"Study-material context:\n{context}\n\n"
            f"Draft answer to rewrite:\n{draft_answer}\n\n"
            f"{_language_instruction(answer_language)}\n\n"
            f"{_build_intent_instructions(intent, answer_language)}\n\n"
            "Rewrite it and return only the final answer in English."
        )
    else:
        user_content = (
            f"Pregunta:\n{question}\n\n"
            f"Contexto:\n{context}\n\n"
            f"Borrador a reescribir:\n{draft_answer}\n\n"
            f"{_language_instruction(answer_language)}\n\n"
            f"{_build_intent_instructions(intent, answer_language)}\n\n"
            "Reescribe y devuelve solo la respuesta final."
        )
    return [
        {"role": "system", "content": _rewrite_prompt(answer_language)},
        {"role": "user", "content": user_content},
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


def _answer_quality_score(
    answer: str,
    intent: QuestionIntent,
    answer_language: AnswerLanguage = "es",
) -> float:
    cleaned = _sanitize_answer_text(answer)
    normalized = _normalize_text(cleaned)
    score = 0.0

    score += min(len(cleaned), 450) / 450.0
    if not _answer_language_mismatch(cleaned, answer_language):
        score += 0.70
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


def _is_answer_grounded(
    answer: str,
    context: str,
    intent: QuestionIntent,
    answer_language: AnswerLanguage,
) -> bool:
    """Verifica que el contenido factual de la respuesta aparezca en el contexto.

    Idea: si el modelo invento conceptos (ej. "rojo, verde" como colores primarios
    cuando el contexto no los menciona), pocos tokens de la respuesta van a aparecer
    literalmente en el contexto. Con un umbral conservador atrapamos alucinaciones
    sin romper respuestas legitimas (parafraseo permitido).
    """
    cleaned = _sanitize_answer_text(answer)
    if not cleaned:
        return True

    normalized_answer = _normalize_text(cleaned)
    # No verificar respuestas-meta cortas (NO_INFO, "si puedo hablar ingles", etc.)
    if any(hint in normalized_answer for hint in _UNCERTAIN_ANSWER_HINTS):
        return True
    if any(hint in normalized_answer for hint in (
        "no encontre informacion",
        "no hay informacion",
        "consulta a tu docente",
        "could not find enough information",
        "ask your teacher",
    )):
        return True
    # Numerico: la respuesta puede contener calculos derivados, no exigir overlap literal.
    if intent == "numeric":
        return True

    normalized_context = _normalize_text(context)
    answer_tokens = [
        t for t in _TEXT_TOKEN_RE.findall(normalized_answer)
        if t not in _STOPWORDS and t not in _ENGLISH_LANGUAGE_MARKERS and len(t) >= 5
    ]
    unique_tokens = list(dict.fromkeys(answer_tokens))
    # Respuestas muy cortas no se pueden juzgar por overlap
    if len(unique_tokens) < 5:
        return True

    grounded_tokens = [t for t in unique_tokens if t in normalized_context]
    overlap = len(grounded_tokens) / len(unique_tokens)

    # Umbral: 35% de tokens significativos deben aparecer literal en el contexto.
    # Conservador para no romper parafraseo, suficiente para atrapar invenciones.
    if overlap < 0.35:
        logger.info(
            "Grounding bajo (%.2f, %d/%d tokens). Posible alucinacion.",
            overlap, len(grounded_tokens), len(unique_tokens),
        )
        return False
    return True


def _choose_best_answer(
    draft_answer: str,
    reviewed_answer: str,
    intent: QuestionIntent,
    answer_language: AnswerLanguage = "es",
) -> str:
    draft_clean = _sanitize_answer_text(draft_answer)
    reviewed_clean = _sanitize_answer_text(reviewed_answer)
    if not reviewed_clean:
        return draft_clean

    reviewed_score = _answer_quality_score(reviewed_clean, intent, answer_language)
    draft_score = _answer_quality_score(draft_clean, intent, answer_language)
    if reviewed_score + 0.05 >= draft_score:
        return reviewed_clean
    return draft_clean


async def query(
    message: str,
    conversation_id: str | None = None,
    top_k: int | None = None,
    history: list[dict] | None = None,
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
    answer_language = _detect_answer_language(clean_message)
    retrieval_message = _strip_language_directives(clean_message)
    question_intent = _detect_question_intent(retrieval_message)
    retrieval_message = _expand_retrieval_message(retrieval_message, answer_language)

    # Memoria conversacional: si el cliente no envio historia explicita, reconstruir
    # los ultimos 2 turnos desde los logs (ayuda con preguntas como "y por que?" o
    # "explicalo mas simple" que dependen de la pregunta anterior).
    if history is None and conversation_id:
        try:
            history = log_store.get_recent_turns(conversation_id, limit=2)
        except Exception as exc:
            logger.debug("No se pudo cargar historia previa: %s", exc)
            history = None

    # Filtro off-topic / jailbreak: bloquear ANTES del embedding+LLM para ahorrar compute.
    if _is_off_topic_question(clean_message):
        logger.info("Pregunta off-topic detectada. NO_INFO sin tocar Ollama.")
        answer_text = _no_info_answer(answer_language)
        yield {"type": "sources", "sources": [], "conversation_id": conversation_id}
        yield {"type": "token", "content": answer_text}
        latency_ms = int((time.time() - start_time) * 1000)
        # Negative cache: cachear tambien las NO_INFO para que repeticiones sean instantaneas
        query_cache.set(clean_message, top_k, {"sources": [], "answer": answer_text})
        asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _safe_log(conversation_id, clean_message, answer_text, [], 0, 0, latency_ms),
        )
        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": latency_ms,
        }
        return

    if _is_language_capability_request(clean_message):
        answer_text = _language_capability_answer(answer_language)
        yield {"type": "sources", "sources": [], "conversation_id": conversation_id}
        yield {"type": "token", "content": answer_text}
        latency_ms = int((time.time() - start_time) * 1000)
        asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _safe_log(conversation_id, clean_message, answer_text, [], 0, 0, latency_ms),
        )
        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": latency_ms,
        }
        return

    cached = query_cache.get(clean_message, top_k)
    if cached:
        cached_answer = cached.get("answer", "")
        if (
            _answer_language_mismatch(cached_answer, answer_language)
            or _has_translation_artifacts(cached_answer, "", answer_language)
        ):
            logger.info("Ignorando cache por idioma incorrecto para: %.60s", clean_message)
        else:
            logger.info("Respondiendo desde cache para: %.60s", clean_message)
            yield {
                "type": "sources",
                "sources": cached["sources"],
                "conversation_id": conversation_id,
            }
            yield {"type": "token", "content": cached_answer}
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
        query_embedding = await embedder.embed_query_async(retrieval_message)
    except Exception as e:
        logger.error("Error generando embedding: %s", e)
        yield {"type": "error", "error": "Error procesando la consulta"}
        return

    try:
        chunks = vector_store.search(query_embedding, query_text=retrieval_message, top_k=top_k)
        if not chunks and top_k < 8:
            chunks = vector_store.search(query_embedding, query_text=retrieval_message, top_k=8)
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
        answer_text = _no_info_answer(answer_language)
        yield {"type": "sources", "sources": [], "conversation_id": conversation_id}
        yield {"type": "token", "content": answer_text}
        latency_ms = int((time.time() - start_time) * 1000)
        # Negative cache: que repeticiones sean instantaneas
        query_cache.set(clean_message, top_k, {"sources": [], "answer": answer_text})
        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": latency_ms,
        }
        asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _safe_log(conversation_id, clean_message, answer_text, [], 0, 0, latency_ms),
        )
        return

    numeric_question = question_intent == "numeric"

    # Chequear confianza del retrieval ANTES del anchoring (los scores post-anchor son recalculados
    # y no reflejan que tan bien el vector search encontro la pregunta).
    retrieval_top_score = max((c.get("score", 0.0) for c in chunks[: max(top_k, 1)]), default=0.0)
    # Promedio de los top chunks: si solo hay 1 chunk decente y el resto basura,
    # probablemente no hay info real para responder y el LLM va a alucinar.
    top_scores = [c.get("score", 0.0) for c in chunks[: max(top_k, 1)]]
    avg_top_score = sum(top_scores) / len(top_scores) if top_scores else 0.0
    weak_avg = avg_top_score < (settings.MIN_TOP_SCORE_TO_ANSWER * 0.6)

    weak_retrieval = retrieval_top_score < settings.MIN_TOP_SCORE_TO_ANSWER or weak_avg
    if not numeric_question and weak_retrieval:
        logger.info("Retrieval debil (top=%.3f avg=%.3f < umbral=%.3f). NO_INFO sin LLM.",
                    retrieval_top_score, avg_top_score, settings.MIN_TOP_SCORE_TO_ANSWER)
        primary_chunks = chunks[: max(top_k, 1)]
        sources_data = _build_sources_payload(primary_chunks)
        answer_text = _no_info_answer(answer_language)
        yield {"type": "sources", "sources": sources_data, "conversation_id": conversation_id}
        yield {"type": "token", "content": answer_text}
        latency_ms = int((time.time() - start_time) * 1000)
        query_cache.set(clean_message, top_k, {"sources": sources_data, "answer": answer_text})
        asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _safe_log(conversation_id, clean_message, answer_text,
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
    primary_chunks = _anchor_primary_chunks(primary_chunks, retrieval_message, question_intent)
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

    context = _build_context(chunks, retrieval_message, question_intent)
    messages = _build_messages(clean_message, context, question_intent, answer_language, history=history)
    source_names = list({chunk["source_name"] for chunk in chunks})

    deliberate_mode = answer_language == "en" or numeric_question or (
        low_confidence and question_intent in {"definition", "list", "comparison"}
    )
    # Siempre usar FAST. El escalado a MEDIUM lo hacia muy lento (>90s) y no
    # mejoraba calidad consistentemente. Mejor bloquear con NO_INFO cuando
    # el retrieval es pesimo (MIN_TOP_SCORE_TO_ANSWER).
    active_model = await _resolve_answer_model(answer_language)
    smart_model = active_model
    total_tokens_in = 0
    total_tokens_out = 0

    try:
        if deliberate_mode:
            deterministic_answer = (
                _solve_special_numeric_case(retrieval_message, context, answer_language)
                if numeric_question
                else None
            )
            if deterministic_answer:
                answer_text = deterministic_answer
                for piece in _stream_text(answer_text):
                    yield {"type": "token", "content": piece}
                latency_ms = int((time.time() - start_time) * 1000)
                query_cache.set(clean_message, top_k, {"sources": sources_data, "answer": answer_text})
                asyncio.get_running_loop().run_in_executor(
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
            needs_language_revision = (
                _answer_language_mismatch(draft_answer, answer_language)
                or _has_translation_artifacts(draft_answer, context, answer_language)
            )
            if needs_language_revision or numeric_question or _answer_needs_revision(draft_answer, question_intent, low_confidence):
                if needs_language_revision:
                    review_messages = _build_rewrite_messages(
                        clean_message,
                        context,
                        draft_answer,
                        question_intent,
                        answer_language,
                    )
                    review_model = active_model
                elif numeric_question or question_intent in {"definition", "list", "comparison"}:
                    smart_model = active_model if answer_language == "en" else await _resolve_smart_model()
                    review_messages = _build_verification_messages(
                        clean_message,
                        context,
                        draft_answer,
                        question_intent,
                        answer_language,
                    )
                    review_model = smart_model
                else:
                    review_messages = _build_rewrite_messages(
                        clean_message,
                        context,
                        draft_answer,
                        question_intent,
                        answer_language,
                    )
                    review_model = active_model

                reviewed_answer, review_stats = await _collect_model_response(
                    review_messages,
                    review_model,
                )
                total_tokens_in += review_stats.tokens_in
                total_tokens_out += review_stats.tokens_out
                answer_text = _choose_best_answer(
                    draft_answer,
                    reviewed_answer,
                    question_intent,
                    answer_language,
                )

        else:
            # Buffer la respuesta antes de yield para poder verificar grounding.
            # Sacrificamos micro-latencia de streaming real por seguridad anti-alucinacion.
            answer_text, draft_stats = await _collect_model_response(
                messages,
                active_model,
            )
            total_tokens_in += draft_stats.tokens_in
            total_tokens_out += draft_stats.tokens_out
            answer_text = _sanitize_answer_text(answer_text)

        # Grounding check final: si la respuesta menciona conceptos que NO estan en
        # el contexto recuperado, probablemente el modelo invento. Reemplazar por NO_INFO.
        if not _is_answer_grounded(answer_text, context, question_intent, answer_language):
            answer_text = _no_info_answer(answer_language)

        for piece in _stream_text(answer_text):
            yield {"type": "token", "content": piece}
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

    # 11. Registrar log en background (no retrasa la respuesta)
    asyncio.get_running_loop().run_in_executor(
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
