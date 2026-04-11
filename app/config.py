import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Rutas base del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.env"

load_dotenv(CONFIG_FILE)


class Settings:
    # Servicio
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8090"))

    # Seguridad
    API_KEY: str = os.getenv("API_KEY", "cambiar-esta-clave-en-produccion")
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))

    # Ollama
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
    OLLAMA_NUM_PREDICT: int = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
    OLLAMA_TEMPERATURE: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))
    OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")

    # RAG
    TOP_K: int = int(os.getenv("TOP_K", "3"))
    MAX_QUERY_LENGTH: int = int(os.getenv("MAX_QUERY_LENGTH", "500"))
    MIN_RELEVANCE_SCORE: float = float(os.getenv("MIN_RELEVANCE_SCORE", "0.25"))
    MAX_CHUNK_LENGTH: int = int(os.getenv("MAX_CHUNK_LENGTH", "500"))

    # Embeddings
    EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIM: int = 384

    # Cache de respuestas RAG
    QUERY_CACHE_TTL: int = int(os.getenv("QUERY_CACHE_TTL", "3600"))      # segundos (1 hora)
    QUERY_CACHE_MAX_SIZE: int = int(os.getenv("QUERY_CACHE_MAX_SIZE", "200"))  # max entradas

    # Servidor central
    SERVER_URL: str = os.getenv("SERVER_URL", "")
    SERVER_API_KEY: str = os.getenv("SERVER_API_KEY", "")
    DEVICE_ID: str = os.getenv("DEVICE_ID", "")

    # Bases de datos
    KNOWLEDGE_DB: Path = DATA_DIR / "knowledge.db"
    LOGS_DB: Path = DATA_DIR / "logs.db"

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.DEVICE_ID:
            self._generate_device_id()

    def _generate_device_id(self):
        """Genera un DEVICE_ID unico y lo persiste en config.env."""
        self.DEVICE_ID = str(uuid.uuid4())
        try:
            content = CONFIG_FILE.read_text(encoding="utf-8")
            content = content.replace("DEVICE_ID=", f"DEVICE_ID={self.DEVICE_ID}")
            CONFIG_FILE.write_text(content, encoding="utf-8")
        except Exception:
            pass


settings = Settings()
