# SisacademiChat — Referencia de API

**Base URL:** `http://<host>:<port>/api/v1`  
**Default local:** `http://127.0.0.1:8090/api/v1`  
**Swagger UI:** `http://127.0.0.1:8090/docs`

---

## Autenticacion

Todos los endpoints (excepto `/health`) requieren la cabecera:

```
X-API-Key: <tu-api-key>
```

Configurada en `config.env` → `API_KEY`.  
Respuesta sin auth: `401 Unauthorized`.

---

## Rate Limiting

`30 peticiones / minuto por IP` (configurable en `RATE_LIMIT_PER_MINUTE`).  
Al superarlo: `429 Too Many Requests`.

---

## Endpoints

### Health

#### `GET /health`

Verifica el estado del servicio. **No requiere autenticacion.**

**Response `200`:**
```json
{
  "status": "ok",
  "ollama": "connected",
  "ollama_model": "qwen2.5:0.5b",
  "knowledge_chunks": 9332,
  "knowledge_sources": 109,
  "pending_logs": 0,
  "device_id": "ba23d820-3b99-435c-9dc0-b3c35be0c07b"
}
```

| Campo | Tipo | Descripcion |
|---|---|---|
| `status` | `"ok"` \| `"degraded"` | `degraded` si Ollama no responde o el modelo no esta disponible |
| `ollama` | string | `"connected"` o descripcion del error |
| `knowledge_chunks` | int | Total de fragmentos en la base de conocimiento |
| `knowledge_sources` | int | Total de fuentes (documentos) indexadas |
| `pending_logs` | int | Logs pendientes de sincronizar con el servidor central |
| `device_id` | string | UUID unico de este dispositivo |

---

### Stats

#### `GET /stats` 🔒

Estadisticas generales del servicio.

**Response `200`:**
```json
{
  "total_sources": 109,
  "total_chunks": 9332,
  "total_queries": 1450,
  "pending_sync_logs": 3,
  "device_id": "ba23d820-3b99-435c-9dc0-b3c35be0c07b"
}
```

---

### Chat

#### `POST /chat` 🔒

Envia una pregunta y recibe la respuesta completa en JSON. Espera a que el LLM termine antes de responder.

**Request body:**
```json
{
  "message": "Que es la fotosintesis?",
  "conversation_id": "opcional-uuid-conversacion",
  "top_k": 3
}
```

| Campo | Tipo | Requerido | Descripcion |
|---|---|---|---|
| `message` | string | Si | Pregunta del usuario. Max 500 caracteres |
| `conversation_id` | string | No | UUID de conversacion para contexto. Si se omite, se genera uno nuevo |
| `top_k` | int (1-20) | No | Fragmentos a recuperar del RAG. Default: valor de `TOP_K` en config |

**Response `200`:**
```json
{
  "answer": "La fotosintesis es el proceso por el cual...",
  "sources": [
    {
      "source_name": "biologia.pdf",
      "chunk_text": "La fotosintesis convierte luz solar en...",
      "page_number": 12,
      "section": "Capitulo 3",
      "score": 0.87
    }
  ],
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tokens_in": 312,
  "tokens_out": 128,
  "latency_ms": 3200
}
```

| Campo | Tipo | Descripcion |
|---|---|---|
| `answer` | string | Respuesta generada por el LLM |
| `sources` | array | Fragmentos de la KB usados como contexto |
| `sources[].source_name` | string | Nombre del documento fuente |
| `sources[].chunk_text` | string | Fragmento exacto usado |
| `sources[].page_number` | int \| null | Pagina del documento |
| `sources[].section` | string \| null | Seccion del documento |
| `sources[].score` | float | Relevancia semantica (0.0 – 1.0) |
| `conversation_id` | string | UUID de la conversacion |
| `tokens_in` | int | Tokens enviados al LLM |
| `tokens_out` | int | Tokens generados por el LLM |
| `latency_ms` | int | Latencia total en milisegundos |

> Si la pregunta no tiene respaldo en la KB (score bajo), el sistema responde con un mensaje de "no tengo informacion" **sin invocar el LLM**, con `sources: []`.

---

#### `POST /chat/stream` 🔒

Misma logica que `/chat` pero responde en **Server-Sent Events (SSE)**. Ideal para mostrar la respuesta token a token en la UI.

**Request body:** identico a `POST /chat`.

