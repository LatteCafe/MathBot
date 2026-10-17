-- Tracks when each periodic job (POTD, newsletter, contest closing) should next run, so jobs
-- survive restarts and missed windows. Used from Phase 3 onward.
CREATE TABLE scheduled_jobs (
    name        TEXT PRIMARY KEY,
    next_run_at TEXT NOT NULL,   -- ISO-8601 UTC
    last_run_at TEXT
);
