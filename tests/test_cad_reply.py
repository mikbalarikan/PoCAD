"""cad-reply: agent'ın cevabı outbox.jsonl'e yazılır ve istasyon sayfasında görünür."""
import json
import subprocess
import sys

from conftest import BIN


def run(proj, *args, stdin=None):
    return subprocess.run([sys.executable, str(BIN / "cad-reply"), str(proj), *args],
                          input=stdin, text=True, capture_output=True, check=True)


def test_arguman_olarak_verilen_cevap_yazilir(tmp_path):
    run(tmp_path, "  v2 hazır, hacim 12 cm³  ")
    msg = json.loads((tmp_path / ".chat/outbox.jsonl").read_text(encoding="utf-8"))
    assert msg["text"] == "v2 hazır, hacim 12 cm³"
    assert isinstance(msg["ts"], float)


def test_stdin_cevabi_ve_eklemeli_yazim(tmp_path):
    run(tmp_path, "bir")
    run(tmp_path, stdin="iki\nsatır\n")
    lines = (tmp_path / ".chat/outbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["text"] for x in lines] == ["bir", "iki\nsatır"]


def test_cevap_sohbet_api_sinde_gorunur(station):
    run(station.proj, "seçenekler: A / B")
    ms = station.json("/_chat/messages")
    assert ms[-1]["role"] == "claude" and ms[-1]["text"] == "seçenekler: A / B"
