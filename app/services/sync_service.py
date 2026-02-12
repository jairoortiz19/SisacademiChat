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
