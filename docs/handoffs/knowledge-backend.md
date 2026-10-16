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

## Second-round interoperability profile (A-side proposal; not a shared-contract freeze)

This mapping was written before implementation. It deliberately names three distinct profiles; version strings are not interchangeable:

| Layer | Exact profile/version | Integrity/authenticity boundary | Planned artifact |
|---|---|---|---|
| A producer record | `PublicBundle` / contract `0.1-draft` / schema `0.1-draft`; package `starhelp-knowledge` | A release hash is `sha256-canonical-json-utf8` over the ordered public record/evidence body. A record `content_hash` hashes `{kind,id,scope,payload,evidence,dependencies}`. Neither value is a B distribution signature. | Preserved as `native_release` inside the signed distribution object. |
| B distribution envelope | A-side adapter profile `starhelp.b-publicbundle-envelope.v1`; outer `PublicBundle` contract/schema remain B's fixed `0.1-draft` | B requires `manifest.signing_key_id`, `manifest.members` as `{object_id: 64-lowercase-hex SHA-256}`, top-level hex `signature`, and `objects` with exactly the same keys. B canonicalizes JSON with UTF-8, `ensure_ascii=False`, sorted keys, compact separators, and `allow_nan=False`; Ed25519 keyring verifies the signature over canonical manifest bytes. Member digests cover each complete outer object. Production trust requires a separately provisioned keyring. | `packages/starhelp-knowledge/artifacts/knowledge-planner-fixture-v1.bpublic.json` and adjacent public-key/sha256 files. |
| C planner consumer view | `starhelp.local.v0.2`, local rules/component `0.2.0`, C schema/contract `0.1-draft` | C `manifest.members` is a list of `{kind,id,revision,content_hash,dependencies}`; `sha256-json-v1` is prefixed `sha256:` and hashes each complete projected member. Its manifest is nested under the B-signed object and remains a distinct digest layer. | Extract from the verified B object `planner_view:<release>`; only emitted when all required fields map explicitly. |

### Field mapping and fail-closed rules

