# Producer compatibility matrix — round 2

Status: in progress, 2026-10-16. This proposal does not change the shared contract. Technical interoperability uses synthetic producer outputs; it does not establish production content approval or complete the old M0/MVP Goal.

## Fixed baselines

| Producer | Commit | Scope |
|---|---|---|
| A knowledge backend | `313508f895cb422d4a309743eb7f8b99f45a7a91` | Inspect and exercise the actual export entry point; retain baseline rejection evidence |
| B desktop serializer | `045965bce4fbc38a3baa79b594535c9dd983d776` | Generate synthetic snapshots through `profiles._snapshot_to_dict`; no store/repository/account operations |
| C native planner | `3133eda8ce571e4a58d217e52e28d6e3d3aa6bff` / wheel `0.2.0` | Preserve the native `analyze` entry and `starhelp.local.v0.2` semantics |

B's working HEAD has advanced; it is not used. Producer sources are read from the specified Git commit and executed only from a temporary copy inside C. A's final positive export will be locked separately after delivery, with its actual commit/profile/release/raw byte SHA-256. Developing A versions cannot be mixed into one acceptance result.

## Current semantic matrix

| Area | A baseline / B fixed output | Consumer policy |
|---|---|---|
| Envelope | A `records[kind]` + record `payload`; no C adapter profile | Identify an explicit producer profile; never relabel as native C input |
| Integrity | A hashes record material and the release content body; evidence is separate from manifest members | Verify original hashes/closure first; preserve raw hashes separately from internal normalized hashes |
| Approval | A publication enforces approved records, but baseline export lacks a complete digest-bound review/publication provenance view | Baseline cannot establish the required executable approval provenance; reject consumption rather than add flags |
| Stage | Baseline sample partitions are names without required seat declarations | Do not infer required seats from whichever variant happens to be present |
| Goal / attributes | Baseline sample lacks exact goal declarations and a typed attribute registry | Reject executable conversion until the producer explicitly supplies these semantics |
| Predicates | A `ne`, `not_in`; C `neq`, `in`, `contains` | `ne` can map to typed `neq`; `not_in` is not `contains` and requires an explicit supported representation or rejection |
| B ownership | Exact `owned` / `not_owned` / `unknown` values | Preserve states; absent entries remain unknown under partial coverage |
| B fields | Flat paths, status, source, timestamps, string scope; no independent unit/context fields | Preserve raw provenance. Missing units/context remain unknown; do not infer buffs, units or battle phase from numeric values |
| B equipment | UUID instance, public type, raw slot, owner, identity; kind not serialized | Only derive kind from a resolved same-release public type; preserve raw slot. Unknown type/slot semantics cannot be assigned |
| Identity | B `player_confirmed`, `source_confirmed`, `ambiguous`, `unconfirmed` | `player_confirmed` retains meaning. Do not upgrade `source_confirmed` to C `source_verified`; keep uncertain until a versioned mapping establishes equivalence |
| B coverage | Set of observed field paths | Never promote observed paths to complete roster/inventory/material coverage |
| Authorization | Not serialized in B snapshot | Require separate explicit caller authorization context matching profile/generation; no implicit active/default generation |
| Revision | B permits zero; C native requires positive snapshot revisions | Preserve revisions; reject zero where native semantics cannot represent it, never add one |
| Distribution | B requires signed manifest, dictionary members/objects and a pinned verifier | B owns signature trust. A native export is not a B signed envelope; internal hashes are not signatures |

## Producer requirements for final positive replay

A must deliver one versioned export profile with required stage seats/resources, exact public goals, full reviewed variants, finite conditions/attribute definitions, revisioned evidence, and original digest-bound approval/publication provenance. Public equipment kind/type/slot semantics must be explicit if equipment is required. Existing B scalar fields cannot establish statistical conditions with missing units/context; those cases must remain pending. A structurally valid condition-free complete variant can exercise ownership/equipment interoperability without inventing panel metadata.

The final report must pin actual producer outputs and exercise normal/complete-alternative/no-match, locks, missing fields, ambiguous instances, cross-release references, tampering and withdrawal using the installed C wheel. Pending or refused cases are reported as such. Producer output files are never edited to add approvals/units or repair a deliberately damaged hash.
