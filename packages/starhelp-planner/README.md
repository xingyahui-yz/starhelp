# StarHelp local planner

`starhelp_planner.analyze(request) -> result` is a deterministic, pure local planning function. It consumes an already materialized public bundle and private snapshot. It performs no network, GUI, filesystem, database, game input, model, or telemetry operations.

## Contract status

The shared `mvp-v0.1` document is an engineering draft. This package currently implements a documented adapter profile for that draft, not a frozen cross-thread API. Stable JSON keys used by this profile are described in `docs/handoffs/local-planner.md`; source identifiers, actual game IDs, condition vocabularies/units, package hash canonicalization, and transport/error enums remain M0 decisions. Fixtures are synthetic and are not approved game data.

The caller (desktop/package loader) is responsible for package authenticity and content-hash verification. The planner independently checks bundle release consistency, object references, required capabilities it understands, stage applicability, and that embedded objects are internally complete. A truthy `verified` flag is never treated as proof of integrity.

## Local development

```powershell
$env:PYTHONPATH = 'src;tests'
python -m unittest discover -s tests -p 'test_stdlib.py' -v
python -m starhelp_planner.demo
```

The package can be built as a wheel with `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist`. No runtime dependencies are required. Pytest and Ruff are optional development tools; the scenario suite also runs with Python's standard library.
