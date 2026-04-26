import sqlite3
import threading
from pathlib import Path

import sqlite_vec

from app.config import settings

_knowledge_conn: sqlite3.Connection | None = None
_knowledge_lock = threading.Lock()

_logs_conn: sqlite3.Connection | None = None
_logs_lock = threading.Lock()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Aplica PRAGMAs de rendimiento comunes."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")   # FULL→NORMAL: mas rapido, igual de seguro con WAL
    conn.execute("PRAGMA cache_size=-4000")     # 4 MB de cache en memoria
    conn.execute("PRAGMA temp_store=MEMORY")    # tablas temporales en RAM


def _get_connection(db_path: Path) -> sqlite3.Connection:
    """Crea una conexion SQLite con sqlite-vec habilitado."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def _connection_is_usable(conn: sqlite3.Connection | None) -> bool:
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1")
        return True
    except sqlite3.ProgrammingError:
        return False


def _get_logs_connection() -> sqlite3.Connection:
    """Crea una conexion SQLite para la BD de logs."""
    conn = sqlite3.connect(str(settings.LOGS_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def open_knowledge_db() -> sqlite3.Connection:
    """Abre una conexion independiente a knowledge.db para lecturas con close()."""
    return _get_connection(settings.KNOWLEDGE_DB)


def _ensure_knowledge_search_support(conn: sqlite3.Connection) -> None:
    """Crea y reconstruye los indices locales de busqueda textual."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts "
            "USING fts5(chunk_text, source_name, section, tokenize='unicode61 remove_diacritics 2')"
        )
        counts = conn.execute(
            """SELECT
                   (SELECT COUNT(*) FROM chunks) AS chunk_count,
                   (SELECT COUNT(*) FROM chunks_fts) AS fts_count,
                   (SELECT COALESCE(MAX(id), 0) FROM chunks) AS chunk_max_id,
                   (SELECT COALESCE(MAX(rowid), 0) FROM chunks_fts) AS fts_max_id"""
        ).fetchone()
        if (
            counts["chunk_count"] == counts["fts_count"]
            and counts["chunk_max_id"] == counts["fts_max_id"]
        ):
            return

        conn.execute("DELETE FROM chunks_fts")
        conn.execute(
            "INSERT INTO chunks_fts (rowid, chunk_text, source_name, section) "
            "SELECT id, chunk_text, source_name, COALESCE(section, '') FROM chunks"
        )
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")
    except sqlite3.OperationalError:
        # Algunas builds de SQLite pueden no incluir FTS5.
        pass


def get_knowledge_db() -> sqlite3.Connection:
    """Retorna una conexion persistente a la BD de conocimiento."""
    global _knowledge_conn
    with _knowledge_lock:
        if not _connection_is_usable(_knowledge_conn):
            _knowledge_conn = _get_connection(settings.KNOWLEDGE_DB)
        return _knowledge_conn


def reset_knowledge_db():
    """Cierra y resetea la conexion persistente (usar tras sync de KB)."""
    global _knowledge_conn
    with _knowledge_lock:
        if _knowledge_conn is not None:
            _knowledge_conn.close()
            _knowledge_conn = None


def get_logs_db() -> sqlite3.Connection:
    """Retorna una conexion persistente a la BD de logs."""
    global _logs_conn
    with _logs_lock:
        if not _connection_is_usable(_logs_conn):
            _logs_conn = _get_logs_connection()
        return _logs_conn


def init_knowledge_db():
    """Inicializa las tablas de la base de conocimiento."""
    conn = get_knowledge_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            chunk_text TEXT NOT NULL,
            page_number INTEGER,
            section TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT UNIQUE NOT NULL,
            chunk_count INTEGER DEFAULT 0,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_source
            ON chunks(source_name);
        CREATE INDEX IF NOT EXISTS idx_chunks_page
            ON chunks(page_number);
    """)
    # Tabla virtual vec0 se crea aparte (no soporta IF NOT EXISTS en executescript)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[384])"
        )
    except sqlite3.OperationalError:
        pass  # Ya existe
    _ensure_knowledge_search_support(conn)
    conn.commit()


def init_logs_db():
    """Inicializa las tablas de logs de uso."""
    conn = get_logs_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            sources_used TEXT,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            synced INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sync_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            last_sync_at TIMESTAMP,
            records_synced INTEGER DEFAULT 0,
            sync_result TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_logs_synced
            ON usage_logs(synced);
        CREATE INDEX IF NOT EXISTS idx_logs_device
            ON usage_logs(device_id);
    """)
    conn.commit()


def init_all():
    """Inicializa todas las bases de datos."""
    init_knowledge_db()
    init_logs_db()
