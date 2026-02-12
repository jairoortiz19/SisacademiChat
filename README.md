# SisacademiChat

SisacademiChat es un cliente de chat educativo local que utiliza **RAG (Generación Aumentada por Recuperación)** para responder preguntas de estudiantes basándose en materiales de curso específicos.

El sistema utiliza modelos locales (**Ollama**) para privacidad y eficiencia, y se sincroniza con un servidor central para actualizaciones de conocimiento y telemetría.

## 🚀 Características

*   **Chat Educativo Local**: Respuestas generadas localmente usando LLMs (sin depender de internet para la inferencia).
*   **RAG (Retrieval-Augmented Generation)**: Respuestas basadas *únicamente* en documentos proporcionados (PDFs, guías, libros).
*   **Sincronización Inteligente**:
    *   Descarga de bases de conocimiento gestionadas centralmente.
    *   Subida de logs y métricas de uso anónimas.
*   **Stack Eficiente**: Python, FastAPI, SQLite (Vector Search), Ollama.

## 🛠️ Requisitos Previos

1.  **Python 3.12+**
2.  **Ollama**: Debe estar instalado y ejecutándose.
    *   Descargar en [ollama.com](https://ollama.com)
    *   Ejecutar `ollama pull qwen2.5:3b` (o el modelo configurado).

## 📦 Instalación

1.  Clonar el repositorio:
    ```bash
    git clone https://github.com/jairoortiz19/SisacademiChat.git
    cd SisacademiChat
    ```

2.  Crear entorno virtual e instalar dependencias:
    ```bash
    python -m venv venv
    .\venv\Scripts\activate
    pip install -r requirements.txt
    ```

3.  Configurar variables de entorno:
    *   Renombrar `config.env.example` a `config.env` (o crear uno nuevo).
    *   Asegurar que `OLLAMA_MODEL` coincida con el modelo que tienes en Ollama.

## ▶️ Ejecución

### Modo Desarrollo
```bash
uvicorn app.main:app --reload --port 8090
```

### Scripts (Windows)
*   `run.bat`: Inicia la aplicación.
*   `install.bat`: Instala dependencias.

## 🏗️ Arquitectura

*   **APP**: FastAPI maneja la API REST.
*   **Vector Store**: `sqlite-vec` almacena los embeddings y realiza búsquedas de similaridad localmente.
*   **LLM Service**: Conecta con Ollama para generar respuestas usando el contexto recuperado.
*   **Sync Service**: Sincroniza `knowledge.db` y `logs.db` con el servidor central.

## 🔧 Solución de Problemas

*   **Error "Ollama no disponible"**: Asegúrate de que la aplicación Ollama de escritorio esté abierta.
*   **Respuestas no relevantes**: Verifica que el `MIN_RELEVANCE_SCORE` en `config.env` sea adecuado para tu modelo de embeddings (si usas modelos no normalizados, valores negativos pueden ser necesarios).

## 📄 Licencia

Privada / Propietaria.
