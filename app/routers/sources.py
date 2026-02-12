from fastapi import APIRouter, Depends

from app.models import SourceInfo
from app.repositories import vector_store
from app.security import verify_api_key

router = APIRouter(tags=["Sources"])


@router.get("/sources", response_model=list[SourceInfo])
async def list_sources(_auth=Depends(verify_api_key)):
    """Lista todas las fuentes de conocimiento disponibles."""
    return vector_store.list_sources()
