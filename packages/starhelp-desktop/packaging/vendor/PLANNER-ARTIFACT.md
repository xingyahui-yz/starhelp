# Local planner artifact pin

B vendors the local planner's black-box Python wheel and does not import its source tree.

- Active artifact: `starhelp_planner-0.4.0-py3-none-any.whl`
- Active SHA-256: `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2`
- Component version: `0.4.0`
- Producer adapter: `starhelp.producers.v0.1`
- Native planner rules: `0.2.0`
- Source commit: `f627590468154cc8622dad8647fefe9f6fd3c4ee`
- Artifact/report delivery commit: `8208c6c8611d6b7e471ed93816c7cf025b134331`
- C lock file: `starhelp_planner-0.4.0.lock.json`, SHA-256
  `f18a85dbb1258d76917e14566b8be0ed3f7e9e61adbc953d25e301e7603297d5`

The wheel implements the frozen synthetic S3 tuple: A producer `dcb1e3ee220b85229bedc6c79d72ebe495825f37`,
release `rel_fixture_s3_0001`, and B1 snapshot producer `103741e02c90ac672017f783058bdd8dacae982e` /
`starhelp.desktop.snapshot.interop-min.v0.1`. C reports 88 isolated installed-wheel tests passed,
204 S3 installed replay checks passed, and 78 legacy-A measurement checks passed. These are synthetic
integration results; C's report still marks full three-party acceptance false and leaves positive
complete material calculations and final-loadout calculations open. The B2 bridge and packaged
candidate must be verified separately before describing the desktop integration as accepted.

`starhelp_planner-0.3.0-py3-none-any.whl` remains in this directory as a historical artifact. The
build script and worker select only the 0.4.0 wheel above, verify its exact digest, and install it
offline before freezing the separate stdio worker.
