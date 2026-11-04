"""pocad CLI (python -m pocad): MCP araçlarının komut satırı karşılığı (karar S-3)."""
import json
import subprocess
import sys

import pytest

from conftest import ROOT


def pocad(*args, cwd=None):
    import os
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])}
    return subprocess.run([sys.executable, "-m", "pocad", *args], capture_output=True, text=True,
                          cwd=cwd, env=env, timeout=300)


def test_init_ve_status_json(tmp_path):
    r = pocad("init", str(tmp_path / "braket"), "--name", "braket", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["name"] == "braket"
    r = pocad("status", str(tmp_path / "braket"), "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["versions"] == 0


def test_insan_icin_metin_ciktisi(tmp_path):
    pocad("init", str(tmp_path / "p"), "--name", "p")
    r = pocad("status", str(tmp_path / "p"))
    assert r.returncode == 0 and "p" in r.stdout and "sürüm" in r.stdout


def test_hata_cikis_kodu_1_ve_turkce_mesaj(tmp_path):
    r = pocad("status", str(tmp_path))
    assert r.returncode == 1
    assert "pocad: " in r.stderr and "pocad.toml" in r.stderr
    assert "Traceback" not in r.stderr


def test_yol_verilmezse_calisma_dizini(tmp_path):
    pocad("init", str(tmp_path / "p"), "--name", "p")
    r = pocad("status", "--json", cwd=tmp_path / "p")
    assert r.returncode == 0 and json.loads(r.stdout)["name"] == "p"


def test_reply_ve_inbox(tmp_path):
    p = tmp_path / "p"
    pocad("init", str(p), "--name", "p")
    (p / ".chat" / "inbox.jsonl").write_text(json.dumps({"ts": 5.0, "text": "merhaba"}) + "\n")
    r = pocad("inbox", str(p), "--since", "1", "--json")
    assert [m["text"] for m in json.loads(r.stdout)["messages"]] == ["merhaba"]
    assert pocad("reply", str(p), "v1 hazır").returncode == 0
    assert "v1 hazır" in (p / ".chat" / "outbox.jsonl").read_text(encoding="utf-8")


def test_yardim_her_araci_listeler():
    r = pocad("--help")
    for cmd in ("init", "status", "build", "export", "report", "inbox", "reply", "mcp"):
        assert cmd in r.stdout


@pytest.mark.cad
def test_build_ve_export(tmp_path):
    pytest.importorskip("build123d")
    pytest.importorskip("OCP.collections", reason="pocad OCP 8 ister")
    p = tmp_path / "p"
    pocad("init", str(p), "--name", "p")
    r = pocad("build", str(p), "--label", "ilk")
    assert r.returncode == 0, r.stderr
    assert "v1" in r.stdout and "built" in r.stdout
    r = pocad("export", str(p), "--json")
    assert set(json.loads(r.stdout)["files"]) == {"output.step", "output.stl", "output.glb"}
    (p / "model.py").write_text("result = 1\n")
    r = pocad("build", str(p))
    assert r.returncode == 1 and "result" in r.stdout + r.stderr
