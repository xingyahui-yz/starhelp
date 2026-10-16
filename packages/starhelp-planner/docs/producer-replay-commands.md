# Reproduce the fixed producer replay

Run commands from `C:/Users/admin/Documents/ChatGPT/星铁/parallel/local-planner/packages/starhelp-planner` with a working Python 3.12+. All outputs stay in C's component. A/B source repositories are read only; no feature-branch merge, cherry-pick or rebase is used.

## Replay the checked-in producer outputs

`interop/a-b790a52/consumer-capture-locks.json` pins A commit `b790a52aea4fabdb362d35c37d9b511b737e1fe4`, profile, release and byte hashes. B is always `045965bce4fbc38a3baa79b594535c9dd983d776`. These are synthetic data and a test public key, not a production trust configuration.

The wheel's producer-signature extra declares the same crypto version range as B. The recorded verification environment uses cryptography 46.0.7, cffi 2.1.1 and pycparser 3.11. To reproduce it without changing A/B or the shared runtime:

```powershell
python -m pip install --target .tmp/interop-deps --only-binary=:all: cryptography==46.0.7 cffi==2.1.1 pycparser==3.11
$env:PYTHONPATH = '.tmp/interop-deps;src;tests'
python -m unittest discover -s tests -p 'test_*.py' -v
$TaskConsumerCommit = git rev-parse HEAD
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
python -m pip install --no-index --no-deps --target .tmp/replay-c dist/starhelp_planner-0.3.0-py3-none-any.whl
python -I -B tools/replay_distribution.py --capture-dir interop/a-b790a52 --b-cases interop/b-b790a52-cases --installed-root .tmp/replay-c --dependency-root .tmp/interop-deps --wheel dist/starhelp_planner-0.3.0-py3-none-any.whl --consumer-source-commit $TaskConsumerCommit --report interop/reports/reproduced-wheel-replay.json
```

Build from a clean source checkout and use a fresh installation directory. The tool verifies the actual module import path and compares every installed Python module against the specified wheel. Reports pin the wheel digest and producer input digests. It records failed and **not exercised** requirements separately. With the current A fixture, full technical acceptance is false: it has one mode and no equipment constraints.

The unchanged native 0.2 rules can be checked without the optional crypto dependency:

```powershell
$env:PYTHONPATH = 'src;tests'
python -m unittest test_stdlib test_semantics test_cultivation test_validation -v
python -m starhelp_planner.demo
```

## Regenerate with A's actual command

Use a temporary local checkout so A's exporter records the correct immutable Git HEAD. An archive under C's own checkout would otherwise let A's Git metadata lookup see C's HEAD. This temporary checkout is source-only; the original A checkout is not changed.

```powershell
git clone --local --no-hardlinks --no-checkout 'C:/Users/admin/Documents/ChatGPT/星铁/parallel/knowledge-backend' .tmp/producer-checkouts/a-b790a52
git -C .tmp/producer-checkouts/a-b790a52 checkout --detach b790a52aea4fabdb362d35c37d9b511b737e1fe4
python -I -B tools/capture_a_distribution.py --a-source .tmp/producer-checkouts/a-b790a52/packages/starhelp-knowledge --a-repository 'C:/Users/admin/Documents/ChatGPT/星铁/parallel/knowledge-backend' --a-commit b790a52aea4fabdb362d35c37d9b511b737e1fe4 --b-repository 'C:/Users/admin/Documents/ChatGPT/星铁/parallel/desktop-account' --dependency-root .tmp/interop-deps --output .tmp/reproduced-a-b790a52
```

The capture tool compares every producer source file against the fixed Git objects, invokes A's own `build-fixture-distribution` and `verify-distribution`, checks the output's producer commit, then checks the source files again. It refuses to overwrite existing captures. The recorded repeat produced byte-identical A bundle, public key and B snapshot; see `interop/reports/a-b790a52-determinism.json`.

## Re-run B's actual verifier

Extract B's fixed source to a new temporary location under C, then invoke its actual verifier:

```powershell
python -I -B tools/extract_fixed_source.py --repository 'C:/Users/admin/Documents/ChatGPT/星铁/parallel/desktop-account' --commit 045965bce4fbc38a3baa79b594535c9dd983d776 --package-subdir packages/starhelp-desktop --destination .tmp/reproduced-b-045965b
python -I -B tools/verify_with_fixed_b.py --b-source .tmp/reproduced-b-045965b/packages/starhelp-desktop --b-repository 'C:/Users/admin/Documents/ChatGPT/星铁/parallel/desktop-account' --bundle interop/a-b790a52/knowledge-planner-fixture-v1.bpublic.json --expected-sha256 145b50b64660dd3c51b23590aba9079e5bf9ccf1557ad7e4b141a9318f6baa00 --expected-release rel_fixture_0001 --public-key interop/a-b790a52/fixture-ed25519-public.pem --key-id starhelp-fixture-ed25519-v1 --dependency-root .tmp/interop-deps --report interop/reports/reproduced-b-verification.json
```

This loads the actual B `BundleValidator` and `Ed25519Keyring` from fixed source. It does not instantiate B's cache, private store, repository, GUI or account source. No always-true verifier is used. A's old unsigned baseline is separately recorded as rejected by B.

## Remaining producer sample requirements

The current replay cannot prove equipment locks or ambiguous-instance allocation when the public producer supplies no equipment requirement at all. A needs to export public equipment types and complete approved variants with explicit kind/slot/type requirements, including an assignment that requires moving an actual B-serialized instance between known characters. Three distinct synthetic mode datasets, each with a main, complete alternative and no-match case, are also still required. C must consume those as a new explicitly pinned delivery; it must not edit the current public payload to manufacture coverage.
