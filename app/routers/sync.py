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
    result = await sync_service.sync_knowledge_base()

    if result["status"] == "skipped":
        raise HTTPException(
            status_code=400,
            detail={"error": result["message"], "code": "NO_SERVER_URL"},
        )
    
    if result["status"] == "error":
        raise HTTPException(
            status_code=502, # Bad Gateway / Upstream error
            detail={"error": result["message"], "code": "SYNC_FAILED"},
        )

    return result
