"""Bir build'in alt süreci: model.py'yi çalıştırır, `result`'ı dışa aktarır ve ölçer.

kullanım (pocad.build çağırır): python -m pocad.build_runner MODEL VDIR CONFIG_JSON

Kullanıcı kodu bu süreçte çalışır; bir çökme ya da sonsuz döngü çağıran süreci
etkilemez. Sonuç VDIR/_runner.json'a yazılır; çağıran süreç onu report.json'a çevirir.
Bir ölçümün yapılamaması build hatası değildir: ölçüm INCONCLUSIVE döner (pocad.result).
"""
from __future__ import annotations

import json
import runpy
import sys
import traceback
from pathlib import Path

RUNNER_FILE = "_runner.json"
TRACE_CHARS = 4000


def _fail(vdir: Path, error: str) -> int:
    (vdir / RUNNER_FILE).write_text(json.dumps({"ok": False, "error": error}, ensure_ascii=False),
                                    encoding="utf-8")
    return 1


def _user_trace(model: Path) -> str:
    """Kullanıcının hatası: kendi çerçevelerimiz atılır, en fazla TRACE_CHARS karakter."""
    text = traceback.format_exc()
    marker = f'File "{model}"'
    if marker in text:
        text = "Traceback (most recent call last):\n  " + text[text.index(marker):]
    return text.replace(str(model), "model.py")[-TRACE_CHARS:]


def main(argv: list[str]) -> int:
    model, vdir, config = Path(argv[0]), Path(argv[1]), json.loads(argv[2])
    try:
        namespace = runpy.run_path(str(model), run_name="__pocad_model__")
    except SystemExit as exc:
        return _fail(vdir, f"model.py sys.exit({exc.code}) çağırdı; parçayı `result`'a atayıp bitmeli")
    except BaseException:
        return _fail(vdir, _user_trace(model))

    shape = namespace.get("result")
    if shape is None:
        return _fail(vdir, "model.py modül düzeyinde `result` değişkeni tanımlamadı (ya da None)")

    from build123d import export_gltf
    from OCP.TopoDS import TopoDS_Shape

    from pocad import core, measure
    from pocad.core.shapes import quiet, volume_mm3
    from pocad.result import Result, inconclusive

    if not isinstance(getattr(shape, "wrapped", shape), TopoDS_Shape):
        return _fail(vdir, f"model.py `result` bir build123d şekli olmalı, {type(shape).__name__} geldi")

    results: dict[str, dict] = {}

    def keep(found: dict[str, Result] | Result) -> None:
        for r in (found.values() if isinstance(found, dict) else [found]):
            results[r.name] = r.to_dict()

    files = {}
    try:
        step = core.write_step(shape, vdir / "output.step", timestamp=config["timestamp"])
        files["output.step"] = {"sha256": step.sha256, "size_bytes": step.size_bytes}
        stl = core.write_stl(shape, vdir / "output.stl", tolerance=config["stl_tolerance"],
                             angular_tolerance=config["stl_angular_tolerance"])
        files["output.stl"] = {"sha256": stl.sha256, "size_bytes": stl.size_bytes}
        with quiet():
            ok = export_gltf(shape, str(vdir / "output.glb"), binary=True,
                             linear_deflection=config["stl_tolerance"],
                             angular_deflection=config["stl_angular_tolerance"])
        if not ok or not (vdir / "output.glb").is_file():
            raise RuntimeError("GLB yazılamadı")
        files["output.glb"] = {"sha256": core.step.file_sha256(vdir / "output.glb"),
                               "size_bytes": (vdir / "output.glb").stat().st_size}
    except Exception as exc:
        return _fail(vdir, f"dışa aktarım başarısız: {type(exc).__name__}: {exc}")

    keep(core.validity(shape))
    keep(measure.envelope(shape))
    try:
        keep(Result("volume_mm3", volume_mm3(shape), "mm3"))
    except Exception as exc:
        keep(inconclusive("volume_mm3", "mm3", f"{type(exc).__name__}: {exc}"))
    keep(stl.checks["max_sagitta"])
    keep(core.compare_step(shape, vdir / "output.step"))

    (vdir / RUNNER_FILE).write_text(json.dumps({"ok": True, "files": files, "results": results},
                                               ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
