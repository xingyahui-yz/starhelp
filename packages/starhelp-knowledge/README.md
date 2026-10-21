# StarHelp Knowledge

An independently installable Python package for StarHelp's **public-only** knowledge service. Version 0.3.0 uses the Python standard library and SQLite for the service; cross-version Ed25519 signing and verification are an optional `crypto` dependency. Supported Python is 3.12 or later.

## Local development

From this directory:

```powershell
python -m starhelp_knowledge init --database .\data\knowledge.sqlite3
python -m starhelp_knowledge serve --database .\data\knowledge.sqlite3
```

When running from the repository without installing the package, set `PYTHONPATH` to `src`:

```powershell
$env:PYTHONPATH = '.\src'
python -m starhelp_knowledge init --database .\data\knowledge.sqlite3
python -m starhelp_knowledge serve --database .\data\knowledge.sqlite3
```

The service binds to `127.0.0.1:8765` by default. The included WSGI server is a local development/runtime entry point, not a public TLS terminator. A shared deployment needs an HTTPS reverse proxy, an independently managed host, backups, monitoring, and an explicit server review before it is exposed to invitees.

## Invitation identities

Create an identity with the minimum role needed:

```powershell
python -m starhelp_knowledge create-token --actor-id curator-1 --role updater
python -m starhelp_knowledge create-token --actor-id reviewer-1 --role reviewer
python -m starhelp_knowledge create-token --actor-id publisher-1 --role publisher
python -m starhelp_knowledge create-token --actor-id maintainer-1 --role updater --role reviewer --role publisher
```

The command prints the random bearer token once and stores only its SHA-256 hash and role list in the auth config, normally `%USERPROFILE%\.starhelp-knowledge\auth.json`. Repeat `--role` to grant one maintainer updater, reviewer, and publisher permissions. The maintainer must still explicitly approve the immutable content hash, then separately build, validate, activate, or roll back a release; each action is audited and requires the corresponding permission. No action is automatically approved or published. Keep the token out of source control and logs. The roles have separate permissions; `reader` is the default for invitees and cannot update, review, or publish. `admin` has every permission. Restart the service after changing its auth config so the new identity set is loaded.

## HTTP surface

- `GET /health`
- `GET /v1/releases`
- `GET /v1/releases/{release_id}/bundle`
- `GET /v1/templates/{template_id}?release={release_id}` (complete stage, variants, and evidence from one release)
- `POST /v1/query` (strict `PublicQuery` allowlist)
- `POST /v1/public-search` (local query first; if no local match, returns a trigger result)
- `GET /v1/admin/source-report` (latest recorded permission and capability snapshots; updater role)
- `/v1/admin/*` (source policy, evidence, candidate, review, release, and update-task commands; bearer auth required)

The local HTTP request schema and route names remain implementation drafts. The separate A/B/C interoperability scope is frozen in the shared contract. Unknown request fields are rejected, error responses do not include input values, and request bodies are not logged by the application. No request may contain account fields or derived account signals. Free-text public questions are used only for local keyword lookup while no authorized remote search provider is configured.

## Content lifecycle

Source policy must be explicitly recorded before evidence can be stored. Marking a policy allowed requires an admin identity, a dated terms reference, permitted domains and optional paths, rate policy, and storage policy. Evidence storage is limited to a small excerpt unless a source policy explicitly allows full text. Candidates require evidence; unknown/withdrawn evidence cannot be published. Review requires the reviewer permission and the exact immutable revision hash; a maintainer with both updater and reviewer permissions may explicitly review their own candidate. Approval does not activate a release, and a publisher action remains separately authorized and audited. Release validation and activation are separate, idempotent publisher actions.

Templates reference one stage and one or more complete variants. Every variant contains a full team, entity dependencies, finite declarative conditions, and ordered steps. Release construction rejects missing stage, variant, entity, or evidence dependencies. A client fetch is pinned to one `index_release_id`; no missing object is filled from a newer release. `sha256-canonical-json-utf8` covers the public record and evidence members, and the manifest stores dependency references and object hashes.

## Sources and current M0 status

No source-specific real adapter is enabled. `VerifiedJSONSourceAdapter` is a generic, permission-gated HTTPS JSON transport only; it requires a matching allowed policy and dated verified capability snapshot, constrains host/path, rejects redirects and query strings, sends no credentials, and reports endpoint coverage as unknown. It does not parse any named provider or claim complete data. `SyntheticFixtureAdapter` exists only for offline tests and always returns `status: synthetic` and unknown real coverage. The Bilibili guide crawler, Nanoka and StarRailRes imports, live public search, and vector retrieval remain disabled until their source access, storage permission, rate limits, field coverage, and reproducible IDs have been verified and recorded. See `docs/handoffs/knowledge-backend.md` for the source matrix and decisions still required.

