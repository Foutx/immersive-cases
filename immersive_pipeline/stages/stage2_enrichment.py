"""Этап 2. Smart Video Enrichment: четырёхвекторный поиск видео по якорям.

A  B2B Showreel Lookup      — "[студия]" "[проект]" case study / showreel / "[студия] showreel [год]"
B  Visual Anchor Querying   — 5–7 «обывательских» запросов от LLM на языке страны ивента
C  Geo-Date Triangulation   — "[площадка] [ивент] recap" в окне Start_Date … End_Date + 7 дней
D  Blogger / Walkthroughs   — "[город] immersive exhibition POV walkthrough", "выставка … обзор"

Каждый найденный ролик проходит верификацию: платформа видео, oEmbed (ролик публичный),
релевантность якорям, дата публикации не раньше года проекта − 1.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import ValidationError

import config
from stages.common import (coverage, get_json, host_of, http_request, load_json, log,
                           save_json, similarity, tokens)
from stages.models import EnrichedCase, RawCandidate, VideoEvidence


# --- Платформы ------------------------------------------------------------------
VIDEO_HOSTS = {
    "youtube.com": "youtube", "m.youtube.com": "youtube", "youtu.be": "youtube",
    "vimeo.com": "vimeo", "player.vimeo.com": "vimeo",
    "tiktok.com": "tiktok", "bilibili.com": "bilibili", "rutube.ru": "rutube",
    "vk.com": "vk", "vkvideo.ru": "vk", "instagram.com": "instagram", "dailymotion.com": "dailymotion",
}
SUPPORT_HOSTS = {"behance.net": "behance"}


def canonical_video_url(url: str) -> tuple[str | None, str | None]:
    """Возвращает (каноническая ссылка, платформа) или (None, None), если это не видео."""
    host = host_of(url)
    platform = VIDEO_HOSTS.get(host)
    parts = urlsplit(url)
    if platform == "youtube":
        if host == "youtu.be":
            vid = parts.path.strip("/").split("/")[0]
        elif parts.path.startswith(("/shorts/", "/embed/", "/live/")):
            vid = parts.path.split("/")[2]
        else:
            vid = (parse_qs(parts.query).get("v") or [""])[0]
        return (f"https://www.youtube.com/watch?v={vid}", platform) if re.fullmatch(r"[\w-]{11}", vid) else (None, None)
    if platform == "vimeo":
        match = re.search(r"/(?:video/)?(\d{6,})", parts.path)
        return (f"https://vimeo.com/{match.group(1)}", platform) if match else (None, None)
    if platform == "tiktok":
        return (url.split("?")[0], platform) if "/video/" in parts.path else (None, None)
    if platform == "vk":
        return (url, platform) if re.search(r"video-?\d+_\d+", url) else (None, None)
    if platform == "instagram":
        return (url.split("?")[0], platform) if re.match(r"/(reel|p|tv)/", parts.path) else (None, None)
    if platform == "bilibili":
        return (url.split("?")[0], platform) if "/video/" in parts.path else (None, None)
    if platform:
        return url.split("#")[0], platform
    return None, None


# --- Поисковые бэкенды -------------------------------------------------------------
@dataclass
class SearchResult:
    url: str
    title: str
    description: str = ""
    channel: str | None = None
    published_at: date | None = None
    backend: str = ""


class SearchError(RuntimeError):
    """Поиск не выполнился (сеть, квота, 5xx) — это не то же самое, что «ничего не найдено»."""


class SearchBackend:
    name = "base"

    async def search(self, query, *, published_after=None, published_before=None, limit=8):
        raise NotImplementedError


class YouTubeBackend(SearchBackend):
    name = "youtube"

    def __init__(self, key):
        self.key = key

    async def search(self, query, *, published_after=None, published_before=None, limit=8):
        params = {"part": "snippet", "type": "video", "maxResults": limit, "q": query, "key": self.key}
        if published_after:
            params["publishedAfter"] = f"{published_after.isoformat()}T00:00:00Z"
        if published_before:
            params["publishedBefore"] = f"{published_before.isoformat()}T23:59:59Z"
        status, data = await get_json("https://www.googleapis.com/youtube/v3/search", params=params)
        if status != 200 or data is None:
            raise SearchError(f"YouTube API {status}" + (" (квота или ключ)" if status == 403 else ""))
        out = []
        for item in data.get("items", []):
            vid, sn = item.get("id", {}).get("videoId"), item.get("snippet", {})
            if vid:
                out.append(SearchResult(f"https://www.youtube.com/watch?v={vid}", sn.get("title", ""),
                                        sn.get("description", ""), sn.get("channelTitle"),
                                        _date(sn.get("publishedAt")), self.name))
        return out


class VimeoBackend(SearchBackend):
    name = "vimeo"

    def __init__(self, token):
        self.token = token

    async def search(self, query, *, published_after=None, published_before=None, limit=8):
        status, data = await get_json(
            "https://api.vimeo.com/videos", headers={"Authorization": f"bearer {self.token}"},
            params={"query": query, "per_page": limit, "fields": "link,name,description,user.name,created_time"})
        if status != 200 or data is None:
            raise SearchError(f"Vimeo API {status}")
        return [SearchResult(v["link"], v.get("name") or "", v.get("description") or "",
                             (v.get("user") or {}).get("name"), _date(v.get("created_time")), self.name)
                for v in data.get("data", []) if v.get("link")]


class DuckDuckGoBackend(SearchBackend):
    """Без ключей: HTML-выдача DuckDuckGo, фильтр по видеохостингам. Хрупко, но бесплатно."""
    name = "duckduckgo"

    async def search(self, query, *, published_after=None, published_before=None, limit=8):
        status, html = await http_request("GET", "https://html.duckduckgo.com/html/", params={"q": query})
        if status != 200:
            raise SearchError(f"DuckDuckGo {status}")
        return parse_ddg(html)[:limit * 2]


def parse_ddg(html: str) -> list[SearchResult]:
    out = []
    blocks = re.split(r'<div[^>]+class="[^"]*result[ _]', html)
    for block in blocks:
        link = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S) or \
            re.search(r'href="([^"]+)"[^>]*class="result__a"[^>]*>(.*?)</a>', block, re.S)
        if not link:
            continue
        href = link.group(1).replace("&amp;", "&")
        if "uddg=" in href:
            href = unquote(parse_qs(urlsplit(href).query).get("uddg", [href])[0])
        snippet = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        clean = lambda s: re.sub(r"<[^>]+>", "", s or "").replace("&amp;", "&").replace("&#x27;", "'").strip()
        out.append(SearchResult(href, clean(link.group(2)), clean(snippet.group(1) if snippet else ""),
                                backend="duckduckgo"))
    return out


def _date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def make_backends(names=None) -> list[SearchBackend]:
    backends = []
    for name in names or config.SEARCH_BACKENDS:
        name = name.strip().lower()
        if name == "youtube" and config.YOUTUBE_API_KEY:
            backends.append(YouTubeBackend(config.YOUTUBE_API_KEY))
        elif name == "vimeo" and config.VIMEO_TOKEN:
            backends.append(VimeoBackend(config.VIMEO_TOKEN))
        elif name == "duckduckgo":
            backends.append(DuckDuckGoBackend())
    return backends


# --- Построение запросов по 4 векторам --------------------------------------------------
@dataclass
class Query:
    vector: str
    text: str
    after: date | None = None
    before: date | None = None


def city_of(case: RawCandidate) -> str:
    return case.country_city.split(",")[-1].strip()


async def build_queries(case: RawCandidate, llm) -> list[Query]:
    a, title, year, city = case.anchors, case.title, case.year, city_of(case)
    queries: list[Query] = []
    # A. B2B Reverse Lookup
    for agency in a.production_agencies[:3]:
        queries += [Query("A", f'"{agency}" "{title}" case study'),
                    Query("A", f"{agency} {title} showreel installation"),
                    Query("A", f"{agency} showreel {year}")]
    # B. Visual anchors (LLM → фолбэк на эвристику)
    visual = await llm.visual_queries(case) if llm and llm.enabled else []
    if not visual:
        visual = [f"{case.brand_or_client} {t} video" for t in a.visual_triggers[:3]]
        visual += [f"immersive {t} {city}" for t in a.visual_triggers[:2]]
    queries += [Query("B", q) for q in visual]
    # C. Geo + Date window
    rng = a.event_date_range
    after = rng.start if rng and rng.start else date(year, 1, 1)
    before = (rng.end if rng and rng.end else (rng.start if rng and rng.start else date(year, 12, 31)))
    before = before + timedelta(days=config.GEO_DATE_TAIL_DAYS)
    place = a.exact_venue or city
    queries.append(Query("C", f"{place} {title} {year} recap", after, before))
    if a.exact_venue:
        queries.append(Query("C", f"{a.exact_venue} {city} immersive {year}", after, before))
    # D. Блогеры / POV
    queries += [Query("D", f"{city} immersive exhibition {title} walkthrough"),
                Query("D", f"{title} POV full tour")]
    if (a.local_language == "ru") or re.search(r"росси|russia|москв|moscow|петербург", case.country_city, re.I):
        queries.append(Query("D", f"выставка {title} обзор экскурсия"))
    for tag in a.official_hashtags[:1]:
        queries.append(Query("D", f"{tag} {city}"))
    seen, unique = set(), []
    for q in queries:
        key = q.text.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    groups = [[q for q in unique if q.vector == v] for v in "ABCD"]
    balanced = []
    while any(groups):
        for group in groups:
            if group:
                balanced.append(group.pop(0))
    return balanced[:config.MAX_QUERIES_PER_CASE]


# --- Верификация ---------------------------------------------------------------
class VideoVerifier:
    OEMBED = {"youtube": "https://www.youtube.com/oembed", "vimeo": "https://vimeo.com/api/oembed.json"}

    def __init__(self, check_oembed: bool = True):
        self.check_oembed = check_oembed
        self._cache: dict[str, bool | None] = {}

    async def oembed(self, url: str, platform: str) -> bool | None:
        if not self.check_oembed or platform not in self.OEMBED:
            return None
        if self._cache.get(url) is None:
            status, _ = await get_json(self.OEMBED[platform], params={"url": url, "format": "json"}, retries=1)
            self._cache[url] = True if status == 200 else (False if status in (401, 403, 404) else None)
        return self._cache[url]

    async def evaluate(self, result: SearchResult, case: RawCandidate, query: Query) -> VideoEvidence | None:
        url, platform = canonical_video_url(result.url)
        if not url:
            return None
        relevance = relevance_score(result, case)
        if result.published_at and result.published_at.year < case.year - 1:
            return None  # ролик старше проекта — это про что-то другое
        if query.vector == "C" and result.published_at and query.before and result.published_at > query.before + timedelta(days=365):
            relevance *= 0.8  # далеко за окном дат: возможно, другой сезон
        oembed_ok = await self.oembed(url, platform) if relevance >= config.VIDEO_RELEVANCE_THRESHOLD else None
        if self.check_oembed and platform in self.OEMBED and oembed_ok is None and relevance >= config.VIDEO_RELEVANCE_THRESHOLD:
            raise SearchError("Проверка видео временно недоступна; повторим кейс")
        threshold = config.VIDEO_RELEVANCE_THRESHOLD
        return VideoEvidence(
            url=url, platform=platform, title=result.title[:300], channel=result.channel,
            published_at=result.published_at, vector=query.vector, query=query.text,
            relevance=round(min(relevance, 1.0), 3), kind=video_kind(result, case, query),
            oembed_ok=oembed_ok, verified=(oembed_ok is True or not self.check_oembed) and relevance >= threshold)


def relevance_score(result: SearchResult, case: RawCandidate) -> float:
    text = f"{result.title} {result.description} {result.channel or ''}"
    bag = tokens(text)
    a = case.anchors
    title_part = max(coverage(case.title, bag), similarity(case.title, result.title))
    context = max([coverage(x, bag) for x in [case.brand_or_client, *a.production_agencies,
                                               a.exact_venue or "", city_of(case)] if x] or [0])
    score = 0.6 * title_part + 0.4 * context
    low = text.lower()
    if any(tag.lower() in low for tag in a.official_hashtags):
        score += 0.15
    if any(coverage(t, bag) >= 0.99 for t in a.visual_triggers):
        score += 0.05
    if re.search(r"trailer|трейлер|reaction|реакция|tutorial|how to", low):
        score -= 0.1
    return max(0.0, min(score, 1.0))


def video_kind(result: SearchResult, case: RawCandidate, query: Query) -> str:
    channel = result.channel or ""
    if channel and any(similarity(channel, ag) > 0.7 or ag.casefold() in channel.casefold()
                       for ag in case.anchors.production_agencies):
        return "agency"
    if channel and (case.brand_or_client.casefold() in channel.casefold()
                    or similarity(channel, case.brand_or_client) > 0.7):
        return "official"
    if query.vector == "A" and re.search(r"showreel|case study|кейс", result.title, re.I):
        return "agency"
    if query.vector in ("B", "D"):
        return "blogger"
    return "unknown"


# --- Этап целиком -------------------------------------------------------------
async def enrich_case(case: RawCandidate, *, llm, backends, verifier) -> EnrichedCase:
    queries = await build_queries(case, llm)
    found: dict[str, VideoEvidence] = {}
    support: list[str] = []
    attempts = failures = 0
    for query in queries:
        for backend in backends:
            attempts += 1
            try:
                results = await backend.search(query.text, published_after=query.after,
                                               published_before=query.before, limit=config.RESULTS_PER_QUERY)
            except Exception as exc:
                failures += 1
                log("WARN", f"{backend.name}: {exc}")
                continue
            for result in results:
                if host_of(result.url) in SUPPORT_HOSTS and relevance_score(result, case) >= config.VIDEO_RELEVANCE_THRESHOLD:
                    support.append(result.url)
                    continue
                evidence = await verifier.evaluate(result, case, query)
                if evidence and (evidence.url not in found or evidence.relevance > found[evidence.url].relevance):
                    found[evidence.url] = evidence
        if sum(v.verified for v in found.values()) >= config.MAX_VIDEOS_PER_CASE:
            break  # хватит — бережём квоты API
    if failures:
        raise SearchError("часть поисковых запросов завершилась ошибкой — кейс останется в очереди")
    ranked = sorted(found.values(), key=lambda v: (not v.verified, -v.relevance))
    return EnrichedCase(**case.model_dump(), videos=ranked[:config.MAX_VIDEOS_PER_CASE * 2],
                        supporting_urls=list(dict.fromkeys(support)),
                        enriched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


async def run_stage2(*, llm, backends=None, verifier=None, in_path=config.RAW_CANDIDATES,
                     out_path=config.ENRICHED_CASES, force=False, limit=None) -> list[EnrichedCase]:
    backends = make_backends() if backends is None else backends
    if not backends:
        log("ERROR", "нет ни одного поискового бэкенда (задайте YOUTUBE_API_KEY / VIMEO_TOKEN "
                     "или оставьте duckduckgo в SEARCH_BACKENDS)")
        return []
    verifier = verifier or VideoVerifier()
    raws = []
    for row in load_json(in_path, []):
        try:
            raws.append(RawCandidate.model_validate(row))
        except ValidationError as exc:
            log("VALIDATION ERROR", f"{row.get('title')}: {exc.errors()[0]['msg']}")
    done: dict[str, EnrichedCase] = {}
    for row in load_json(out_path, []):
        try:
            case = EnrichedCase.model_validate(row)
            done[case.id] = case
        except ValidationError:
            pass
    todo = [c for c in raws if force or c.id not in done or not done[c.id].enriched_at]
    if limit:
        todo = todo[:limit]
    log("INFO", f"Этап 2: {len(raws)} кандидатов, уже обогащено {len(raws) - len(todo)}, "
                f"в работе {len(todo)}; бэкенды: {', '.join(b.name for b in backends)}")
    order = [c.id for c in raws]
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY)

    def snapshot():
        return [done[i].model_dump(mode="json") for i in order if i in done]

    async def worker(case):
        async with semaphore:
            try:
                enriched = await enrich_case(case, llm=llm, backends=backends, verifier=verifier)
            except Exception as exc:
                log("ERROR", f"{case.id}: {type(exc).__name__}: {exc}")
                return
        async with lock:
            done[case.id] = enriched
            save_json(out_path, snapshot())  # сохраняем после каждого кейса — перезапуск безопасен
        n = len(enriched.verified_videos)
        if n:
            vectors = "".join(sorted({v.vector for v in enriched.verified_videos}))
            log("ENRICHED", f"{case.id} {case.title}: {n} видео (векторы {vectors})")
        else:
            log("NO VIDEO", f"{case.id} {case.title}: подтверждённых видео нет")

    await asyncio.gather(*(worker(c) for c in todo))
    save_json(out_path, snapshot())
    with_video = sum(bool(c.verified_videos) for c in done.values())
    log("DONE", f"Этап 2: {with_video}/{len(done)} кейсов с подтверждённым видео → {out_path}")
    return [done[i] for i in order if i in done]
