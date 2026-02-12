import json
import logging
from dataclasses import dataclass
from typing import AsyncGenerator

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMStats:
    """Estadisticas de la respuesta del LLM."""
    tokens_in: int = 0
    tokens_out: int = 0


class OllamaClient:
    """Cliente HTTP async para Ollama API."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
            )
        return self._client

    async def stream_chat(
        self,
        messages: list[dict],
        model: str | None = None,
    ) -> AsyncGenerator[tuple[str, LLMStats | None], None]:
        """
        Envia mensajes a Ollama y retorna tokens en streaming.

        Yields:
            Tuplas de (token_text, stats_or_none).
            El ultimo yield tiene stats con conteo de tokens.
        """
        client = await self._get_client()
        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": True,
        }

        try:
            async with client.stream(
                "POST", "/api/chat", json=payload
            ) as response:
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
                        # Ultimo mensaje con estadisticas
                        stats.tokens_in = data.get("prompt_eval_count", 0)
                        stats.tokens_out = data.get("eval_count", 0)
                        yield "", stats
                        return

                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content, None

        except httpx.ConnectError:
            raise ConnectionError(
                f"No se pudo conectar a Ollama en {self.base_url}. "
                "Verifica que Ollama este corriendo (run.bat o 'ollama serve')."
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Error de Ollama: {e.response.status_code} - {e.response.text}")

    async def is_available(self) -> bool:
        """Verifica si Ollama esta disponible."""
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    async def has_model(self) -> bool:
        """Verifica si el modelo configurado esta disponible en Ollama."""
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags")
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            return any(self.model in m for m in models)
        except Exception:
            return False

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Singleton
ollama_client = OllamaClient()
