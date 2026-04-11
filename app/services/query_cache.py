"""
Cache TTL para respuestas RAG completas.

En un contexto educativo los estudiantes hacen preguntas repetidas.
Cachear la respuesta completa evita re-embedear y re-consultar Ollama
para queries identicas dentro de la ventana de tiempo.
"""

import hashlib
import logging
import time

from app.config import settings

logger = logging.getLogger(__name__)


class QueryCache:
    """Cache en memoria con TTL y tamaño maximo (eviccion LRU simple)."""

    def __init__(self, ttl_seconds: int, max_size: int):
        # {key: {"data": dict, "ts": float}}
        self._store: dict[str, dict] = {}
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._hits = 0
        self._misses = 0

    def _key(self, message: str, top_k: int) -> str:
        raw = f"{message.lower().strip()}:{top_k}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

    def get(self, message: str, top_k: int) -> dict | None:
        key = self._key(message, top_k)
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        if time.monotonic() - entry["ts"] > self.ttl:
            del self._store[key]
            self._misses += 1
            return None
        self._hits += 1
        logger.debug("Cache HIT para query (hits=%d, misses=%d)", self._hits, self._misses)
        return entry["data"]

    def set(self, message: str, top_k: int, data: dict) -> None:
        if len(self._store) >= self.max_size:
            # Evictar la entrada mas antigua
            oldest = min(self._store, key=lambda k: self._store[k]["ts"])
            del self._store[oldest]
        key = self._key(message, top_k)
        self._store[key] = {"data": data, "ts": time.monotonic()}

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def stats(self) -> dict:
        return {"hits": self._hits, "misses": self._misses, "size": self.size}


# Singleton — parametros configurables en config.env
query_cache = QueryCache(
    ttl_seconds=settings.QUERY_CACHE_TTL,
    max_size=settings.QUERY_CACHE_MAX_SIZE,
)