**Response:** `Content-Type: text/event-stream`

Secuencia de eventos:

```
data: {"type": "sources", "sources": [...], "conversation_id": "uuid"}

data: {"type": "token", "content": "La "}

data: {"type": "token", "content": "fotosintesis "}

data: {"type": "done", "conversation_id": "uuid", "tokens_in": 312, "tokens_out": 128, "latency_ms": 3200}
```

| Evento | Campos | Descripcion |
|---|---|---|
| `sources` | `sources`, `conversation_id` | Primer evento. Llega antes de los tokens con las fuentes usadas |
| `token` | `content` | Un fragmento de texto de la respuesta |
| `done` | `conversation_id`, `tokens_in`, `tokens_out`, `latency_ms` | Fin del stream con metricas |
| `error` | `error` | Fallo durante el procesamiento |

**Ejemplo con curl:**
```bash
curl -X POST http://127.0.0.1:8090/api/v1/chat/stream \
  -H "X-API-Key: tu-api-key" \
  -H "Content-Type: application/json" \
  -d '{"message": "Que es la fotosintesis?"}' \
  --no-buffer
```

---

### Sources

#### `GET /sources` 🔒

Lista todas las fuentes de conocimiento indexadas en la base de datos local.

**Response `200`:**
```json
[
  {
    "source_name": "biologia.pdf",
    "chunk_count": 145,
    "ingested_at": "2026-04-20T10:32:00"
  }
]
```

---

### Profesor

> Estos endpoints leen datos academicos pre-procesados por SisacademiServer y sincronizados
> localmente via `POST /sync/knowledge`. Funcionan completamente **offline** despues de la
> primera sincronizacion.
>
> Si los datos academicos no estan disponibles devuelven `503` con instrucciones para sincronizar.

---

#### `GET /professor/dashboard` 🔒

Panel de control global con radiografia completa de todos los estudiantes.

**Response `200`:**
```json
{
  "total_estudiantes": 120,
  "total_evaluaciones": 840,
  "promedio_general": 7.3,
  "nota_minima": 3.0,
  "nota_maxima": 10.0,
  "distribucion": {
    "reprobado": 95,
    "suficiente": 120,
    "bien": 310,
    "notable": 215,
    "sobresaliente": 100
  },
  "rendimiento_por_materia": [
    { "source_name": "Matematicas", "promedio": 6.1, "estudiantes": 120 }
  ],
  "estudiantes_en_riesgo": [
    { "id": 42, "name": "Juan Lopez", "group_name": "3ro-A", "promedio": 4.2 }
  ],
  "resumen_narrativo": "Se identifican 18 estudiantes en riesgo...",
  "generado_con_ia": true
}
```

| Campo | Descripcion |
|---|---|
| `distribucion` | Evaluaciones por rango: reprobado (0–5.9), suficiente (6–6.9), bien (7–7.9), notable (8–8.9), sobresaliente (9–10) |
| `rendimiento_por_materia` | Ordenado de menor a mayor promedio |
| `estudiantes_en_riesgo` | Hasta 20 estudiantes con promedio < 6.0 |
| `resumen_narrativo` | Texto generado por IA con alertas y recomendaciones. `null` si Ollama no esta activo |

---

#### `GET /professor/grades/student/{student_id}` 🔒

Historial completo de calificaciones de un estudiante.

**Path params:**
- `student_id` (int) — ID del estudiante

**Query params:**
- `source_name` (string, opcional) — Filtrar por materia. Ej: `?source_name=Matematicas`

**Response `200`:**
```json
{
  "student": { "id": 42, "name": "Juan Lopez", "group": "3ro-A" },
  "grades": [
    {
      "source_name": "Matematicas",
      "grade": 6.5,
      "max_grade": 10.0,
      "evaluation_type": "examen",
      "topic": "Ecuaciones cuadraticas",
      "notes": "Necesita refuerzo en factorizacion",
      "created_at": "2026-03-15T09:00:00"
    }
  ],
  "total": 24
}
```

**Errores:** `404` si el estudiante no existe.

---

#### `GET /professor/analytics/student/{student_id}` 🔒

Resumen estadistico del rendimiento de un estudiante.

