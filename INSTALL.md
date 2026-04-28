# SisacademiChat — Guia de Instalacion e Integracion

---

## Requisitos del sistema

| Requisito | Detalle |
|---|---|
| Sistema operativo | Windows 10 (build 1803+) o Windows 11, 64-bit |
| RAM minima | 4 GB (recomendado 8 GB) |
| Disco | ~3 GB libres (Python + modelo Ollama + embeddings) |
| Internet | Requerido solo en la primera instalacion |
| Software previo | Ninguno — el instalador descarga todo automaticamente |

---

## Instalacion en PC nuevo

### Paso 1 — Descargar el instalador

Descargar `install.bat` desde el repositorio y guardarlo en cualquier ubicacion (Escritorio, unidad USB, etc.).

### Paso 2 — Ejecutar

Doble clic en `install.bat`. El proceso es completamente automatico:

```
[1/5] Verificando requisitos del sistema
[2/5] Descargando repositorio desde GitHub
[3/5] Extrayendo archivos
[4/5] Escribiendo configuracion (config.env)
[5/5] Iniciando SisacademiChat
        └── [1/6] Ollama
        └── [2/6] Servicio Ollama y modelos LLM
        └── [3/6] Python embebido
        └── [4/6] Dependencias Python
        └── [5/6] Base de datos y embeddings
        └── [6/6] Servicio HTTP
```

La primera instalacion tarda entre **5 y 20 minutos** dependiendo de la conexion a internet (descarga el modelo LLM ~500 MB y el modelo de embeddings ~46 MB).

### Paso 3 — Verificar

Al finalizar, la terminal muestra:

```
============================================
  Servicio:  http://127.0.0.1:8090
  API Docs:  http://127.0.0.1:8090/docs
  Detener:   Ctrl+C  o  stop.bat
============================================
```

Abrir `http://127.0.0.1:8090/health` en el navegador debe retornar `{"status":"ok",...}`.

---

## Directorio de instalacion

El instalador crea todo en:

```
C:\Sitios\SisacademiChat\
├── app\                   # Codigo fuente de la aplicacion
├── data\
│   ├── knowledge.db       # Base de conocimiento (vectores + documentos)
│   └── logs.db            # Logs de uso
├── python\                # Python 3.12 embebido (portable, no afecta el sistema)
├── config.env             # Configuracion local del servicio
├── requirements.txt       # Dependencias Python
├── run.bat                # Inicia el servicio
└── stop.bat               # Detiene el servicio
```

> `python\` y `config.env` **no se sobreescriben** en reinstalaciones, preservando la configuracion y evitando rebajar Python.

---

## Iniciar y detener el servicio

| Accion | Comando |
|---|---|
| Iniciar | Doble clic en `C:\Sitios\SisacademiChat\run.bat` |
| Detener | Doble clic en `C:\Sitios\SisacademiChat\stop.bat` o `Ctrl+C` en la terminal |
| Reinstalar / actualizar | Doble clic en `install.bat` → seleccionar `S` |

El servicio **no arranca automaticamente** con Windows. Para configurar inicio automatico, crear una tarea en el Programador de tareas de Windows apuntando a `run.bat`.

---

## Puerto y direccion del servicio

| Parametro | Valor por defecto | Donde cambiarlo |
|---|---|---|
| Host | `127.0.0.1` (solo local) | `HOST` en `config.env` |
| Puerto | `8090` | `PORT` en `config.env` |
| Prefijo de API | `/api/v1` | Fijo en el codigo |

**URL base:** `http://127.0.0.1:8090/api/v1`

> Por defecto el servicio escucha **solo en localhost**. Para exponerlo en la red local
> cambiar `HOST=0.0.0.0` en `config.env` y reiniciar con `run.bat`.

### Exponer en red local (opcional)

Editar `C:\Sitios\SisacademiChat\config.env`:

```env
HOST=0.0.0.0
PORT=8090
```

Reiniciar el servicio. Otros equipos en la misma red podran acceder via:
```
http://<IP-del-PC>:8090/api/v1
```

---

## Integracion desde otro sistema

### Autenticacion

Todas las peticiones (excepto `/health`) deben incluir la cabecera:

```
X-API-Key: <valor-de-API_KEY-en-config.env>
```

### Verificar que el servicio esta activo

Antes de hacer peticiones, consultar el health check:

```bash
curl http://127.0.0.1:8090/health
```

Respuesta esperada:
```json
{
  "status": "ok",
  "ollama": "connected",
  "knowledge_chunks": 9332,
  "knowledge_sources": 109
}
```

Si `status` es `"degraded"`, el LLM no esta disponible pero el servicio puede responder con datos de cache.

