import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.import_events import import_batch,save_event
from database.connection import connect

class ImportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.db=Path(self.tmp.name)/'db.sqlite3'
  self.data=json.loads((Path(__file__).resolve().parents[1]/'docs/event-import.example.json').read_text())
  self.event=self.data['events'][0]
 def run_import(self):return import_batch(self.data,self.db)
 def test_repeat(self):
  self.assertEqual(self.run_import()['added'],1)
  self.assertEqual(self.run_import()['unchanged'],1)
  with connect(self.db) as db:
   self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT count(*) FROM event_proofs').fetchone()[0],1)
 def test_add_relations(self):
  self.run_import();self.event['city']='Tokyo'
  self.event['tags']=[dict(kind='technology',slug='xr')]
  self.event['studios']=['Example studio']
  self.event['claims']=[dict(field='environment',value='VR',evidence=[dict(url=self.event['source_url'],quote='VR experience')])]
  self.assertEqual(self.run_import()['updated'],1)
  self.assertEqual(self.run_import()['unchanged'],1)
  with connect(self.db) as db:
   for table in ('event_tags','event_parties','event_claims','claim_evidence'):
    self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],1)
 def test_manual_values_preserved_and_conflicts_saved(self):
  self.run_import()
  with connect(self.db) as db:db.execute("UPDATE events SET title='Manual title',city='Paris'")
  self.event['title']='LLM title';self.event['city']=None
  self.assertEqual(self.run_import()['conflicts'],1)
  with connect(self.db) as db:
   row=db.execute('SELECT title,city FROM events').fetchone()
   self.assertEqual(tuple(row),('Manual title','Paris'))
   self.assertIn('title',db.execute('SELECT conflicts_json FROM import_records ORDER BY rowid DESC').fetchone()[0])
 def test_different_producers_not_merged(self):
  self.run_import();self.data['producer']='second_source'
  self.assertEqual(self.run_import()['added'],1)
 def test_stale_does_not_change_event(self):
  self.run_import();self.data['collected_at']='2025-01-01T00:00:00Z';self.event['city']='Tokyo'
  self.assertEqual(self.run_import()['stale'],1)
  with connect(self.db) as db:self.assertIsNone(db.execute('SELECT city FROM events').fetchone()[0])
 def test_proof_checks_use_latest_timestamp(self):
  proof=self.event['proofs'][0];proof.update(checked_at='2026-11-25T10:00:00Z',http_status=200)
  self.run_import();proof.update(checked_at='2026-11-26T09:00:00Z',http_status=404)
  self.assertEqual(self.run_import()['updated'],1)
  proof.update(checked_at='2026-11-24T10:00:00Z',http_status=200)
  self.run_import()
  with connect(self.db) as db:self.assertEqual(db.execute('SELECT http_status FROM event_proofs').fetchone()[0],404)
 def test_batch_atomic_and_failure_logged(self):
  self.data['events'].append(dict(self.event,source_record_id='second'))
  def fail_second(db,event,producer,collected):
   if event.source_record_id=='second':raise RuntimeError('test failure')
   return save_event(db,event,producer,collected)
  with patch('services.import_events.save_event',side_effect=fail_second):
   with self.assertRaises(RuntimeError):self.run_import()
  with connect(self.db) as db:
   self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT status FROM import_runs').fetchone()[0],'failed')
 def test_invalid_batch_no_database_mutation(self):
  self.event['moderation_status']='published'
  with self.assertRaises(ValueError):self.run_import()
  self.assertFalse(self.db.exists())

if __name__=='__main__':unittest.main()
