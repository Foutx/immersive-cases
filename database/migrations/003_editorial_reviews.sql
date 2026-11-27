CREATE TABLE event_reviews (
 id INTEGER PRIMARY KEY,
 event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 decision TEXT NOT NULL CHECK(decision IN ('published','rejected','in_review')),
 reviewer TEXT NOT NULL CHECK(length(trim(reviewer)) BETWEEN 1 AND 100),
 reviewed_at TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 1000)
);
CREATE INDEX event_reviews_by_event ON event_reviews(event_id,id);
