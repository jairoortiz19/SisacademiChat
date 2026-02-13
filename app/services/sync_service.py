import logging

import httpx

from app.config import settings
from app.repositories import log_store

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


async def sync_logs() -> dict:
    """
    Sincroniza logs pendientes con el servidor central.

    Returns:
        dict con: synced, failed, message
    """
    if not settings.SERVER_URL:
        return {"synced": 0, "failed": 0, "message": "SERVER_URL no configurado"}

    total_synced = 0
    total_failed = 0

    # Usar SERVER_API_KEY si esta configurado, sino API_KEY local
    auth_key = settings.SERVER_API_KEY or settings.API_KEY
    headers = {"X-API-Key": auth_key}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                pending = log_store.get_pending_logs(limit=BATCH_SIZE)
                if not pending:
                    break

                payload = {
                    "device_id": settings.DEVICE_ID,
                    "logs": pending,
                }

                try:
                    resp = await client.post(
                        f"{settings.SERVER_URL}/api/v1/logs/receive",
                        json=payload,
                        headers=headers,
                    )
                    resp.raise_for_status()

                    synced_ids = [log["id"] for log in pending]
                    log_store.mark_as_synced(synced_ids)
                    total_synced += len(synced_ids)

                except httpx.HTTPError as e:
                    logger.warning("Error sincronizando batch: %s", e)
                    total_failed += len(pending)
                    break

    except Exception as e:
        logger.error("Error de conexion al servidor: %s", e)
        total_failed += log_store.get_pending_count()
        result = "error"
    else:
        result = "success" if total_failed == 0 else "partial"

    log_store.record_sync_result(total_synced, result)

    return {
        "synced": total_synced,
        "failed": total_failed,
        "message": f"Sincronizacion {result}: {total_synced} enviados, {total_failed} fallidos",
    }


async def sync_knowledge_base() -> dict:
    """
    Descarga la base de conocimiento desde el servidor central.
    """
    import os
    import shutil
    import sqlite3
    import tempfile
    from app.database import init_knowledge_db, reset_knowledge_db
    from app.repositories import vector_store

    if not settings.SERVER_URL:
        return {"status": "skipped", "message": "SERVER_URL no configurado"}

    download_url = f"{settings.SERVER_URL}/api/v1/knowledge/download"
    db_path = settings.KNOWLEDGE_DB
    backup_path = db_path.with_suffix(".db.bak")

    # Auth para el servidor
    auth_key = settings.SERVER_API_KEY or settings.API_KEY
    headers = {"X-API-Key": auth_key}

    # 1. Descargar
    logger.info("Descargando knowledge.db desde: %s", download_url)
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.get(download_url, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Error descargando KB: %s", e)
        return {"status": "error", "message": f"Error descarga: {e}"}

    # 2. Guardar en temporal y validar
    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.write(resp.content)
        tmp.close()
        tmp_path = tmp.name

        conn = sqlite3.connect(tmp_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()

        # Solo exigir chunks y sources
        required = {"chunks", "sources"}
        missing = required - set(tables)
        if missing:
            os.unlink(tmp_path)
            return {"status": "error", "message": f"DB invalida. Faltan tablas: {missing}"}

    except Exception as e:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        logger.error("Error validando KB descargada: %s", e)
        return {"status": "error", "message": f"Archivo invalido: {e}"}

    # 3. Backup del actual y reemplazar
    old_stats = vector_store.get_stats()

    if db_path.exists():
        shutil.copy2(str(db_path), str(backup_path))
        logger.info("Backup creado: %s", backup_path)

    shutil.move(tmp_path, str(db_path))
    logger.info("knowledge.db reemplazado exitosamente")

    # 4. Re-inicializar (resetear conexion persistente)
    reset_knowledge_db()
    init_knowledge_db()
    new_stats = vector_store.get_stats()

    return {
        "status": "ok",
        "message": "Base de conocimiento actualizada",
        "previous": old_stats,
        "current": new_stats,
    }


if __name__ == "__main__":
    import asyncio
    import sys

    # Configure logging for CLI usage
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

    async def main():
        if not settings.SERVER_URL:
            logger.info("SERVER_URL no configurado. Saltando sincronizacion.")
            return

        logger.info(f"Intentando sincronizar KB desde {settings.SERVER_URL}...")
        try:
            result = await sync_knowledge_base()
            
            if result["status"] == "ok":
                logger.info("Sincronizacion EXITOSA.")
                logger.info(f"KB actual: {result['current']}")
            elif result["status"] == "skipped":
                logger.info(f"Sincronizacion SALTADA: {result['message']}")
            else:
                logger.warning(f"Sincronizacion FALLIDA: {result['message']}")
        except Exception as e:
            logger.error(f"Error inesperado durante sincronizacion: {e}")

    asyncio.run(main())
