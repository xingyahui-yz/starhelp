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

    import onnxruntime
    import rapidocr
    from PIL import Image, ImageDraw, ImageFont

    from starhelp_desktop.imports import RapidOcrEngine

    if not Path(rapidocr.__file__).resolve().is_relative_to(internal):
        raise SystemExit("RapidOCR was not loaded from the frozen candidate")
    if not Path(onnxruntime.__file__).resolve().is_relative_to(internal):
        raise SystemExit("ONNX Runtime was not loaded from the frozen candidate")

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
        "rapidocr_module": str(Path(rapidocr.__file__).resolve()),
        "onnxruntime_module": str(Path(onnxruntime.__file__).resolve()),
        "recognized_text": recognized,
        "model_sha256": model_hashes,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
