# SisacademiChat

SisacademiChat es un cliente de chat educativo local que utiliza **RAG (Generacion Aumentada por Recuperacion)** para responder preguntas de estudiantes basandose en materiales de curso especificos.

El sistema utiliza modelos locales (**Ollama**) para privacidad y eficiencia, y se sincroniza con un servidor central para actualizaciones de conocimiento y telemetria.

## Caracteristicas

* **Chat Educativo Local**: Respuestas generadas localmente usando LLMs (sin depender de internet para la inferencia).
* **RAG (Retrieval-Augmented Generation)**: Respuestas basadas *unicamente* en documentos proporcionados (PDFs, guias, libros).
* **Sincronizacion Inteligente**:
    * Descarga de bases de conocimiento gestionadas centralmente.
    * Subida de logs y metricas de uso anonimas.
* **Stack Eficiente**: Python, FastAPI, SQLite (Vector Search), Ollama.
* **Instalacion Automatica**: Scripts resilientes que descargan e instalan todo automaticamente.
* **Optimizacion de Rendimiento**: Parametros configurables para reducir latencia de respuestas.

## Requisitos Previos

* **Windows 10/11** (64-bit)
* **Conexion a internet** (solo para la instalacion inicial)
* No se necesita Python instalado en el sistema (se usa Python embebido)

## Instalacion

### Instalacion automatica (recomendada)

```bash
git clone https://github.com/jairoortiz19/SisacademiChat.git
cd SisacademiChat
install.bat
```

El instalador se encarga de todo automaticamente:
1. Descarga e instala **Ollama** si no esta presente
2. Descarga el modelo LLM (`qwen2.5:3b`)
3. Descarga **Python 3.12 embebido** (portable, no requiere instalacion en el sistema)
4. Instala **pip** y todas las dependencias
5. Inicializa las bases de datos SQLite
6. Descarga el modelo de embeddings (~46MB)
7. Sincroniza la base de conocimiento desde el servidor central

Todas las descargas tienen **reintentos automaticos** (hasta 3 intentos). Si algo falla, el script informa el error y sugiere solucion.

### Instalacion manual

