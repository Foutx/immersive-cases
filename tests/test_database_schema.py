import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database.connection import connect
from database.migrate import migrate, MIGRATIONS

class SchemaTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name)/'db.sqlite3'
  migrate(self.path)
 def event(self,db,id='a'):
  db.execute('INSERT INTO events(id,title,description,source_url) VALUES(?,?,?,?)',
   (id,'Световая инсталляция','Посетители проходят через световые проекции','https://example.org/'+id))
 def test_repeat_preserves_data(self):
  with connect(self.path) as db:self.event(db)
  self.assertEqual(migrate(self.path),[])
  with connect(self.path) as db:
   self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)
 def test_default_draft_and_invalid_status(self):
  with connect(self.path) as db:
   self.event(db)
   self.assertEqual(db.execute('SELECT moderation_status FROM events').fetchone()[0],'draft')
   with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE events SET moderation_status='published'")
   with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE events SET score=101")
 def test_identity_and_proof_uniqueness(self):
  with connect(self.path) as db:
   self.event(db)
   db.execute("INSERT INTO event_sources VALUES('collector','external-1','a','2026-11-26T00:00:00Z')")
   with self.assertRaises(sqlite3.IntegrityError):db.execute("INSERT INTO event_sources VALUES('collector','external-1','a','2026-11-26T00:00:00Z')")
   db.execute("INSERT INTO event_proofs(event_id,url,kind) VALUES('a','https://example.org/a','official')")
   with self.assertRaises(sqlite3.IntegrityError):db.execute("INSERT INTO event_proofs(event_id,url,kind) VALUES('a','https://example.org/a','video')")
 def test_cross_event_evidence_rejected_and_cascade(self):
  with connect(self.path) as db:
   self.event(db,'a');self.event(db,'b')
   proof=db.execute("INSERT INTO event_proofs(event_id,url,kind) VALUES('a','https://example.org/a','official')").lastrowid
   claim=db.execute("INSERT INTO event_claims(event_id,field,value) VALUES('b','environment','light')").lastrowid
   with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT INTO claim_evidence VALUES(?,?,?,?)',('b',claim,proof,'quote'))
   db.execute("DELETE FROM events WHERE id='a'")
   self.assertEqual(db.execute('SELECT count(*) FROM event_proofs').fetchone()[0],0)
 def test_search_tracks_updates_deletes(self):
  with connect(self.path) as db:
   self.event(db)
   self.assertEqual(db.execute("SELECT count(*) FROM events_fts WHERE events_fts MATCH 'инсталляция'").fetchone()[0],1)
   db.execute("UPDATE events SET title='Театр' WHERE id='a'")
   self.assertEqual(db.execute("SELECT count(*) FROM events_fts WHERE events_fts MATCH 'инсталляция'").fetchone()[0],0)
   self.assertEqual(db.execute("SELECT count(*) FROM events_fts WHERE events_fts MATCH 'театр'").fetchone()[0],1)
   db.execute("DELETE FROM events WHERE id='a'")
   self.assertEqual(db.execute("SELECT count(*) FROM events_fts WHERE events_fts MATCH 'театр'").fetchone()[0],0)
 def test_failed_migration_rolls_back(self):
  folder=Path(self.temp.name)/'migrations';shutil.copytree(MIGRATIONS,folder)
  (folder/'999_bad.sql').write_text('CREATE TABLE test_rollback (id INTEGER);\nINVALID SQL;\n')
  with self.assertRaises(sqlite3.Error):migrate(self.path,folder)
  with connect(self.path) as db:
   self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='test_rollback'").fetchone())
   self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],len(list(MIGRATIONS.glob('*.sql'))))
 def test_changed_migration_rejected(self):
  folder=Path(self.temp.name)/'migrations';shutil.copytree(MIGRATIONS,folder)
  with (folder/'001_initial.sql').open('a') as f:f.write('\n-- changed\n')
  with self.assertRaises(ValueError):migrate(self.path,folder)

if __name__=='__main__':unittest.main()
