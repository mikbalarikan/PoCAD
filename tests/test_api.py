"""pocad.api: MCP araçlarının ve CLI komutlarının ortak işlevleri."""
import json

import pytest

from pocad import api


def test_init_ve_status(tmp_path):
    out = api.project_init(str(tmp_path / "braket"), name="braket")
    assert out["name"] == "braket" and out["process"] == "fdm"
    assert out["path"] == str((tmp_path / "braket").resolve())
    st = api.project_status(str(tmp_path / "braket"))
    assert st["versions"] == 0 and st["latest"] is None and st["latest_built"] is None
    assert st["unread_messages"] == 0


def test_var_olan_proje_icin_init_hata(tmp_path):
    api.project_init(str(tmp_path / "p"), name="p")
    with pytest.raises(api.PocadError, match="zaten var"):
        api.project_init(str(tmp_path / "p"), name="p")


def test_proje_olmayan_yol_pocad_hatasi(tmp_path):
    with pytest.raises(api.PocadError, match="pocad.toml"):
        api.project_status(str(tmp_path))


def test_bos_yol_ortam_degiskenine_sonra_calisma_dizinine_duser(tmp_path, monkeypatch):
    api.project_init(str(tmp_path / "p"), name="p")
    monkeypatch.setenv("POCAD_PROJECT", str(tmp_path / "p"))
    assert api.project_status("")["name"] == "p"
    monkeypatch.delenv("POCAD_PROJECT")
    monkeypatch.chdir(tmp_path / "p")
    assert api.project_status("")["name"] == "p"


def test_surum_yokken_export_ve_report_aciklayan_hata(tmp_path):
    api.project_init(str(tmp_path / "p"), name="p")
    with pytest.raises(api.PocadError, match="başarılı sürüm yok"):
        api.export(str(tmp_path / "p"))
    with pytest.raises(api.PocadError, match="v7"):
        api.report(str(tmp_path / "p"), version=7)


def test_reply_outboxa_yazar_inbox_since_ile_suzer(tmp_path):
    p = tmp_path / "p"
    api.project_init(str(p), name="p")
    inbox = p / ".chat" / "inbox.jsonl"
    inbox.write_text(json.dumps({"ts": 1.0, "text": "a"}) + "\n" + json.dumps({"ts": 2.0, "text": "b"}) + "\n"
                     + "bozuk\n", encoding="utf-8")
    assert [m["text"] for m in api.chat_inbox(str(p))["messages"]] == ["a", "b"]
    assert [m["text"] for m in api.chat_inbox(str(p), since=1.0)["messages"]] == ["b"]
    out = api.chat_reply(str(p), "  v2 hazır  ")
    msg = json.loads((p / ".chat" / "outbox.jsonl").read_text(encoding="utf-8"))
    assert out["ok"] and msg["text"] == "v2 hazır" and msg["ts"] == out["ts"]
    with pytest.raises(api.PocadError):
        api.chat_reply(str(p), "   ")


def test_okunmamis_mesaj_son_cevaptan_sonrakilerdir(tmp_path):
    p = tmp_path / "p"
    api.project_init(str(p), name="p")
    (p / ".chat" / "inbox.jsonl").write_text(json.dumps({"ts": 1.0, "text": "a"}) + "\n")
    assert api.project_status(str(p))["unread_messages"] == 1
    api.chat_reply(str(p), "tamam")
    assert api.project_status(str(p))["unread_messages"] == 0


@pytest.mark.cad
def test_build_status_export_report(tmp_path):
    pytest.importorskip("build123d")
    pytest.importorskip("OCP.collections", reason="pocad OCP 8 ister")
    p = str(tmp_path / "p")
    api.project_init(p, name="p")
    out = api.build(p, label="ilk")
    assert out["status"] == "built" and out["n"] == 1
    assert out["summary"]["solid_count"]["measured"] == 1
    assert round(out["summary"]["envelope_size_x"]["measured"], 6) == 20
    st = api.project_status(p)
    assert st["latest"]["n"] == 1 and st["latest_built"]["n"] == 1 and st["versions"] == 1
    ex = api.export(p)
    assert ex["n"] == 1 and set(ex["files"]) == {"output.step", "output.stl", "output.glb"}
    for f in ex["files"].values():
        assert f["path"].endswith(tuple(ex["files"])) and f["sha256"] and f["size_bytes"] > 0
    assert api.report(p)["schema"] == "pocad-report-v1"
    (tmp_path / "p" / "model.py").write_text("result = 1\n")
    bad = api.build(p, label="bozuk")
    assert bad["status"] == "failed" and bad["summary"] == {}
    assert api.export(p)["n"] == 1                       # son başarılı sürüm hâlâ v1
    with pytest.raises(api.PocadError, match="başarısız"):
        api.export(p, version=2)
