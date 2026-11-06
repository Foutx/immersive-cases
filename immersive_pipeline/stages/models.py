"""Pydantic v2-схемы кейса на всех этапах.

CaseCore   — поля итогового cases.json (строгая схема из ТЗ).
RawCandidate  = CaseCore + служебные якоря DiscoveryAnchors (этап 1).
EnrichedCase  = RawCandidate + найденные видео (этап 2).
ScoredCase    = EnrichedCase + баллы (этап 3).
FinalCase     = CaseCore + video_urls, без отладочных полей (этап 4).
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Literal, Optional

from pydantic import (AnyHttpUrl, BaseModel, ConfigDict, Field, TypeAdapter,
                      field_validator, model_validator)

import config
from stages.common import norm_text

CATEGORIES = (
    "Museums & Cultural Exhibitions",
    "Brand Activations & Corporate Shows",
    "Festivals & Public Art",
    "Immersive Performance & Theatre",
)
Category = Literal[
    "Museums & Cultural Exhibitions",
    "Brand Activations & Corporate Shows",
    "Festivals & Public Art",
    "Immersive Performance & Theatre",
]
TechMarker = Literal["projection_mapping", "interactive_generative", "spatial_audio", "xr", "kinetic"]
TECH_MARKERS = ("projection_mapping", "interactive_generative", "spatial_audio", "xr", "kinetic")

# Ключевые слова для нормализации ответа LLM и для детекции маркеров по тексту.
_CATEGORY_HINTS = [
    ("Immersive Performance & Theatre", r"theat|театр|спектак|promenade|променад|vr.?theat|immersive show|иммерсивн\w* шоу|perform"),
    ("Brand Activations & Corporate Shows", r"brand|бренд|activation|активац|corporate|корпорат|launch|премьер|\bces\b|пмэф|stand|стенд|product|продукт|retail|pop.?up"),
    ("Festivals & Public Art", r"festiv|фестив|public art|urban|городск|outdoor|facade|фасад|light show|световое шоу|biennale|биеннале"),
    ("Museums & Cultural Exhibitions", r"museum|музе|galler|галере|exhibit|выставк|экспозиц|heritage|наследи|art center|арт.?центр"),
]
_TECH_HINTS = {
    "projection_mapping": r"projection|mapping|проекц|мэппинг|маппинг|\b360\b|360°|dome|купол|panoram|панорам",
    "interactive_generative": r"interactiv|интерактив|sensor|датчик|сенсор|generativ|генератив|real.?time|реальном времени|motion.?track|gesture|жест|touch|lidar|kinect|reacts?|реагиру",
    "spatial_audio": r"spatial (audio|sound)|пространственн\w* звук|ambisonic|multichannel|многоканальн|binaural|бинаурал|atmos|l-isa|3d sound|soundscape|звуков\w* ландшафт|аудиоспектакл|audio walk",
    "xr": r"\b(vr|ar|mr|xr)\b|virtual reality|augmented|mixed reality|виртуальн\w* реальн|дополненн\w* реальн|смешанн\w* реальн|headset|vision pro|oculus|quest",
    "kinetic": r"kinetic|кинетич|motori[sz]ed|моториз|robot|робот|mechani[sc]|механич",
}


def detect_tech_markers(text: str) -> list[str]:
    low = (text or "").lower()
    return [marker for marker, pattern in _TECH_HINTS.items() if re.search(pattern, low)]


def normalize_category(value) -> str:
    raw = str(value or "").strip()
    for category in CATEGORIES:
        if raw.casefold() == category.casefold():
            return category
    low = raw.lower()
    for category, pattern in _CATEGORY_HINTS:
        if re.search(pattern, low):
            return category
    raise ValueError(f"неизвестная категория: {raw!r}")


def parse_year(value) -> Optional[int]:
    if isinstance(value, int):
        return value
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def make_case_id(brand: str, title: str, year) -> str:
    """Детерминированный id: хэш (brand + title + year)."""
    base = f"{norm_text(brand)}|{norm_text(title)}|{parse_year(year)}"
    return "case_" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


_URL = TypeAdapter(AnyHttpUrl)


def check_url(value: str) -> str:
    _URL.validate_python(value)
    return str(value).strip()


def _str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[;,\n]", value)
    seen = {}
    for item in value:
        item = str(item or "").strip()
        if item and item.casefold() not in seen:
            seen[item.casefold()] = item
    return list(seen.values())


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: Optional[date] = None
    end: Optional[date] = None

    @model_validator(mode="before")
    @classmethod
    def _parse(cls, data):
        if isinstance(data, str):
            found = re.findall(r"\d{4}-\d{2}-\d{2}", data)
            data = {"start": found[0] if found else None, "end": found[1] if len(found) > 1 else None}
        elif isinstance(data, (list, tuple)):
            data = {"start": data[0] if data else None, "end": data[1] if len(data) > 1 else None}
        if isinstance(data, dict):
            # LLM часто пишет "2023" или "октябрь 2023" — такие даты отбрасываем.
            for key in ("start", "end"):
                if data.get(key) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data[key])):
                    data[key] = None
        return data

    @model_validator(mode="after")
    def _order(self):
        if self.start and self.end and self.end < self.start:
            self.start, self.end = self.end, self.start
        return self


class DiscoveryAnchors(BaseModel):
    """Служебные якоря для поиска видео на этапе 2."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    production_agencies: list[str] = Field(default_factory=list)
    visual_triggers: list[str] = Field(default_factory=list)
    exact_venue: Optional[str] = None
    event_date_range: Optional[DateRange] = None
    official_hashtags: list[str] = Field(default_factory=list)
    local_language: Optional[str] = None  # ISO-код языка страны ивента (en, zh, ja, ko, fr, es, ru)

    @field_validator("production_agencies", "visual_triggers", mode="before")
    @classmethod
    def _lists(cls, value):
        return _str_list(value)

    @field_validator("official_hashtags", mode="before")
    @classmethod
    def _tags(cls, value):
        return ["#" + t.lstrip("#").replace(" ", "") for t in _str_list(value)]

    @field_validator("local_language", mode="before")
    @classmethod
    def _lang(cls, value):
        value = str(value or "").strip().lower()[:2]
        return value or None


