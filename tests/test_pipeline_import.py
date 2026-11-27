import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'immersive_pipeline')]
from stages.models import RawCandidate,ScoredCase
from stages.stage4_exporter import run_stage4
from services.pipeline_import import import_pipeline_file
from database.connection import connect

class PipelineImportTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.folder=Path(self.temp.name);self.source=self.folder/'cards.json';self.db=self.folder/'db.sqlite3'
  self.raw=RawCandidate(title='Example installation',brand_or_client='Example studio',year=2023,
   country_city='Japan, Tokyo',category='Museums & Cultural Exhibitions',immersive_format='Projection room',
   summary='Visitors walk into a space with projections covering the walls around them.',source_url='https://example.org/project')
 def write(self,rows):self.source.write_text(json.dumps(rows),encoding='utf-8')
 def scored(self):
  return ScoredCase(**self.raw.model_dump(),score=50,videos=[dict(url='https://www.youtube.com/watch?v=abcdefghijk',platform='youtube',vector='A',query='example',relevance=1,verified=True)])
 def export(self,save_db):
  return run_stage4(in_path=self.source,out_path=self.folder/'final.json',schema_path=self.folder/'schema.json',save_db=save_db,db_path=self.db)
 def test_raw_without_video_and_repeat(self):
  self.write([self.raw.model_dump(mode='json')])
  self.assertEqual(import_pipeline_file(self.source,self.db)['added'],1)
  self.assertEqual(import_pipeline_file(self.source,self.db)['unchanged'],1)
 def test_stage4_json_and_db_preserve_anchors(self):
  case=self.scored();case.anchors.production_agencies=['Example studio'];self.write([case.model_dump(mode='json')])
  self.export(True)
  self.assertEqual(len(json.loads((self.folder/'final.json').read_text())),1)
  with connect(self.db) as db:
   self.assertEqual(db.execute('SELECT name FROM event_parties').fetchone()[0],'Example studio')
   self.assertEqual(db.execute('SELECT moderation_status FROM events').fetchone()[0],'draft')
 def test_json_only_does_not_touch_db(self):
  self.write([self.scored().model_dump(mode='json')]);self.export(False)
  self.assertFalse(self.db.exists())
 def test_bad_stage4_has_no_outputs(self):
  self.write([self.scored().model_dump(mode='json'),{'title':'Broken'}])
  with self.assertRaises(ValueError):self.export(True)
  self.assertFalse(self.db.exists());self.assertFalse((self.folder/'final.json').exists())
 def test_legacy_rejected(self):
  self.write([dict(title='Legacy',description='Old format')])
  with self.assertRaises(ValueError):import_pipeline_file(self.source,self.db)
 def test_missing_source(self):
  with self.assertRaises(ValueError):self.export(True)
  self.assertFalse(self.db.exists())
 def test_cli_from_other_directory(self):
  self.write([self.raw.model_dump(mode='json')])
  env=dict(os.environ,PYTHONIOENCODING='utf-8')
  result=subprocess.run([sys.executable,str(ROOT/'immersive_pipeline/main.py'),'import-db','--input',str(self.source),'--db-path',str(self.db)],cwd=self.folder,env=env,capture_output=True,text=True,encoding='utf-8')
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  self.assertIn('SQLite',result.stdout)

if __name__=='__main__':unittest.main()
