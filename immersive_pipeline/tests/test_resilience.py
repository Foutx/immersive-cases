import asyncio
import json
import time

import pytest

from stages import llm
from stages.stage4_exporter import run_stage4


@pytest.fixture(autouse=True)
def isolate_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(llm.config, "STATE_DIR", tmp_path / "state")


def test_double_encoded_json():
    assert llm.parse_json_loose(json.dumps('{"cases": []}')) == {"cases": []}


def test_default_model_and_bounded_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "secret-test")
    monkeypatch.delenv("GIGACHAT_MODEL", raising=False)
    monkeypatch.delenv("GIGACHAT_STRUCTURED", raising=False)
    calls = []
    async def request(method, url, **kwargs):
        if url.endswith("oauth"):
            return 200, json.dumps({"access_token": "secret-token", "expires_at": time.time() + 1800})
        calls.append(kwargs["json_body"])
        return 200, json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "Not JSON"}}]})
    monkeypatch.setattr(llm, "http_request", request)
    with pytest.raises(llm.LLMError):
        asyncio.run(llm.GigaChatLLM().extract_cases("page", "https://example.org"))
    assert len(calls) == 2
    assert calls[0]["model"] == "GigaChat-2-Max"
    assert "response_format" not in calls[0]
    diagnostic = (llm.config.STATE_DIR / "gigachat_last_response.json").read_text()
    assert "secret-test" not in diagnostic and "secret-token" not in diagnostic


def test_llm_failure_is_not_empty_discovery():
    class Broken(llm.BaseLLM):
        enabled = True

    with pytest.raises(llm.LLMError):
        asyncio.run(Broken().extract_cases("page text", "https://example.org"))


def test_incomplete_publish_preserves_destination(tmp_path):
    destination = tmp_path / "published.json"
    destination.write_text("original")
    with pytest.raises(ValueError):
        run_stage4(in_path=tmp_path / "missing.json", out_path=tmp_path / "out.json",
                   schema_path=tmp_path / "schema.json", publish_to=destination)
    assert destination.read_text() == "original"


def test_gigachat_refresh_and_cache(monkeypatch):
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test-key")
    calls = []

    async def request(method, url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("oauth"):
            return 200, json.dumps({"access_token": "token", "expires_at": (time.time() + 1800) * 1000})
        if sum(u.endswith("chat/completions") for u, _ in calls) == 1:
            return 401, ""
        return 200, json.dumps({"choices": [{"message": {"content": '{"cases": []}'}}]})

    monkeypatch.setattr(llm, "http_request", request)

    async def run():
        client = llm.GigaChatLLM()
        assert await client.complete_json("system", "user") == {"cases": []}
        assert await client.complete_json("system", "user") == {"cases": []}

    asyncio.run(run())
    assert sum(u.endswith("oauth") for u, _ in calls) == 2
    assert calls[0][1]["json_body"] == b"scope=GIGACHAT_API_PERS"


def test_all_query_vectors_survive_limit():
    from test_pipeline import ROW
    from stages.stage1_discovery import build_candidate
    from stages.stage2_enrichment import build_queries
    case = build_candidate({**ROW, "production_agencies": ["One", "Two", "Three"]},
                           page_url="https://example.org", seed={"kind": "manual"})

    class Visual:
        enabled = True
        async def visual_queries(self, case):
            return [f"visual query {i}" for i in range(7)]

    queries = asyncio.run(build_queries(case, Visual()))
    assert {q.vector for q in queries} == set("ABCD")


def test_video_network_failure_requires_retry(monkeypatch):
    from test_pipeline import ROW
    from stages.stage1_discovery import build_candidate
    from stages.stage2_enrichment import VideoVerifier, SearchResult, Query, SearchError
    case = build_candidate(ROW, page_url="https://example.org", seed={"kind": "manual"})
    verifier = VideoVerifier()

    async def unavailable(*args):
        return None

    monkeypatch.setattr(verifier, "oembed", unavailable)
    result = SearchResult("https://youtu.be/abcdefghijk", case.title + " " + case.brand_or_client)
    with pytest.raises(SearchError):
        asyncio.run(verifier.evaluate(result, case, Query("A", "query")))


def test_gigachat_extraction_requests_schema_and_retries(monkeypatch):
    monkeypatch.setenv("GIGACHAT_STRUCTURED", "1")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test")
    requests = []

    async def request(method, url, **kwargs):
        if url.endswith("oauth"):
            return 200, json.dumps({"access_token": "test", "expires_at": time.time() + 1800})
        requests.append(kwargs["json_body"])
        content = "not json" if len(requests) == 1 else '{"cases": []}'
        return 200, json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}]})

    monkeypatch.setattr(llm, "http_request", request)
    assert asyncio.run(llm.GigaChatLLM().extract_cases("test page", "https://example.org")) == []
    assert len(requests) == 2
    schema = requests[0]["response_format"]["schema"]
    item = schema["properties"]["cases"]["items"]
    assert "id" not in item["required"]
    assert item["properties"]["summary"]["minLength"] == 40


