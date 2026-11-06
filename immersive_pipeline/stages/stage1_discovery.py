"""Этап 1. Entity Discovery: обход каталогов премий и портфолио студий,
извлечение кейсов через LLM, валидация Pydantic и дедупликация.

Выход: data/raw_candidates.json (целевой пул 250–300 кандидатов).
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urljoin, urldefrag, urlsplit

from pydantic import ValidationError

import config
from stages.common import host_of, http_request, load_json, log, save_json, similarity
from stages.models import RawCandidate, detect_tech_markers
from stages.llm import LLMError


# --- Загрузка страниц ---------------------------------------------------------
@dataclass
class Page:
    url: str
    text: str
    links: list[str] = field(default_factory=list)
    ok: bool = True


class PageFetcher:
    """Crawl4AI (если установлен) с фолбэком на urllib + BeautifulSoup."""

    def __init__(self, use_crawl4ai: str = config.USE_CRAWL4AI):
        self._crawler = None
        self._want = use_crawl4ai

    async def __aenter__(self):
        if self._want != "no":
            try:
                from crawl4ai import AsyncWebCrawler

                self._crawler = AsyncWebCrawler()
                await self._crawler.__aenter__()
                log("INFO", "Парсинг через Crawl4AI")
            except ImportError:
                if self._want == "yes":
                    raise
                log("WARN", "Crawl4AI не установлен — использую urllib + BeautifulSoup")
        return self

    async def __aexit__(self, *exc):
        if self._crawler:
            await self._crawler.__aexit__(*exc)

    async def fetch(self, url: str) -> Page:
        if self._crawler:
            result = await self._crawler.arun(url=url)
            if not result.success:
                return Page(url, "", ok=False)
            markdown = getattr(result.markdown, "raw_markdown", None) or str(result.markdown or "")
            links = [l.get("href") for group in (result.links or {}).values() for l in group if l.get("href")]
            return Page(result.url or url, markdown, [urljoin(url, l) for l in links])
        status, html = await http_request("GET", url)
        if status != 200:
            return Page(url, "", ok=False)
        return Page(url, *html_to_text(html, url))


def html_to_text(html: str, base: str) -> tuple[str, list[str]]:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        links = [urljoin(base, a["href"]) for a in soup.find_all("a", href=True)]
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text("\n")
    except ImportError:
        links = [urljoin(base, unescape(h)) for h in re.findall(r'href=["\']([^"\']+)', html)]
        text = unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", html)))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(l for l in lines if l), links


# --- Дедупликация ---------------------------------------------------------------
class Deduplicator:
    """Точное совпадение id + нечёткое SequenceMatcher > FUZZY_THRESHOLD."""

    def __init__(self, threshold: float = config.FUZZY_THRESHOLD):
        self.threshold = threshold
        self._known: list[dict] = []

    def remember(self, *, id=None, title="", brand="", year=None, label=""):
        self._known.append(dict(id=id, title=title, brand=brand or "", year=year, label=label or title))

    def find(self, case: RawCandidate):
        full = f"{case.brand_or_client} {case.title}"
        for known in self._known:
            if known["id"] and known["id"] == case.id:
                return known
            if known["year"] and abs(int(known["year"]) - case.year) > 1:
                continue
            if similarity(full, f"{known['brand']} {known['title']}") > self.threshold:
                return known
            if similarity(case.title, known["title"]) > self.threshold and _brands_compatible(
                    case.brand_or_client, known["brand"]):
                return known
        return None


def _brands_compatible(a: str, b: str) -> bool:
    if not a or not b:
        return True
    a, b = a.casefold(), b.casefold()
    return a in b or b in a or similarity(a, b) > 0.6


def load_existing(paths) -> list[dict]:
    """Кейсы, которые уже есть в базе (в любой из схем: ТЗ или culture.ru)."""
    rows = []
    for path in paths:
        data = load_json(path, [])
        for row in data if isinstance(data, list) else []:
            if isinstance(row, dict) and row.get("title"):
                rows.append(row)
    return rows


def merge(current: RawCandidate, new: RawCandidate) -> RawCandidate:
    a, b = current.anchors, new.anchors
    anchors = a.model_copy(update=dict(
        production_agencies=_union(a.production_agencies, b.production_agencies),
        visual_triggers=_union(a.visual_triggers, b.visual_triggers),
        official_hashtags=_union(a.official_hashtags, b.official_hashtags),
        exact_venue=a.exact_venue or b.exact_venue,
        event_date_range=a.event_date_range or b.event_date_range,
        local_language=a.local_language or b.local_language))
    return current.model_copy(update=dict(
        anchors=anchors, awards=_union(current.awards, new.awards),
        tech_markers=_union(current.tech_markers, new.tech_markers),
        discovered_from=_union(current.discovered_from, new.discovered_from),
        seed_kind="award" if "award" in (current.seed_kind, new.seed_kind) else current.seed_kind))


def _union(a, b):
    return list(dict.fromkeys([*a, *b]))


# --- Сборка кандидата из ответа LLM ------------------------------------------------
_CORE_FIELDS = ("title", "brand_or_client", "year", "country_city", "category",
                "immersive_format", "tech_markers", "summary", "source_url")
_ANCHOR_FIELDS = ("production_agencies", "visual_triggers", "exact_venue",
                  "official_hashtags", "local_language")


def build_candidate(row: dict, *, page_url: str, seed: dict) -> RawCandidate:
    data = {k: row.get(k) for k in _CORE_FIELDS if row.get(k) not in (None, "", [])}
    if seed.get("default_brand"):
        data.setdefault("brand_or_client", seed["default_brand"])
    missing = [key for key in ("title", "brand_or_client", "year", "country_city", "category",
                              "immersive_format", "summary") if not data.get(key)]
    if missing:
        raise ValueError("Не хватает данных: " + ", ".join(missing))
    data.setdefault("source_url", page_url)
    if not str(data["source_url"]).startswith("http"):
        data["source_url"] = urljoin(page_url, str(data["source_url"]))
    anchors = {k: row.get(k) for k in _ANCHOR_FIELDS if row.get(k) not in (None, "", [])}
    if isinstance(row.get("anchors"), dict):  # формат ручного импорта
        anchors.update({k: v for k, v in row["anchors"].items() if v not in (None, "", [])})
    if row.get("event_start") or row.get("event_end"):
        anchors["event_date_range"] = {"start": row.get("event_start"), "end": row.get("event_end")}
    if seed.get("kind") == "studio" and seed.get("name"):
        anchors["production_agencies"] = [seed["name"], *anchors.get("production_agencies", [])]
    awards = list(row.get("awards") or [])
    if seed.get("kind") == "award" and seed.get("name"):
        awards.append(seed["name"])
    # Маркеры, которые LLM не отметила, но которые прямо названы в тексте.
    text = f"{data.get('immersive_format', '')} {data.get('summary', '')}"
    data["tech_markers"] = [*(data.get("tech_markers") or []), *detect_tech_markers(text)]
    return RawCandidate(**data, anchors=anchors, awards=awards,
                        discovered_from=list(dict.fromkeys([page_url, data["source_url"]])),
                        seed_kind=seed.get("kind", "other"))


def _error_text(exc: ValidationError) -> str:
    err = exc.errors()[0]
    return f"{'.'.join(str(p) for p in err['loc']) or 'case'}: {err['msg']}"


# --- Этап целиком --------------------------------------------------------------
class Discovery:
    def __init__(self, *, out_path, state_path, existing_rows, target_max):
        self.out_path, self.state_path, self.target_max = out_path, state_path, target_max
        self.dedup = Deduplicator()
        for row in existing_rows:
            self.dedup.remember(title=row["title"], brand=row.get("brand_or_client", ""),
                                year=row.get("year"), label=f"существующий: {row['title']}")
        self.pool: list[RawCandidate] = []
        for row in load_json(out_path, []):
            try:
                case = RawCandidate.model_validate(row)
            except ValidationError as exc:
                log("VALIDATION ERROR", f"{row.get('title')}: {_error_text(exc)} (из прошлого запуска)")
                continue
            self.pool.append(case)
            self.dedup.remember(id=case.id, title=case.title, brand=case.brand_or_client,
                                year=case.year, label=case.id)
        self.state = load_json(state_path, {"pages": [], "links": {}})
        if self.state.get("validation_version") != 2:
            self.state["pages"] = []  # Revisit old pages; preserve candidates and deduplicate.
            self.state["validation_version"] = 2
        self.done_pages = set(self.state["pages"])
        self.lock = asyncio.Lock()

    @property
    def full(self):
        return len(self.pool) >= self.target_max

    def add(self, row: dict, *, page_url: str, seed: dict) -> bool:
        try:
            case = build_candidate(row, page_url=page_url, seed=seed)
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            reason = _error_text(exc) if isinstance(exc, ValidationError) else str(exc)
            log("VALIDATION ERROR", f"{row.get('title') or '?'} — {reason}")
            return False
        match = self.dedup.find(case)
        if match:
            position = next((i for i, c in enumerate(self.pool) if c.id == match["id"]), None)
            if position is not None:
                self.pool[position] = merge(self.pool[position], case)
            log("SKIP - DUPLICATE", f"{case.title} ≈ {match['label']}")
            return False
        if self.full:
            return False
        self.pool.append(case)
        self.dedup.remember(id=case.id, title=case.title, brand=case.brand_or_client,
                            year=case.year, label=case.id)
        log("ADDED", f"{case.id} {case.title} ({case.brand_or_client}, {case.year}) — {case.category}")
        return True

    def save(self):
        save_json(self.out_path, [c.model_dump(mode="json") for c in self.pool])
        self.state["pages"] = sorted(self.done_pages)
        save_json(self.state_path, self.state)


def seed_links(page: Page, seed: dict, limit: int) -> list[str]:
    pattern = re.compile(seed["follow_pattern"]) if seed.get("follow_pattern") else None
    if not pattern:
        return []
    host = host_of(seed["url"])
    found = []
    for link in page.links:
        link = urldefrag(link)[0]
        if host_of(link) == host and pattern.search(urlsplit(link).path) and link not in found and link != seed["url"]:
            found.append(link)
    return found[:limit]


async def run_stage1(*, seeds, llm, out_path=config.RAW_CANDIDATES,
                     state_path=config.STATE_DIR / "stage1.json",
                     manual_path=config.MANUAL_CANDIDATES, existing_paths=config.EXISTING_CASES,
                     target_max=config.TARGET_POOL_MAX, max_pages=config.CRAWL_MAX_PAGES_PER_SEED,
                     fetcher=None, only_seed=None) -> list[RawCandidate]:
    job = Discovery(out_path=out_path, state_path=state_path,
                    existing_rows=load_existing(existing_paths), target_max=target_max)
    log("INFO", f"Этап 1: в пуле уже {len(job.pool)} кандидатов")

    manual = load_json(manual_path, [])
    for row in manual:
        job.add(row, page_url=row.get("source_url") or "manual://", seed={"kind": "manual"})
    job.save()

    if not llm.enabled:
        log("WARN", "LLM не настроена (LLM_PROVIDER=none) — seed-страницы не разбираются, "
                    "в пул попали только ручные кандидаты")
        return job.pool

    async def process(page_url: str, seed: dict, fetch):
        if page_url in job.done_pages or job.full:
            return
        page = await fetch(page_url)
        if not page.ok:
            log("WARN", f"не загрузилась {page_url}")
            return
        context = (f"Source brand: {seed['default_brand']}\n" if seed.get("default_brand") else "")
        rows = await llm.extract_cases(context + page.text, page.url)
        async with job.lock:
            valid_page = True
            for row in rows:
                try:
                    build_candidate(row, page_url=page.url, seed=seed)
                except (ValidationError, ValueError, KeyError, TypeError) as exc:
                    valid_page = False
                    save_json(job.state_path.parent / "last_invalid_candidate.json",
                              {"page_url": page.url, "candidate": row,
                               "error": _error_text(exc) if isinstance(exc, ValidationError) else str(exc)})
                job.add(row, page_url=page.url, seed=seed)
            if valid_page:
                job.done_pages.add(page_url)
            else:
                log("WARN", f"Невалидные карточки; страница остаётся для повтора: {page_url}")
            job.save()

    fetcher = fetcher or PageFetcher()
    async with fetcher:
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY)

        async def guarded(url, seed):
            async with semaphore:
                try:
                    await process(url, seed, fetcher.fetch)
                except LLMError:
                    raise
                except Exception as exc:  # одна битая страница не должна ронять этап
                    log("ERROR", f"{url}: {type(exc).__name__}: {exc}")

        for seed in seeds:
            if only_seed and only_seed.casefold() not in seed.get("name", "").casefold():
                continue
            if job.full:
                break
            log("INFO", f"Seed: {seed.get('name')} — {seed['url']}")
            links = job.state["links"].get(seed["url"])
            if links is None:
                listing = await fetcher.fetch(seed["url"])
                if not listing.ok:
                    log("WARN", f"Каталог недоступен, повторим позже: {seed['url']}")
                    continue
                links = seed_links(listing, seed, max_pages)
                job.state["links"][seed["url"]] = links
            # A catalog supplies links; extracting all its previews produces oversized answers.
            links = seed_links(Page(seed["url"], "", links), seed, max_pages)
            pages = links if links else [seed["url"]]
            if getattr(llm, "name", "") == "gigachat":
                for u in pages:
                    await guarded(u, seed)
            else:
                await asyncio.gather(*(guarded(u, seed) for u in pages))
    job.save()
    total = len(job.pool)
    status = "DONE" if total >= config.TARGET_POOL_MIN else "WARN"
    log(status, f"Этап 1: {total} кандидатов (цель {config.TARGET_POOL_MIN}–{target_max}) → {out_path}")
    return job.pool
