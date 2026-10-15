# Local planner handoff

Status: component 0.2.0 under the **proposed** `starhelp.local.v0.2` adapter profile. The shared `mvp-v0.1` contract is still `0.1-draft`. Local behavior has been checked with synthetic data; this is not real-game integration, human approval of guides, or MVP completion.

## Entry point and current artifact

- Package: `packages/starhelp-planner/`; import: `starhelp_planner`.
- API: `from starhelp_planner import analyze`; `analyze(request) -> dict`.
- Version constants: `PLANNER_VERSION == "0.2.0"`, `ADAPTER_PROFILE == "starhelp.local.v0.2"`.
- Current wheel: `packages/starhelp-planner/artifacts/starhelp_planner-0.2.0-py3-none-any.whl`.
- SHA-256: `b4071619fd3e74e6008e004769583dad3df61f460e07e0c162eba7ef380783ca`.
- Python 3.12+, no runtime dependencies. Install the exact wheel with `python -m pip install --no-index --no-deps <wheel-path>` or add this component's `src` to the caller's import path during development.
- The retained 0.1.0 wheel is historical. Its profile lacks the semantic/integrity corrections below; use the explicitly versioned 0.2.0 artifact for this handoff.
- Detailed JSON semantics, compatibility changes, examples and proposed error enums: [local-profile-v0.2.md](../../packages/starhelp-planner/docs/local-profile-v0.2.md).

`analyze` accepts only fully materialized built-in JSON values, validates before copying, and does not mutate inputs. It performs no network, GUI, filesystem/database access, model calls, telemetry, account persistence or game input. B owns reading, authorization, encryption, result-generation checks, display and explicit report save. The demo CLI prints synthetic JSON as a separate caller of this pure API.

## Corrections in 0.2.0

1. **Explicit compatibility.** Request and bundle must select `starhelp.local.v0.2`; the supported mandatory capability is `starhelp.local-profile.v0.2`. Old local 0.1.0 bundles are incompatible. Optional exact `local_rule_version` pins are checked, and results identify the actual implementation version. Shared schemas remain the unmodified `0.1-draft`.
2. **Integrity and dependencies.** Every member's canonical digest is recomputed; manifest membership must exactly match embedded objects. Typed references, explicit and inferred dependencies, nested required capabilities/schema/release declarations, duplicate identities and private identity fields are checked. `sha256-json-v1` is an explicit local proposal, not agreed cross-language canonicalization. B still owns authenticity and whole-package/manifest verification; matching a member hash does not establish trust or approval.
3. **Availability.** Latest-known withdrawals and disabled object statuses propagate through nested evidence and dependency links. Losing an alternative does not disable independent sibling variants merely through a template's alternatives list. A disabled selected stage cannot execute. No online validity check occurs.
4. **Scope and goal.** Object scopes and declared entity game-version/environment must fit the task; derived availability retains object kinds. Stage identity/revision must agree with its scope; request/template scope matches all six fields. `task.public_goal` must exactly match a declared template goal. Approval/publication and full partition/seat rosters remain mandatory. Independent substitutions are not composed into new rosters.
5. **Condition semantics.** Registered typed attributes, explicit units, phase and assumptions are checked. Missing/conflicting/stale/unconfirmed/wrong-unit/wrong-context data remains unknown. Public evidence state stays separate from local match state. Booleans cannot satisfy numeric predicates. Unsupported conditions cannot execute.
6. **Allocation-specific evaluation.** Every examined equipment mapping gets its own condition checks, including equipment-slot predicates. Original loadout-dependent character panels are invalid after moves/removals. A final-loadout fingerprint plus confirmed `loadout_views` fields can provide a new basis; no combat-stat simulator is implied. Otherwise the candidate remains pending. Search is bounded to 50,000 nodes / 256 assignments; truncated failure to find a passing mapping remains unknown rather than proving infeasibility.
7. **Cultivation.** Character/light-cone/trace/relic gaps use confirmed integer progression fields and final item identity. Revisioned scope/entity/attribute-bound transition tables cover the entire requested range. Static `applicable: true` costs are insufficient. Zero gap costs zero; stale/missing progression is never filled with zero. Per-step costs are gross; `plan.cultivation_cost` sums all steps and deducts each material inventory once. Incomplete/conflicting/stale material counts permit valid gross cost but no net shortage. Incomplete step costs produce no aggregate claim.
8. **Troubleshooting.** Reviewed, scope-bound declarative triggers retain their own results. Target complete variants are rechecked against this task's ownership, fixed/excluded roles, locks, equipment, goal and conditions. Infeasible targets are not suggested; unknown targets are explicitly pending. Optional source-variant applicability and supplied feedback scope are checked. No unsupported advice or learning is generated.

