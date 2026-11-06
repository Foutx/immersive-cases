"""Этап 4. Экспорт: топ-100 → чистый cases.json по строгой схеме + JSON Schema."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import ValidationError

import config
from stages.common import load_json, log, save_json
from stages.models import FINAL_LIST, FinalCase, ScoredCase


def to_final(case: ScoredCase) -> FinalCase:
    videos = [v.url for v in sorted(case.verified_videos, key=lambda v: -v.relevance)]
    data = case.model_dump(include=set(FinalCase.model_fields) - {"video_urls"})
    return FinalCase(**data, video_urls=videos[:config.MAX_VIDEOS_PER_CASE])


def run_stage4(*, in_path=config.TOP_CASES, out_path=config.FINAL_CASES,
               schema_path=config.FINAL_SCHEMA, strict=False, publish_to: Path | None = None):
    final = []
    for row in load_json(in_path, []):
        try:
            final.append(to_final(ScoredCase.model_validate(row)))
        except ValidationError as exc:
            log("VALIDATION ERROR", f"{row.get('title')}: {exc.errors()[0]['msg']}")
    ids = [c.id for c in final]
    if len(ids) != len(set(ids)):
        raise ValueError("в экспорте повторяются id")
    if len(final) != config.FINAL_COUNT:
        message = f"в экспорте {len(final)} кейсов вместо {config.FINAL_COUNT}"
        if strict or publish_to:
            raise ValueError(message)
        log("WARN", message)

    save_json(out_path, [c.model_dump(mode="json") for c in final])
    save_json(schema_path, FINAL_LIST.json_schema())
    # Контроль: файл читается как UTF-8 и проходит схему заново.
    reread = json.loads(Path(out_path).read_bytes().decode("utf-8", errors="strict"))
    FINAL_LIST.validate_python(reread)
    log("DONE", f"Этап 4: {len(final)} кейсов → {out_path} (схема: {schema_path})")
    if publish_to:
        shutil.copyfile(out_path, publish_to)
        log("DONE", f"Скопировано в {publish_to}")
    return final
