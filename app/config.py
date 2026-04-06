import os
import sys

cur_dir = os.getcwd()
parent_dir = os.path.realpath(os.path.join(os.path.dirname(cur_dir)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)
    sys.path.append(cur_dir)
sys.path.insert(1, ".")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
# -------------------------
# Core Services
# -------------------------

VLLM_URL = os.getenv("VLLM_URL")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL_NAME")
REDIS_URL = os.getenv("REDIS_URL")

# -------------------------
# Embeddings
# -------------------------

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2"
)

EMBEDDING_DIMENSION = 384

# -------------------------
# ChromaDB
# -------------------------
CHROMA_PERSIST_DIR = os.getenv(
    "CHROMA_PERSIST_DIR",
    os.path.join(PROJECT_ROOT, "data", "chroma"),
)
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "rag_docs")
CHROMA_ANONYMIZED_TELEMETRY = os.getenv("CHROMA_ANONYMIZED_TELEMETRY", "false").strip().lower() in {"1", "true", "yes", "on"}
USECASE_REGISTRY_PATH = os.getenv(
    "USECASE_REGISTRY_PATH",
    os.path.join(PROJECT_ROOT, "data", "usecases.json"),
)
DEFAULT_USECASE_ID = os.getenv("DEFAULT_USECASE_ID", "default")
FINANCE_USECASE_ID = os.getenv("FINANCE_USECASE_ID", "financial-guide")

# -------------------------
# RAG
# -------------------------

TOP_K = 5
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# -------------------------
# Cache
# -------------------------

CACHE_TTL_SECONDS = 3600

# -------------------------
# Finance Assistant
# -------------------------
FINANCE_DB_PATH = os.getenv(
    "FINANCE_DB_PATH",
    os.path.join(PROJECT_ROOT, "data", "finance.db"),
)
CHAT_DB_PATH = os.getenv(
    "CHAT_DB_PATH",
    os.path.join(PROJECT_ROOT, "data", "chat_history.db"),
)
DB_BACKEND = os.getenv("DB_BACKEND", "postgres").strip().lower()
DATABASE_URL = os.getenv(
    "DATABASE_URL"
)
FINANCE_DATABASE_URL = os.getenv(
    "FINANCE_DATABASE_URL",
    DATABASE_URL if DB_BACKEND == "postgres" else f"sqlite:///{FINANCE_DB_PATH}",
)
TTS_OUTPUT_DIR = os.getenv(
    "TTS_OUTPUT_DIR",
    os.path.join(PROJECT_ROOT, "data", "tts"),
)
TTS_FILE_TTL_SECONDS = int(os.getenv("TTS_FILE_TTL_SECONDS"))
CHAT_DAILY_LIMIT = int(os.getenv("CHAT_DAILY_LIMIT"))
CHAT_DAILY_LIMITS = os.getenv("CHAT_DAILY_LIMITS")
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Africa/Addis_Ababa")

# -------------------------
# Gemini API Configurations
     # other gemini API key = AIzaSyArp5ALNAMDnQvOI3jFhG-e4bLwYMNNC84
# -------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_STT_MODEL = os.getenv("GEMINI_STT_MODEL")
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL")
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE")
VISION_CHAT_URL = os.getenv("VISION_CHAT_URL")
