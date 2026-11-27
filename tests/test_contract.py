import copy
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'immersive_pipeline'))
from pydantic import ValidationError
from contracts.events import ImportBatch, from_pipeline
from stages.models import RawCandidate

class ContractTests(unittest.TestCase):
 def setUp(self):
  self.data=json.loads((ROOT/'docs/event-import.example.json').read_text(encoding='utf-8'))
  self.event=self.data['events'][0]
 def reject(self):
  with self.assertRaises(ValidationError): ImportBatch.model_validate(self.data)
 def test_example_and_schema(self):
  batch=ImportBatch.model_validate(self.data)
  self.assertEqual(ImportBatch.model_validate_json(batch.model_dump_json()),batch)
  self.assertEqual(json.loads((ROOT/'docs/event-import.schema.json').read_text()),ImportBatch.model_json_schema())
 def test_publication_not_collector_owned(self):
  self.event['moderation_status']='published';self.reject()
 def test_unknown_version(self):
  self.data['schema_version']='2.0';self.reject()
 def test_missing_evidence(self):
  self.event['occurrence']='completed';self.reject()
 def test_bad_dates(self):
  self.event.update(start_date='2025-12-01',end_date='2025-01-01');self.reject()
 def test_future_completion(self):
  self.event.update(occurrence='completed',end_date='2027-01-01',claims=[{'field':'occurred','value':'held','evidence':[{'url':self.event['source_url'],'quote':'held'}]}]);self.reject()
 def test_missing_proof_reference(self):
  self.event['claims']=[{'field':'environment','value':'projection','evidence':[{'url':'https://example.org/missing','quote':'projection'}]}];self.reject()
 def test_empty_quote(self):
  self.event['claims']=[{'field':'environment','value':'projection','evidence':[{'url':self.event['source_url'],'quote':'  '}]}];self.reject()
 def test_duplicate_record(self):
  self.data['events'].append(copy.deepcopy(self.event));self.reject()
 def test_check_requires_timestamp(self):
  self.event['proofs'][0]['http_status']=404;self.reject()
 def test_naive_timestamp(self):
  self.data['collected_at']='2026-11-26T10:00:00';self.reject()
 def test_score_requires_method(self):
  self.event['score']=70;self.reject()
 def test_legacy_adapter_does_not_invent_facts(self):
  row=RawCandidate(title='Example project',brand_or_client='Example client',year=2023,
   country_city='Japan, Tokyo',category='Museums & Cultural Exhibitions',
   immersive_format='Projection room',summary='Visitors walk around a room with large projections covering the walls.',
   source_url='https://example.org/project')
  result=from_pipeline(row)
  self.assertIsNone(result.start_date)
  self.assertIsNone(result.country_code)
  self.assertEqual(result.occurrence,'unknown')
  self.assertEqual(result.claims,[])
  self.assertEqual(result.organizers,[])
  self.assertEqual(result.client_name,'Example client')

if __name__=='__main__': unittest.main()
