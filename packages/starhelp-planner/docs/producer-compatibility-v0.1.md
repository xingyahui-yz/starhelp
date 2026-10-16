# Producer compatibility matrix — round 2

Status: first fixed producer delivery consumed, partial acceptance, 2026-10-16. This proposal does not change the shared contract. Technical interoperability uses synthetic producer outputs; it does not establish production content approval or complete the old M0/MVP Goal.

## Fixed baselines

| Producer | Commit | Scope |
|---|---|---|
| A knowledge backend | `313508f895cb422d4a309743eb7f8b99f45a7a91` | Inspect and exercise the actual export entry point; retain baseline rejection evidence |
| B desktop serializer | `045965bce4fbc38a3baa79b594535c9dd983d776` | Generate synthetic snapshots through `profiles._snapshot_to_dict`; no store/repository/account operations |
| C native planner | `3133eda8ce571e4a58d217e52e28d6e3d3aa6bff` / wheel `0.2.0` | Preserve the native `analyze` entry and `starhelp.local.v0.2` semantics |

B's working HEAD has advanced; it is not used. Producer sources are read from the specified Git commit and executed only from a temporary copy inside C. A's first new positive export is locked separately below, with its actual commit/profile/release/raw byte SHA-256. Developing A versions cannot be mixed into one acceptance result.

## Accepted first delivery (kept separate from the baseline)

| Item | Fixed value |
|---|---|
| A executing code commit / package | `b790a52aea4fabdb362d35c37d9b511b737e1fe4` / `0.2.0` |
| A profile | `starhelp.b-publicbundle-envelope.v1` |
| Release | `rel_fixture_0001` |
| Original raw A SHA-256 | `145b50b64660dd3c51b23590aba9079e5bf9ccf1557ad7e4b141a9318f6baa00` |
| A native content digest | `e34461116bb66071262067a3804acf66652b1907c840a9eb21bb303304086f85` |
| Original projected manifest digest | `ea436574636cb9094c4e7e53ed1bd75e2e6aa8900ae8bc4f33f995b5a5cc28d8` |
| B serialized snapshot SHA-256 | `a0c9fd982bd78e11e2ead2460b08b4ed13b4cb52afbe7f9274a6ecd35bd0cbd5` |
| Test signing identity | `starhelp-fixture-ed25519-v1`, Ed25519, synthetic purpose only |

The actual producer command was invoked from a detached temporary checkout of that commit. A's own verifier accepted the result; the fixed B `BundleValidator` with its real `Ed25519Keyring` also accepted it. Repeating the actual producer command produced byte-identical bundle, public key and B snapshot. No artifact from another A development revision is used in this acceptance set.

Current producer data has one mode (`fixture:mode:duo`), two complete reviewed variants, one soft statistical condition per variant, and no equipment requirements or equipment entities. Missing fields/units remain unknown warnings, not satisfied conditions. This supports normal/complete-alternate/no-match and refusal/degradation checks. It does **not** establish three-mode coverage or nontrivial equipment-lock/ambiguity interoperability. Those remain explicit acceptance gaps requiring additional A-produced fixtures.

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
