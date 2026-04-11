import json
from datetime import datetime, timezone

from app.database import get_logs_db
from app.config import settings

_MAX_ANSWER_LOG = 500  # caracteres maximos a guardar del answer en logs


def log_usage(
    conversation_id: str,
    question: str,
    answer: str,
    sources_used: list[str],
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
):
    """Registra un uso del chatbot en los logs."""
    conn = get_logs_db()
    conn.execute(
        """INSERT INTO usage_logs
           (device_id, conversation_id, question, answer, sources_used,
            tokens_in, tokens_out, latency_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            settings.DEVICE_ID,
            conversation_id,
            question,
            answer[:_MAX_ANSWER_LOG] if answer else "",
            json.dumps(sources_used),
            tokens_in,
            tokens_out,
            latency_ms,
        ),
    )
    conn.commit()


def get_pending_logs(limit: int = 100) -> list[dict]:
    """Obtiene logs pendientes de sincronizacion."""
    conn = get_logs_db()
    rows = conn.execute(
        """SELECT id, device_id, conversation_id, question, answer,
                  sources_used, tokens_in, tokens_out, latency_ms, created_at
           FROM usage_logs
           WHERE synced = 0
           ORDER BY created_at ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def mark_as_synced(log_ids: list[int]):
    """Marca logs como sincronizados."""
    if not log_ids:
        return
    conn = get_logs_db()
    placeholders = ",".join("?" * len(log_ids))
    conn.execute(
        f"UPDATE usage_logs SET synced = 1 WHERE id IN ({placeholders})",
        log_ids,
    )
    conn.commit()


def record_sync_result(records_synced: int, result: str):
    """Registra el resultado de una sincronizacion."""
    conn = get_logs_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO sync_status (last_sync_at, records_synced, sync_result) VALUES (?, ?, ?)",
        (now, records_synced, result),
    )
    conn.commit()


def get_sync_status() -> dict:
    """Obtiene el estado de la ultima sincronizacion."""
    conn = get_logs_db()
    pending = conn.execute(
        "SELECT COUNT(*) FROM usage_logs WHERE synced = 0"
    ).fetchone()[0]

    last_sync = conn.execute(
        "SELECT last_sync_at, records_synced, sync_result FROM sync_status ORDER BY id DESC LIMIT 1"
    ).fetchone()

    return {
        "pending_logs": pending,
        "last_sync_at": last_sync["last_sync_at"] if last_sync else None,
        "records_synced": last_sync["records_synced"] if last_sync else 0,
        "last_sync_result": last_sync["sync_result"] if last_sync else None,
    }


def get_total_queries() -> int:
    """Retorna el total de queries realizados."""
    conn = get_logs_db()
    return conn.execute("SELECT COUNT(*) FROM usage_logs").fetchone()[0]


def get_pending_count() -> int:
    """Retorna la cantidad de logs pendientes de sincronizacion."""
    conn = get_logs_db()
    return conn.execute(
        "SELECT COUNT(*) FROM usage_logs WHERE synced = 0"
    ).fetchone()[0]
