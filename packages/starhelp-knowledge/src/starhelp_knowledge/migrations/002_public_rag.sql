CREATE TABLE IF NOT EXISTS public_rag_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    evidence_revision INTEGER NOT NULL CHECK (evidence_revision > 0),
    content_hash TEXT NOT NULL,
    chunker_profile TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    release_id TEXT NOT NULL,
    text TEXT NOT NULL,
    title TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    locator_json TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('supports','refutes','qualifies','context')),
    evidence_status TEXT NOT NULL CHECK (evidence_status IN ('confirmed','suggested','unknown')),
    published_at TEXT,
    observed_at TEXT NOT NULL,
    embedding_json TEXT,
    embedding_profile TEXT,
    indexed_at TEXT NOT NULL,
    UNIQUE(source_id, evidence_id, evidence_revision, content_hash, chunker_profile, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_public_rag_release ON public_rag_chunks(release_id, evidence_id, chunk_index);
CREATE TABLE IF NOT EXISTS public_rag_index_state (
    release_id TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL,
    chunker_profile TEXT NOT NULL,
    semantic_encoder_profile TEXT NOT NULL,
    chunk_count INTEGER NOT NULL CHECK (chunk_count >= 0),
    indexed_at TEXT NOT NULL
);
