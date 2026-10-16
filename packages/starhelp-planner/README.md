# StarHelp local planner

`starhelp_planner.analyze(request) -> result` is a deterministic, pure local planning function. It consumes an already materialized public bundle and private snapshot. It performs no network, GUI, filesystem, database, game input, model, or telemetry operations.

## Producer adapter (round 2, in progress)

Component 0.3.0 adds the separate `analyze_producers` / `prepare_producer_request` API with profile `starhelp.producers.v0.1`. The native `analyze` API and its `PLANNER_VERSION == "0.2.0"` rules remain unchanged. See [the compatibility matrix](docs/producer-compatibility-v0.1.md) and [producer API](docs/producer-adapter-api-v0.1.md).

Original-byte hashes, producer commits/profiles and approval/publication provenance are checked before conversion. B's missing units/context/coverage are kept unknown; no identity trust is upgraded. Signed producer consumption uses the optional `producer-signature` extra and separately pinned test public keys; missing mathematical verification has no bypass. Native 0.2 analysis still needs only the standard library. A's final fixed producer delivery and installed-wheel positive interoperability remain pending.

## Contract status

The shared `mvp-v0.1` document remains an engineering draft. Package 0.2.0 implements the explicit `starhelp.local.v0.2` adapter proposal, described in [docs/local-profile-v0.2.md](docs/local-profile-v0.2.md). It is incompatible with the old local 0.1.0 profile and is not a frozen cross-thread API. Fixtures are synthetic and are not approved game data. M0 and real A/B integration remain outstanding.

The caller owns package authenticity and whole-package verification. The planner checks member digests under its explicit local canonicalization proposal, typed references/dependencies, releases, capabilities, scope/goal, and complete variants. Conditions check units/context and final equipment mappings. Version-bound progression tables supply gross costs; complete confirmed material counts additionally permit one aggregate inventory deduction. A truthy `verified` flag is never proof of integrity.

## Local development

```powershell
$env:PYTHONPATH = 'src;tests'
python -m unittest discover -s tests -p 'test_*.py' -v
python -m starhelp_planner.demo
```

The package can be built as a wheel with `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist`. No runtime dependencies are required. Pytest and Ruff are optional development tools; the scenario suite also runs with Python's standard library.
