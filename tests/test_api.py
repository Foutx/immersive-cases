import json
import sys
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.app import create_app
from database.migrate import migrate
from database.connection import connect

class ApiTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'db.sqlite3';migrate(self.path)
  with connect(self.path) as db:
   for id,status in [('public','published'),('secret','draft')]:
    db.execute("INSERT INTO events(id,title,description,source_url,country_code,reported_year,moderation_status,reviewed_by,reviewed_at) VALUES(?,?,?,?,?,?,?,?,?)",(id,'Световая выставка','Комната проекций','https://example.org/'+id,'JP',2023,status,'tester','2026-11-26T00:00:00Z'))
   db.execute("INSERT INTO event_proofs(event_id,url,kind) VALUES('public','https://example.org/video','video')")
   db.execute("INSERT INTO tags(kind,slug) VALUES('technology','xr')")
   db.execute("INSERT INTO event_tags VALUES('public',1)")
 def request(self,path='/api/events',query='',method='GET',preview=False):
  env={};setup_testing_defaults(env);env.update(PATH_INFO=path,QUERY_STRING=query,REQUEST_METHOD=method)
  result={}
  def start(status,headers):result.update(status=int(status.split()[0]),headers=dict(headers))
  result['body']=b''.join(create_app(self.path,preview)(env,start)).decode()
  return result
 def test_website_assets_and_api_info(self):
  page=self.request('/')
  self.assertEqual(page['status'],200)
  self.assertIn('text/html',page['headers']['Content-Type'])
  self.assertNotIn('{{',page['body'])
  self.assertIn('/static/catalogue.js',page['body'])
  for asset in ('style.css','menu.js','catalogue.js'):
   self.assertEqual(self.request('/static/'+asset)['status'],200)
  self.assertEqual(self.request('/static/../contracts/events.py')['status'],404)
  self.assertEqual(json.loads(self.request('/api/info')['body'])['visibility'],'published_only')
 def test_visibility_and_pagination(self):
  result=json.loads(self.request(query='per_page=1')['body']);self.assertEqual(result['total'],1)
  self.assertEqual(result['items'][0]['id'],'public')
  self.assertEqual(json.loads(self.request(query='page=2')['body'])['items'],[])
  self.assertEqual(self.request('/api/events/secret')['status'],404)
  self.assertEqual(json.loads(self.request(preview=True)['body'])['total'],2)
 def test_search_filters(self):
  for q in ('q=выставка','country=JP&year=2023&tag=xr&has_video=true'):
   self.assertEqual(json.loads(self.request(query=q)['body'])['total'],1)
  self.assertEqual(json.loads(self.request(query='has_video=false')['body'])['total'],0)
 def test_invalid_input(self):
  for q in ('page=0','per_page=101','country=oops','has_video=yes','page=1&page=2','status=draft'):
   self.assertEqual(self.request(query=q)['status'],400)
 def test_fts_and_sql_injection_safe(self):
  for q in ('q=%22%20OR%201=1--','q=OR','q=%22','country=JP%27%20OR%201=1'):
   self.assertIn(self.request(query=q)['status'],(200,400))
  self.assertEqual(json.loads(self.request()['body'])['total'],1)
 def test_details_filters_and_status(self):
  card=json.loads(self.request('/api/events/public')['body'])
  self.assertEqual(card['proofs'][0]['kind'],'video');self.assertNotIn('reviewed_by',card)
  options=json.loads(self.request('/api/filters')['body']);self.assertEqual(options['countries'],['JP'])
  status=json.loads(self.request('/api/collection-status')['body']);self.assertIsNone(status['last_collection_at'])
 def test_export_visibility_and_csv_safety(self):
  with connect(self.path) as db:db.execute("UPDATE events SET title='=danger' WHERE id='public'")
  export=json.loads(self.request('/api/export')['body']);self.assertEqual(len(export),1)
  self.assertIn("'=danger",self.request('/api/export','format=csv')['body'])
  self.assertEqual(self.request('/api/export','page=1')['status'],400)
 def test_method_and_routes(self):
  self.assertEqual(self.request(method='POST')['status'],405)
  self.assertEqual(self.request('/missing')['status'],404)

if __name__=='__main__':unittest.main()