**Response `200`:**
```json
{
  "student": { "id": 42, "name": "Juan Lopez", "group": "3ro-A" },
  "promedio_global": 7.2,
  "nota_minima": 4.5,
  "nota_maxima": 9.8,
  "total_evaluaciones": 24,
  "por_materia": [
    { "source_name": "Matematicas", "promedio": 5.9, "evaluaciones": 8 }
  ],
  "por_tipo": [
    { "evaluation_type": "examen", "promedio": 6.0 },
    { "evaluation_type": "tarea", "promedio": 8.1 }
  ]
}
```

---

#### `GET /professor/analytics/source/{source_name}` 🔒

Estadisticas completas de una materia/asignatura.

**Path params:**
- `source_name` (string) — Nombre de la materia. Ej: `Matematicas`

**Response `200`:**
```json
{
  "source_name": "Matematicas",
  "total_evaluaciones": 360,
  "estudiantes_evaluados": 45,
  "promedio": 6.8,
  "nota_minima": 2.0,
  "nota_maxima": 10.0,
  "distribucion": {
    "reprobado": 12, "suficiente": 10, "bien": 8, "notable": 10, "sobresaliente": 5
  },
  "estudiantes_en_riesgo": [
    { "id": 42, "name": "Juan Lopez", "promedio": 4.2 }
  ],
  "top_estudiantes": [
    { "id": 7, "name": "Sofia Ramirez", "promedio": 9.8 }
  ]
}
```

---

#### `GET /professor/analytics/group/{group_name}` 🔒

Rendimiento academico de un grupo completo.

**Path params:**
- `group_name` (string) — Nombre del grupo. Ej: `3ro-A`

**Response `200`:**
```json
{
  "group_name": "3ro-A",
  "total_estudiantes": 30,
  "total_evaluaciones": 720,
  "promedio_general": 7.4,
  "nota_minima": 3.0,
  "nota_maxima": 10.0,
  "por_materia": [
    { "source_name": "Historia", "promedio": 8.2 },
    { "source_name": "Quimica", "promedio": 6.1 }
  ],
  "ranking": [
    { "id": 7, "name": "Sofia Lopez", "promedio": 9.1 },
    { "id": 15, "name": "Miguel Torres", "promedio": 4.8 }
  ]
}
```

---

#### `GET /professor/analytics/groups/compare` 🔒

Compara rendimiento entre 2 o mas grupos lado a lado.

**Query params:**
- `groups` (string, requerido) — Nombres de grupos separados por coma. Ej: `?groups=3ro-A,3ro-B`

**Response `200`:**
```json
{
  "grupos_comparados": ["3ro-A", "3ro-B"],
  "ranking": [
    { "group_name": "3ro-A", "promedio": 7.8, "estudiantes": 30, "evaluaciones": 720 },
    { "group_name": "3ro-B", "promedio": 7.1, "estudiantes": 28, "evaluaciones": 672 }
  ],
  "por_materia": [
    {
      "source_name": "Matematicas",
      "3ro-A": { "promedio": 7.5 },
      "3ro-B": { "promedio": 6.3 },
      "mejor_grupo": "3ro-A",
      "diferencia": 1.2
    }
  ],
  "resumen": "3ro-A lidera con promedio 7.8. 3ro-B tiene promedio 7.1.",
  "analisis_narrativo": "La diferencia mas significativa se encuentra en Matematicas...",
  "generado_con_ia": true
}
```

**Errores:** `400` si se pasa menos de 2 grupos.

---

#### `GET /professor/student/{student_id}/improvement-plan` 🔒

Genera un plan de mejora academica personalizado listo para imprimir. Combina analisis de calificaciones, busqueda semantica en la KB (RAG) y generacion de texto con IA.

**Response `200`:**
```json
{
  "student": { "id": 42, "name": "Juan Lopez", "group": "3ro-A" },
  "promedio_general": 5.8,
  "materias_debiles": [
    { "source_name": "Matematicas", "promedio": 4.5, "tendencia": "Empeorando" }
  ],
  "materias_detalle": [ ... ],
  "plan_imprimible": "PLAN DE MEJORA ACADEMICA\n========================\n...",
  "generado_con_ia": true
}
```

| Campo | Descripcion |
|---|---|
| `plan_imprimible` | Texto completo listo para imprimir y firmar. `null` si Ollama no esta activo |
| `materias_detalle` | Temas criticos + fragmentos del material de estudio encontrados via RAG |
| `generado_con_ia` | `false` si Ollama no estaba disponible (retorna datos estructurados sin texto) |

