"""build: bir projenin model.py'sini yeni bir sürüm olarak kurar (agentcad'in `run`'ının yerine).

Kullanıcı kodu `pocad.build_runner` alt sürecinde, zaman sınırıyla çalışır. Her çağrı,
başarılı ya da başarısız, bir sürüm numarası alır ve versions/registry.json'a yazılır.
Geometrinin geçersiz olması build hatası değildir; ölçümler report.json'a girer ve
kararı gate'ler verir.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pocad.build_runner import RUNNER_FILE
from pocad.core.step import file_sha256
from pocad.project import Project

REPORT_SCHEMA = "pocad-report-v1"
LOG_CHARS = 20_000
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _versions() -> dict:
    from pocad import _ocp
    return _ocp.versions()


def build(project: Project, label: str = "") -> dict:
    """model.py'yi kurar; registry satırını döndürür (n, label, status, error, duration_s …)."""
    reg = project.registry()
    n = reg.next_number()
    vdir = project.version_dir(n)
    vdir.mkdir(parents=True, exist_ok=False)
    created = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    model = vdir / "model.py"
    shutil.copy2(project.model, model)
    config = {"timestamp": created[:-1], **{k: project.export[k] for k in ("stl_tolerance",
                                                                             "stl_angular_tolerance")}}
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        p for p in (str(PACKAGE_ROOT), os.environ.get("PYTHONPATH", "")) if p)}

    start = time.monotonic()
    error, log = None, ""
    try:
        proc = subprocess.run([sys.executable, "-m", "pocad.build_runner", str(model), str(vdir),
                               json.dumps(config)], cwd=project.root, env=env, capture_output=True,
                              text=True, timeout=float(project.export["timeout_s"]))
        log = (proc.stdout + proc.stderr)[-LOG_CHARS:]
    except subprocess.TimeoutExpired as exc:
        log = _text(exc.stdout) + _text(exc.stderr)
        error = f"zaman aşımı: model.py {project.export['timeout_s']} sn içinde bitmedi, süreç durduruldu"
    duration = round(time.monotonic() - start, 3)

    runner = vdir / RUNNER_FILE
    out = json.loads(runner.read_text(encoding="utf-8")) if runner.is_file() else None
    runner.unlink(missing_ok=True)
    if error is None:
        if out is None:
            error = f"build süreci sonuç yazmadan bitti (çıkış kodu {proc.returncode})"
        elif not out["ok"]:
            error = out["error"]
    status = "built" if error is None else "failed"

    report = {"schema": REPORT_SCHEMA, "n": n, "label": label, "status": status, "created": created,
              "model_sha256": file_sha256(model), "versions": _versions(),
              "files": (out or {}).get("files", {}) if status == "built" else {},
              "results": (out or {}).get("results", {}) if status == "built" else {},
              "error": error, "log": log[-LOG_CHARS:]}
    (vdir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    entry = {"n": n, "label": label, "status": status, "created": created, "duration_s": duration,
             "model_sha256": report["model_sha256"], "error": error}
    reg.record(entry)
    return entry


def _text(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value
