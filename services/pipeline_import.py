"""Bridge existing pipeline cards to the versioned storage contract."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Legacy stages import config/stages as top-level modules.
sys.path.insert(0, str(ROOT / 'immersive_pipeline'))
from stages.models import RawCandidate, EnrichedCase, ScoredCase
from contracts.events import ImportBatch, from_pipeline
from services.import_events import import_batch


def prepare_batch(cases, collected_at=None):
    return ImportBatch(producer='immersive_pipeline',
                       collected_at=collected_at or datetime.now(timezone.utc),
                       events=[from_pipeline(case) for case in cases])


def import_pipeline_file(path, db_path=None):
    path = Path(path)
    rows = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(rows, list):
        raise ValueError('Expected an array of pipeline cards')
    cases = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f'Card {index + 1}: expected an object')
        if 'summary' not in row or 'video_urls' in row:
            raise ValueError(f'Card {index + 1}: use raw_candidates, enriched_cases, scored_cases or top_cases; not legacy/final JSON')
        model = ScoredCase if 'score' in row or 'score_breakdown' in row else EnrichedCase if 'videos' in row or 'enriched_at' in row else RawCandidate
        cases.append(model.model_validate(row))
    # File modification time is a conservative ordering marker for saved snapshots,
    # not proof of when the event or crawl happened. Override by API if needed.
    collected_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    batch = prepare_batch(cases, collected_at)
    return import_batch(batch, db_path)
