import json
from pathlib import Path
import tempfile
import unittest
from database.connection import connect
from services.catalogue import detail,list_events,parse_filters
from services.import_events import import_batch
from services.review import decide
from services.showcase import load_editorial,load_preview
from services.export_showcase import export_to

class TestEditorial(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=self.root/'test.sqlite3'

    def test_showcase_has_seven_real_sources_and_no_overwrite(self):
        batch=load_editorial()
        self.assertEqual(len({c.country_code for c in batch.events}),7)
        self.assertEqual(load_preview(self.db)['added'],7)
        with self.assertRaises(FileExistsError): load_preview(self.db)
        with connect(self.db) as db:
            listing=list_events(db,parse_filters({'tag':'motion_response'}))
            self.assertEqual({r['title'] for r in listing['items']},{'Rain Room','teamLab Planets TOKYO'})
            card=detail(db,listing['items'][0]['id'])
            self.assertTrue(any(c['field']=='immersion_mechanism' and c['evidence'] for c in card['claims']))

    def test_import_and_review_are_separate(self):
        batch=load_editorial()
        import_batch(batch,self.db)
        with connect(self.db) as db:
            self.assertEqual(list_events(db,parse_filters({}))['total'],0)
            eid=list_events(db,parse_filters({}),True)['items'][0]['id']
        decide(self.db,eid,'published','test editor','Checked dates and mechanism',3)
        with connect(self.db) as db:
            self.assertEqual(list_events(db,parse_filters({}))['total'],1)
            self.assertEqual(detail(db,eid)['score'],75)
            self.assertEqual(db.execute('SELECT count(*) FROM event_reviews').fetchone()[0],1)
        decide(self.db,eid,'rejected','test editor','Correction')
        with connect(self.db) as db:
            self.assertEqual(list_events(db,parse_filters({}))['total'],0)
            self.assertEqual(db.execute('SELECT count(*) FROM event_reviews').fetchone()[0],2)

    def test_review_gate_rejects_lacking_evidence(self):
        batch=load_editorial().model_dump(mode='json')
        batch['events']=batch['events'][:1]
        batch['events'][0]['claims']=[c for c in batch['events'][0]['claims'] if c['field']!='occurred']
        import_batch(batch,self.db)
        with connect(self.db) as db:
            eid=list_events(db,parse_filters({}),True)['items'][0]['id']
        with self.assertRaisesRegex(ValueError,'цитаты'):
            decide(self.db,eid,'published','reviewer','missing facts')

    def test_portable_snapshot(self):
        target=self.root/'offline.html'
        export_to(target)
        page=target.read_text(encoding='utf-8')
        self.assertNotIn('src="/static',page)
        self.assertIn('Автономная копия',page)
        text=page.split('id="editorial-snapshot">',1)[1].split('</script>',1)[0]
        self.assertEqual(len(json.loads(text)['rows']),7)
