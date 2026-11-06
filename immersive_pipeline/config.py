"""Конфигурация пайплайна: пути, ключи API, пороги и квоты.

Любое значение можно переопределить переменной окружения или файлом `.env`
рядом с этим файлом (см. `.env.example`).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:  # python-dotenv необязателен
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


def _env(name, default=None):
    value = os.getenv(name)
    return default if value in (None, "") else value


def _int(name, default):
    return int(_env(name, default))


def _float(name, default):
    return float(_env(name, default))


# --- Пути -------------------------------------------------------------------
DATA_DIR = Path(_env("DATA_DIR", BASE_DIR / "data"))
STATE_DIR = DATA_DIR / ".state"
SEEDS_FILE = Path(_env("SEEDS_FILE", BASE_DIR / "seeds.json"))
MANUAL_CANDIDATES = DATA_DIR / "manual_candidates.json"   # кейсы, добавленные руками
RAW_CANDIDATES = DATA_DIR / "raw_candidates.json"         # выход этапа 1
ENRICHED_CASES = DATA_DIR / "enriched_cases.json"         # выход этапа 2
SCORED_CASES = DATA_DIR / "scored_cases.json"             # все оценённые кейсы (этап 3)
TOP_CASES = DATA_DIR / "top_cases.json"                   # отобранные топ-100 (этап 3)
FINAL_CASES = DATA_DIR / "final_cases.json"               # выход этапа 4 (cases.json)
FINAL_SCHEMA = DATA_DIR / "cases.schema.json"             # JSON Schema для cases.json

# Уже имеющиеся проекты, с которыми нельзя пересекаться (через os.pathsep).
EXISTING_CASES = [Path(p) for p in _env(
    "EXISTING_CASES", str(DATA_DIR / "existing_cases.json")).split(os.pathsep) if p]

# --- Предметные ограничения -------------------------------------------------
YEAR_MIN = 2018
YEAR_MAX = 2026
FUZZY_THRESHOLD = _float("FUZZY_THRESHOLD", 0.82)   # SequenceMatcher для дублей
TARGET_POOL_MIN = 250
TARGET_POOL_MAX = _int("TARGET_POOL_MAX", 300)
FINAL_COUNT = _int("FINAL_COUNT", 100)
SUMMARY_LANGUAGE = _env("SUMMARY_LANGUAGE", "ru")

# Сбалансированная структура топ-100 (сумма = FINAL_COUNT). Недобор в одной
# категории добирается лучшими кейсами из остальных.
CATEGORY_QUOTAS = {
    "Museums & Cultural Exhibitions": 30,
    "Brand Activations & Corporate Shows": 30,
    "Festivals & Public Art": 25,
    "Immersive Performance & Theatre": 15,
}
MAX_PER_AGENCY = _int("MAX_PER_AGENCY", 12)  # чтобы teamLab не занял полтоп

# Веса 100-балльной шкалы (сумма = 100).
SCORE_WEIGHTS = {
    "interactivity": 25,     # реакция на зрителя, генеративность
    "tech_integration": 25,  # сколько технологических маркеров задействовано
    "scale": 15,             # 360°, купола, фасады, площадь
    "media_citations": 20,   # независимые источники, премии
    "video_evidence": 15,    # качество и количество подтверждённых видео
}

# --- LLM --------------------------------------------------------------------
LLM_PROVIDER = _env("LLM_PROVIDER", "ollama")       # ollama | openai | none
OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OPENAI_BASE_URL = _env("OPENAI_BASE_URL", "https://api.openai.com/v1")  # любой OpenAI-совместимый
OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")
LLM_MAX_INPUT_CHARS = _int("LLM_MAX_INPUT_CHARS", 12000)

# --- Поиск видео ------------------------------------------------------------
YOUTUBE_API_KEY = _env("YOUTUBE_API_KEY")          # YouTube Data API v3
VIMEO_TOKEN = _env("VIMEO_TOKEN")                  # https://developer.vimeo.com
# Порядок бэкендов; без ключа бэкенд пропускается. duckduckgo работает без ключа.
SEARCH_BACKENDS = _env("SEARCH_BACKENDS", "youtube,vimeo,duckduckgo").split(",")
RESULTS_PER_QUERY = _int("RESULTS_PER_QUERY", 8)
MAX_QUERIES_PER_CASE = _int("MAX_QUERIES_PER_CASE", 14)
MAX_VIDEOS_PER_CASE = _int("MAX_VIDEOS_PER_CASE", 5)
VIDEO_RELEVANCE_THRESHOLD = _float("VIDEO_RELEVANCE_THRESHOLD", 0.5)
GEO_DATE_TAIL_DAYS = 7  # окно Start_Date — End_Date + 7 дней

# --- Сеть -------------------------------------------------------------------
USER_AGENT = _env("USER_AGENT", "ImmersiveCasesPipeline/1.0 (student research project)")
HTTP_TIMEOUT = _int("HTTP_TIMEOUT", 25)
MAX_CONCURRENCY = _int("MAX_CONCURRENCY", 4)
PER_HOST_DELAY = _float("PER_HOST_DELAY", 1.0)    # пауза между запросами к одному хосту
CRAWL_MAX_PAGES_PER_SEED = _int("CRAWL_MAX_PAGES_PER_SEED", 40)
USE_CRAWL4AI = _env("USE_CRAWL4AI", "auto")       # auto | yes | no
