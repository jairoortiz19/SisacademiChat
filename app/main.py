import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_all
from app.infrastructure import embedder
from app.services.llm_client import ollama_client
from app.routers import chat, sources, health, sync
from app.repositories import vector_store, log_store
from app.models import StatsResponse
from app.security import verify_api_key

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sisacademichat")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializacion y limpieza del servicio."""
    logger.info("=== SisacademiChat iniciando ===")
    logger.info("Device ID: %s", settings.DEVICE_ID)

    # Inicializar bases de datos
    init_all()
    logger.info("Bases de datos inicializadas")

    # Pre-cargar modelo de embeddings
    logger.info("Cargando modelo de embeddings (primera vez puede descargar ~46MB)...")
    embedder.warmup()

    # Verificar Ollama
    if await ollama_client.is_available():
        has_model = await ollama_client.has_model()
        if has_model:
            logger.info("Ollama conectado con modelo '%s'", settings.OLLAMA_MODEL)
        else:
            logger.warning(
                "Ollama conectado pero modelo '%s' no encontrado. "
                "Ejecuta: ollama pull %s",
                settings.OLLAMA_MODEL,
                settings.OLLAMA_MODEL,
            )
    else:
        logger.warning(
            "Ollama no disponible en %s. "
            "El chat no funcionara hasta que Ollama este corriendo.",
            settings.OLLAMA_BASE_URL,
        )

    stats = vector_store.get_stats()
    logger.info(
        "Base de conocimiento: %d chunks, %d fuentes",
        stats["total_chunks"],
        stats["total_sources"],
    )

    if settings.SERVER_URL:
        logger.info("Servidor central: %s", settings.SERVER_URL)
    else:
        logger.info("Servidor central: no configurado (SERVER_URL vacio)")

    logger.info(
        "=== SisacademiChat listo en http://%s:%d ===",
        settings.HOST,
        settings.PORT,
    )

    yield

    # Limpieza
    await ollama_client.close()
    logger.info("=== SisacademiChat detenido ===")


app = FastAPI(
    title="SisacademiChat",
    description="Chatbot educativo RAG - Cliente local",
    version="1.0.0",
    lifespan=lifespan,
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# --- Routers ---
PREFIX = "/api/v1"
app.include_router(chat.router, prefix=PREFIX)
app.include_router(sources.router, prefix=PREFIX)
app.include_router(health.router, prefix=PREFIX)
app.include_router(sync.router, prefix=PREFIX)


# --- Stats endpoint ---
@app.get(f"{PREFIX}/stats", response_model=StatsResponse, tags=["Stats"])
async def get_stats(_auth=Depends(verify_api_key)):
    """Estadisticas generales del servicio."""
    kb_stats = vector_store.get_stats()
    total_queries = log_store.get_total_queries()
    pending = log_store.get_pending_count()

    return StatsResponse(
        total_sources=kb_stats["total_sources"],
        total_chunks=kb_stats["total_chunks"],
        total_queries=total_queries,
        pending_sync_logs=pending,
        device_id=settings.DEVICE_ID,
    )


# --- Global exception handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Error no manejado: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Error interno del servidor", "code": "INTERNAL_ERROR"},
    )
