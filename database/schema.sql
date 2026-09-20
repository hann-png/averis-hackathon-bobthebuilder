CREATE TABLE IF NOT EXISTS emails (
    email_id TEXT PRIMARY KEY,
    sender TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attachments (
    id BIGSERIAL PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(email_id) ON DELETE CASCADE,
    attachment_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT,
    content_sha256 TEXT,
    extracted_text TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (email_id, attachment_path)
);

CREATE TABLE IF NOT EXISTS verification_results (
    email_id TEXT PRIMARY KEY REFERENCES emails(email_id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    status TEXT NOT NULL,
    review_reason TEXT,
    has_defect BOOLEAN NOT NULL DEFAULT FALSE,
    defect_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    processed_at TIMESTAMPTZ,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS comparison_fields (
    email_id TEXT NOT NULL REFERENCES emails(email_id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    si_value TEXT,
    bl_value TEXT,
    is_mismatch BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (email_id, field_name)
);

CREATE TABLE IF NOT EXISTS email_activity (
    email_id TEXT PRIMARY KEY,
    first_seen_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ,
    reviewed BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_at TIMESTAMPTZ,
    last_opened_at TIMESTAMPTZ,
    reviewed_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_drafts (
    email_id TEXT PRIMARY KEY,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    saved_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_events (
    id BIGSERIAL PRIMARY KEY,
    email_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    actor TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    UNIQUE (email_id, event_type, title, occurred_at)
);

CREATE INDEX IF NOT EXISTS idx_verification_status ON verification_results(status);
CREATE INDEX IF NOT EXISTS idx_verification_category ON verification_results(category);
CREATE INDEX IF NOT EXISTS idx_verification_processed_at ON verification_results(processed_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);
CREATE INDEX IF NOT EXISTS idx_activity_reviewed_at ON email_activity(reviewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_opened_at ON email_activity(last_opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_events_email_time ON activity_events(email_id, occurred_at DESC);
