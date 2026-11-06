"""Офлайн-тесты: сеть, LLM и поиск подменены заглушками."""
import asyncio
import json
from datetime import date

import pytest
from pydantic import ValidationError

import config
from stages import stage2_enrichment as s2
from stages.models import CATEGORIES, FinalCase, RawCandidate, make_case_id
from stages.stage1_discovery import Page, run_stage1
from stages.stage2_enrichment import SearchResult, canonical_video_url, run_stage2, parse_ddg
from stages.stage3_scoring import run_stage3, select_balanced, score_case
from stages.stage4_exporter import run_stage4

config.PER_HOST_DELAY = 0

ROW = dict(title="Infinite Garden", brand_or_client="Bloom Museum", year="2023",
           country_city="South Korea, Seoul", category="museum exhibition",
           immersive_format="360° projection room with interactive floor",
           tech_markers=["Projection mapping", "interactive"],
           summary="Visitors walk through a 360-degree room where generative flowers react to their steps in real time. Spatial audio follows them.",
           source_url="https://example.org/infinite-garden",
           production_agencies=["Studio Lumen"], visual_triggers=["glowing flowers", "mirrors"],
           exact_venue="Coex Hall B", event_start="2023-10-10", event_end="2023-10-25",
           official_hashtags=["infinitegarden"], local_language="ko")


def test_model_normalizes_and_ids_are_deterministic():
    case = RawCandidate(**{k: ROW[k] for k in ("title", "brand_or_client", "year", "country_city", "category",
                                              "immersive_format", "tech_markers", "summary", "source_url")})
    assert case.year == 2023 and case.category == "Museums & Cultural Exhibitions"
    assert case.tech_markers == ["projection_mapping", "interactive_generative"]
    assert case.id == make_case_id(" bloom museum ", "INFINITE garden!", 2023)


def test_year_gate_in_schema():
    with pytest.raises(ValidationError):
        RawCandidate(**{**{k: ROW[k] for k in ("title", "brand_or_client", "country_city", "category",
                                                "immersive_format", "summary", "source_url")}, "year": 2015})


class FakeLLM:
    enabled = True

    def __init__(self, pages):
        self.pages = pages

    async def extract_cases(self, text, url):
        return self.pages.get(url, [])

    async def visual_queries(self, case):
        return [f"{t} {case.country_city.split(',')[-1].strip()}" for t in case.anchors.visual_triggers]


class FakeFetcher:
    def __init__(self, links):
        self.links = links

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def fetch(self, url):
        return Page(url, "text", self.links.get(url, []))


WORDS = ("Aurora Borealis Hall", "Neon Ocean", "Kinetic Rain Forest", "Mirror Labyrinth", "Desert Dreams",
         "Volcano Pulse", "Silent Cathedral", "Quantum Garden", "Glacier Echo", "Solar Theatre",
         "Midnight Carnival", "Paper Cosmos", "Liquid Gold", "Velvet Storm")


def make_rows(n):
    rows = []
    for i in range(n):
        cat = CATEGORIES[i % 4]
        rows.append({**ROW, "title": f"Project {WORDS[i]}", "brand_or_client": f"{WORDS[-1 - i]} Group",
                     "category": cat, "source_url": f"https://example.org/p{i}"})
    return rows


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.calls = 0

    async def search(self, query, *, published_after=None, published_before=None, limit=8):
        self.calls += 1
        if "Project" not in query and "Infinite" not in query:
            return []
        title = query.split('"')[3] if query.count('"') >= 4 else query
        vid = (str(abs(hash(title)))[:11]).ljust(11, "x")
        return [SearchResult(f"https://youtu.be/{vid}", f"{title} | Studio Lumen case study",
                             "immersive installation", "Studio Lumen", date(2023, 11, 1)),
                SearchResult("https://www.youtube.com/watch?v=AAAAAAAAAAA", "Cooking pasta tutorial", "", "Chef", date(2023, 1, 1)),
                SearchResult("https://example.com/not-video", title, "")]


class FakeVerifier(s2.VideoVerifier):
    def __init__(self):
        super().__init__(check_oembed=False)


