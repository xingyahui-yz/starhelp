from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
planner_v2_dependencies = root / "build" / "planner-v2-deps"
sys.path.insert(0, str(planner_v2_dependencies))
planner_datas, planner_binaries, planner_hiddenimports = collect_all("starhelp_planner")
crypto_datas, crypto_binaries, crypto_hiddenimports = collect_all("cryptography")

a = Analysis(
    [str(root / "packaging" / "planner_v2_worker_entrypoint.py")],
    pathex=[str(root / "src"), str(planner_v2_dependencies)],
    binaries=planner_binaries + crypto_binaries,
    datas=planner_datas + crypto_datas,
    hiddenimports=[
        *planner_hiddenimports,
        *crypto_hiddenimports,
        "cryptography.hazmat.primitives.asymmetric.ed25519",
    ],
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
    name="StarHelpPlannerV2Worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=True,
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
    name="StarHelpPlannerV2Worker",
)
