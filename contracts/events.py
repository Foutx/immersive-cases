"""Versioned collector -> storage contract. Does not modify legacy pipeline models."""
from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, AnyHttpUrl, AwareDatetime, model_validator

Text = Annotated[str, Field(min_length=1, max_length=2000)]

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Evidence(Model):
    url: AnyHttpUrl
    quote: Text

class Claim(Model):
    field: Literal['environment', 'visitor_actions', 'system_response', 'visitor_role',
                   'immersion_mechanism', 'dates', 'location', 'occurred']
    value: Text
    evidence: list[Evidence] = Field(min_length=1)

class Proof(Model):
    url: AnyHttpUrl
    kind: Literal['official', 'article', 'video', 'photo', 'other']
    title: Text | None = None
    checked_at: AwareDatetime | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    error: Text | None = None
    relevance: Literal['unreviewed', 'automatic_match'] = 'unreviewed'

    @model_validator(mode='after')
    def check_result(self):
        if (self.http_status is not None or self.error is not None) and self.checked_at is None:
            raise ValueError('check result requires checked_at')
        return self

class Tag(Model):
    kind: Literal['format', 'technology']
    slug: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')

class EventImport(Model):
    # This key identifies a collector record, not the database UUID.
    source_record_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=2, max_length=300)
    description: Text
    source_url: AnyHttpUrl
    start_date: date | None = None
    end_date: date | None = None
    reported_year: int | None = Field(default=None, ge=1800, le=2200)
    country_code: str | None = Field(default=None, pattern=r'^[A-Z]{2}$')
    city: Text | None = None
    venue: Text | None = None
    location_text: Text | None = None
    organizers: list[Text] = Field(default_factory=list)
    studios: list[Text] = Field(default_factory=list)
    client_name: Text | None = None
    format_text: Text | None = None
    category: Text | None = None
    tags: list[Tag] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    proofs: list[Proof] = Field(min_length=1)
    occurrence: Literal['unknown', 'announced', 'ongoing', 'completed'] = 'unknown'
    score: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    score_method: Text | None = None

    @model_validator(mode='after')
    def consistency(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError('end_date precedes start_date')
        if (self.score is None) != (self.score_method is None):
            raise ValueError('score and score_method must be provided together')
        urls = {str(p.url) for p in self.proofs}
        if str(self.source_url) not in urls:
            raise ValueError('source_url must be included in proofs')
        if len(urls) != len(self.proofs):
            raise ValueError('proof URLs must be unique')
        for claim in self.claims:
            if any(str(e.url) not in urls for e in claim.evidence):
                raise ValueError('claim evidence must reference proofs')
            allowed = {'system_response': {'reacts', 'does_not_react'},
                       'visitor_role': {'observer', 'participant', 'co_creator'}}
            if claim.field in allowed and claim.value not in allowed[claim.field]:
                raise ValueError('invalid controlled claim value')
        if self.occurrence == 'completed' and not any(c.field == 'occurred' for c in self.claims):
            raise ValueError('completed requires evidence of occurrence')
        return self

class ImportBatch(Model):
    schema_version: Literal['1.0'] = '1.0'
    producer: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,63}$')
    collected_at: AwareDatetime
    events: list[EventImport] = Field(max_length=1000)

    @model_validator(mode='after')
    def check_events(self):
        ids = [e.source_record_id for e in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate source_record_id in batch')
        for event in self.events:
            if event.occurrence == 'completed' and event.end_date and event.end_date >= self.collected_at.date():
                raise ValueError('completed must end before collection date')
            if any(p.checked_at and p.checked_at > self.collected_at for p in event.proofs):
                raise ValueError('proof check cannot be newer than collection')
        return self


def from_pipeline(case) -> EventImport:
    """Adapt a validated RawCandidate/EnrichedCase/ScoredCase, without guessing facts."""
    anchors = case.anchors
    dates = anchors.event_date_range
    proofs = {case.source_url: Proof(url=case.source_url, kind='other')}
    for url in [*case.discovered_from, *getattr(case, 'supporting_urls', [])]:
        proofs.setdefault(url, Proof(url=url, kind='other'))
    for video in getattr(case, 'videos', []):
        proofs[video.url] = Proof(url=video.url, kind='video', title=video.title or None,
            relevance='automatic_match' if video.verified else 'unreviewed')
    by_claim = {}
    for item in getattr(case, 'immersion_evidence', []):
        proofs.setdefault(item.source_url, Proof(url=item.source_url, kind='other'))
        by_claim.setdefault((item.field, item.value), []).append(
            Evidence(url=item.source_url, quote=item.quote))
    claims = [Claim(field=f, value=v, evidence=items) for (f, v), items in by_claim.items()]
    score = getattr(case, 'score', None)
    return EventImport(source_record_id=case.id, title=case.title, description=case.summary,
        source_url=case.source_url, start_date=dates.start if dates else None,
        end_date=dates.end if dates else None, reported_year=case.year,
        location_text=case.country_city, venue=anchors.exact_venue,
        studios=anchors.production_agencies, client_name=case.brand_or_client,
        category=case.category, format_text=case.immersive_format,
        tags=[Tag(kind='technology', slug=t) for t in case.tech_markers],
        proofs=list(proofs.values()), claims=claims, score=score,
        score_method='legacy_rules_v1' if score is not None else None)