1. Instalar [Ollama](https://ollama.com) y ejecutar: `ollama pull qwen2.5:3b`
2. Instalar Python 3.12+
3. Instalar dependencias:
    ```bash
    pip install -r requirements.txt
    ```
4. Copiar `config.env.example` a `config.env` y ajustar valores.

## Ejecucion

### Scripts Windows

| Script | Descripcion |
|---|---|
| `install.bat` | Instalacion completa con reintentos automaticos |
| `run.bat` | Inicia el servicio (auto-instala si es necesario) |
| `stop.bat` | Detiene el servicio de forma segura |

### Ejecucion manual

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8090
```

### Manejo automatico de errores en run.bat

* **Python no instalado**: Ejecuta `install.bat` automaticamente
* **Dependencias faltantes**: Reinstala `requirements.txt` automaticamente
* **Ollama no corriendo**: Lo inicia automaticamente con reintentos (5 intentos x 5s)
* **Puerto ocupado**: Ofrece 3 opciones:
    1. Cerrar el proceso anterior y reusar el puerto
    2. Buscar un puerto libre automaticamente (+1 a +20)
    3. Cancelar

## Configuracion

Todas las opciones se configuran en `config.env`:

### Servicio

| Variable | Default | Descripcion |
|---|---|---|
| `HOST` | `127.0.0.1` | Direccion del servidor |
| `PORT` | `8090` | Puerto del servidor |

### Seguridad

| Variable | Default | Descripcion |
|---|---|---|
| `API_KEY` | (requerido) | Clave de autenticacion para la API |
| `RATE_LIMIT_PER_MINUTE` | `30` | Limite de peticiones por minuto por IP |

### Ollama (LLM)

| Variable | Default | Descripcion |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL de Ollama |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Modelo LLM a usar |

### Rendimiento de Ollama

| Variable | Default | Descripcion |
|---|---|---|
| `OLLAMA_NUM_CTX` | `2048` | Ventana de contexto del LLM (tokens). Reducir = mas rapido |
| `OLLAMA_NUM_PREDICT` | `512` | Maximo de tokens de salida. Limita largo de respuesta |
| `OLLAMA_TEMPERATURE` | `0.1` | Temperatura de sampling. Menor = mas rapido y determinista |
| `OLLAMA_KEEP_ALIVE` | `30m` | Tiempo que el modelo se mantiene cargado en RAM |

### RAG

| Variable | Default | Descripcion |
|---|---|---|
| `TOP_K` | `3` | Cantidad de fragmentos a recuperar de la base de conocimiento |
| `MAX_QUERY_LENGTH` | `500` | Longitud maxima de la pregunta (caracteres) |
| `MIN_RELEVANCE_SCORE` | `0.25` | Score minimo de relevancia para incluir un fragmento |
| `MAX_CHUNK_LENGTH` | `500` | Longitud maxima de cada fragmento enviado al LLM |

### Servidor Central

| Variable | Default | Descripcion |
|---|---|---|
| `SERVER_URL` | (vacio) | URL del servidor central para sincronizacion |
| `SERVER_API_KEY` | (vacio) | API Key del servidor central |
| `DEVICE_ID` | (auto-generado) | Identificador unico del dispositivo |

## Arquitectura

```
HTTP Requests
    |
[Routers] - FastAPI (auth, validacion, rate limiting)
    |
[Services] - Logica de negocio (RAG pipeline, sync)
    |
[Repositories] - Acceso a datos (vector search, logs)
    |
[Infrastructure] - Componentes base (embeddings, DB)
    |
[Databases] - SQLite + sqlite-vec
```

### Pipeline RAG

```
Pregunta --> Sanitizacion --> Embedding (384d) --> Busqueda vectorial (top_k)
    --> Filtrado por relevancia --> Truncado de chunks --> Contexto al LLM
    --> Respuesta en espanol --> Log de uso
```

### Estructura de directorios

```
SisacademiChat/
├── app/
│   ├── main.py              # Entry point FastAPI
│   ├── config.py             # Settings desde config.env
│   ├── database.py           # SQLite (conexion persistente + sqlite-vec)
│   ├── models.py             # Modelos Pydantic
│   ├── security.py           # API key, rate limiting, sanitizacion
│   ├── infrastructure/
│   │   └── embedder.py       # Modelo de embeddings (FastEmbed)
│   ├── repositories/
│   │   ├── vector_store.py   # Busqueda vectorial
│   │   └── log_store.py      # Logs de uso
│   ├── services/
│   │   ├── rag_engine.py     # Pipeline RAG completo
│   │   ├── llm_client.py     # Cliente Ollama (streaming)
│   │   └── sync_service.py   # Sincronizacion con servidor central
│   └── routers/
│       ├── chat.py           # POST /chat, POST /chat/stream
│       ├── health.py         # GET /health
│       ├── sources.py        # GET /sources
│       └── sync.py           # POST /sync/*, GET /sync/status
├── data/
│   ├── knowledge.db          # Base vectorial (chunks + embeddings)
│   └── logs.db               # Logs de uso
├── python/                   # Python 3.12 embebido (portable)
├── config.env                # Configuracion local
├── config.env.example        # Plantilla de configuracion
├── requirements.txt          # Dependencias Python
├── install.bat               # Instalador automatico
├── run.bat                   # Inicio del servicio
└── stop.bat                  # Detencion del servicio
```

## API Endpoints

Base URL: `http://127.0.0.1:8090/api/v1`

| Metodo | Ruta | Auth | Descripcion |
|---|---|---|---|
| GET | `/health` | No | Health check (publico) |
| GET | `/stats` | Si | Estadisticas del servicio |
| GET | `/sources` | Si | Listar fuentes de conocimiento |
| POST | `/chat` | Si | Chat con respuesta JSON completa |
| POST | `/chat/stream` | Si | Chat con streaming SSE |
| GET | `/sync/status` | Si | Estado de sincronizacion |
| POST | `/sync/logs` | Si | Subir logs al servidor central |
| POST | `/sync/knowledge` | Si | Descargar base de conocimiento |

### Ejemplo de uso

```bash
curl -X POST http://127.0.0.1:8090/api/v1/chat \
  -H "X-API-Key: tu-api-key" \
  -H "Content-Type: application/json" \
  -d '{"message": "Que es la fotosintesis?", "top_k": 3}'
```

Respuesta:
```json
{
  "answer": "La fotosintesis es...",
  "sources": [
    {"source_name": "biologia.pdf", "page_number": 5, "score": 0.87}
  ],
  "conversation_id": "uuid",
  "tokens_in": 512,
  "tokens_out": 256,
  "latency_ms": 8500
}
```

Documentacion interactiva disponible en: `http://127.0.0.1:8090/docs`

## Solucion de Problemas

| Problema | Solucion |
|---|---|
| "Ollama no disponible" | Asegurate de que Ollama este corriendo (`ollama serve`) |
| Puerto ocupado | Usa `stop.bat` o elige otro puerto en `run.bat` |
| Respuestas lentas | Reduce `TOP_K`, `OLLAMA_NUM_CTX` o `MAX_CHUNK_LENGTH` en `config.env` |
| Respuestas cortadas | Aumenta `OLLAMA_NUM_PREDICT` en `config.env` |
| Respuestas no relevantes | Ajusta `MIN_RELEVANCE_SCORE` (mayor = mas estricto) |
| ModuleNotFoundError | Ejecuta `install.bat` para reinstalar dependencias |
| Base de conocimiento vacia | Configura `SERVER_URL` y ejecuta sync desde la API o `run.bat` |

## Licencia

Privada / Propietaria.
