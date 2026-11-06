"""Этап 3. Scoring Engine: жёсткие гейты + 100-балльная оценка иммерсивности
и сбалансированный отбор топ-100 по категориям.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from pydantic import ValidationError

import config
from stages.common import host_of, load_json, log, save_json
from stages.models import EnrichedCase, ScoredCase

INTERACTIVE = r"interactiv|интерактив|sensor|датчик|сенсор|generativ|генератив|real.?time|реальн\w* времени|" \
              r"gesture|жест|touch|касан|voice|голос|motion|движени|participat|участ|react|реагир|" \
              r"tracking|трекинг|ai\b|нейросет|personali[sz]|персонал"
SCALE = r"\b360\b|360°|dome|купол|panoram|панорам|facade|фасад|stadium|стадион|city.?wide|" \
        r"\d[\d\s,.]*\s?(m2|m²|sq\.? ?m|square met|кв\.? ?м)|\d+\s?(projectors|проектор)|" \
        r"\d+\s?(rooms|zones|halls|залов|зон)|hectare|гектар|km|км\b|million visitors|млн посетител"
KIND_WEIGHT = {"agency": 1.0, "official": 0.9, "blogger": 0.7, "unknown": 0.5}


def gate(case: EnrichedCase) -> str | None:
    if not case.verified_videos:
        return "нет подтверждённого видео"
    if not config.YEAR_MIN <= case.year <= config.YEAR_MAX:
        return f"год {case.year} вне {config.YEAR_MIN}–{config.YEAR_MAX}"
    return None


def _hits(pattern: str, text: str) -> int:
    return len({m.group(0).lower() for m in re.finditer(pattern, text, re.I)})


def score_case(case: EnrichedCase) -> ScoredCase:
    text = f"{case.immersive_format} {case.summary} {' '.join(case.anchors.visual_triggers)}"
    markers = set(case.tech_markers)
    parts = {
        "interactivity": min(1.0, _hits(INTERACTIVE, text) / 3 + (0.34 if "interactive_generative" in markers else 0)),
        "tech_integration": min(1.0, len(markers) / 3),
        "scale": min(1.0, _hits(SCALE, text) / 2),
    }
    sources = {host_of(u) for u in [case.source_url, *case.discovered_from, *case.supporting_urls]
               if u.startswith("http")}
    channels = {(v.channel or v.url).casefold() for v in case.verified_videos}
    citations = len(sources) + len(case.awards) * 2 + max(0, len(channels) - 1)
    parts["media_citations"] = min(1.0, math.log2(1 + citations) / math.log2(1 + 8))
    videos = case.verified_videos
    best_kind = max(KIND_WEIGHT[v.kind] for v in videos) if videos else 0
    parts["video_evidence"] = 0.6 * best_kind + 0.4 * min(1.0, len(videos) / 3)
    breakdown = {k: round(config.SCORE_WEIGHTS[k] * v, 1) for k, v in parts.items()}
    return ScoredCase(**case.model_dump(), score=round(sum(breakdown.values()), 1),
                      score_breakdown=breakdown)


def main_agency(case: ScoredCase) -> str | None:
    agencies = case.anchors.production_agencies
    return agencies[0].casefold() if agencies else None


def select_balanced(cases: list[ScoredCase], *, total=config.FINAL_COUNT,
                    quotas=config.CATEGORY_QUOTAS, max_per_agency=config.MAX_PER_AGENCY) -> list[ScoredCase]:
    ranked = sorted(cases, key=lambda c: (-c.score, c.id))
    chosen, ids = [], set()
    per_cat, per_agency = Counter(), Counter()

    def take(case):
        chosen.append(case)
        ids.add(case.id)
        per_cat[case.category] += 1
        if main_agency(case):
            per_agency[main_agency(case)] += 1

    def agency_ok(case):
        return not main_agency(case) or per_agency[main_agency(case)] < max_per_agency

    for case in ranked:  # проход 1: квоты категорий
        if len(chosen) < total and per_cat[case.category] < quotas.get(case.category, 0) and agency_ok(case):
            take(case)
    for case in ranked:  # проход 2: добор лучших, если какая-то категория недобрала
        if len(chosen) < total and case.id not in ids and agency_ok(case):
            take(case)
    return sorted(chosen, key=lambda c: (-c.score, c.id))


def run_stage3(*, in_path=config.ENRICHED_CASES, scored_path=config.SCORED_CASES,
               top_path=config.TOP_CASES, total=config.FINAL_COUNT) -> list[ScoredCase]:
    scored = []
    for row in load_json(in_path, []):
        try:
            case = EnrichedCase.model_validate(row)
        except ValidationError as exc:
            log("VALIDATION ERROR", f"{row.get('title')}: {exc.errors()[0]['msg']}")
            continue
        reason = gate(case)
        if reason:
            log("GATE", f"{case.id} {case.title}: {reason}")
            continue
        scored.append(score_case(case))
    save_json(scored_path, [c.model_dump(mode="json") for c in sorted(scored, key=lambda c: -c.score)])
    top = select_balanced(scored, total=total)
    for rank, case in enumerate(top, 1):
        log("SELECTED", f"#{rank:>3} {case.score:5.1f}  {case.title} — {case.category}")
    save_json(top_path, [c.model_dump(mode="json") for c in top])
    mix = Counter(c.category for c in top)
    log("DONE" if len(top) == total else "WARN",
        f"Этап 3: прошли гейты {len(scored)}, отобрано {len(top)}/{total}: "
        + "; ".join(f"{k} — {v}" for k, v in mix.most_common()))
    return top