## Public release files

Export a validated release for a client or offline mirror, then independently verify its canonical hashes:

```powershell
python -m starhelp_knowledge export-bundle --database .\data\knowledge.sqlite3 --release RELEASE_ID --output .\data\release.json
python -m starhelp_knowledge verify-bundle --path .\data\release.json
```

The export operation uses the service's release checks, writes canonical JSON through a temporary file, and includes only members in that release. Verification checks record/evidence hashes, manifest hash, and reference closure without opening the database.

## Signed B distribution and C planner view

The `starhelp.local.v0.2` adapter preserves three separate integrity layers: A's native release hash, C's `sha256-json-v1` member hashes, and B's Ed25519-signed `PublicBundle/0.1-draft` envelope. `verify-distribution` checks all three layers, exact collection schemas, release identity, capability declarations, object hashes, and dependency closure. B's pinned `BundleValidator` independently validates the outer envelope.

Install the optional signing dependency, then export a published release with a separately provisioned Ed25519 private key:

```powershell
python -m pip install -e '.[crypto]'
python -m starhelp_knowledge export-distribution --database .\data\knowledge.sqlite3 --release RELEASE_ID --profile starhelp.local.v0.2 --private-key .\secrets\production-ed25519-private.pem --key-id production-knowledge-v1 --producer-commit COMMIT_SHA --output .\data\knowledge-distribution.json
python -m starhelp_knowledge verify-distribution --path .\data\knowledge-distribution.json --trusted-public-key .\secrets\production-ed25519-public.pem --trusted-key-id production-knowledge-v1
```

Keep signing and trust keys outside source control. The exporter requires an active or superseded release, exact approved review hashes, and an activation/rollback audit event. It refuses a C projection when public meanings such as stage seats, resource reuse, variant rosters, equipment requirements, public goals, or registered condition attributes are missing or ambiguous.

The original deterministic fixture command remains the `rel_fixture_0001` compatibility sample. It exercises the A lifecycle using only synthetic `fixture:` records, then calls the snapshot serializer and bundle validator from the exact pinned B source commit. Pass the read-only B repository path explicitly:

```powershell
python -m starhelp_knowledge build-fixture-distribution --output-dir .\artifacts --b-root ..\desktop-account --overwrite
python -m starhelp_knowledge verify-distribution --path .\artifacts\knowledge-planner-fixture-v1.bpublic.json --trusted-public-key .\artifacts\fixture-ed25519-public.pem --trusted-key-id starhelp-fixture-ed25519-v1
```

This writes the signed envelope, a test-only public key, a synthetic B account snapshot, and `SHA256SUMS.txt`. The deterministic private fixture seed is test-only and is not a production trust anchor. The fixture contains synthetic approvals to exercise the exporter; it does not represent human approval or real game content. The interop tests load the exact pinned C planner source into a temporary directory and verify main, complete-alternate, and no-matching-goal outcomes without modifying B or C.

The frozen S3 sample has a separate immutable output path and never overwrites that original fixture:

```powershell
python -m starhelp_knowledge build-s3-interop-fixture --output-dir .\artifacts\interop-min-v0.1-s3 --b-root ..\desktop-account
python -m starhelp_knowledge verify-distribution --path .\artifacts\interop-min-v0.1-s3\starhelp-interop-min-v0.1-s3.bpublic.json --trusted-public-key .\artifacts\interop-min-v0.1-s3\fixture-ed25519-public.pem --trusted-key-id starhelp-fixture-ed25519-v1
```

The S3 output includes the A public bundle, public test key, finite equipment type table, B-pinned synthetic snapshot input, and raw-file checksums. The snapshot is generated only by B's pinned serializer. The three-mode alpha equipment case is partial-inventory coverage; a locked instance stays fixed and unresolved inventory is reported as pending, never as proof that no other item exists. The replay checks C's pinned core planner against normalized fixture input; it does not establish full C producer-adapter support for A 0.3.0 or full B host-flow acceptance. All S3 records and approvals are synthetic and are not production trust or content approval.

## Verification

From the repository root, with the package source on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = '.\packages\starhelp-knowledge\src'
python -m unittest discover -s .\packages\starhelp-knowledge\tests -v
```

The tests use synthetic fixture data and simulated identities. They do not establish real-source permission, real game content coverage, production-key provisioning, or human approval of production content.
