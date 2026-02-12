import re
import time
from collections import defaultdict

from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

# --- API Key Authentication ---

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Rutas que no requieren autenticacion
PUBLIC_PATHS = {"/api/v1/health", "/docs", "/openapi.json", "/redoc"}


async def verify_api_key(request: Request, api_key: str = Security(api_key_header)):
    """Verifica que el API Key sea valido. Excepcion para rutas publicas."""
    if request.url.path in PUBLIC_PATHS:
        return
    if not api_key or api_key != settings.API_KEY:
        raise HTTPException(
            status_code=401,
            detail={"error": "API Key invalida o ausente", "code": "UNAUTHORIZED"},
        )


# --- Rate Limiting ---

class RateLimiter:
    """Rate limiter simple en memoria por IP."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, client_ip: str) -> bool:
        """Retorna True si la peticion esta permitida."""
        now = time.time()
        cutoff = now - self.window

        # Limpiar timestamps viejos
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if t > cutoff
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            return False

        self._requests[client_ip].append(now)
        return True

    def get_retry_after(self, client_ip: str) -> int:
        """Retorna segundos hasta que se libere un slot."""
        if not self._requests[client_ip]:
            return 0
        oldest = min(self._requests[client_ip])
        return max(1, int(self.window - (time.time() - oldest)))


rate_limiter = RateLimiter(
    max_requests=settings.RATE_LIMIT_PER_MINUTE,
    window_seconds=60,
)


async def check_rate_limit(request: Request):
    """Middleware dependency para rate limiting."""
    if request.url.path in PUBLIC_PATHS:
        return
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.check(client_ip):
        retry_after = rate_limiter.get_retry_after(client_ip)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Demasiadas peticiones. Intenta de nuevo mas tarde.",
                "code": "RATE_LIMITED",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )


# --- Input Sanitization ---

# Patron para caracteres de control (excepto newline y tab)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_query(text: str) -> str:
    """Limpia y valida el texto de la consulta del usuario."""
    if not text or not text.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": "La consulta no puede estar vacia", "code": "EMPTY_QUERY"},
        )

    # Strip y limitar longitud
    text = text.strip()
    if len(text) > settings.MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"La consulta excede el limite de {settings.MAX_QUERY_LENGTH} caracteres",
                "code": "QUERY_TOO_LONG",
            },
        )

    # Remover caracteres de control
    text = _CONTROL_CHARS.sub("", text)

    return text
