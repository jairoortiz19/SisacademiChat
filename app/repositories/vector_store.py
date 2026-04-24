import re
import struct
import unicodedata

from app.database import get_knowledge_db

_TOKEN_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")
_STOPWORDS = {
    "que", "como", "cual", "cuales", "donde", "cuando", "para", "sobre", "desde",
    "hasta", "entre", "solo", "solo", "esta", "este", "estos", "estas", "del",
    "las", "los", "una", "uno", "unos", "unas", "con", "sin", "por", "sus",
    "han", "hay", "fue", "son", "ser", "mas", "muy", "porque", "segun", "puede",
    "pueden", "tiene", "tienen", "cada", "esto", "esa", "ese", "esas", "esos",
    "cómo", "qué", "cuál", "cuáles", "cómo", "más",
}
_RRF_K = 60


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Convierte lista de floats a bytes para sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _row_to_chunk(row, score: float) -> dict:
    return {
        "chunk_id": row["rowid"] if "rowid" in row.keys() else row["id"],
        "chunk_text": row["chunk_text"],
        "source_name": row["source_name"],
        "page_number": row["page_number"],
        "section": row["section"],
        "score": score,
    }


def _normalize_text(text: str) -> str:
    """Normaliza texto para comparaciones lexicas."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def _extract_terms(text: str) -> list[str]:
    """Extrae terminos utiles para FTS, removiendo stopwords."""
    seen = set()
    terms = []
    for raw in _TOKEN_RE.findall(text):
        term = _normalize_text(raw)
        if term in _STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _build_fts_query(text: str) -> str | None:
    """Construye una consulta FTS relativamente tolerante."""
    terms = _extract_terms(text)
    if not terms:
        return None

    clauses = []
    if len(terms) >= 2:
        clauses.append(f"\"{' '.join(terms[:4])}\"")
    clauses.append(" AND ".join(f"{term}*" for term in terms[:4]))
    clauses.append(" OR ".join(f"{term}*" for term in terms[:8]))

    seen = set()
    filtered = []
    for clause in clauses:
        if clause and clause not in seen:
            seen.add(clause)
            filtered.append(clause)
    return " OR ".join(filtered)


def _normalize_phrase(text: str) -> str:
    return " ".join(_normalize_text(text).split())


def _ordered_term_hits(haystack: str, query_terms: list[str]) -> int:
    index = -1
    hits = 0
    for term in query_terms:
        found = haystack.find(term, index + 1)
        if found < 0:
            continue
        hits += 1
        index = found
    return hits


def _search_dense(query_embedding: list[float], limit: int) -> list[dict]:
    """Busqueda vectorial pura."""
    conn = get_knowledge_db()
    embedding_bytes = _serialize_embedding(query_embedding)
    rows = conn.execute(
        """SELECT
               v.rowid,
               v.distance,
               c.chunk_text,
               c.source_name,
               c.page_number,
               c.section
           FROM vec_chunks v
           INNER JOIN chunks c ON c.id = v.rowid
           WHERE v.embedding MATCH ?
             AND k = ?""",
        (embedding_bytes, limit),
    ).fetchall()

    return [_row_to_chunk(row, 1.0 - row["distance"]) for row in rows]


def _search_keyword(query_text: str, limit: int) -> list[dict]:
    """Busqueda lexical via FTS5 si esta disponible."""
    conn = get_knowledge_db()
    fts_query = _build_fts_query(query_text)
    if not fts_query:
        return []

    try:
        rows = conn.execute(
            """SELECT
                   f.rowid,
                   bm25(chunks_fts) AS bm25_score,
                   c.chunk_text,
                   c.source_name,
                   c.page_number,
                   c.section
               FROM chunks_fts f
               INNER JOIN chunks c ON c.id = f.rowid
               WHERE chunks_fts MATCH ?
               ORDER BY bm25_score
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
    except Exception:
        return []

    results = []
    for row in rows:
        bm25_score = row["bm25_score"] if row["bm25_score"] is not None else 0.0
        lexical_score = 1.0 / (1.0 + abs(bm25_score))
        results.append(_row_to_chunk(row, lexical_score))
    return results


def search(query_embedding: list[float], query_text: str | None = None, top_k: int = 5) -> list[dict]:
    """
    Busca los chunks mas similares combinando vector search y FTS.

    Returns:
        Lista de dicts con: chunk_id, chunk_text, source_name, page_number, section, score
    """
    pool_size = max(top_k * 8, 24)
    dense_results = _search_dense(query_embedding, pool_size)
    lexical_results = _search_keyword(query_text or "", pool_size) if query_text else []

    query_terms = _extract_terms(query_text or "")
    query_phrase = _normalize_phrase(query_text or "")
    combined: dict[int, dict] = {}

    for rank, result in enumerate(dense_results, start=1):
        entry = combined.setdefault(result["chunk_id"], dict(result))
        entry["dense_score"] = max(result["score"], entry.get("dense_score", result["score"]))
        entry["rrf"] = entry.get("rrf", 0.0) + 1.0 / (_RRF_K + rank)

    for rank, result in enumerate(lexical_results, start=1):
        entry = combined.setdefault(result["chunk_id"], dict(result))
        entry["keyword_score"] = max(result["score"], entry.get("keyword_score", result["score"]))
        entry["rrf"] = entry.get("rrf", 0.0) + 1.0 / (_RRF_K + rank)

    for entry in combined.values():
        normalized_haystack = _normalize_text(
            " ".join(
                filter(
                    None,
                    [
                        entry.get("source_name", ""),
                        entry.get("section", ""),
                        entry.get("chunk_text", "")[:300],
                    ],
                )
            )
        )
        term_hits = sum(1 for term in query_terms if term in normalized_haystack)
        term_boost = min(term_hits * 0.03, 0.15)
        all_terms_boost = 0.08 if query_terms and all(term in normalized_haystack for term in query_terms[:5]) else 0.0
        phrase_boost = 0.12 if query_phrase and query_phrase in normalized_haystack else 0.0
        dense_score = entry.get("dense_score", 0.0)
        keyword_score = entry.get("keyword_score", 0.0)
        entry["score"] = (
            entry.get("rrf", 0.0)
            + (dense_score * 0.35)
            + (keyword_score * 0.25)
            + term_boost
            + all_terms_boost
            + phrase_boost
        )

    ranked = sorted(
        combined.values(),
        key=lambda item: (
            item.get("score", 0.0),
            item.get("dense_score", 0.0),
            item.get("keyword_score", 0.0),
        ),
        reverse=True,
    )
    return ranked[:top_k]


