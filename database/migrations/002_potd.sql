-- Problem of the Day: per-server settings, one row per daily post, one row per user per post.

CREATE TABLE guild_settings (
    guild_id           INTEGER PRIMARY KEY,
    potd_enabled       INTEGER NOT NULL DEFAULT 0,
    potd_channel_id    INTEGER,
    potd_hour          INTEGER NOT NULL DEFAULT 9  CHECK (potd_hour BETWEEN 0 AND 23),
    potd_minute        INTEGER NOT NULL DEFAULT 0  CHECK (potd_minute BETWEEN 0 AND 59),
    timezone           TEXT NOT NULL DEFAULT 'UTC',
    difficulty         TEXT NOT NULL DEFAULT 'any' CHECK (difficulty IN ('any', 'core', 'advanced', 'challenge')),
    repeat_window_days INTEGER NOT NULL DEFAULT 60 CHECK (repeat_window_days >= 1)
);

-- UNIQUE (guild_id, post_date) is what prevents a double post: the row is "claimed" BEFORE the Discord message is
-- sent, and message_id stays NULL until the send succeeds.
CREATE TABLE potd_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    problem_id  TEXT NOT NULL,
    post_date   TEXT NOT NULL,      -- local date in the server's timezone at posting time (YYYY-MM-DD)
    timezone    TEXT NOT NULL,      -- that timezone, so a later timezone change cannot reopen old problems
    channel_id  INTEGER,
    message_id  INTEGER,
    claimed_at  TEXT NOT NULL,      -- UTC, fixed-width format so text comparison orders correctly
    UNIQUE (guild_id, post_date)
);
CREATE INDEX idx_potd_posts_message ON potd_posts (message_id);

CREATE TABLE potd_progress (
    post_id         INTEGER NOT NULL REFERENCES potd_posts (id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL,
    hints_used      INTEGER NOT NULL DEFAULT 0,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    solved_at       TEXT,
    revealed_at     TEXT,
    PRIMARY KEY (post_id, user_id)
);
CREATE INDEX idx_potd_progress_user ON potd_progress (user_id);