| A native field | C 0.2 consumer field | A-side mapping rule / current gap |
|---|---|---|
| `manifest.index_release_id` | `manifest.index_release_id` and every C object `index_release_id` (where declared) | Copy the exact active/superseded release ID. Never combine revisions or objects across releases. |
| A `manifest.members[]` `{kind,id,revision,content_hash,dependencies}` | C `manifest.members[]` with the same identity/dependency triple | Preserve A member hashes under `source_proof`; compute a separate C profile digest over each exact projected object. B outer `members` is a keyed map and uses the B object digest, not either inner digest. |
| `entity.payload.entity_type`, `canonical_name`, `scope`, `revision`, evidence | C `entities[]`: `id`, `revision`, `entity_type`, `name`, exact source `scope`, evidence references | `canonical_name` maps to `name`; the exact declared applicability scope is retained. No account/ownership fields enter this projection. |
| `stage.payload.partitions`, stage `scope`, revision, dependencies/evidence | C `stages[]`: `stage_id`, `revision`, scope with `stage_revision`, structured `partitions[{partition_id,slots:[{slot_id}]}]`, explicit `resource_reuse`, evidence | Current A stage payload stores only partition labels and cannot establish seats or reuse semantics. Such records are rejected by the C profile until curators provide explicit roster/seat and resource rules; no seats are inferred from variants. |
| `template.payload.title`, `primary_variant_id`, `alternate_variant_ids`, `scope.stage_id`, dependencies | C `templates[]`: `id`, `revision`, `title`, `approval_status`, `publication_status`, `stage_ids`, `scope`, `public_goals`, `variant_ids` | Stage ID comes from the single typed stage dependency; variants preserve primary/alternate relationship in a separate `variant_roles` projection and C's `variant_ids`. `public_goals` is missing in the current A schema and must be authored explicitly. Approval is derived only from the exact revision's approved review/hash; publication only from a validated active/superseded release. |
| `variant.payload.team[]` with `slot_id`, `entity_id`, optional `partition`; conditions, steps, dependencies/evidence | C `variants[]`: `template_id`, `variant_kind`, `teams{partition_id:[{slot_id,character_id,equipment_requirements}]}`, conditions, steps and evidence | `entity_id` maps to `character_id` only when referenced entity is explicitly a character. Every slot needs an explicit partition, and team slots must match the stage seats; complete alternate remains its own complete reviewed variant. Missing partition/seat/equipment-requirement semantics is rejected, not filled from a sibling variant. |
| A condition `{subject,attribute,operator,value,unit,measurement_context,requirement,evidence_status,evidence_refs}` | C condition with same named fields and registered attribute | `team_slot` maps directly; A `entity` maps to C `character` only for known character entities. `eq`, `gt`, `gte`, `lt`, `lte`, `in` are candidate identity mappings after operand checks; A `ne` maps to C `neq`. A `not_in`, team-wide subject, or any unregistered/ambiguous subject is unsupported (C's `contains` has no A equivalent). Attribute definitions must be explicit, including type, unit, allowed phases, and `loadout_dependent`; never infer units/context/trust from the value. |
| A evidence `{id,title,url,excerpt,locator,relation,scope,evidence_status,content_hash,license_status}` | C `evidence[]`: `{id,revision,title,source_url,locator,excerpt,status,scope}` | `url` maps to `source_url`; exact source scope is retained; `evidence_status` maps to `status` only for non-unknown evidence, and the source's allowed license remains in source proof. Missing provenance or withdrawn/unknown evidence rejects the projection. |
| A `troubleshooting` record | C `troubleshooting[]` with stage scope, trigger conditions, supported variant and evidence refs | Pass only a record whose payload explicitly satisfies C's shape and whose variant dependency is in this exact release. There is no generic paraphrase or inferred troubleshooting rule. |
| A `knowledge`, `resource` records | No C 0.2 member collection | Retain in `native_release`; mark as unconsumed in profile metadata. Do not silently alias them to troubleshooting or conditions. |
| A `required_capabilities` | B outer required-capability allowlist and C inner `starhelp.local-profile.v0.2` | Keep sets scoped per layer. Unknown/missing mandatory capabilities fail the A verifier. B validation must be called with the explicitly configured supported set. |
| A review/release state and withdrawal controls | C top-level template/variant `approval_status` and `publication_status`; C latest validity inputs | Derive approval from exact approved review revision/hash; derive publication from active/superseded release; never from candidate state or an unsigned flag. Re-check disabled/withdrawn refs at export and verification time. |

The versioned adapter is implemented, but current generic draft records are not automatically C-compatible. Export requires explicitly authored C stage seats/resource reuse, template public goals, complete variant rosters with per-slot equipment requirements, and a registered condition attribute type/unit/phase/loadout meaning. It rejects unsupported operators/subjects and ambiguous evidence or dependencies. B production signing/trust keys have not been provisioned.

### Expected repeatable commands

The fixture command is intentionally synthetic and uses only fixture identifiers/data. The final implementation will provide these commands (exact options are pinned here for reproducibility):

```powershell
$env:PYTHONPATH = '.\packages\starhelp-knowledge\src'
python -m starhelp_knowledge build-fixture-distribution --output-dir .\packages\starhelp-knowledge\artifacts --b-root ..\desktop-account --overwrite
python -m starhelp_knowledge verify-distribution --path .\packages\starhelp-knowledge\artifacts\knowledge-planner-fixture-v1.bpublic.json --trusted-public-key .\packages\starhelp-knowledge\artifacts\fixture-ed25519-public.pem --trusted-key-id starhelp-fixture-ed25519-v1 --supported-capability starhelp.knowledge-distribution.v1
```

Expected artifact set: signed B envelope, test-only Ed25519 public key, synthetic B snapshot, and `SHA256SUMS.txt`. Production export requires an external Ed25519 private-key path and a production trust configuration; the fixture key ID is never a production trust anchor. The final artifact record includes producer commit/package version, profile version, release and member/dependency closure, native/projected/B digest algorithms, artifact SHA-256 values, signature algorithm/key ID/use, fixture label, and independent verify command.

## Implemented package areas

The package currently provides SQLite migrations and tables for sources/policies/capability snapshots, entities and revisions, public records and immutable revisions, evidence, reviews, index releases, disabled references, audit events, command receipts, update runs, tasks, leases, and checkpoints. The service implements strict request validation, candidate creation, explicit review, release build/validation/activation/rollback, same-release complete template retrieval, deterministic public search, empty-result search triggering, and idempotent update-task recovery. The CLI exports validated release bundles and verifies them without a database; bundle verification checks member hashes, manifest hash, dependencies, and evidence closure.

### Not yet proven or delivered

- No genuine external source integration or full source coverage report has been verified beyond the research matrix above.
- No real game template, complete production alternative, or no-match content case has been curated, reviewed, or published. Synthetic tests do not substitute for those human content gates.
- No vector/semantic search or remote public-answer provider is active.
- No shared server has been provisioned; current CLI uses a local WSGI server and bearer-token hash configuration. TLS, deployment hardening, backups, monitoring and recovery drills remain deployment work.
- B and C interoperability has been exercised from their pinned commits using synthetic data. Production signing keys are not provisioned and the shared paths/schemas remain draft interfaces requiring coordination before production use.
- M6 identity management is file-provisioned for local operation; invite workflow, secure secret distribution, storage ACL review and server identity provider selection remain outstanding.

## Verification evidence

Verification run on 2026-10-15: `compileall` succeeded; `unittest discover` passed all 12 tests, including explicit release hash tampering and source-policy/capability binding rejection. Tests use `fixture:` identifiers and simulated curator/reviewer/publisher/admin principals. The test identities are not production identities; their approvals do not approve any real game content.

## Reference links

- [Bilibili user agreement](https://www.bilibili.com/blackboard/protocal/licence.html)
- [Bilibili Open Platform docs](https://open.bilibili.com/doc)
- [Nanoka community skill repository](https://github.com/Run2zZ/hsr-nanoka)
- [StarRailRes repository](https://github.com/Mar-7th/StarRailRes)
- [Enka API docs](https://github.com/EnkaNetwork/API-docs/blob/master/api.md)
