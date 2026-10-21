# StarHelp local planner

`starhelp_planner.analyze(request) -> result` is a deterministic, pure local planning function. It consumes an already materialized public bundle and private snapshot. It performs no network, GUI, filesystem, database, game input, model, or telemetry operations.

## Producer adapter (S3 implementation in progress)

Component 0.4.0 is under development for the frozen `starhelp.interop-min.v0.1` technical scope. It retains `starhelp.producers.v0.1`, native `starhelp.local.v0.2` and `PLANNER_VERSION == "0.2.0"`, with scope/equipment shape validation corrections and an explicitly pinned B1 producer tuple. The published wheel remains 0.3.0 until the new A delivery and final installed-wheel replay are locked. See [S3 implementation evidence](docs/interop-s3-evidence.md), [the compatibility matrix](docs/producer-compatibility-v0.1.md) and [producer API](docs/producer-adapter-api-v0.1.md).

Original-byte hashes, producer commits/profiles and approval/publication provenance are checked before conversion. B's missing units/context/coverage are kept unknown; no identity trust is upgraded. Signed producer consumption uses the optional `producer-signature` extra and separately pinned test public keys; missing mathematical verification has no bypass. Native analysis still needs only the standard library. New A code `dcb1e3e` / package 0.3.0 / artifact `4610573e` and actual B1 `103741e` are explicitly supported; the old `00d4a58` and `b790a52` inputs remain independent regressions. Source verification covers three synthetic modes and nontrivial equipment constraints; installed-wheel/B2 evidence is recorded separately.

## Contract status

The shared `mvp-v0.1` document remains an engineering draft. The limited `starhelp.interop-min.v0.1` technical scope was frozen on 2026-10-21; this does not complete M0. The native profile is described in [docs/local-profile-v0.2.md](docs/local-profile-v0.2.md), with S3 validation corrections documented separately. Fixtures are synthetic and are not approved game data. Real source/content review and production trust remain outstanding.

The caller owns package authenticity and whole-package verification. The planner checks member digests under its explicit local canonicalization proposal, typed references/dependencies, releases, capabilities, scope/goal, and complete variants. Conditions check units/context and final equipment mappings. Version-bound progression tables supply gross costs; complete confirmed material counts additionally permit one aggregate inventory deduction. A truthy `verified` flag is never proof of integrity.

## Local development

```powershell
$env:PYTHONPATH = 'src;tests'
python -m unittest discover -s tests -p 'test_*.py' -v
python -m starhelp_planner.demo
```

The package can be built as a wheel with `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist`. No runtime dependencies are required. Pytest and Ruff are optional development tools; the scenario suite also runs with Python's standard library.
