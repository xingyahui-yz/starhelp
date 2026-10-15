# StarHelp Knowledge

An independently installable Python package for StarHelp's **public-only** knowledge service. It uses the Python standard library and SQLite; supported Python is 3.12 or later.

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
```

The command prints the random bearer token once and stores only its SHA-256 hash and role in the auth config, normally `%USERPROFILE%\.starhelp-knowledge\auth.json`. Keep the token out of source control and logs. The three roles have separate permissions; `reader` is the default for invitees and cannot update, review, or publish. `admin` is required to mark a source policy allowed or claim a capability verified. Restart the service after changing its auth config so the new identity set is loaded.

## HTTP surface

- `GET /health`
- `GET /v1/releases`
- `GET /v1/releases/{release_id}/bundle`
- `GET /v1/templates/{template_id}?release={release_id}` (complete stage, variants, and evidence from one release)
- `POST /v1/query` (strict `PublicQuery` allowlist)
- `POST /v1/public-search` (local query first; if no local match, returns a trigger result)
- `GET /v1/admin/source-report` (latest recorded permission and capability snapshots; updater role)
- `/v1/admin/*` (source policy, evidence, candidate, review, release, and update-task commands; bearer auth required)

The request schema and route names are implementation drafts pending the shared M0 freeze. Unknown request fields are rejected, error responses do not include input values, and request bodies are not logged by the application. No request may contain account fields or derived account signals. Free-text public questions are used only for local keyword lookup while no authorized remote search provider is configured.

## Content lifecycle

Source policy must be explicitly recorded before evidence can be stored. Marking a policy allowed requires an admin identity, a dated terms reference, permitted domains and optional paths, rate policy, and storage policy. Evidence storage is limited to a small excerpt unless a source policy explicitly allows full text. Candidates require evidence; unknown/withdrawn evidence cannot be published. Review is tied to an immutable revision hash, the creator cannot approve their own candidate, and approval does not activate a release. Release validation and activation are separate, idempotent publisher actions.

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

## Verification

From the repository root, with the package source on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = '.\packages\starhelp-knowledge\src'
python -m unittest discover -s .\packages\starhelp-knowledge\tests -v
```

The tests use synthetic fixture data and simulated identities. They do not establish real-source permission, real game content coverage, or human approval of production content.
