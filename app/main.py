import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_all
from app.infrastructure import embedder
from app.services.llm_client import ollama_client
from app.routers import chat, sources, health, sync, professor
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
    description="""
**SisacademiChat** es el cliente local inteligente de la plataforma educativa Sisacademi.
Combina un chatbot con IA (LLM local via Ollama) y un panel completo de analitica academica
para profesores — todo funcionando **100% offline** despues de la primera sincronizacion.

---

## Arquitectura

```
SisacademiServer (nube)            SisacademiChat (local)
  Procesa PDFs, Excel       -->      Descarga knowledge.db
  Genera embeddings          |       (chunks + vectores + estudiantes + calificaciones)
  Recibe sync academico      |
                             |       Estudiante pregunta --> LLM local (Ollama)
                             |       Profesor consulta   --> Analytics offline
                             |
  Recibe logs de uso        <--      Envia logs cuando hay internet
```

---

## Modulos

| Modulo | Descripcion |
|--------|-------------|
| **Chat IA** | Chatbot RAG con modelo local (Ollama). Busca en la base de conocimiento por significado y genera respuestas contextualizadas. |
| **Panel del Profesor** | Dashboard, estadisticas por materia/grupo, plan de mejora, prediccion de rendimiento (regresion lineal), comparacion entre grupos. **Todo offline.** |
| **Sincronizacion** | Descarga knowledge.db del servidor central (incluye material de estudio + datos academicos). Envia logs de uso cuando hay conexion. |

---

## Flujo de uso

1. **Sincronizar** (cuando hay internet): `POST /sync/knowledge` descarga la BD actualizada del servidor.
2. **Estudiante usa el chat** (offline): `POST /chat` recibe respuestas del LLM local con contexto de la base de conocimiento.
3. **Profesor consulta analytics** (offline): Los endpoints `/professor/*` leen directamente de la BD local.
4. **Enviar logs** (cuando hay internet): `POST /sync/logs` envia registros de uso al servidor para analisis.
    """,
    version="1.1.0",
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "Chat",
            "description": "Chatbot con IA local (Ollama + RAG). Genera respuestas usando busqueda semantica en la base de conocimiento.",
        },
        {
            "name": "Profesor",
            "description": "**Panel completo para el profesor.** Dashboard, calificaciones, estadisticas por materia/grupo, plan de mejora personalizado, prediccion de rendimiento y comparacion entre grupos. Funciona 100% offline.",
        },
        {
            "name": "Sync",
            "description": "Sincronizacion con el servidor central. Descarga knowledge.db (material + datos academicos) y envia logs de uso.",
        },
        {
            "name": "Sources",
            "description": "Consulta las fuentes de conocimiento disponibles (documentos procesados).",
        },
        {
            "name": "Health",
            "description": "Health check del servicio.",
        },
        {
            "name": "Stats",
            "description": "Estadisticas generales del servicio local.",
        },
    ],
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
app.include_router(professor.router, prefix=PREFIX)


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
