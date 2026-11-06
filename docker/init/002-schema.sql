-- Schema do corpus RIG (F0.4).
-- Idempotente: CREATE ... IF NOT EXISTS em todas as tabelas/índices.

CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc_type TEXT,
    doc_meta JSONB,
    content_hash TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, doc_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc_type TEXT,
    doc_meta JSONB,
    breadcrumb TEXT NOT NULL,
    hierarchy JSONB,
    kind TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    char_span INTEGER[],
    page INTEGER,
    extraction_quality TEXT,
    content_hash TEXT NOT NULL,
    embedding vector(1024),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('pt_unaccent', immutable_unaccent(chunk_text))
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (source, doc_id)
        REFERENCES documents (source, doc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS chunks_tsv_gin
    ON chunks USING GIN (tsv);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS ingest_cursor (
    source TEXT NOT NULL,
    scope TEXT NOT NULL,
    last_id TEXT,
    last_ts TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, scope)
);

CREATE TABLE IF NOT EXISTS ingest_run (
    id BIGSERIAL PRIMARY KEY,
    source TEXT,
    scope TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    fetched INTEGER NOT NULL DEFAULT 0,
    new INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    dataset_version TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    error TEXT
);
