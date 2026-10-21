# PyInstaller candidate build. Publisher signing is a separate release gate.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
ocr_datas, ocr_binaries, ocr_hiddenimports = collect_all("rapidocr")
runtime_datas, runtime_binaries, runtime_hiddenimports = collect_all("onnxruntime")
fixture_root = root / "tests" / "fixtures" / "producer-interop-s3"
demo_fixture_names = (
    "starhelp-interop-min-v0.1-s3.bpublic.json",
    "synthetic-b-snapshot-045965b.json",
    "equipment-type-table.json",
    "fixture-ed25519-public.pem",
)
demo_datas = [(str(fixture_root / name), "demo-fixtures") for name in demo_fixture_names]

a = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root / "src")],
    binaries=ocr_binaries + runtime_binaries,
    datas=ocr_datas + runtime_datas + demo_datas,
    hiddenimports=["PIL.Image", *ocr_hiddenimports, *runtime_hiddenimports],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    name="StarHelp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StarHelp",
)
