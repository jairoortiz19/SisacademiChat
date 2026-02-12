import sqlite3
from pathlib import Path

import sqlite_vec

from app.config import settings


def _get_connection(db_path: Path) -> sqlite3.Connection:
    """Crea una conexion SQLite con sqlite-vec habilitado."""
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_knowledge_db() -> sqlite3.Connection:
    return _get_connection(settings.KNOWLEDGE_DB)


def get_logs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.LOGS_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_knowledge_db():
    """Inicializa las tablas de la base de conocimiento."""
    conn = get_knowledge_db()
    try:
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
        """)
        # Tabla virtual vec0 se crea aparte (no soporta IF NOT EXISTS en executescript)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[384])"
            )
        except sqlite3.OperationalError:
            pass  # Ya existe
        conn.commit()
    finally:
        conn.close()


def init_logs_db():
    """Inicializa las tablas de logs de uso."""
    conn = get_logs_db()
    try:
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
    finally:
        conn.close()


def init_all():
    """Inicializa todas las bases de datos."""
    init_knowledge_db()
    init_logs_db()
