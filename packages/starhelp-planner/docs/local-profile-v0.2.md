# Local adapter proposal v0.2

Status: C-only implementation proposal for M0 review. This does not freeze or change `docs/contracts/mvp-v0.1.md`. No versioned A bundle, B snapshot specification, shared fixture, or agreed M0 contract was available as of 2026-10-16. Every `fixture:` identity and associated rule/value is fictional. Fixture approval flags exercise the code and do not record human approval.

## Versions and invocation

| Item | This implementation |
|---|---|
| Component / local rules | `0.2.0` |
| Shared draft schema / contract | `0.1-draft` |
| Request and bundle `adapter_profile` | `starhelp.local.v0.2` |
| Supported mandatory capability | `starhelp.local-profile.v0.2` |
| Canonical member integrity profile | `sha256-json-v1` |

```python
from starhelp_planner import ADAPTER_PROFILE, PLANNER_VERSION, analyze
from starhelp_planner.demo_data import synthetic_request

request = synthetic_request()  # fictional, already materialized objects
request["local_rule_version"] = PLANNER_VERSION  # optional exact pin
result = analyze(request)
```

The argument must contain built-in JSON objects/arrays/scalars; arbitrary Mapping implementations, callbacks, paths, connections, cycles and non-finite numbers are rejected. Limits are 100,000 JSON nodes and depth 48. The planner copies the validated input, performs no I/O, and returns JSON-compatible values. It never saves a report, changes equipment, calls a model, or verifies authorization against an external authority. B must check authorization again before accepting an asynchronous result.

v0.2 is incompatible with the old local 0.1.0 fixture profile: it requires explicit adapter selection, real member digests/dependencies, registered measurement semantics, and transition-based cultivation rules. Do not rename an older bundle to bypass validation. Unknown schemas/capabilities/rule versions return errors.

## Request, scope, and snapshot

`AnalysisRequest` has `contract_version`, `schema_id`, `schema_version`, a nonempty `request_id`, positive integer `authorization_generation`, `public_bundle`, `account_snapshot`, and `task`. Optional keys are `evaluation_time`, `local_rule_version`, `required_capabilities`, `latest_known_validity`, and `feedback`.

`task.scope` must match the selected stage and template in all six fields: `game_version`, `environment`, `mode_id`, `cycle_id`, `stage_id`, `stage_revision`. A stage's scope cannot contradict its own identity/revision. `task.public_goal` must exactly equal one of a template's `public_goals`; matching only the stage does not establish goal suitability.

`task.fixed_character_ids`, `excluded_character_ids`, and `locked_local_instance_ids` are unique arrays of IDs. `allow_rearrangement` is boolean and defaults to false. The planner never relaxes these constraints.

`AccountSnapshot` requires its schema, `profile_id`, `snapshot_id`, positive integer `snapshot_revision`, active authorization state, and the same authorization generation as the request. It has `characters` and `equipment_instances` arrays; `materials` and `loadout_views` are optional arrays. Duplicate character, equipment or material identities are rejected.

Characters use `{entity_id, ownership, fields}` with ownership `owned`, `not_owned`, or `unknown`. Only confirmed ownership enters available plans. Missing roles under incomplete roster coverage remain pending. Under explicit `coverage.roster: complete`, an absent role is rejected as absent from that supplied complete list. B owns the validity of any completeness claim.

Equipment uses local instance identity plus public type identity, `kind`, `slot`, `equipped_by`, `identity_state`, and optional fields. Supported identity states are `player_confirmed`, `source_verified`, `ambiguous`, `unconfirmed`, `unknown`. An ambiguous item can be examined on its current character; movement requires reliable identity. Type identity and attribute equality never establish item identity.

## Public bundle integrity and availability

All six arrays are mandatory, even when empty: `entities`, `stages`, `templates`, `variants`, `evidence`, `troubleshooting`. A bundle has one manifest/release and one revision for each stable identity within each kind. Manifest object schemas must explicitly declare all six supported draft schemas.

Each manifest member is `{kind, id, revision, content_hash, dependencies}`. `dependencies` is an explicit array of `{kind, id, revision}`. Members must equal the embedded object set: no duplicate, missing or orphaned entry. Dependencies must exist and include the dependencies actually referenced by the object.

