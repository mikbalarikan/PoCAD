"""PoCAD'in araç yüzeyi: MCP araçları (pocad.mcp_server) ve CLI komutları (pocad.cli) bunları çağırır.

Her işlev JSON'a çevrilebilir bir dict döndürür; beklenen hatalar Türkçe `PocadError` olur.
Ölçümler rapordan olduğu gibi aktarılır (Result.to_dict()); burada hiçbir sayı yeniden
hesaplanmaz. CAD çekirdeği yalnız `build` çağrılınca yüklenir.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from pocad import project as _project

SUMMARY = ("solid_count", "brep_valid", "naked_edges", "envelope_size_x", "envelope_size_y", "envelope_size_z",
           "volume_mm3", "stl_max_sagitta")
REPLY_CHARS = 200_000                    # cad-chat sayfasının kullanıcı mesajına koyduğu sınırla aynı
_chat_lock = threading.Lock()


class PocadError(Exception):
    """Kullanıcıya ya da agent'a olduğu gibi gösterilecek, beklenen bir hata."""


def _open(path: str) -> _project.Project:
    root = path or os.environ.get("POCAD_PROJECT") or os.getcwd()
    try:
        return _project.open_project(root)
    except (FileNotFoundError, ValueError) as exc:
        raise PocadError(str(exc)) from exc


def _summary(p: _project.Project) -> dict:
    return {"path": str(p.root), "name": p.name, "process": p.process, "machine": p.machine,
            "export": dict(p.export)}


def project_init(path: str, name: str, process: str = "fdm", machine: str = "") -> dict:
    """Yeni bir PoCAD projesi kurar: pocad.toml, SPEC.md, model.py, versions/, .chat/."""
    try:
        p = _project.init(path or os.getcwd(), name=name, process=process, machine=machine)
    except (FileExistsError, ValueError) as exc:
        raise PocadError(str(exc)) from exc
    return _summary(p)


def project_status(path: str = "") -> dict:
    """Projenin durumu: son sürüm, son başarılı sürüm, sürüm sayısı ve cevapsız mesajlar
    (agent'ın son cevabından sonra gelen kullanıcı mesajları)."""
    p = _open(path)
    try:
        versions = p.registry().versions()
    except ValueError as exc:
        raise PocadError(str(exc)) from exc
    built = [v for v in versions if v.get("status") == "built"]
    return {**_summary(p), "versions": len(versions), "latest": versions[-1] if versions else None,
            "latest_built": built[-1] if built else None, "unanswered_messages": len(_unanswered(p))}


def build(path: str = "", label: str = "") -> dict:
    """model.py'yi yeni bir sürüm olarak kurar, dışa aktarır ve ölçer."""
    p = _open(path)
    from pocad import build as _build
    try:
        entry = _build.build(p, label)
    except (_build.BuildBusy, ValueError) as exc:
        raise PocadError(str(exc)) from exc
    results = _read_report(p, entry["n"]).get("results", {})
    return {**entry, "summary": {k: results[k] for k in SUMMARY if k in results}}


def export(path: str = "", version: int | None = None) -> dict:
    """Bir sürümün (verilmezse son başarılı sürümün) çıktı dosyaları: mutlak yol, sha256, boyut."""
    p = _open(path)
    n = _pick(p, version)
    rep = _read_report(p, n)
    if rep.get("status") != "built":
        raise PocadError(f"v{n} başarısız bir build; dışa aktarılacak dosyası yok ({rep.get('error')})")
    vdir = p.version_dir(n)
    files = rep.get("files")
    if not isinstance(files, dict) or not files:
        raise PocadError(f"v{n} raporunda dosya listesi yok: {vdir / 'report.json'}")
    return {"n": n, "label": rep.get("label", ""),
            "files": {name: {"path": str(vdir / name), **info} for name, info in files.items()}}


def report(path: str = "", version: int | None = None) -> dict:
    """Bir sürümün (verilmezse son başarılı sürümün) report.json'u, olduğu gibi."""
    p = _open(path)
    return _read_report(p, _pick(p, version))


def chat_inbox(path: str = "", since: float = 0.0) -> dict:
    """İstasyon sayfasından gelen kullanıcı mesajları; `since`'ten (ts) sonrakiler."""
    p = _open(path)
    return {"messages": [m for m in _read_jsonl(p.root / ".chat" / "inbox.jsonl") if m["ts"] > since]}


def chat_reply(text: str, path: str = "") -> dict:
    """İstasyon sayfasına cevap yazar (cad-reply ile aynı biçim: .chat/outbox.jsonl)."""
    p = _open(path)
    text = (text or "").strip()
    if not text:
        raise PocadError("boş cevap gönderilemez")
    if len(text) > REPLY_CHARS:
        raise PocadError(f"cevap çok uzun ({len(text)} karakter, sınır {REPLY_CHARS}); böl ya da dosyaya yaz")
    ts = time.time()
    outbox = p.root / ".chat" / "outbox.jsonl"
    outbox.parent.mkdir(exist_ok=True)
    with _chat_lock, outbox.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "text": text}, ensure_ascii=False) + "\n")
    return {"ok": True, "ts": ts}


# ── yardımcılar ───────────────────────────────────────────────────────────────
def _pick(p: _project.Project, version: int | None) -> int:
    if version is not None:
        return int(version)
    try:
        latest = p.registry().latest_built()
    except ValueError as exc:
        raise PocadError(str(exc)) from exc
    if latest is None:
        raise PocadError("henüz başarılı sürüm yok: önce build çalıştır")
    return latest["n"]


def _read_report(p: _project.Project, n: int) -> dict:
    path = p.version_dir(n) / "report.json"
    if not path.is_file():
        raise PocadError(f"v{n} yok ya da raporu yazılmamış: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PocadError(f"{path}: rapor okunamadı ({exc})") from exc
    if not isinstance(data, dict):
        raise PocadError(f"{path}: rapor bir JSON nesnesi değil")
    return data


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        ts = m.get("ts") if isinstance(m, dict) else None
        if isinstance(ts, (int, float)) and not isinstance(ts, bool) and isinstance(m.get("text"), str):
            out.append(m)
    return out


def _unanswered(p: _project.Project) -> list[dict]:
    replies = _read_jsonl(p.root / ".chat" / "outbox.jsonl")
    last = max((m["ts"] for m in replies), default=0.0)
    return [m for m in _read_jsonl(p.root / ".chat" / "inbox.jsonl") if m["ts"] > last]
