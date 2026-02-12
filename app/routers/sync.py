import logging
import os
import shutil
import sqlite3
import tempfile

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.database import init_knowledge_db
from app.models import SyncStatusResponse, SyncResult
from app.repositories import log_store, vector_store
from app.security import verify_api_key
from app.services import sync_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sync"])


@router.post("/sync/logs", response_model=SyncResult)
async def sync_logs(_auth=Depends(verify_api_key)):
    """Sincroniza logs pendientes con el servidor central."""
    result = await sync_service.sync_logs()
    return SyncResult(**result)


@router.get("/sync/status", response_model=SyncStatusResponse)
async def sync_status(_auth=Depends(verify_api_key)):
    """Retorna el estado de la ultima sincronizacion."""
    status = log_store.get_sync_status()
    return SyncStatusResponse(**status)


@router.post("/sync/knowledge")
async def sync_knowledge(_auth=Depends(verify_api_key)):
    """
    Descarga la base de conocimiento desde el servidor central.

    Usa SERVER_URL configurado en config.env. Descarga el archivo,
    valida que sea SQLite valido, hace backup y reemplaza el actual.
    """
    if not settings.SERVER_URL:
        raise HTTPException(
            status_code=400,
            detail={"error": "SERVER_URL no configurado en config.env", "code": "NO_SERVER_URL"},
        )

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
        raise HTTPException(
            status_code=502,
            detail={"error": f"Error descargando KB del servidor: {e}", "code": "DOWNLOAD_FAILED"},
        )

    # 2. Guardar en temporal y validar
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.write(resp.content)
        tmp.close()

        conn = sqlite3.connect(tmp.name)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()

        # Solo exigir chunks y sources (processed_files es del servidor)
        required = {"chunks", "sources"}
        missing = required - set(tables)
        if missing:
            os.unlink(tmp.name)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": f"DB invalida. Faltan tablas: {missing}",
                    "code": "INVALID_DB",
                },
            )
    except sqlite3.DatabaseError:
        os.unlink(tmp.name)
        raise HTTPException(
            status_code=400,
            detail={"error": "El archivo descargado no es una base de datos SQLite valida", "code": "INVALID_DB"},
        )

    # 3. Backup del actual y reemplazar
    old_stats = vector_store.get_stats()

    if db_path.exists():
        shutil.copy2(str(db_path), str(backup_path))
        logger.info("Backup creado: %s", backup_path)

    shutil.move(tmp.name, str(db_path))
    logger.info("knowledge.db reemplazado exitosamente")

    # 4. Re-inicializar (por si faltan tablas virtuales)
    init_knowledge_db()

    new_stats = vector_store.get_stats()

    return {
        "status": "ok",
        "message": "Base de conocimiento actualizada desde servidor",
        "server": settings.SERVER_URL,
        "backup": str(backup_path) if backup_path.exists() else None,
        "previous": old_stats,
        "current": new_stats,
    }