---

#### `GET /professor/student/{student_id}/practice-exercises` 🔒

Genera ejercicios de practica personalizados para las materias debiles del estudiante, basados en el material real del curso.

**Response `200`:**
```json
{
  "student": { "id": 42, "name": "Juan Lopez", "group": "3ro-A" },
  "promedio_general": 5.8,
  "materias_detalle": [ ... ],
  "ejercicios_generados": "EJERCICIOS DE PRACTICA PERSONALIZADOS\n...",
  "generado_con_ia": true
}
```

**Errores:** `404` si el estudiante no tiene materias debiles o no hay datos academicos.

---

#### `GET /professor/student/{student_id}/prediction` 🔒

Predice el rendimiento futuro del estudiante usando regresion lineal sobre su historial.

**Response `200`:**
```json
{
  "student": { "id": 42, "name": "Juan Lopez" },
  "riesgo_global": "alto",
  "materias_criticas": ["Fisica"],
  "predicciones": [
    {
      "source_name": "Matematicas",
      "promedio_actual": 5.8,
      "tendencia": "Mejorando",
      "pendiente": 0.3,
      "nota_predicha": 6.5,
      "probabilidad_aprobar": 0.72
    },
    {
      "source_name": "Fisica",
      "promedio_actual": 4.5,
      "tendencia": "Empeorando",
      "pendiente": -0.4,
      "nota_predicha": 3.8,
      "probabilidad_aprobar": 0.35
    }
  ],
  "mensaje": "Tendencia positiva en Matematicas. Fisica requiere atencion urgente."
}
```

| Campo | Valores | Descripcion |
|---|---|---|
| `riesgo_global` | `bajo` \| `medio` \| `alto` \| `critico` | Basado en promedio general y materias criticas |
| `tendencia` | `Mejorando` \| `Empeorando` \| `Estable` | Pendiente > 0.1 = Mejorando, < -0.1 = Empeorando |
| `probabilidad_aprobar` | 0.0 – 1.0 | Probabilidad estimada de aprobar la proxima evaluacion |

> Requiere minimo 3 evaluaciones por materia para calcular la prediccion. Materias con menos datos no aparecen en `predicciones`.

---

### Sync

#### `POST /sync/knowledge` 🔒

Descarga la base de conocimiento desde el servidor central y reemplaza la local. Hace backup automatico antes de reemplazar.

**Response `200`:**
```json
{
  "status": "success",
  "message": "Base de conocimiento actualizada"
}
```

**Errores:**
- `400` — `SERVER_URL` no configurado en `config.env`
- `502` — Error al conectar con el servidor central

---

#### `POST /sync/logs` 🔒

Envia los logs de uso pendientes al servidor central.

**Response `200`:**
```json
{
  "synced": 42,
  "failed": 0,
  "message": "42 logs sincronizados"
}
```

---

#### `GET /sync/status` 🔒

Estado de la ultima sincronizacion realizada.

**Response `200`:**
```json
{
  "pending_logs": 5,
  "last_sync_at": "2026-04-27T21:00:00",
  "last_sync_result": "success",
  "records_synced": 38
}
```

---

## Codigos de error comunes

| HTTP | Descripcion |
|---|---|
| `401` | API Key ausente o invalida |
| `404` | Recurso no encontrado (estudiante, grupo, etc.) |
| `422` | Error de validacion en el body o parametros |
| `429` | Rate limit excedido |
| `400` | Parametro invalido o servidor central no configurado |
| `502` | Error al comunicarse con el servidor central |
| `503` | Datos academicos no disponibles (ejecutar `POST /sync/knowledge`) |

**Formato de error:**
```json
{
  "detail": {
    "error": "Descripcion del error",
    "code": "CODIGO_ERROR"
  }
}
```

---

## Notas de integracion

- El endpoint `/chat/stream` es preferible para interfaces de usuario ya que muestra la respuesta en tiempo real.
- Los endpoints del profesor bajo `/professor/` requieren datos academicos sincronizados. Verificar con `GET /health` → `knowledge_sources > 0` antes de usarlos.
- `conversation_id` en `/chat` es opcional pero recomendado para agrupar logs de la misma sesion.
- El campo `score` en `sources` indica la relevancia semantica del fragmento (0.0 – 1.0). Scores < 0.25 indican baja confianza.
