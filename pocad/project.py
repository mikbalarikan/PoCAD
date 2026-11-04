"""PoCAD proje dizini: pocad.toml, SPEC.md, model.py ve sürüm kaydı (agentcad'in yerine).

Yalnız standart kütüphane; CAD çekirdeği gerektirmez. Dizin düzeni tasarım belgesinin
§4'ündedir (docs/tasarim/2026-11-04-pocad-cekirdek-mcp.md).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROCESSES = ("fdm",)                     # Aşama 1 (karar S-2); diğer süreçler sonra
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
REGISTRY_SCHEMA = "pocad-registry-v1"
DEFAULT_EXPORT = {"stl_tolerance": 0.01, "stl_angular_tolerance": 0.1, "timeout_s": 600}

TOML_TEMPLATE = """name = "{name}"
process = "{process}"          # Aşama 1: yalnız fdm
machine = "{machine}"             # boşsa tabla gate'i varsayımla geçer (A-##)

[export]
stl_tolerance = 0.01     # mm, mutlak
stl_angular_tolerance = 0.1  # rad
timeout_s = 600
"""

SPEC_TEMPLATE = """# {name}: şartname

## Gereksinimler

## Varsayım defteri
| ID | Varsayım | Kaynak | Durum |
|---|---|---|---|

## Gate tablosu
| ID | Gereksinim | Ölçüm | Sınır | Durum |
|---|---|---|---|---|
"""

MODEL_TEMPLATE = '''"""{name}: parametrik model. Parçayı modül düzeyinde `result` değişkenine ata.

Build bu dosyanın versions/vN/ altındaki kopyasını proje kökünde çalıştırır: dosyalara
göreli yolla eriş (Path("olculer.csv")), `__file__`'a değil.
"""
from build123d import Box

result = Box(20, 10, 5)
'''


@dataclass(frozen=True)
class Project:
    root: Path
    name: str
    process: str
    machine: str
    export: dict = field(default_factory=dict)

    @property
    def model(self) -> Path:
        return self.root / "model.py"

    @property
    def versions_dir(self) -> Path:
        return self.root / "versions"

    def version_dir(self, n: int) -> Path:
        return self.versions_dir / f"v{int(n)}"

    def registry(self) -> Registry:
        return Registry(self.versions_dir / "registry.json")


def init(path: Path | str, *, name: str, process: str = "fdm", machine: str = "") -> Project:
    """Yeni bir proje dizini kurar. Var olan bir projenin üstüne yazmaz."""
    if not NAME_RE.match(name or ""):
        raise ValueError(f"proje adı harf, rakam, '-' ve '_' içerebilir (en fazla 64), {name!r} değil")
    if process not in PROCESSES:
        raise ValueError(f"süreç şimdilik yalnız {', '.join(PROCESSES)}, {process!r} değil")
    root = Path(path)
    if (root / "pocad.toml").exists():
        raise FileExistsError(f"proje zaten var: {root}")
    (root / "versions").mkdir(parents=True, exist_ok=True)
    (root / ".chat").mkdir(exist_ok=True)
    (root / "pocad.toml").write_text(TOML_TEMPLATE.format(name=name, process=process, machine=machine),
                                     encoding="utf-8")
    for fname, text in (("SPEC.md", SPEC_TEMPLATE), ("model.py", MODEL_TEMPLATE)):
        if not (root / fname).exists():
            (root / fname).write_text(text.format(name=name), encoding="utf-8")
    for f in ("inbox.jsonl", "outbox.jsonl"):
        (root / ".chat" / f).touch()
    reg = Registry(root / "versions" / "registry.json")
    if not reg.path.exists():
        reg._write([])
    return open_project(root)


def open_project(path: Path | str) -> Project:
    """Var olan bir projeyi pocad.toml'dan okur ve değerlerini doğrular."""
    root = Path(path).resolve()
    toml = root / "pocad.toml"
    if not toml.is_file():
        raise FileNotFoundError(f"pocad.toml yok: {root} bir PoCAD projesi değil")
    try:
        data = tomllib.loads(toml.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{toml}: TOML okunamadı ({exc})") from exc
    name, process = data.get("name", root.name), data.get("process", "fdm")
    machine, export = data.get("machine", ""), data.get("export", {})
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValueError(f"{toml}: name harf, rakam, '-' ve '_' içerebilir, {name!r} değil")
    if process not in PROCESSES:
        raise ValueError(f"{toml}: process şimdilik yalnız {', '.join(PROCESSES)}, {process!r} değil")
    if not isinstance(machine, str):
        raise ValueError(f"{toml}: machine bir metin olmalı, {machine!r} değil")
    if not isinstance(export, dict):
        raise ValueError(f"{toml}: [export] bir tablo olmalı")
    export = {**DEFAULT_EXPORT, **export}
    for key in DEFAULT_EXPORT:
        value = export[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
            raise ValueError(f"{toml}: export.{key} pozitif bir sayı olmalı, {value!r} değil")
    return Project(root=root, name=name, process=process, machine=machine, export=export)


class Registry:
    """versions/registry.json: her build bir satır; dosya her yazımda atomik değişir."""

    def __init__(self, path: Path):
        self.path = path

    def versions(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"{self.path}: sürüm kaydı okunamadı ({exc})") from exc
        if not isinstance(data, dict) or data.get("schema") != REGISTRY_SCHEMA:
            found = data.get("schema") if isinstance(data, dict) else type(data).__name__
            raise ValueError(f"{self.path}: şema {found!r}, beklenen {REGISTRY_SCHEMA}")
        versions = data.get("versions")
        if not isinstance(versions, list) or not all(isinstance(v, dict) and isinstance(v.get("n"), int)
                                                     for v in versions):
            raise ValueError(f"{self.path}: 'versions' her satırı numaralı (n) bir liste olmalı")
        return versions

    def next_number(self) -> int:
        return max((v["n"] for v in self.versions()), default=0) + 1

    def latest_built(self) -> dict | None:
        built = [v for v in self.versions() if v.get("status") == "built"]
        return built[-1] if built else None

    def record(self, entry: dict) -> None:
        versions = self.versions()
        if any(v["n"] == entry["n"] for v in versions):
            raise ValueError(f"v{entry['n']} zaten kayıtlı")
        self._write(versions + [entry])

    def _write(self, versions: list[dict]) -> None:
        text = json.dumps({"schema": REGISTRY_SCHEMA, "versions": versions}, ensure_ascii=False, indent=2)
        atomic_write(self.path, text + "\n")


def atomic_write(path: Path, text: str) -> None:
    """Metni geçici dosyaya yazıp yerine taşır: okuyan hiçbir zaman yarım dosya görmez."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
