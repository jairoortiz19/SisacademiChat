import logging
from typing import Optional

from fastembed import TextEmbedding

from app.config import settings

logger = logging.getLogger(__name__)

_model: Optional[TextEmbedding] = None


def _get_model() -> TextEmbedding:
    """Inicializa el modelo de embeddings de forma lazy (singleton)."""
    global _model
    if _model is None:
        logger.info("Cargando modelo de embeddings: %s", settings.EMBEDDING_MODEL)
        _model = TextEmbedding(model_name=settings.EMBEDDING_MODEL)
        logger.info("Modelo de embeddings cargado correctamente")
    return _model


def embed_query(text: str) -> list[float]:
    """
    Genera el embedding de una consulta de usuario.

    Args:
        text: Texto de la consulta.

    Returns:
        Vector de 384 dimensiones.
    """
    model = _get_model()
    embeddings = list(model.embed([text]))
    return embeddings[0].tolist()


def warmup():
    """Pre-carga el modelo para evitar latencia en la primera consulta."""
    _get_model()
    logger.info("Modelo de embeddings listo")
