"""Prepare the independent, localhost-only editorial showcase (no API key required)."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from wsgiref.simple_server import make_server

from api.app import create_app
from contracts.events import ImportBatch
from database.connection import connect
from services.import_events import import_batch, utc

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / 'editorial' / 'collection.json'
TAG_LABELS = {
    'motion_response': 'Реакция на движение', 'generative_installation': 'Генеративная среда',
    'sensory_journey': 'Сенсорный маршрут', 'free_roam_xr': 'Свободное перемещение в VR',
    'surround_projection': 'Проекции в архитектуре',
}

def load_editorial():
    batch = ImportBatch.model_validate_json(COLLECTION.read_text(encoding='utf-8'))
    if batch.producer != 'editorial_v1' or not batch.events:
        raise ValueError('Unexpected showcase collection')
    for event in batch.events:
        evidence = {c.field for c in event.claims}
        if not {'immersion_mechanism', 'occurred'}.issubset(evidence):
            raise ValueError(f'Editorial evidence missing: {event.title}')
        if event.score_method != 'editorial_immersion_v1' or event.score not in (25,50,75,100):
            raise ValueError(f'Editorial score missing: {event.title}')
    return batch

def load_preview(path):
    # A fresh DB only. Never write to the user's existing catalogue.
    if path.exists():
        raise FileExistsError('Local showcase requires a fresh SQLite file')
    batch = load_editorial()
    result = import_batch(batch, path)
    if result['added'] != len(batch.events):
        raise ValueError('Incomplete showcase import')
    with connect(path) as db:
        for slug, label in TAG_LABELS.items():
            db.execute("UPDATE tags SET label=? WHERE kind='format' AND slug=?", (label,slug))
        db.execute("""UPDATE events SET moderation_status='published',reviewed_by=?,reviewed_at=?
            WHERE id IN (SELECT event_id FROM event_sources WHERE producer=?)""",
            ('editorial-showcase', utc(batch.collected_at), batch.producer))
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=5002)
    args = parser.parse_args()
    with TemporaryDirectory(prefix='immersive-showcase-') as tmp:
        path = Path(tmp) / 'showcase.sqlite3'
        outcome = load_preview(path)
        with make_server('127.0.0.1',args.port,create_app(path)) as server:
            print(f'Immersive Cases — {outcome["added"]} cases — http://127.0.0.1:{args.port}/',flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass

if __name__ == '__main__':
    main()