`sha256-json-v1` is a local proposal: serialize the member object with Python `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`, encode UTF-8, hash with SHA-256 and prefix the lowercase hex digest with `sha256:`. Hashes cover the complete member object, excluding its manifest entry. This is not RFC 8785/JCS and is not claimed to match another language's serializer. Manifest authenticity, its metadata/attribute registry, distribution signatures, permissions, and whole-package verification remain the loader's responsibility. A caller can rehash a changed object; a matching digest alone does not establish trust or approval.

Typed reference fields include `evidence_refs`/`citations`, `entity_refs`/`enemy_refs`/`character_refs`, `stage_refs`, `template_refs`, `variant_refs`, and `troubleshooting_refs`. They use `{id, revision}`; the field supplies the kind, and the containing release supplies the release identity. Explicit nested release/schema/capability declarations are checked. Unknown reference fields fail closed. Character/type/material/subject-entity IDs and stage/template/variant links are also dependencies. Public objects cannot contain private snapshot/item/authorization/match identities.

Explicit object scopes and entity game-version/environment declarations must also fit the selected task; incompatible objects and their dependents cannot execute. Derived availability preserves the reference kind, even if an entity and template share the same ID.

Latest-known withdrawals may specify an ID (all revisions) or `{id, revision}`. Disabled/rejected/expired/withdrawn members and their dependent objects become unavailable, including evidence cited deep inside steps or costs. A template's `variant_ids` list describes alternatives: loss of one alternative does not revoke its siblings. Required dependencies still propagate unavailability. The result separates explicit withdrawals from the derived unavailable-object set. A disabled selected stage returns `withdrawn_public_object` with no executable plans.

## Complete variants and resources

Stages declare nonempty partitions and unique seats. This profile supports stage-wide `exclusive` character/equipment resource semantics; omitted rules default to exclusive. Other reuse semantics are rejected pending an agreed model.

Templates/variants require both `approval_status: approved` and `publication_status: published`. A variant supplies the exact complete partition/seat roster and all public character identities. Multiple independently approved substitutions never become a new combined roster. Slot equipment requirements use a supported kind (`light_cone`/`relic`), explicit slot, and optional public type or allowed types.

Current and rearrangement plans have separate result arrays. Rearrangement assigns unique local instances jointly across all partitions, preserves locks, accounts for displaced items, and enumerates at most 50,000 nodes / 256 completed assignments. Every examined mapping receives its own condition evaluation. Sorting considers soft failures, unknown conditions, evidence status, action count, then stable identities. It does not establish global optimality after truncation. If no examined mapping passes before the bound, the result remains pending with `allocation_search_incomplete`.

## Conditions, units, contexts, and loadouts

The manifest's `attribute_definitions` registers each attribute's `value_type` (`number`, `integer`, `string`, `boolean`, `array`), `unit`, allowed `phases`, and boolean `loadout_dependent`. This registry is supplied public metadata, not a claim that the planner knows a real game's combat formulas.

Each condition explicitly includes `condition_id`, `subject`, `attribute`, `operator`, `value`, `unit`, `measurement_context: {phase, assumptions: []}`, `requirement` (`hard`/`soft`), `evidence_status` (`confirmed`/`suggested`/`unknown`), and evidence references. Unsupported condition keys, attributes, subjects, units, phases or operand types cannot execute.

| Operator | Meaning |
|---|---|
| `eq`, `neq` | Typed equality/inequality; booleans are not numbers |
| `gt`, `gte`, `lt`, `lte` | Finite numeric comparison |
| `in` | Actual value equals an element of the expected array |
| `contains` | Array membership or string substring |

Variant subjects are `{kind: team_slot, slot_id}`, `{kind: character, character_id}`, or `{kind: equipment_slot, slot_id, equipment_kind, equipment_slot}`. Public conditions never contain local item identities. Troubleshooting may additionally inspect `feedback` and `task` fields.

A local field has `value`, explicit confirmed state, `unit` and `measurement_context`; optional source/timestamp/scope/validity metadata is retained. Unit conversion and inferred buffs are not implemented. Context objects must agree, treating assumptions as an unordered list. Missing/unconfirmed/conflicting/stale/wrong-unit/wrong-context values yield `unknown`, not zero or satisfaction. `user_reported` is accepted only for feedback. A supplied expiry requires caller-supplied `evaluation_time`; expired/future/invalid field times remain unknown. Without an expiry, B's explicit field state determines freshness; the planner does not invent a TTL.

Known false hard conditions reject a mapping. Unknown hard conditions/ownership remain pending. Soft issues appear in warnings and sorting. `evidence_status` stays separate from the computed `match_status`.