def test_invalid_page_remains_retryable(tmp_path):
    from test_pipeline import FakeLLM, FakeFetcher, ROW
    from stages.stage1_discovery import run_stage1
    url = "https://example.org/work"
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"pages": [url], "links": {}}))
    asyncio.run(run_stage1(seeds=[{"url": url, "name": "test", "kind": "studio"}],
                          llm=FakeLLM({url: [{**ROW, "summary": "short"}]}),
                          fetcher=FakeFetcher({}), out_path=tmp_path / "raw.json", state_path=state,
                          manual_path=tmp_path / "none.json", existing_paths=[]))
    assert url not in json.loads(state.read_text())["pages"]


def test_length_retry_changes_request(monkeypatch):
    monkeypatch.setenv("GIGACHAT_STRUCTURED", "1")
    import copy
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test")
    requests = []
    async def request(method, url, **kwargs):
        if url.endswith("oauth"):
            return 200, json.dumps({"access_token": "test", "expires_at": time.time() + 1800})
        requests.append(copy.deepcopy(kwargs["json_body"]))
        reason = "length" if len(requests) == 1 else "stop"
        return 200, json.dumps({"choices": [{"finish_reason": reason, "message": {"content": '{"cases": []}'}}]})
    monkeypatch.setattr(llm, "http_request", request)
    assert asyncio.run(llm.GigaChatLLM().extract_cases("project", "https://example.org")) == []
    assert len(requests) == 2
    assert "response_format" in requests[0] and "response_format" not in requests[1]
    assert requests[0]["messages"] != requests[1]["messages"]
    assert requests[0]["response_format"]["schema"]["properties"]["cases"]["maxItems"] == 1


def test_catalog_only_supplies_links(tmp_path):
    from test_pipeline import FakeFetcher
    from stages.stage1_discovery import run_stage1
    catalog = "https://example.org/work"
    project = catalog + "/project"
    visited = []
    class Extractor:
        enabled = True
        async def extract_cases(self, text, url):
            visited.append(url)
            return []
    asyncio.run(run_stage1(seeds=[{"url": catalog, "name": "test", "follow_pattern": "/work/"}],
                          llm=Extractor(), fetcher=FakeFetcher({catalog: [project]}),
                          out_path=tmp_path / "raw.json", state_path=tmp_path / "state.json",
                          manual_path=tmp_path / "none.json", existing_paths=[]))
    assert visited == [project]


def test_missing_year_reports_source_field():
    from test_pipeline import ROW
    from stages.stage1_discovery import build_candidate
    with pytest.raises(ValueError, match="year"):
        build_candidate({**ROW, "year": None}, page_url="https://example.org", seed={"kind": "manual"})


def test_catalog_query_is_not_project_slug():
    from stages.stage1_discovery import Page, seed_links
    seed = {"url": "https://www.teamlab.art/w/", "follow_pattern": r"/(w|e)/[^/]+/?$"}
    project = "https://www.teamlab.art/w/cosmos/"
    page = Page(seed["url"], "", ["https://www.teamlab.art/e/?type=pickup", project])
    assert seed_links(page, seed, 3) == [project]


def test_explicit_source_brand_preserves_named_client():
    from test_pipeline import ROW
    from stages.stage1_discovery import build_candidate
    seed = {"kind": "studio", "name": "teamLab", "default_brand": "teamLab"}
    case = build_candidate({**ROW, "brand_or_client": None}, page_url="https://example.org", seed=seed)
    assert case.brand_or_client == "teamLab"
    case = build_candidate({**ROW, "brand_or_client": "Museum"}, page_url="https://example.org", seed=seed)
    assert case.brand_or_client == "Museum"
    with pytest.raises(ValueError, match="country_city"):
        build_candidate({**ROW, "brand_or_client": None, "country_city": None},
                        page_url="https://example.org", seed=seed)


def test_studio_is_not_automatically_client():
    from test_pipeline import ROW
    from stages.stage1_discovery import build_candidate
    with pytest.raises(ValueError, match="brand_or_client"):
        build_candidate({**ROW, "brand_or_client": None}, page_url="https://example.org",
                        seed={"kind": "studio", "name": "Production Studio"})
