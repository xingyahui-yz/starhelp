from __future__ import annotations

import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path


def main() -> int:
    package_root = Path(__file__).resolve().parents[1]
    candidate = package_root / "dist" / "StarHelp"
    internal = candidate / "_internal"
    source = package_root / "src"
    if not (candidate / "StarHelp.exe").is_file() or not internal.is_dir():
        raise SystemExit("built StarHelp candidate is missing; build it before the OCR smoke")

    sys.path.insert(0, str(internal))
    sys.path.insert(1, str(source))

    import numpy
    import cv2
    import onnxruntime
    import rapidocr
    from PIL import Image, ImageDraw, ImageFont
    from PyInstaller.archive.readers import pkg_archive_contents

    from starhelp_desktop.imports import RapidOcrEngine

    runtime_modules = {
        "RapidOCR": rapidocr.__file__,
        "ONNX Runtime": onnxruntime.__file__,
        "OpenCV": cv2.__file__,
    }
    for name, module_path in runtime_modules.items():
        if not Path(module_path).resolve().is_relative_to(internal):
            raise SystemExit(f"{name} was not loaded from the frozen candidate: {module_path}")

    archived_modules = set(pkg_archive_contents(candidate / "StarHelp.exe"))
    required_archived_modules = {
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
        "numpy",
        "starhelp_desktop.imports",
    }
    missing_archived_modules = required_archived_modules - archived_modules
    if missing_archived_modules:
        raise SystemExit(
            "frozen executable archive is missing expected Pillow/app modules: "
            f"{sorted(missing_archived_modules)!r}"
        )

    for name, pattern in (("NumPy", "numpy/**/*.pyd"), ("OpenCV", "cv2/**/*.pyd")):
        if not any(internal.glob(pattern)):
            raise SystemExit(f"candidate native {name} extension is missing from _internal")

    model_root = Path(rapidocr.__file__).resolve().parent / "models"
    model_names = (
        "PP-OCRv6_det_small.onnx",
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "PP-OCRv6_rec_small.onnx",
    )
    model_hashes: dict[str, str] = {}
    for name in model_names:
        model_path = model_root / name
        if not model_path.is_file():
            raise SystemExit(f"candidate OCR model is missing: {name}")
        model_hashes[name] = hashlib.sha256(model_path.read_bytes()).hexdigest()

    image = Image.new("RGB", (900, 160), "white")
    ImageDraw.Draw(image).text(
        (40, 40), "LEVEL 80", fill="black", font=ImageFont.load_default(size=64)
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    draft = RapidOcrEngine().recognize(buffer.getvalue())
    recognized = [line.text for line in draft.lines]
    if not any("LEVEL 80" in text.upper() for text in recognized):
        raise SystemExit(f"candidate OCR did not recognize synthetic text: {recognized!r}")

    print(json.dumps({
        "candidate": str(candidate),
        "runtime_modules": {
            name: str(Path(path).resolve()) for name, path in runtime_modules.items()
        },
        "archived_modules": sorted(required_archived_modules),
        "build_environment_modules": {
            "NumPy": str(Path(numpy.__file__).resolve()),
            "Pillow": str(Path(Image.__file__).resolve()),
        },
        "recognized_text": recognized,
        "model_sha256": model_hashes,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
