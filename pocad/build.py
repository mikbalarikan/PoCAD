"""build: bir projenin model.py'sini yeni bir sürüm olarak kurar (agentcad'in `run`'ının yerine).

Kullanıcı kodu `pocad.build_runner` alt sürecinde, zaman sınırıyla ve kendi süreç
grubunda çalışır: zaman aşımında ve iş bitince grubun tamamı (modelin başlattığı
süreçler dahil) durdurulur. Çıktı borudan değil versions/vN/build.log dosyasından
okunur; böylece modelin açık bıraktığı bir süreç build'i bekletemez, büyük çıktı da
belleği doldurmaz.

Her çağrı, başarılı ya da başarısız, bir sürüm numarası alır ve versions/registry.json'a
yazılır: hazırlıkta ya da yürütmede ne olursa olsun satır kaydedilir. Aynı projede iki
build aynı anda çalışamaz (versions/.build.lock). Geometrinin geçersiz olması build
hatası değildir; ölçümler report.json'a girer ve kararı gate'ler verir.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pocad.build_runner import RUNNER_FILE
from pocad.project import Project, atomic_write

REPORT_SCHEMA = "pocad-report-v1"
LOG_CHARS = 20_000
LOG_KEEP_BYTES = 1_000_000            # build.log'un sonu bu kadar tutulur
OUTPUTS = ("output.step", "output.stl", "output.glb")
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
POSIX = os.name == "posix"


class BuildBusy(RuntimeError):
    """Aynı projede başka bir build sürüyor."""


def build(project: Project, label: str = "") -> dict:
    """model.py'yi kurar; registry satırını döndürür (n, label, status, error, duration_s …)."""
    with _lock(project):
        reg = project.registry()
        n, vdir = _allocate(project, reg.next_number())
        created = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        start = time.monotonic()
        error, log, out, model_sha = None, "", None, None
        try:
            model = vdir / "model.py"
            if not project.model.is_file():
                raise FileNotFoundError(f"model.py yok: {project.model}")
            shutil.copy2(project.model, model)
            model_sha = _sha256(model)
            error, log, out = _run(project, model, vdir, created)
        except Exception as exc:                      # hazırlık hatası da bir sürüm olarak kaydedilir
            error = error or f"build hazırlanamadı: {type(exc).__name__}: {exc}"
        duration = round(time.monotonic() - start, 3)
        status = "built" if error is None else "failed"
        if status == "failed":
            for f in OUTPUTS:
                (vdir / f).unlink(missing_ok=True)    # yarım kalmış çıktılar sürümde kalmaz

        report = {"schema": REPORT_SCHEMA, "n": n, "label": label, "status": status, "created": created,
                  "model_sha256": model_sha, "versions": _versions(),
                  "files": out["files"] if status == "built" else {},
                  "results": out["results"] if status == "built" else {},
                  "error": error, "log": log}
        atomic_write(vdir / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        entry = {"n": n, "label": label, "status": status, "created": created, "duration_s": duration,
                 "model_sha256": model_sha, "error": error}
        reg.record(entry)
        return entry


def _run(project: Project, model: Path, vdir: Path, created: str):
    """Çalıştırıcıyı başlatır; (hata ya da None, log kuyruğu, çalıştırıcı sonucu) döndürür."""
    config = {"timestamp": created[:-1], "project_root": str(project.root), "parent_pid": os.getpid(),
              "timeout_s": float(project.export["timeout_s"]),
              **{k: float(project.export[k]) for k in ("stl_tolerance", "stl_angular_tolerance")}}
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": os.pathsep.join(
        p for p in (str(PACKAGE_ROOT), os.environ.get("PYTHONPATH", "")) if p)}
    timeout = float(project.export["timeout_s"])
    logfile = vdir / "build.log"
    error = None
    with logfile.open("wb") as sink:
        # -P: proje dizini sys.path'in başına girmez (proje kökündeki bir json.py çalıştırıcıyı bozamaz);
        # çalıştırıcı proje kökünü sys.path'in sonuna ekler, yardımcı modüller yine içe aktarılır.
        proc = subprocess.Popen([sys.executable, "-P", "-m", "pocad.build_runner", str(model), str(vdir),
                                 json.dumps(config)], cwd=project.root, env=env, stdin=subprocess.DEVNULL,
                                stdout=sink, stderr=subprocess.STDOUT, start_new_session=POSIX,
                                creationflags=0 if POSIX else subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.wait()
            code = None
            error = f"zaman aşımı: model.py {project.export['timeout_s']} sn içinde bitmedi, süreç durduruldu"
        finally:
            _kill_group(proc)                         # modelin başlattığı ve bıraktığı süreçler
    log = _tail(logfile)

    runner = vdir / RUNNER_FILE
    out = None
    if runner.is_file():
        out = json.loads(runner.read_text(encoding="utf-8"))
        runner.unlink()
    if error is None:
        if out is None:
            error = f"build süreci sonuç yazmadan bitti ({_exit_reason(code)})"
        elif not out["ok"]:
            error = out["error"]
    return error, log, out


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        if POSIX:
            os.killpg(proc.pid, signal.SIGKILL)
        elif proc.poll() is None:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _exit_reason(code) -> str:
    if code is not None and code < 0:
        try:
            return f"sinyal {signal.Signals(-code).name}: Python yorumlayıcısı çöktü"
        except ValueError:
            return f"sinyal {-code}"
    return f"çıkış kodu {code}"


def _tail(logfile: Path) -> str:
    """build.log'un sonunu tutar (en fazla LOG_KEEP_BYTES) ve son LOG_CHARS karakteri döndürür."""
    size = logfile.stat().st_size
    with logfile.open("rb") as f:
        f.seek(max(0, size - LOG_KEEP_BYTES))
        data = f.read()
    if size > LOG_KEEP_BYTES:
        logfile.write_bytes(data)
    return data.decode("utf-8", "replace")[-LOG_CHARS:]


def _allocate(project: Project, from_registry: int) -> tuple[int, Path]:
    """Kayıtta da diskte de olmayan ilk numara; yarım kalmış bir vN klasörü numarayı kilitlemez."""
    project.versions_dir.mkdir(parents=True, exist_ok=True)
    on_disk = [int(p.name[1:]) for p in project.versions_dir.glob("v*") if p.name[1:].isdigit()]
    n = max([from_registry - 1, *on_disk]) + 1
    while True:
        vdir = project.version_dir(n)
        try:
            vdir.mkdir()
            return n, vdir
        except FileExistsError:
            n += 1


@contextmanager
def _lock(project: Project):
    path = project.versions_dir / ".build.lock"
    project.versions_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if _holder_alive(path):
                raise BuildBusy(f"bu projede başka bir build sürüyor ({path} var); bitmesini bekle") from None
            path.unlink(missing_ok=True)              # ölmüş bir build'den kalan kilit
    else:
        raise BuildBusy(f"build kilidi alınamadı: {path}")
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def _holder_alive(path: Path) -> bool:
    try:
        pid = int(path.read_text().strip() or "0")
        age = time.time() - path.stat().st_mtime
    except (OSError, ValueError):
        return True
    if pid <= 0:
        return age < 60                               # henüz yazılmakta olan kilit; eskiyse ölü
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _versions() -> dict:
    try:
        from pocad import _ocp
        return _ocp.versions()
    except Exception as exc:                          # sürüm bilgisi raporu bozmaz
        return {"error": f"{type(exc).__name__}: {exc}"}
