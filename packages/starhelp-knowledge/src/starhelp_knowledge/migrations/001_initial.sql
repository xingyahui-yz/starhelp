PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    source_role TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_policy_revisions (
    policy_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    revision INTEGER NOT NULL,
    permission_status TEXT NOT NULL CHECK (permission_status IN ('unknown','allowed','restricted','disallowed')),
    terms_reference TEXT,
    allowed_domains_json TEXT NOT NULL,
    allowed_paths_json TEXT NOT NULL,
    rate_policy_json TEXT NOT NULL,
    storage_policy_json TEXT NOT NULL,
    checked_at TEXT,
    UNIQUE (source_id, revision)
);
CREATE TABLE IF NOT EXISTS source_capability_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    adapter_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('declared','verified','partial','unavailable','unknown')),
    capabilities_json TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_revisions (
    entity_revision_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    revision INTEGER NOT NULL,
    game_version_id TEXT,
    environment TEXT NOT NULL CHECK (environment IN ('live','beta','unknown')),
    release_status TEXT NOT NULL CHECK (release_status IN ('released','unreleased','unknown')),
    payload_schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    validity_status TEXT NOT NULL DEFAULT 'valid' CHECK (validity_status IN ('valid','withdrawn','disabled')),
    observed_at TEXT NOT NULL,
    UNIQUE(entity_id, revision)
);
CREATE TABLE IF NOT EXISTS mode_cycles (
    cycle_id TEXT PRIMARY KEY,
    mode_id TEXT NOT NULL,
    external_cycle_key TEXT NOT NULL,
    game_version_id TEXT,
    environment TEXT NOT NULL CHECK (environment IN ('live','beta','unknown')),
    cycle_revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(mode_id, external_cycle_key, cycle_revision)
);
CREATE TABLE IF NOT EXISTS stages (
    stage_revision_id TEXT PRIMARY KEY,
    stage_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL REFERENCES mode_cycles(cycle_id),
    revision INTEGER NOT NULL,
    external_stage_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(stage_id, revision)
);
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    external_content_id TEXT,
    canonical_url TEXT NOT NULL,
    content_kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, external_content_id)
);
CREATE TABLE IF NOT EXISTS document_revisions (
    document_revision_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    revision INTEGER NOT NULL,
    title TEXT NOT NULL,
    author_id TEXT,
    excerpt TEXT,
    locator_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    license_status TEXT NOT NULL CHECK (license_status IN ('unknown','allowed','restricted','disallowed')),
    published_at TEXT,
    observed_at TEXT NOT NULL,
    validity_status TEXT NOT NULL CHECK (validity_status IN ('valid','withdrawn','disabled')),
    UNIQUE(document_id, revision)
);
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    document_revision_id TEXT NOT NULL REFERENCES document_revisions(document_revision_id),
    locator_json TEXT NOT NULL,
    excerpt TEXT,
    relation TEXT NOT NULL CHECK (relation IN ('supports','refutes','qualifies','context')),
    scope_json TEXT NOT NULL,
    evidence_status TEXT NOT NULL CHECK (evidence_status IN ('confirmed','suggested','unknown')),
    content_hash TEXT NOT NULL,
    validity_status TEXT NOT NULL CHECK (validity_status IN ('valid','withdrawn','disabled')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS public_records (
    record_id TEXT NOT NULL,
    record_kind TEXT NOT NULL CHECK (record_kind IN ('entity','knowledge','stage','template','variant','troubleshooting','resource')),
    current_revision INTEGER NOT NULL,
    PRIMARY KEY(record_kind, record_id)
);
CREATE TABLE IF NOT EXISTS public_record_revisions (
    record_revision_id TEXT PRIMARY KEY,
    record_kind TEXT NOT NULL,
    record_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('candidate','approved','rejected','withdrawn','disabled')),
    scope_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    dependency_refs_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(record_kind, record_id, revision),
    FOREIGN KEY(record_kind, record_id) REFERENCES public_records(record_kind, record_id)
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    record_revision_id TEXT NOT NULL REFERENCES public_record_revisions(record_revision_id),
    review_revision INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved','rejected')),
    actor_id TEXT NOT NULL,
    note TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(record_revision_id, review_revision)
);
CREATE TABLE IF NOT EXISTS index_releases (
    index_release_id TEXT PRIMARY KEY,
    parent_release_id TEXT REFERENCES index_releases(index_release_id),
    schema_version TEXT NOT NULL,
    required_capabilities_json TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('built','validated','active','superseded','withdrawn')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS release_members (
    index_release_id TEXT NOT NULL REFERENCES index_releases(index_release_id),
    record_kind TEXT NOT NULL,
    record_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    dependency_refs_json TEXT NOT NULL,
    PRIMARY KEY(index_release_id, record_kind, record_id),
    FOREIGN KEY(record_kind, record_id, revision)
      REFERENCES public_record_revisions(record_kind, record_id, revision)
);
CREATE TABLE IF NOT EXISTS disabled_refs (
    record_kind TEXT NOT NULL,
    record_id TEXT NOT NULL,
    revision INTEGER,
    reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    disabled_at TEXT NOT NULL,
    PRIMARY KEY(record_kind, record_id, revision)
);
CREATE TABLE IF NOT EXISTS publication_events (
    event_id TEXT PRIMARY KEY,
    index_release_id TEXT,
    operation_kind TEXT NOT NULL CHECK (operation_kind IN ('validate','activate','rollback','withdraw','disable')),
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    expected_active_release_id TEXT,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(actor_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS update_runs (
    run_id TEXT PRIMARY KEY,
    request_key TEXT NOT NULL,
    request_actor TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','running','waiting_review','completed','failed','cancelled')),
    source_id TEXT REFERENCES sources(source_id),
    public_scope_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(request_actor, request_key)
);
CREATE TABLE IF NOT EXISTS update_tasks (
    task_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES update_runs(run_id),
    stage TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending','running','waiting_review','completed','failed','cancelled')),
    lease_owner TEXT,
    lease_expires_at TEXT,
    checkpoint_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id, stage)
);
CREATE TABLE IF NOT EXISTS command_receipts (
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    command_kind TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(actor_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_revision INTEGER,
    result TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entity_revisions_lookup
    ON entity_revisions(entity_id, game_version_id, environment, release_status);
CREATE INDEX IF NOT EXISTS idx_records_state ON public_record_revisions(state, record_kind, record_id);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON update_tasks(state, updated_at);