Moving or removing equipment invalidates original loadout-dependent character fields. Such a condition requires one exact `loadout_views` entry with `character_id`, `loadout_fingerprint`, and confirmed fields. The fingerprint is SHA-256 of compact UTF-8 JSON for the sorted list of `[kind, slot, local_instance_id]` tuples equipped by that character in the final mapping. Use `conditions.final_equipment` and `conditions.loadout_fingerprint` to reproduce the local convention. The planner does not simulate resulting stats. A missing/ambiguous view yields `loadout_changed_without_confirmed_panel`.

## Cultivation and inventory

Requirements specify an ID, category, subject, `current_field`, integer `target_value`, unit/context, priority/reason, evidence references, and optional `cost_rule`. Categories are `character`, `trace`, `light_cone`, `relic`; the first two use a character subject, the latter two an equipment-slot subject. Current/target progression must be nonnegative integers for a registered, loadout-independent integer attribute. Equipment progression uses the final assigned item and requires reliable identity.

A cost rule requires an ID/revision, evidence, matching category/subject public entity/attribute/unit, matching game version/environment, and a `transitions` array. Each transition is `{from: n, to: n+1, materials: [{material_id, amount}]}` with nonnegative integer quantities. Every edge from current to target must be covered exactly once; mismatched scope/entity, missing edges, invalid amounts and duplicate edges produce `not_calculated`. An `applicable: true` flag is insufficient. Tables are limited to 10,000 edges and requested increments. Zero gap costs zero.

Each step reports gross cost before inventory. `plan.cultivation_cost` aggregates all calculated steps before deducting inventory once. Repeated requirements for the same local subject/attribute are unsupported, preventing double charges. If any step is uncalculable, no aggregate total/net shortage is claimed. Valid gross costs remain available when material coverage is partial; `net_status` is `not_calculated` and shortages are null.

Net shortage requires complete material coverage and explicit nonnegative confirmed counts, with `unit: item_count` and context `{phase: inventory, assumptions: []}`. Conflicting/stale/missing/invalid counts are never zero-filled. Duplicate material records are an input conflict.

## Troubleshooting and results

Only reviewed/published, applicable, available declarative rules run. Triggers must all match; no unsupported feedback rule means `unable_to_determine`. Optional `applies_to_variant_ids` requires an exact source variant ID/revision in feedback. Supplied feedback scope must equal the current task scope. Suggested complete target variants pass the same roster, constraints, equipment, goal and condition checks as ordinary candidates. Unknown targets are labeled `confirmation_required`; infeasible targets are not suggested. Rules may instead request actual condition rechecks or display the computed cultivation gaps. Nothing is learned or persisted.

Success results identify the actual planner/rule/profile versions, request/snapshot/generation, public release/stage/template/variant revisions, scope/goal/constraints, current/rearrangement/pending plans, condition bases, cultivation, bounded troubleshooting, coverage and citation catalog. Pending plans retain `candidate_plan_kind`, reasons and any assessed allocation. Ranking is an adaptation order, never a clear probability. Rejected hard-condition candidates retain their gaps/evidence for explanation.

| Result or error | Caller meaning |
|---|---|
| `plans_available` | At least one available local plan |
| `confirmation_required` | Only pending candidates |
| `no_reviewed_template` | No applicable available reviewed template for this exact scope/goal; public stage material retained |
| `no_feasible_variant` | Reviewed candidates conflict with known constraints/conditions |
| `coverage_insufficient` | No executable candidate established |
| `invalid_payload`, `snapshot_conflict` | Invalid shapes, values or conflicting local identities |
| `unsupported_schema`, `unsupported_profile`, `unsupported_rule_version`, `unsupported_capability` | Explicit incompatibility |
| `invalid_public_bundle` | Integrity/membership/reference/schema/capability problem; inspect `error.details.issues` |
| `authorization_inactive`, `superseded_generation` | Reject this request/result generation |
| `scope_mismatch`, `withdrawn_public_object` | Selected stage/scope unavailable for execution |

Expected errors return `status: error`, `error: {code, message, retryable: false, details}` and empty plan/citation arrays. These are proposed local enums, not approved production error semantics.

## Remaining M0 and integration evidence

Real source permissions/coverage, stable identity mapping, actual mode/partition/goal semantics, attribute registry and field-state/freshness rules, reviewed production variants/evidence, cost tables, distribution integrity/authenticity and client result/error behavior remain external inputs. The synthetic tests establish behavior of this component only. Three-mode real fixed samples, release-current A packages, B artifact loading/black-box integration and complete MVP acceptance remain unverified.
