"""cad-chat istasyon sunucusu: sohbet API'si, proje bilgisi, çıktı indirme ve görüntüleyici vekili."""
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import add_version


# ── sohbet ────────────────────────────────────────────────────────────────────
def test_sayfa_proje_adini_icerir(station):
    status, headers, body = station.get("/")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    html = body.decode()
    assert "braket" in html
    assert "__NAME__" not in html and "__VBASE__" not in html


def test_gonderilen_mesaj_inbox_dosyasina_yazilir(station):
    status, _, _ = station.post("/_chat/send", {"text": "  20 mm braket  "})
    assert status == 200
    lines = (station.proj / ".chat/inbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    msg = json.loads(lines[0])
    assert msg["text"] == "20 mm braket"
    assert isinstance(msg["ts"], float)


@pytest.mark.parametrize("body", [b"", b"{}", b'{"text": "   "}', b"bozuk json"])
def test_bos_ya_da_bozuk_mesaj_reddedilir(station, body):
    status, _, _ = station.post("/_chat/send", body)
    assert status == 400
    assert (station.proj / ".chat/inbox.jsonl").read_text() == ""


def test_mesajlar_zaman_sirasiyla_ve_rolleriyle_doner(station):
    chat = station.proj / ".chat"
    (chat / "inbox.jsonl").write_text(
        json.dumps({"ts": 1.0, "text": "ilk"}) + "\n" + json.dumps({"ts": 3.0, "text": "üçüncü"}) + "\n"
    )
    (chat / "outbox.jsonl").write_text(json.dumps({"ts": 2.0, "text": "ikinci"}) + "\nbozuk satır\n")
    ms = station.json("/_chat/messages")
    assert [(m["role"], m["text"]) for m in ms] == [("user", "ilk"), ("claude", "ikinci"), ("user", "üçüncü")]


def test_cok_uzun_mesaj_kesilir(station):
    station.post("/_chat/send", {"text": "x" * 300000})
    msg = json.loads((station.proj / ".chat/inbox.jsonl").read_text())
    assert len(msg["text"]) == 200000


# ── proje bilgisi ─────────────────────────────────────────────────────────────
def test_bilgi_bos_projede_bos_doner(station):
    d = station.json("/_pocad/info")
    assert d["name"] == "braket"
    assert d["version"] is None and d["attempt"] is None and d["files"] == [] and d["vbase"] is None


def test_bilgi_son_basarili_surumu_ve_son_denemeyi_gosterir(station):
    meta = {"metrics": {"dimensions": [20, 30, 5], "volume": 1234.5, "face_count": 12},
            "validation": {"is_valid": True}, "created": "2026-11-04T10:00:00"}
    add_version(station.proj, 1, meta=meta)
    add_version(station.proj, 2, status="failed", files=())
    d = station.json("/_pocad/info")
    assert d["version"] == {"version": 1, "label": "v1"}
    assert d["attempt"] == {"version": 2, "label": "v2", "status": "failed"}
    assert d["metrics"]["dims"] == [20, 30, 5]
    assert d["metrics"]["valid"] is True
    assert [f["n"] for f in d["files"]] == ["output.step", "output.stl"]


def test_bilgi_dogrulama_raporunu_ayristirir(station):
    (station.proj / "verify_report.txt").write_text(
        "[PASS] duvar kalınlığı: 2.0 mm\n[FAIL] taşma açısı: 62°\nserbest satır\n[WARN] köprü\n"
    )
    d = station.json("/_pocad/info")
    assert d["verify"] == [
        {"s": "PASS", "n": "duvar kalınlığı", "v": "2.0 mm"},
        {"s": "FAIL", "n": "taşma açısı", "v": "62°"},
        {"s": "WARN", "n": "köprü", "v": ""},
    ]


# ── çıktı indirme ─────────────────────────────────────────────────────────────
def test_cikti_proje_adiyla_indirilir(station):
    add_version(station.proj, 1)
    status, headers, body = station.get("/_pocad/file?n=output.stl")
    assert status == 200
    assert body == b"output.stl of v1"
    assert headers["Content-Disposition"] == 'attachment; filename="braket.stl"'


@pytest.mark.parametrize("name", ["../agentcad.toml", "meta.json", "output.glb", ""])
def test_izin_listesi_disindaki_ya_da_olmayan_dosya_404(station, name):
    add_version(station.proj, 1, meta={})
    status, _, _ = station.get(f"/_pocad/file?n={name}")
    assert status == 404


# ── görüntüleyici vekili ──────────────────────────────────────────────────────
VIEWER_HTML = b"<html><head><title>v</title></head><body>new THREE.Color(0xefefef)</body></html>"


@pytest.fixture
def upstream():
    """agentcad görüntüleyici servisinin yerine geçen sahte sunucu."""
    seen = []

    class Up(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.path)
            body = VIEWER_HTML if self.path.endswith("viewer.html") else b'{"ok":1}'
            self.send_response(200)
            self.send_header("Content-Type", "text/html" if self.path.endswith(".html") else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], seen
    srv.shutdown()


def write_viewer_config(proj, port, secret="gizli"):
    root = (proj / "build").resolve()
    cfg = root / ".agentcad/viewer/config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"port": port, "secret": secret}))
    return hmac.new(secret.encode(), str(root).encode(), hashlib.sha256).hexdigest()


def test_goruntuleyici_yokken_vekil_503(station):
    status, _, _ = station.get("/projects/abc/state")
    assert status == 503


def test_vekil_token_ile_yonlendirir(station, upstream):
    port, seen = upstream
    tok = write_viewer_config(station.proj, port)
    assert station.json("/_pocad/info")["vbase"] == f"/projects/{tok}/"
    status, _, body = station.get(f"/projects/{tok}/state")
    assert status == 200 and json.loads(body) == {"ok": 1}
    assert seen == [f"/projects/{tok}/state"]


def test_vekil_surum_goruntuleyicisine_koyu_tema_ekler(station, upstream):
    port, _ = upstream
    tok = write_viewer_config(station.proj, port)
    status, _, body = station.get(f"/projects/{tok}/artifacts/3/viewer.html")
    html = body.decode()
    assert status == 200
    assert 'id="pocad-skin"' in html
    assert html.index('id="pocad-skin"') < html.index("</head>")
    assert "0x141F2B" in html and "0xefefef" not in html
