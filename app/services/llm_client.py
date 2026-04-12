import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [1.0, 2.0]   # segundos entre reintentos (max 2 intentos extra)
_CB_THRESHOLD = 3             # fallos consecutivos para abrir el circuit breaker
_CB_RESET = 30.0              # segundos antes de volver a intentar tras abrir


@dataclass
class LLMStats:
    """Estadisticas de la respuesta del LLM."""
    tokens_in: int = 0
    tokens_out: int = 0


class _CircuitBreaker:
    """Circuit breaker simple: abre tras N fallos consecutivos y se resetea tras T segundos."""

    def __init__(self, threshold: int, reset_timeout: float):
        self._failures = 0
        self._open_until: float = 0.0
        self.threshold = threshold
        self.reset_timeout = reset_timeout

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._open_until = time.monotonic() + self.reset_timeout
            logger.warning(
                "Circuit breaker ABIERTO tras %d fallos. "
                "Ollama no disponible por %.0fs.",
                self._failures, self.reset_timeout,
            )


class OllamaClient:
    """Cliente HTTP async para Ollama API con retry y circuit breaker."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
        self._client: httpx.AsyncClient | None = None
        self._cb = _CircuitBreaker(_CB_THRESHOLD, _CB_RESET)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=10.0),
            )
        return self._client

    async def _do_stream(
        self,
        messages: list[dict],
        model: str | None,
    ) -> AsyncGenerator[tuple[str, LLMStats | None], None]:
        """Realiza el stream HTTP a Ollama (sin retry, sin circuit breaker)."""
        client = await self._get_client()
        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            "options": {
                "num_ctx": settings.OLLAMA_NUM_CTX,
                "num_predict": settings.OLLAMA_NUM_PREDICT,
                "temperature": settings.OLLAMA_TEMPERATURE,
            },
        }

        async with client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            stats = LLMStats()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("done"):
                    stats.tokens_in = data.get("prompt_eval_count", 0)
                    stats.tokens_out = data.get("eval_count", 0)
                    yield "", stats
                    return
                content = data.get("message", {}).get("content", "")
                if content:
                    yield content, None

    async def stream_chat(
        self,
        messages: list[dict],
        model: str | None = None,
    ) -> AsyncGenerator[tuple[str, LLMStats | None], None]:
        """
        Envia mensajes a Ollama con retry en conexion y circuit breaker.

        Solo reintenta si no se ha comenzado a recibir tokens (evita duplicados).
        """
        if self._cb.is_open:
            raise ConnectionError(
                "Ollama no disponible temporalmente. Reintentando en breve."
            )

        started = False
        last_error: Exception | None = None

        for attempt in range(len(_RETRY_DELAYS) + 1):
            if attempt > 0:
                delay = _RETRY_DELAYS[attempt - 1]
                logger.info("Reintentando conexion a Ollama (intento %d, espera %.1fs)...", attempt + 1, delay)
                await asyncio.sleep(delay)

            try:
                async for token, stats in self._do_stream(messages, model):
                    if token:
                        started = True
                    yield token, stats
                self._cb.success()
                return

            except httpx.ConnectError as e:
                self._cb.failure()
                last_error = e
                if started:
                    # Ya empezamos a streamear — no reintentar (causaria tokens duplicados)
                    break

            except httpx.HTTPStatusError as e:
                self._cb.failure()
                raise RuntimeError(
                    f"Error de Ollama: {e.response.status_code} - {e.response.text}"
                )

        raise ConnectionError(
            f"No se pudo conectar a Ollama en {self.base_url} "
            f"tras {len(_RETRY_DELAYS) + 1} intentos. "
            "Verifica que Ollama este corriendo (run.bat o 'ollama serve')."
        )

    async def check_status(self) -> tuple[bool, bool]:
        """
        Verifica disponibilidad de Ollama y existencia del modelo rapido en una sola llamada.

        Returns:
            (is_available, has_fast_model)
        """
        available, installed = await self.check_models_status()
        fast = settings.OLLAMA_MODEL_FAST
        return available, fast in installed

    async def check_models_status(self) -> tuple[bool, set[str]]:
        """
        Retorna (is_available, set_de_modelos_instalados).
        Permite verificar cualquier modelo con una sola llamada HTTP.
        """
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags")
            if resp.status_code != 200:
                return False, set()
            data = resp.json()
            installed = {m.get("name", "") for m in data.get("models", [])}
            return True, installed
        except Exception:
            return False, set()

    async def is_available(self) -> bool:
        available, _ = await self.check_status()
        return available

    async def has_model(self) -> bool:
        _, model_ok = await self.check_status()
        return model_ok

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Singleton
ollama_client = OllamaClient()
