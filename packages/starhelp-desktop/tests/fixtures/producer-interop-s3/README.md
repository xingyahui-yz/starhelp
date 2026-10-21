# Producer interop S3 fixture

These files are immutable synthetic inputs for the B2 producer bridge and desktop demo.
They do not contain a real account, production trust configuration, or real game mapping.

- A producer source commit: `dcb1e3ee220b85229bedc6c79d72ebe495825f37`
- A format profile: `starhelp.b-publicbundle-envelope.v1`
- B snapshot serializer commit: `103741e02c90ac672017f783058bdd8dacae982e`
- B snapshot format profile: `starhelp.desktop.snapshot.interop-min.v0.1`
- Signed fixture release: `rel_fixture_s3_0001`
- Bundle: `starhelp-interop-min-v0.1-s3.bpublic.json`
- Synthetic snapshot: `synthetic-b-snapshot-045965b.json`
- Equipment table: `equipment-type-table.json`
- Test-only Ed25519 public key: `fixture-ed25519-public.pem`

`SHA256SUMS.txt` records the producer-published checksums. B also pins each fixture digest in
`src/starhelp_desktop/synthetic_demo.py` and checks them before use. The fixed profile and
test-only key must never be used for production data or trust decisions.

The demo selects a public task with `allow_rearrangement=true` so the captured synthetic
snapshot can produce plans. This choice is shown in the demo confirmation and progress text.