class CaseCore(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^case_[0-9a-f]{12}$")
    title: str = Field(min_length=2, max_length=200)
    brand_or_client: str = Field(min_length=1, max_length=150)
    year: int = Field(ge=config.YEAR_MIN, le=config.YEAR_MAX)
    country_city: str = Field(min_length=2, max_length=120)
    category: Category
    immersive_format: str = Field(min_length=3, max_length=200)
    tech_markers: list[TechMarker] = Field(default_factory=list)
    summary: str = Field(min_length=40, max_length=1500)
    source_url: str

    @model_validator(mode="before")
    @classmethod
    def _prepare(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            data["year"] = parse_year(data.get("year"))
            missing = [key for key in ("title", "brand_or_client", "year") if not data.get(key)]
            if missing:
                raise ValueError("Не хватает исходных данных для карточки: " + ", ".join(missing))
            if data.get("title") and data.get("brand_or_client") and data["year"]:
                data["id"] = make_case_id(data["brand_or_client"], data["title"], data["year"])
        return data

    @field_validator("category", mode="before")
    @classmethod
    def _category(cls, value):
        return normalize_category(value)

    @field_validator("tech_markers", mode="before")
    @classmethod
    def _markers(cls, value):
        found = []
        for item in _str_list(value):
            key = item.lower().replace(" ", "_").replace("-", "_")
            for marker in ([key] if key in TECH_MARKERS else detect_tech_markers(item)):
                if marker not in found:
                    found.append(marker)
        return found

    @field_validator("source_url")
    @classmethod
    def _url(cls, value):
        return check_url(value)


class RawCandidate(CaseCore):
    anchors: DiscoveryAnchors = Field(default_factory=DiscoveryAnchors)
    awards: list[str] = Field(default_factory=list)
    discovered_from: list[str] = Field(default_factory=list)
    seed_kind: Literal["award", "studio", "media", "manual", "other"] = "other"


class VideoEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    platform: str
    title: str = ""
    channel: Optional[str] = None
    published_at: Optional[date] = None
    vector: Literal["A", "B", "C", "D"]
    query: str
    relevance: float = Field(ge=0, le=1)
    kind: Literal["agency", "official", "blogger", "unknown"] = "unknown"
    oembed_ok: Optional[bool] = None
    verified: bool = False


class EnrichedCase(RawCandidate):
    videos: list[VideoEvidence] = Field(default_factory=list)
    supporting_urls: list[str] = Field(default_factory=list)  # Behance и т.п. — не видео
    enriched_at: Optional[str] = None

    @property
    def verified_videos(self) -> list[VideoEvidence]:
        return [v for v in self.videos if v.verified]


class ScoredCase(EnrichedCase):
    score: float = 0
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class FinalCase(CaseCore):
    video_urls: list[str] = Field(min_length=1)

    @field_validator("video_urls")
    @classmethod
    def _videos(cls, value):
        return list(dict.fromkeys(check_url(v) for v in value))


FINAL_LIST = TypeAdapter(list[FinalCase])
