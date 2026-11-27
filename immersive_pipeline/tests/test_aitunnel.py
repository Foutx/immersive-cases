import asyncio
import json

import pytest

from stages import llm
from stages.stage1_discovery import build_candidate, merge


SOURCE = 'https://example.org/exhibit'
QUOTE = 'As visitors walk, projected waves follow their footsteps.'
CASE = {
    "title": "Test Waves", "brand_or_client": "Test Studio", "year": 2024,
    "country_city": "Japan, Tokyo", "category": "Museums & Cultural Exhibitions",
    "immersive_format": "Проекции реагируют на шаги",
    "summary": "Зрители проходят через зал с волнами. Проекции следуют за их шагами.",
    "source_url": "https://example.org/invented",
    "immersion_evidence": [
        {"field": "immersion_mechanism", "value": "Волны окружают зрителя во время движения", "quote": QUOTE},
        {"field": "system_response", "value": "reacts", "quote": QUOTE},
        {"field": "visitor_role", "value": "co_creator", "quote": "The visitor becomes a co-creator."},
        {"field": "system_response", "value": "maybe", "quote": QUOTE},
        {"field": "environment", "value": "Похожая, но не точная цитата", "quote": QUOTE.lower()},
    ],
}


def api_payload(value, finish='stop'):
    return json.dumps({"choices": [{"finish_reason": finish, "message": {"content": json.dumps(value)}}],
                       "usage": {"prompt_tokens": 500, "completion_tokens": 250}})


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(llm.config, "AITUNNEL_API_KEY", "unit-test-key")
    monkeypatch.setattr(llm.config, "AITUNNEL_MODEL", "gpt-4.1-nano")
    monkeypatch.setattr(llm.config, "AITUNNEL_MAX_CALLS", 1)
    return llm.make_llm("aitunnel")


def test_paid_parser_one_request_and_evidence_to_sqlite(provider, monkeypatch, tmp_path):
    from contracts.events import from_pipeline
    from services.pipeline_import import import_pipeline_file
    from services.catalogue import list_events, parse_filters, detail
    from database.connection import connect

    calls = []
    async def request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        return 200, api_payload({"cases": [CASE]})
    monkeypatch.setattr(llm, "http_request", request)
    data = asyncio.run(provider.extract_cases(QUOTE.replace(" waves ", "   waves\n"), SOURCE))
    assert len(calls) == 1
    method, url, options = calls[0]
    assert (method, url) == ("POST", "https://api.aitunnel.ru/v1/chat/completions")
    assert options['headers']['Authorization'] == 'Bearer unit-test-key'
    assert options['retries'] == 0 and not options['follow_redirects']
    assert options['json_body']['model'] == 'gpt-4.1-nano'
    fmt = options['json_body']['response_format']
    assert fmt['type'] == 'json_schema' and fmt['json_schema']['strict'] is True
    schema = fmt['json_schema']['schema']['properties']['cases']['items']
    assert 'immersion_evidence' in schema['required'] and 'source_url' not in schema['required']
    assert 'кириллица' in options['json_body']['messages'][1]['content']
    assert (provider.tokens_in, provider.tokens_out) == (500, 250)
    assert data[0]['source_url'] == SOURCE
    assert [c['field'] for c in data[0]['immersion_evidence']] == ['immersion_mechanism', 'system_response']
    candidate = build_candidate(data[0], page_url=SOURCE, seed={})
    assert len(merge(candidate, candidate).immersion_evidence) == 2
    event = from_pipeline(candidate)
    assert event.occurrence == 'unknown'
    assert event.claims[0].evidence[0].quote == QUOTE
    raw = tmp_path / 'raw.json'
    raw.write_text(json.dumps([candidate.model_dump(mode='json')]), encoding='utf-8')
    db = tmp_path / 'preview.sqlite3'
    import_pipeline_file(raw, db)
    f = parse_filters({'has_mechanism':'true'})
    with connect(db) as conn:
        assert list_events(conn, f)['total'] == 0
        row = list_events(conn, f, True)['items'][0]
        assert row['has_mechanism'] == 1
        d = detail(conn, row['id'], True)
        assert d['moderation_status'] == 'draft'
        assert any(c['evidence'][0]['quote'] == QUOTE for c in d['claims'])
        assert list_events(conn, parse_filters({'has_mechanism':'false'}), True)['total'] == 0
    with pytest.raises(llm.LLMError, match='AITUNNEL_MAX_CALLS'):
        asyncio.run(provider.extract_cases(QUOTE, SOURCE))
    assert len(calls) == 1


@pytest.mark.parametrize('status,body', [
    (401, 'unit-test-key'),
    (402, 'balance'),
    (429, 'rate limit'),
    (0, 'timeout'),
    (200, '{'),
    (200, api_payload({'cases': []}, finish='length')),
    (200, api_payload({'wrong': []})),
])
def test_errors_not_treated_as_empty_and_not_retried(provider, monkeypatch, status, body):
    calls = []
    async def request(*args, **kwargs):
        calls.append(kwargs)
        return status, body
    monkeypatch.setattr(llm, "http_request", request)
    with pytest.raises(llm.LLMError) as exc:
        asyncio.run(provider.extract_cases(QUOTE, SOURCE))
    assert len(calls) == 1
    assert 'unit-test-key' not in str(exc.value)


def test_empty_is_valid(provider, monkeypatch):
    async def request(*args, **kwargs):
        return 200, api_payload({'cases': []})
    monkeypatch.setattr(llm, 'http_request', request)
    assert asyncio.run(provider.extract_cases('An index page', SOURCE)) == []


def test_missing_key_is_an_error(monkeypatch):
    monkeypatch.setattr(llm.config, "AITUNNEL_API_KEY", None)
    with pytest.raises(llm.LLMError, match='AITUNNEL_API_KEY'):
        llm.make_llm("aitunnel")


def test_direct_page_once_and_resume_does_not_use_paid_model_again(provider, monkeypatch, tmp_path):
    from stages.stage1_discovery import Page, run_stage1

    attempts = []
    async def request(*args, **kwargs):
        attempts.append(kwargs)
        return 200, api_payload({"cases": [CASE]})
    monkeypatch.setattr(llm, "http_request", request)

    class Fetcher:
        calls = 0
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def fetch(self, url):
            self.calls += 1
            assert url == SOURCE
            return Page(url, QUOTE)

    fetcher = Fetcher()
    kwargs = dict(seeds=[{"name": "Test", "url": SOURCE}], llm=provider, fetcher=fetcher,
                  out_path=tmp_path / "raw.json", state_path=tmp_path / "state.json",
                  manual_path=tmp_path / "manual.json", existing_paths=[])
    assert len(asyncio.run(run_stage1(**kwargs))) == 1
    assert len(asyncio.run(run_stage1(**kwargs))) == 1
    assert fetcher.calls == len(attempts) == 1