## Result and error semantics

Success results include request/profile/snapshot/generation references, actual planner/rule/profile versions, one release, public scope/goal/constraints, stage/template/variant revisions, current plans, rearrangement plans, pending candidates, rejected variants, condition bases, cultivation costs/gaps, tactics/mechanics/risks, troubleshooting, coverage/validity and a same-release citation catalog. Ranking is an adaptation order and never a win probability. Unsupported resource reuse semantics fail closed; this profile supports stage-wide exclusive character/item use only.

Expected errors return `status: "error"`, `{code, message, retryable: false, details}` and empty plan/citation arrays. Proposed codes include `invalid_payload`, `snapshot_conflict`, `invalid_public_bundle`, `unsupported_schema`, `unsupported_profile`, `unsupported_rule_version`, `unsupported_capability`, `authorization_inactive`, `superseded_generation`, `scope_mismatch`, and `withdrawn_public_object`. Inspect `invalid_public_bundle.error.details.issues` for integrity/dependency/reference/schema problems. These are not frozen A/B enums.

## Verification evidence

Verified locally on Python 3.12.14:

- `python -m compileall -q src tests` succeeded.
- `python -m unittest discover -s tests -p 'test_*.py' -v` passed **45 tests**. This is one suite, not a claim of 45 real game scenarios; several tests contain related subcases.
- The suite includes the original 24 synthetic scenarios plus measurement/loadout/allocation truncation, transition/range/version/quantity checks, all four cultivation categories and shared inventory deduction, tamper/missing/orphan/dependency/type checks, nested withdrawal, target eligibility, malformed/non-JSON input, deterministic results and input/result isolation.
- Built the wheel with local setuptools/wheel and `PIP_NO_INDEX=1`; installed it into a separate temporary target with `--no-index --no-deps`.
- Under Python isolated mode (`-I`), explicitly imported from that installed target, asserted the module path/version, and ran the same 45 tests successfully against the installed implementation.
- Ran the installed `starhelp_planner.demo` entry point, parsed its JSON and checked version `0.2.0`, status `plans_available`, and two current synthetic plans. This does not validate real sources, actual item IDs, human-approved content, B loading, or live accounts.

`tests/test_stdlib.py` wraps the original plain scenario functions. The other three unittest modules cover the new behavior. Semantic tests explicitly republish modified **synthetic** objects; integrity tests call the raw API without refreshing damaged hashes/dependencies. `refresh_fixture_members` refuses non-fixture releases and never changes approval flags. No pytest/Ruff installation or claimed lint run was needed for the standard-library suite.

## Local execution

From `packages/starhelp-planner/`:

```powershell
$env:PYTHONPATH = 'src;tests'
python -m unittest discover -s tests -p 'test_*.py' -v
python -m starhelp_planner.demo
```

Sample constructor: `starhelp_planner.demo_data.synthetic_request()`. All `fixture:` IDs/values and approval statuses are fictional. The source-level dependency guard checks for prohibited network/GUI/storage/game-input imports; the actual API remains in-memory. Build with `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist` and transfer/pin the resulting version and digest through the agreed handoff process.

## M0 and external dependencies

On 2026-10-16 the user confirmed that no versioned local artifacts exist for the common contract, A's public package or B's snapshot specification. This component therefore records a concrete proposal and cannot claim M0, M5/M6 or B black-box integration has passed.

Required inputs/evidence:

1. An agreed M0 contract/version and shared fixture, including accepted predicate/attribute registry, units/context, field-state/freshness/completeness and error semantics.
2. A versioned published A bundle with verified source permissions, real mode/cycle/stage/entity mappings, complete reviewed/published variants, evidence, dependencies, cost tables and revocation metadata.
3. A versioned B snapshot specification/artifact for ownership, field provenance/context/time, instance identity, locks/material coverage, and any confirmed final-loadout views.
4. Agreed manifest canonicalization/authenticity/verification ownership and supported capability negotiation.
5. Three-mode real fixed samples, release-current coverage, actual B component loading, and black-box acceptance evidence.

No other feature branch was merged, rebased or cherry-picked; no shared contract, root configuration, other component or main change is part of this handoff. The Goal remains incomplete while these integration requirements are unmet.
