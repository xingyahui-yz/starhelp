# Local planner handoff

Status: first implementation of the `mvp-v0.1` engineering draft. It is a synthetic-fixture-verified local component, not a real-game data integration or a complete MVP. Contract names below describe the package's current draft adapter and still need M0 confirmation.

## Package and entry point

- Package: `packages/starhelp-planner/`, import name `starhelp_planner`.
- Built component artifact: `packages/starhelp-planner/artifacts/starhelp_planner-0.1.0-py3-none-any.whl`; SHA-256 `0ea7c5f1149ada42b4dae14729e1b34199bd1c2a4a6e6ef2fa814bcac5213267`.
- Public API: `from starhelp_planner import analyze`; call `analyze(request: Mapping[str, Any]) -> dict[str, Any]`.
- Runtime: Python 3.12+, standard library only. The package performs no network, GUI, filesystem, database, model, telemetry, or game-input operation. It does not mutate the request or persist account information.
- Synthetic sample: `starhelp_planner.demo_data.synthetic_request()`; run `python -m starhelp_planner.demo` from this package directory after setting `PYTHONPATH=src`.
- Caller owns reading/authorization/encryption, public-package authenticity/hash verification, current revocation state, and report persistence. The planner checks embedded member closure and references but does not claim to authenticate a package from `verified: true` or implement the not-yet-frozen hash canonicalization.

## Current draft input profile

The demo data is the executable profile. Every identifier prefixed `fixture:` and every associated value is synthetic, not a Star Rail ID, source record, or human-approved guide.

- `AnalysisRequest` contains `request_id`, matching integer `authorization_generation`, an active `account_snapshot`, one `public_bundle`, `task.scope`, constraints and optional `feedback`.
- `task.scope` must specify `game_version`, `environment`, `mode_id`, `cycle_id`, `stage_id`, and `stage_revision`; the selected stage and template must match all known scope fields exactly.
- Bundle manifest members use `{kind, id, revision, content_hash}`. Current code requires declared member identity and a nonempty hash field, checks that all embedded objects are listed, and checks internal references. M0 still needs to select canonicalization, hashing, signature/authenticity and download/verification ownership.
- Templates and variants are executable only when both `approval_status: "approved"` and `publication_status: "published"`. Each variant is a complete partition/slot roster. The planner never composes slots from different variants.
- Stage partition data uses `partitions: [{partition_id, slots: [{slot_id}]}]`; `resource_reuse` can declare `characters` and `equipment` as `exclusive` or another explicit mode. Current default is exclusive across the stage.
- Snapshot character ownership is `owned`, `not_owned`, or `unknown`; a missing character is treated as unknown unless roster coverage is complete. A hard unknown condition or unknown ownership is returned only under `pending_confirmation_candidates`. A confirmed not-owned character is rejected.
- Condition subjects currently support `team_slot`, `character`, `equipment_instance`, `feedback`, and `task`; operators currently allow `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, and `contains`. Field values count as known only with an explicit confirmed state. Hard unsatisfied conditions reject a variant; hard unknown conditions remain pending; soft issues are warnings and affect ordering. Evidence status is retained separately from local match status.
- Current equipment stays with its current character even if instance identity is ambiguous. Cross-character rearrangement requires a `player_confirmed` or `source_verified` local instance identity, unique assignment, user permission, and no lock conflict. This component proposes changes only; it never applies them.
- Cultivation cost is calculated only with a numeric current/target gap, an applicable revisioned cost rule, complete material coverage, and confirmed material counts. Otherwise it reports `not_calculated`; it does not synthesize a net shortage.
- Troubleshooting reads only reviewed/published declarative rules. A matching rule may point to another complete published variant, request rechecking conditions, or request reviewing cultivation gaps. Unsupported or untriggered cases return `unable_to_determine`; no learning occurs.

The exact condition vocabulary, units and measurement contexts, completeness semantics, production object schema, stage resource rules, error enums, and all real IDs are unconfirmed M0 items. Unknown schemas/capabilities fail closed. The current result's ranking counts known/unknown conditions, evidence status and equipment changes; it is only an adaptation order and never a win probability.

## Result and error envelope

Success results include planner and local-rule versions, request/profile/snapshot generation references, one public release and stage/template/variant revisions, current plans, separate rearrangement plans, pending candidates, rejected variants, bounded troubleshooting output, coverage, latest-known validity, and a citation catalog bound to the same release. Each plan includes the full approved team, condition evidence and match statuses, equipment assignments/actions, cultivation gaps/cost state, references and warnings.

Expected failures return `status: "error"` with `{code, message, retryable, details}` and empty plan arrays. Current codes include `invalid_payload`, `invalid_public_bundle`, `unsupported_schema`, `unsupported_capability`, `authorization_inactive`, `superseded_generation`, and `scope_mismatch`. No production error enum has been frozen.

## Validation evidence

Scenario assertions in `packages/starhelp-planner/tests/test_planner.py` cover a full synthetic template, condition satisfied/unsatisfied/unknown, typed comparisons, evidence-vs-match status, owned/not-owned/unknown and partially observed rosters, fixed characters, lock conflicts, ambiguous equipment identity, complete-vs-partial material coverage, reviewed and scope-bound troubleshooting, scope mismatch, missing manifest members, revision-bound withdrawals, absent citations, disallowing rearrangement, and a source-level guard against network/GUI/storage/game-input dependencies. `tests/test_stdlib.py` exposes the 23 scenarios to Python's standard `unittest` runner without installing test dependencies. Verified on Python 3.12.14: `compileall` succeeded and `python -m unittest discover -s tests -p test_stdlib.py -v` passed all 23 scenarios. The built wheel was installed into a temporary local target without network access and its `analyze` API returned the expected synthetic plan result.

The sample remains synthetic. No real source adapter, real public bundle, real IDs, user-approved variant, live account, cross-thread binary, or complete MVP behavior has been validated. M5/M6 and B black-box integration remain outstanding.

## Build and desktop consumption

No runtime dependencies are required. During development, add `packages/starhelp-planner/src` to the desktop process's import path or install the checked-in wheel. Package metadata is in `packages/starhelp-planner/pyproject.toml`; rebuild command from the package directory: `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist`. The desktop caller should pin a version, validate its own snapshot authorization generation, pass full materialized objects, and retain the result only after explicit user save.

## M0 items to resolve

1. Confirm source permissions, actual fields, coverage/freshness statuses, and stable public identity mapping for characters, modes, cycles and stages.
2. Freeze template approval/publication representation, complete team/partition rules, reference identities, and status behavior for revocation/withdrawal.
3. Freeze the finite condition predicate list, units, subject paths, measurement phase/buff assumptions, hard/soft requirements, field freshness/conflict semantics and evidence statuses.
4. Freeze local item identity states, locked-item semantics, stage-wide character/equipment reuse rules, and when incomplete inventory can support a current plan.
5. Freeze applicable cost-rule schemas and whether/materials coverage is sufficient to compute gross cost or net shortage.
6. Freeze manifest member canonicalization/hash/signature verification owner, required schemas/capabilities, and error/result enums with B and A.
7. Validate this adapter against the agreed shared fixture and a versioned package from A/B before claiming black-box integration.
