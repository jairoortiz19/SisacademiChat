import struct

from app.database import get_knowledge_db


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Convierte lista de floats a bytes para sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def search(query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """
    Busca los chunks mas similares al embedding de la consulta.

    Returns:
        Lista de dicts con: chunk_id, chunk_text, source_name, page_number, section, score
    """
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
        (embedding_bytes, top_k),
    ).fetchall()

    results = []
    for row in rows:
        results.append(
            {
                "chunk_id": row["rowid"],
                "chunk_text": row["chunk_text"],
                "source_name": row["source_name"],
                "page_number": row["page_number"],
                "section": row["section"],
                "score": 1.0 - row["distance"],
            }
        )
    return results


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
