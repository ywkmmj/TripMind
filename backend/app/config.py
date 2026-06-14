import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

# ChromaDB telemetry can create background network retries in restricted
# environments and does not affect product behavior.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


# 数据库配置
DB_DIR = BACKEND_DIR / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)

# 数据库类型配置
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite")  # "sqlite" or "postgresql"

# SQLite 配置（默认）
SQLITE_DB_PATH = DB_DIR / "app.db"

# PostgreSQL 配置
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "trip_planner")

# 构建数据库 URL
if DATABASE_TYPE == "postgresql":
    DATABASE_URL = (
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
else:
    DATABASE_URL = f"sqlite:///{SQLITE_DB_PATH.as_posix()}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# 大模型配置
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai_compatible")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-max")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))
ENABLE_LLM_QUERY_REWRITE = os.getenv("ENABLE_LLM_QUERY_REWRITE", "false").lower() == "true"

# 快速模式专用模型（比默认模型更快，适合fast/async模式）
TRIP_PLANNER_FAST_MODEL = os.getenv("TRIP_PLANNER_FAST_MODEL", "qwen-max")


# RAG / 向量库配置
_chroma_db_dir_raw = Path(os.getenv("CHROMA_DB_DIR", "db/chroma_db"))
CHROMA_DB_DIR = (
    _chroma_db_dir_raw
    if _chroma_db_dir_raw.is_absolute()
    else BACKEND_DIR / _chroma_db_dir_raw
)
CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)

CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "travel_guides")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))
RERANK_MODEL = os.getenv("RERANK_MODEL", "qwen3-rerank")
USE_HYBRID_SEARCH = os.getenv("USE_HYBRID_SEARCH", "true").lower() == "true"


# Redis / 缓存配置
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "trip_planner")
REDIS_CACHE_VERSION = os.getenv("REDIS_CACHE_VERSION", "v1")  # 缓存版本号
REDIS_DEFAULT_TTL_SECONDS = int(os.getenv("REDIS_DEFAULT_TTL_SECONDS", "1800"))
REDIS_WEATHER_TTL_SECONDS = int(os.getenv("REDIS_WEATHER_TTL_SECONDS", "1800"))
REDIS_MAP_TTL_SECONDS = int(os.getenv("REDIS_MAP_TTL_SECONDS", "86400"))
REDIS_RAG_TTL_SECONDS = int(os.getenv("REDIS_RAG_TTL_SECONDS", "21600"))
REDIS_RERANK_TTL_SECONDS = int(os.getenv("REDIS_RERANK_TTL_SECONDS", "21600"))
REDIS_LLM_DRAFT_TTL_SECONDS = int(os.getenv("REDIS_LLM_DRAFT_TTL_SECONDS", "21600"))


# 高德地图配置
AMAP_API_KEY = os.getenv("AMAP_API_KEY", "")
AMAP_BASE_URL = os.getenv("AMAP_BASE_URL", "https://restapi.amap.com/v3")
AMAP_WEB_SEARCH_API_URL = os.getenv("AMAP_WEB_SEARCH_API_URL", "https://restapi.amap.com/v3/place/text")
AMAP_DEFAULT_CITY = os.getenv("AMAP_DEFAULT_CITY", "")
AMAP_TIMEOUT_SECONDS = int(os.getenv("AMAP_TIMEOUT_SECONDS", "20"))
ENABLE_AMAP_ENRICHMENT = os.getenv("ENABLE_AMAP_ENRICHMENT", "true").lower() == "true"