def expand_with_neighbors(chunks: list[dict], limit: int = 1, max_chunks: int | None = None) -> list[dict]:
    """Agrega chunks vecinos para no perder contexto cuando la respuesta queda partida."""
    if not chunks or limit <= 0:
        return chunks

    conn = get_knowledge_db()
    expanded = {chunk["chunk_id"]: dict(chunk) for chunk in chunks}
    seed_chunks = chunks[: min(len(chunks), 3)]

    for chunk in seed_chunks:
        page_number = chunk.get("page_number")
        params = (
            chunk["source_name"],
            chunk["chunk_id"],
            page_number,
            page_number,
            limit,
        )
        before_rows = conn.execute(
            """SELECT id, chunk_text, source_name, page_number, section
               FROM chunks
               WHERE source_name = ?
                 AND id < ?
                 AND (? IS NULL OR page_number IS NULL OR ABS(page_number - ?) <= 2)
               ORDER BY id DESC
               LIMIT ?""",
            params,
        ).fetchall()
        after_rows = conn.execute(
            """SELECT id, chunk_text, source_name, page_number, section
               FROM chunks
               WHERE source_name = ?
                 AND id > ?
                 AND (? IS NULL OR page_number IS NULL OR ABS(page_number - ?) <= 2)
               ORDER BY id ASC
               LIMIT ?""",
            params,
        ).fetchall()

        for row in before_rows + after_rows:
            page_bonus = 0.02 if row["page_number"] == page_number else 0.0
            section_bonus = 0.02 if row["section"] and row["section"] == chunk.get("section") else 0.0
            neighbor_score = max((chunk.get("score", 0.0) * 0.92) + page_bonus + section_bonus, 0.12)
            existing = expanded.get(row["id"])
            candidate = _row_to_chunk(row, neighbor_score)
            if not existing or candidate["score"] > existing.get("score", 0.0):
                expanded[row["id"]] = candidate

    ranked = sorted(
        expanded.values(),
        key=lambda item: (item.get("score", 0.0), -item.get("chunk_id", 0)),
        reverse=True,
    )
    if max_chunks is not None:
        return ranked[:max_chunks]
    return ranked


def find_supporting_chunks(source_name: str, query_text: str, limit: int = 3) -> list[dict]:
    """Busca dentro de una misma fuente chunks que desarrollen mejor la consulta."""
    query_terms = _extract_terms(query_text)[:6]
    if not source_name or not query_terms:
        return []

    query_phrase = _normalize_phrase(query_text)
    conn = get_knowledge_db()
    rows = conn.execute(
        """SELECT id, chunk_text, source_name, page_number, section
           FROM chunks
           WHERE source_name = ?""",
        (source_name,),
    ).fetchall()

    matches = []
    for row in rows:
        chunk_preview = row["chunk_text"][:500]
        normalized_haystack = _normalize_text(
            " ".join(
                filter(
                    None,
                    [
                        row["source_name"],
                        row["section"],
                        chunk_preview,
                    ],
                )
            )
        )
        term_hits = sum(1 for term in query_terms if term in normalized_haystack)
        if term_hits == 0:
            continue
        ordered_hits = _ordered_term_hits(normalized_haystack, query_terms)
        term_frequency = sum(normalized_haystack.count(term) for term in query_terms)
        phrase_boost = 0.20 if query_phrase and query_phrase in normalized_haystack else 0.0
        intro_penalty = 0.12 if _normalize_text(chunk_preview).startswith(("temas", "unidad", "objetivo")) else 0.0
        score = (
            (term_hits * 0.05)
            + (term_frequency * 0.03)
            + (ordered_hits * 0.04)
            + phrase_boost
            - intro_penalty
        )
        matches.append((_row_to_chunk(row, score), term_hits, ordered_hits))

    matches.sort(
        key=lambda item: (
            item[0]["score"],
            item[1],
            item[2],
            -(item[0].get("page_number") or 0),
        ),
        reverse=True,
    )
    return [item[0] for item in matches[:limit]]


def list_sources() -> list[dict]:
    """Lista todas las fuentes de conocimiento."""
    conn = get_knowledge_db()
    rows = conn.execute(
        "SELECT source_name, chunk_count, ingested_at FROM sources ORDER BY ingested_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def get_stats() -> dict:
    """Retorna estadisticas generales de la base de conocimiento."""
    conn = get_knowledge_db()
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM chunks) AS total_chunks, "
        "(SELECT COUNT(*) FROM sources) AS total_sources"
    ).fetchone()
    return {"total_chunks": row["total_chunks"], "total_sources": row["total_sources"]}
