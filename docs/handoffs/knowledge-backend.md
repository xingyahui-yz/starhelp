# StarHelp Knowledge Backend Handoff

Status: implementation in progress. This is a public-only backend component; this handoff does not claim the StarHelp MVP is complete or production content is published.

## Ownership and boundary

- Package: `packages/starhelp-knowledge/`, import name `starhelp_knowledge`.
- This workstream owns only the package above and this handoff file.
- The service rejects non-allowlisted public-query fields and prohibited private field names in public records. It has no UID proxy route, account table, private-report input, or remote model/provider configured.
- Old `src/abyss_ai/`, the shared contract, root dependencies, and other component folders remain untouched.

## M0 source and coverage report (checked 2026-10-15)

| Candidate source | Evidence checked | Capability and coverage evidence | Permission/storage outcome | Status |
|---|---|---|---|---|
| Nanoka static game-data source (`static.nanoka.cc`) | [Community skill repository](https://github.com/Run2zZ/hsr-nanoka) documents a static JSON endpoint, a manifest, character/light-cone/eidolon/trace/memorial data, and says the underlying data is owned by the original source and HoYoverse and is for study/research. Its MIT license applies to that skill repository's code, not by itself to the upstream game dataset. No source terms authorizing StarHelp redistribution or service use were found. | The documented interface suggests a versioned manifest and lookup may exist. No endpoint was requested, no field enumeration or enemy/endgame-stage coverage was verified, and no rate policy was established. | Dataset redistribution, excerpting, commercial/service use, and rate limits are unverified. Do not ingest or bundle until permission and terms are confirmed. | `unknown`; disabled |
| Mar-7th/StarRailRes | [Repository README](https://github.com/Mar-7th/StarRailRes) lists versioned JSON indexes for characters, skills, light cones, relics, and items; it identifies Dimbreath/StarRailData as a game-data source. GitHub labels the repository AGPL-3.0. | This demonstrates a useful public file layout and a partial data taxonomy, not verified enumeration, freshness, stable cross-source mappings, enemy/rotation coverage, or a service API. No repository contents were cloned or imported. | The repository code license does not establish permission to redistribute the game's extracted data/assets or third-party upstream data in a StarHelp package. Obtain source-specific permission/rights analysis before bundling. | `partial declared`; disabled |
| Bilibili guide content | [Bilibili user agreement](https://www.bilibili.com/blackboard/protocal/licence.html) says automated acquisition of platform services/content/data requires prior explicit written permission. [Open Platform docs](https://open.bilibili.com/doc) describe application review and user-authorized account/manuscript data capabilities. | Open Platform docs do not establish general public guide search, all four query categories, the 8+12 author buckets, 20-result cap, latest-order pagination, transcripts, or full-text fields. No app credentials were provided or used. | No crawler or unofficial API is enabled. Public visibility is not recorded as scraping or republication permission. Ask for approved API scope or written permission before building a source-specific adapter. | `unavailable for current scope`; disabled |
| HoYoLAB / official in-game wiki | Project plan lists it as a candidate knowledge source, but no official machine-readable search API, collection scope, or republishing terms were verified in this M0 pass. | Field and discovery coverage unknown; no requests made. | Permission, quota and storage terms unknown. | `unknown`; disabled |
| Mihomo / Enka showcase API | Existing design notes and public API documentation describe user showcase data, request TTL/rate limits, and that showcase lists can be partial/stale. This is a desktop account-source candidate, not a knowledge ingestion source. | The endpoint does not prove full roster, inventory, combat history, endgame history, or reliable specific equipment-instance identity. No UID request was made. | Keep out of this backend. The selected UID/region should be sent only by the user-confirmed desktop flow to its selected showcase service; the backend must not proxy it. | outside A ownership |
| Baidu, Weibo, and WeChat Index | Listed for independent creator/trend analysis. No credentials, authorized interface, or data-export scope was available for this task. | Coverage and comparable metrics unverified. | Not a prerequisite for public facts, evidence, templates, or retrieval. Do not block the public knowledge pipeline on them. | deferred and non-blocking |

### M0 decision

The repository contains no evidence sufficient to mark a live content source as both authorized and verified. Ingestion is therefore limited to the explicitly synthetic test adapter and manually supplied public evidence after an admin has recorded an allowed source policy. No production source has been activated. The next source decision needs: written/official permission or applicable terms for the intended storage and redistribution; approved API/domain/path; rate and freshness rules; actual fields and discovery/pagination bounds; a dated read-only sample; and stable game-version, environment, mode, cycle, stage, entity, and external-ID mappings.

## Contract freeze still required

`docs/contracts/mvp-v0.1.md` remains a draft. This package uses the following local proposal while keeping the shared contract untouched:

- The HTTP query schema is `PublicQuery` version `0.1-draft`; public query fields are allowlisted. Current route names are provisional.
- Mode IDs, cycle IDs, stage keys, external entity ID mapping, and their source-of-truth are not yet verified.
- Declarative condition operator set is `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, and `not_in`. Units and attribute dictionaries still need a shared M0 mapping.
- Bundle hashes use SHA-256 over canonical UTF-8 JSON (sorted keys, compact separators), and each record/evidence member carries its own content hash. Manifest signatures and any cross-thread canonicalization agreement remain open.
- Search currently uses deterministic local substring/keyword matching. No embedding model, vector database, remote answer model, or authorized live search source is configured.
- The current trigger for controlled public search is an empty local result. Other trigger states (stale, conflicting, latest-requested) need source-specific freshness and an agreed query shape.
- Error codes and the WSGI paths are draft implementation choices; align them with B/C before freezing.
- `VerifiedJSONSourceAdapter` is only an allowlisted HTTPS JSON transport. It requires an allowed policy and source/version-matched verified capability snapshot; it does not implement a real named source, and its coverage remains unknown.

Do not change the shared contract from this branch. If a cross-component field or semantic change becomes necessary, add a proposal here with old meaning, proposed meaning, impact, and compatibility strategy for the user to coordinate.

## Implemented package areas

The package currently provides SQLite migrations and tables for sources/policies/capability snapshots, entities and revisions, public records and immutable revisions, evidence, reviews, index releases, disabled references, audit events, command receipts, update runs, tasks, leases, and checkpoints. The service implements strict request validation, candidate creation, explicit review, release build/validation/activation/rollback, same-release complete template retrieval, deterministic public search, empty-result search triggering, and idempotent update-task recovery. The CLI exports validated release bundles and verifies them without a database; bundle verification checks member hashes, manifest hash, dependencies, and evidence closure.

### Not yet proven or delivered

- No genuine external source integration or full source coverage report has been verified beyond the research matrix above.
- No real game template, complete production alternative, or no-match content case has been curated, reviewed, or published. Synthetic tests do not substitute for those human content gates.
- No vector/semantic search or remote public-answer provider is active.
- No shared server has been provisioned; current CLI uses a local WSGI server and bearer-token hash configuration. TLS, deployment hardening, backups, monitoring and recovery drills remain deployment work.
- No B/C cross-package black-box integration has been run. Current paths and schemas are not frozen.
- M6 identity management is file-provisioned for local operation; invite workflow, secure secret distribution, storage ACL review and server identity provider selection remain outstanding.

## Verification evidence

Verification run on 2026-10-15: `compileall` succeeded; `unittest discover` passed all 12 tests, including explicit release hash tampering and source-policy/capability binding rejection. Tests use `fixture:` identifiers and simulated curator/reviewer/publisher/admin principals. The test identities are not production identities; their approvals do not approve any real game content.

## Reference links

- [Bilibili user agreement](https://www.bilibili.com/blackboard/protocal/licence.html)
- [Bilibili Open Platform docs](https://open.bilibili.com/doc)
- [Nanoka community skill repository](https://github.com/Run2zZ/hsr-nanoka)
- [StarRailRes repository](https://github.com/Mar-7th/StarRailRes)
- [Enka API docs](https://github.com/EnkaNetwork/API-docs/blob/master/api.md)
