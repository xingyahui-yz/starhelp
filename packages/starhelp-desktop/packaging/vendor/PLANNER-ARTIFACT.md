# Local planner artifact pin

This package vendors the local planner's black-box Python wheel, not its source tree.

- Artifact: `starhelp_planner-0.3.0-py3-none-any.whl`
- SHA-256: `f7b6c5c221e2491c9399ed76656945175961ac94188b11ad2fe4d4160d0aa0ca`
- Producer adapter: `starhelp.producers.v0.1`
- Native planner rules: `0.2.0`
- Built runtime source commit: `b87e963c195acb236918b579d76d74a2853cc623`
- Delivery commit in the planner worktree: `2cadb7c`

The build script verifies the digest and installs this exact wheel offline before freezing the
separate stdio worker. Its producer adapter currently has only synthetic producer acceptance. The
wheel must not be represented as production content or as full M0/MVP interoperability.