### Enviar una pregunta (chat)

```bash
curl -X POST http://127.0.0.1:8090/api/v1/chat \
  -H "X-API-Key: uoemm2mEzkGwxVS_6T7WPvOdgwB5kyyHScOdssq-zfI" \
  -H "Content-Type: application/json" \
  -d '{"message": "Que es la fotosintesis?"}'
```

Respuesta:
```json
{
  "answer": "La fotosintesis es el proceso mediante el cual...",
  "sources": [
    {
      "source_name": "biologia.pdf",
      "page_number": 12,
      "score": 0.87,
      "chunk_text": "..."
    }
  ],
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tokens_in": 312,
  "tokens_out": 128,
  "latency_ms": 3200
}
```

### Enviar una pregunta (streaming)

Recomendado para interfaces de usuario que muestran la respuesta en tiempo real:

```bash
curl -X POST http://127.0.0.1:8090/api/v1/chat/stream \
  -H "X-API-Key: uoemm2mEzkGwxVS_6T7WPvOdgwB5kyyHScOdssq-zfI" \
  -H "Content-Type: application/json" \
  -d '{"message": "Que es la fotosintesis?"}' \
  --no-buffer
```

La respuesta llega como eventos SSE en este orden:

```
data: {"type":"sources","sources":[...],"conversation_id":"uuid"}

data: {"type":"token","content":"La "}
data: {"type":"token","content":"fotosintesis "}
...
data: {"type":"done","tokens_in":312,"tokens_out":128,"latency_ms":3200}
```

**Consumir SSE desde JavaScript:**

```javascript
const response = await fetch('http://127.0.0.1:8090/api/v1/chat/stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': 'tu-api-key'
  },
  body: JSON.stringify({ message: 'Que es la fotosintesis?' })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const lines = decoder.decode(value).split('\n');
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const event = JSON.parse(line.slice(6));

    if (event.type === 'token') {
      process.stdout.write(event.content); // mostrar token en pantalla
    } else if (event.type === 'sources') {
      console.log('Fuentes:', event.sources);
    } else if (event.type === 'done') {
      console.log('Latencia:', event.latency_ms, 'ms');
    }
  }
}
```

**Consumir SSE desde Python:**

```python
import httpx, json

with httpx.Client() as client:
    with client.stream(
        "POST",
        "http://127.0.0.1:8090/api/v1/chat/stream",
        headers={"X-API-Key": "tu-api-key", "Content-Type": "application/json"},
        json={"message": "Que es la fotosintesis?"},
        timeout=120,
    ) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event["type"] == "token":
                print(event["content"], end="", flush=True)
            elif event["type"] == "done":
                print(f"\nLatencia: {event['latency_ms']}ms")
```

---

## Configuracion en `config.env`

El archivo `C:\Sitios\SisacademiChat\config.env` controla todo el comportamiento del servicio.
Editar con cualquier editor de texto y reiniciar `run.bat` para aplicar cambios.

```env
# Servicio
PORT=8090
HOST=127.0.0.1

# Autenticacion
API_KEY=uoemm2mEzkGwxVS_6T7WPvOdgwB5kyyHScOdssq-zfI
RATE_LIMIT_PER_MINUTE=30

# Modelo LLM (Ollama)
OLLAMA_MODEL=qwen2.5:0.5b

# Servidor central (sincronizacion de base de conocimiento)
SERVER_URL=http://servidor-central:8091
SERVER_API_KEY=clave-del-servidor
DEVICE_ID=uuid-unico-de-este-dispositivo
```

Para referencia completa de todas las variables ver [API.md](API.md) seccion Configuracion, o el [README.md](README.md).

---

## Solucion de problemas

| Problema | Causa probable | Solucion |
|---|---|---|
| `install.bat` falla en descarga | Repositorio privado o sin internet | Verificar conexion; si el repo es privado contactar al administrador |
| Puerto 8090 ocupado | Otro proceso usa el puerto | `run.bat` lo detecta y ofrece liberar el puerto o usar otro |
| `status: degraded` en `/health` | Ollama no esta corriendo | Ejecutar `ollama serve` o reiniciar con `run.bat` |
| `knowledge_chunks: 0` | Base de conocimiento vacia | Ejecutar `POST /api/v1/sync/knowledge` con la API key |
| El servicio se cierra solo | Error en la app | Revisar la terminal para ver el mensaje de error |
| Respuestas muy lentas | Hardware limitado o modelo grande | Reducir `OLLAMA_NUM_CTX` y `TOP_K` en `config.env` |
| `503` en endpoints `/professor/` | Datos academicos no sincronizados | Ejecutar `POST /api/v1/sync/knowledge` |
