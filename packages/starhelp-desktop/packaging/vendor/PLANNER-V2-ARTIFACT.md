# Local producer v0.2 planner artifact pin

B keeps the historical C 0.4.0 wheel and v0.1 worker unchanged. The isolated v0.2 worker uses
the C 0.5.1 wheel delivered in C commit `97f14bd`.

- Artifact: `starhelp_planner-0.5.1-py3-none-any.whl`
- SHA-256: `c79ceb58e78d11cf947c0c9f7c5c862ccad8155886fab715a76f7d8977f98322`
- Component: `0.5.1`
- Adapter: `starhelp.producers.v0.2`
- Source commit: `9057a6a6e11c9497f053c0ba4ccd227d2ad26e0b`
- C artifact lock SHA-256: `aceb07b0b8bec677e2ccfc39ce6b1018662991dd22524c6340eb3995134f9121`

C 0.5.1 hard-disables production execution. B's source worker and candidate build pin this exact wheel;
the existing C 0.4.0 worker remains the separate synthetic S3 compatibility path. This pin and its
synthetic tests do not approve a production A/B/C tuple or enable production analysis.