def test_full_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FINAL_COUNT", 8)
    quotas = {CATEGORIES[0]: 2, CATEGORIES[1]: 2, CATEGORIES[2]: 2, CATEGORIES[3]: 2}
    monkeypatch.setattr(config, "CATEGORY_QUOTAS", quotas)
    rows = make_rows(12)
    dup = {**rows[0], "title": rows[0]["title"] + "!", "production_agencies": ["Other Studio"]}
    existing = tmp_path / "existing.json"
    existing.write_text(json.dumps([{"title": rows[1]["title"], "brand_or_client": rows[1]["brand_or_client"]}]))
    seed_url = "https://studio.example/work"
    pages = {seed_url: [], f"{seed_url}/1": rows[:6] + [dup], f"{seed_url}/2": rows[6:]}
    seeds = [{"name": "Studio Lumen", "kind": "studio", "url": seed_url, "follow_pattern": "/work/\\d"}]
    fetcher = FakeFetcher({seed_url: [f"{seed_url}/1", f"{seed_url}/2", "https://other.host/work/3"]})
    raw = tmp_path / "raw.json"
    kw = dict(seeds=seeds, llm=FakeLLM(pages), out_path=raw, state_path=tmp_path / "s1.json",
              manual_path=tmp_path / "none.json", existing_paths=[existing], fetcher=fetcher)
    pool = asyncio.run(run_stage1(**kw))
    assert len(pool) == 11  # 12 − 1 уже существующий; dup слит
    merged = next(c for c in pool if c.brand_or_client == rows[0]["brand_or_client"])
    assert {"Studio Lumen", "Other Studio"} <= set(merged.anchors.production_agencies)
    assert len(asyncio.run(run_stage1(**kw))) == 11  # идемпотентность

    enriched_path = tmp_path / "enriched.json"
    backend = FakeBackend()
    out = asyncio.run(run_stage2(llm=FakeLLM({}), backends=[backend], verifier=FakeVerifier(),
                                 in_path=raw, out_path=enriched_path))
    assert all(c.verified_videos for c in out)
    assert all(v.vector in "ABCD" for c in out for v in c.videos)
    assert not any("watch?v=AAAAAAAAAAA" in v.url and v.verified for c in out for v in c.videos)
    calls = backend.calls
    asyncio.run(run_stage2(llm=FakeLLM({}), backends=[backend], verifier=FakeVerifier(),
                           in_path=raw, out_path=enriched_path))
    assert backend.calls == calls  # повторный запуск ничего не ищет

    data = json.loads(enriched_path.read_text())
    data[0]["videos"] = []  # без видео → гейт
    enriched_path.write_text(json.dumps(data))
    top = run_stage3(in_path=enriched_path, scored_path=tmp_path / "scored.json",
                     top_path=tmp_path / "top.json", total=8)
    assert len(top) == 8 and data[0]["id"] not in {c.id for c in top}

    final_path = tmp_path / "cases.json"
    final = run_stage4(in_path=tmp_path / "top.json", out_path=final_path, schema_path=tmp_path / "schema.json")
    exported = json.loads(final_path.read_text(encoding="utf-8"))
    assert len(exported) == 8 and set(exported[0]) == set(FinalCase.model_fields)
    assert "anchors" not in exported[0] and exported[0]["video_urls"]


def test_select_balanced_fills_shortfall():
    cases = []
    for i, row in enumerate(make_rows(8)):
        row = {**row, "category": CATEGORIES[0] if i < 6 else CATEGORIES[1]}
        c = RawCandidate(**{k: row[k] for k in ("title", "brand_or_client", "year", "country_city", "category",
                                                "immersive_format", "summary", "source_url")})
        ev = s2.EnrichedCase(**c.model_dump(), videos=[s2.VideoEvidence(
            url=f"https://vimeo.com/12345{i}0", platform="vimeo", vector="A", query="q",
            relevance=0.9, verified=True)])
        cases.append(score_case(ev))
    top = select_balanced(cases, total=5, quotas={CATEGORIES[0]: 2, CATEGORIES[1]: 2, CATEGORIES[2]: 1},
                          max_per_agency=99)
    assert len(top) == 5


def test_canonical_urls_and_ddg():
    assert canonical_video_url("https://youtu.be/dQw4w9WgXcQ?t=3")[0] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert canonical_video_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")[1] == "youtube"
    assert canonical_video_url("https://vimeo.com/channels/staffpicks/123456789")[0] == "https://vimeo.com/123456789"
    assert canonical_video_url("https://example.com/x") == (None, None)
    html = ('<div class="result results_links"><a rel="nofollow" class="result__a" '
            'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fvimeo.com%2F123456789&rut=x">Show <b>reel</b></a>'
            '<a class="result__snippet" href="#">Case study</a></div>')
    [r] = parse_ddg(html)
    assert r.url == "https://vimeo.com/123456789" and r.title == "Show reel"
