CREATE TABLE import_records (
 run_id TEXT NOT NULL REFERENCES import_runs(id) ON DELETE CASCADE,
 source_record_id TEXT NOT NULL,
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 outcome TEXT NOT NULL CHECK(outcome IN ('added','updated','unchanged','stale')),
 payload_json TEXT NOT NULL,
 conflicts_json TEXT NOT NULL DEFAULT '[]',
 PRIMARY KEY(run_id,source_record_id)
);
CREATE INDEX import_records_event ON import_records(event_id);
