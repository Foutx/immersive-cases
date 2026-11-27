CREATE TABLE events (
 id TEXT PRIMARY KEY NOT NULL,
 title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 2 AND 300),
 description TEXT NOT NULL CHECK(length(trim(description)) > 0),
 source_url TEXT NOT NULL,
 start_date TEXT, end_date TEXT,
 reported_year INTEGER CHECK(reported_year BETWEEN 1800 AND 2200),
 country_code TEXT CHECK(country_code GLOB '[A-Z][A-Z]'),
 city TEXT, venue TEXT, location_text TEXT,
 client_name TEXT, format_text TEXT, category TEXT,
 occurrence TEXT NOT NULL DEFAULT 'unknown' CHECK(occurrence IN ('unknown','announced','ongoing','completed')),
 score REAL CHECK(score BETWEEN 0 AND 100), score_method TEXT,
 moderation_status TEXT NOT NULL DEFAULT 'draft' CHECK(moderation_status IN ('draft','in_review','published','rejected')),
 reviewed_by TEXT, reviewed_at TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(start_date IS NULL OR end_date IS NULL OR end_date >= start_date),
 CHECK((score IS NULL AND score_method IS NULL) OR (score IS NOT NULL AND score_method IS NOT NULL)),
 CHECK(moderation_status != 'published' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE TABLE event_sources (
 producer TEXT NOT NULL, source_record_id TEXT NOT NULL,
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 last_collected_at TEXT NOT NULL,
 PRIMARY KEY(producer, source_record_id)
);
CREATE TABLE event_parties (
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('organizer','studio')),
 name TEXT NOT NULL CHECK(length(trim(name)) > 0),
 PRIMARY KEY(event_id, role, name)
);
CREATE TABLE event_proofs (
 id INTEGER PRIMARY KEY,
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 url TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('official','article','video','photo','other')),
 title TEXT, checked_at TEXT,
 http_status INTEGER CHECK(http_status BETWEEN 100 AND 599), error TEXT,
 relevance TEXT NOT NULL DEFAULT 'unreviewed' CHECK(relevance IN ('unreviewed','automatic_match')),
 reviewed_by TEXT, reviewed_at TEXT,
 UNIQUE(event_id,url), UNIQUE(event_id,id),
 CHECK((http_status IS NULL AND error IS NULL) OR checked_at IS NOT NULL)
);
CREATE TABLE event_claims (
 id INTEGER PRIMARY KEY,
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 field TEXT NOT NULL CHECK(field IN ('environment','visitor_actions','system_response','visitor_role','immersion_mechanism','dates','location','occurred')),
 value TEXT NOT NULL CHECK(length(trim(value)) > 0),
 UNIQUE(event_id,field,value), UNIQUE(event_id,id),
 CHECK(field != 'system_response' OR value IN ('reacts','does_not_react')),
 CHECK(field != 'visitor_role' OR value IN ('observer','participant','co_creator'))
);
CREATE TABLE claim_evidence (
 event_id TEXT NOT NULL, claim_id INTEGER NOT NULL, proof_id INTEGER NOT NULL,
 quote TEXT NOT NULL CHECK(length(trim(quote)) > 0),
 PRIMARY KEY(claim_id,proof_id,quote),
 FOREIGN KEY(event_id,claim_id) REFERENCES event_claims(event_id,id) ON DELETE CASCADE,
 FOREIGN KEY(event_id,proof_id) REFERENCES event_proofs(event_id,id) ON DELETE CASCADE
);
CREATE TABLE tags (
 id INTEGER PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN ('format','technology')),
 slug TEXT NOT NULL CHECK(length(slug) BETWEEN 1 AND 64 AND slug NOT GLOB '*[^a-z0-9_]*' AND substr(slug,1,1) GLOB '[a-z]'),
 label TEXT,
 UNIQUE(kind,slug)
);
CREATE TABLE event_tags (
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
 PRIMARY KEY(event_id,tag_id)
);
CREATE TABLE import_runs (
 id TEXT PRIMARY KEY NOT NULL,
 producer TEXT NOT NULL, schema_version TEXT NOT NULL,
 started_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','succeeded','partial','failed')),
 added_count INTEGER NOT NULL DEFAULT 0 CHECK(added_count >= 0),
 updated_count INTEGER NOT NULL DEFAULT 0 CHECK(updated_count >= 0),
 rejected_count INTEGER NOT NULL DEFAULT 0 CHECK(rejected_count >= 0),
 error TEXT,
 CHECK(finished_at IS NULL OR finished_at >= started_at)
);
CREATE TABLE scrape_logs (
 id INTEGER PRIMARY KEY,
 run_id TEXT REFERENCES import_runs(id) ON DELETE SET NULL,
 url TEXT NOT NULL, checked_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('success','skipped','failed')),
 http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
 content_hash TEXT, error TEXT
);
CREATE INDEX events_country_year ON events(country_code,reported_year);
CREATE INDEX events_year ON events(reported_year);
CREATE INDEX events_moderation ON events(moderation_status);
CREATE INDEX events_end_date ON events(end_date);
CREATE INDEX sources_event ON event_sources(event_id);
CREATE INDEX proofs_kind_event ON event_proofs(kind,event_id);
CREATE INDEX proofs_checked ON event_proofs(checked_at);
CREATE INDEX evidence_proof ON claim_evidence(event_id,proof_id);
CREATE INDEX tags_events ON event_tags(tag_id,event_id);
CREATE INDEX logs_url_time ON scrape_logs(url,checked_at);
CREATE INDEX logs_run ON scrape_logs(run_id);
CREATE INDEX runs_status_time ON import_runs(status,started_at);
CREATE VIRTUAL TABLE events_fts USING fts5(title,description,content='events',content_rowid='rowid',tokenize='unicode61');
CREATE TRIGGER events_fts_insert AFTER INSERT ON events BEGIN
 INSERT INTO events_fts(rowid,title,description) VALUES(new.rowid,new.title,new.description);
END;
CREATE TRIGGER events_fts_delete AFTER DELETE ON events BEGIN
 INSERT INTO events_fts(events_fts,rowid,title,description) VALUES('delete',old.rowid,old.title,old.description);
END;
CREATE TRIGGER events_fts_update AFTER UPDATE OF title,description ON events BEGIN
 INSERT INTO events_fts(events_fts,rowid,title,description) VALUES('delete',old.rowid,old.title,old.description);
 INSERT INTO events_fts(rowid,title,description) VALUES(new.rowid,new.title,new.description);
END;
