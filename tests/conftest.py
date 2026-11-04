"""Ortak test yardımcıları.

`bin/` altındaki betikler Termux shebang'i taşır ve modül düzeyinde çalışır; bu yüzden
testler onları içe aktarmak yerine şu anki Python yorumlayıcısıyla alt süreç olarak başlatır.
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
SCRIPTS = ROOT / "scripts"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method, url, body=None, headers=None):
    """(durum, başlıklar, gövde) döndürür; HTTP hata kodlarında istisna atmaz."""
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class Station:
    """Geçici bir proje dizini için çalışan bir cad-chat sunucusu."""

    def __init__(self, proj: Path):
        self.proj = proj
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc = subprocess.Popen(
            [sys.executable, str(BIN / "cad-chat.py"), str(proj), str(self.port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 10
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("cad-chat erken kapandı:\n" + self.proc.stdout.read().decode())
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        self.stop()
        raise RuntimeError("cad-chat 10 sn içinde dinlemeye başlamadı")

    def get(self, path, **kw):
        return http("GET", self.base + path, **kw)

    def post(self, path, body=None, **kw):
        return http("POST", self.base + path, body, **kw)

    def json(self, path):
        status, _, body = self.get(path)
        assert status == 200, (status, body)
        return json.loads(body)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def project(tmp_path):
    """agentcad init sonrasına benzeyen boş bir proje dizini."""
    proj = tmp_path / "braket"
    (proj / "build").mkdir(parents=True)
    (proj / "agentcad.toml").write_text('build_dir = "./build"\n')
    return proj


@pytest.fixture
def station(project):
    s = Station(project)
    yield s
    s.stop()


def add_version(proj: Path, n: int, status="success", files=("output.step", "output.stl"), meta=None):
    """build/agentcad.json'a bir sürüm kaydı ve sürüm klasörü ekler."""
    build = proj / "build"
    reg = build / "agentcad.json"
    data = json.loads(reg.read_text()) if reg.exists() else {"versions": []}
    vdir = build / f"v{n}"
    vdir.mkdir(parents=True, exist_ok=True)
    data["versions"].append({"version": n, "label": f"v{n}", "status": status, "path": f"v{n}"})
    reg.write_text(json.dumps(data))
    for fn in files:
        (vdir / fn).write_bytes(f"{fn} of v{n}".encode())
    if meta is not None:
        (vdir / "meta.json").write_text(json.dumps(meta))
    return vdir
