#!/data/data/com.termux/files/usr/bin/python3
"""cad-chat — tek sayfalık CAD istasyonu: canlı agentcad görüntüleyici + Claude oturumuyla sohbet.

kullanım: cad-chat.py PROJE_DIZINI [PORT]

  kullanıcı mesajları -> PROJE/.chat/inbox.jsonl   (Claude oturumu bu dosyayı izler)
  Claude cevapları    -> PROJE/.chat/outbox.jsonl  (`cad-reply PROJE "mesaj"` ile yazılır)

Sayfa (`pocad-page.html`, Türkişi Engineering kimliği, palet v5) her istekte diskten okunur.
Görüntüleyici `X-Frame-Options: SAMEORIGIN` gönderdiği için bu sunucu onu kendi origin'i
altında ters vekil (reverse proxy) olarak sunar ve sürüm görüntüleyicisine (viewer.html)
koyu tema enjekte eder. Görüntüleyici portu ve proje token'ı projenin
build/.agentcad/viewer/config.json dosyasından her istekte okunur.
Ek uç noktalar:
  /_pocad/info   son sürümün ölçüleri, doğrulama raporu (verify_report.txt), çıktı dosyaları
  /_pocad/file   son sürüm klasöründeki bir çıktıyı indirir (?n=output.step)
Yalnızca 127.0.0.1'e bağlanır.
"""
import hashlib
import hmac
import http.client
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

proj = Path(sys.argv[1]).resolve()
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
here = Path(__file__).resolve().parent
page_file = here / "pocad-page.html"
chat = proj / ".chat"
chat.mkdir(exist_ok=True)
inbox, outbox = chat / "inbox.jsonl", chat / "outbox.jsonl"
for f in (inbox, outbox):
    f.touch()
lock = threading.Lock()


def build_root():
    toml = proj / "agentcad.toml"
    bd = "."
    if toml.exists():
        m = re.search(r'^\s*build_dir\s*=\s*"([^"]+)"', toml.read_text(), re.M)
        if m:
            bd = m.group(1)
    return (proj / bd).resolve()


def viewer_target():
    """(port, '/projects/<token>/') ya da görüntüleyici henüz yoksa None."""
    root = build_root()
    try:
        c = json.loads((root / ".agentcad/viewer/config.json").read_text())
        if c.get("port") and c.get("secret"):
            tok = hmac.new(c["secret"].encode(), str(root).encode(), hashlib.sha256).hexdigest()
            return int(c["port"]), f"/projects/{tok}/"
    except (OSError, ValueError):
        pass
    return None


def read(path, role):
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            m = json.loads(line)
            m["role"] = role
            out.append(m)
        except ValueError:
            pass
    return out


# ── proje bilgisi ──────────────────────────────────────────────────────────────
OUT_FILES = [("output.step", "STEP", "CAD"), ("output.stl", "STL", "baskı"),
             ("output.glb", "GLB", "görüntüleme"), ("preview.png", "PNG", "önizleme")]
VERIFY_RE = re.compile(r"^\[(PASS|FAIL|WARN)\]\s*(.+?)(?::\s*(.*))?$")


def latest_version():
    """(son başarılı sürüm kaydı, klasörü, son deneme kaydı) — build/agentcad.json'dan."""
    root = build_root()
    try:
        vs = json.loads((root / "agentcad.json").read_text()).get("versions", [])
    except (OSError, ValueError):
        return None, None, None
    ok = [v for v in vs if v.get("status") == "success"]
    last = vs[-1] if vs else None
    if not ok:
        return None, None, last
    v = ok[-1]
    return v, (root / v.get("path", "")).resolve(), last


def info():
    v, vdir, last = latest_version()
    d = {"name": proj.name, "version": None, "attempt": None, "metrics": None, "files": [], "verify": [],
         "verify_mtime": None}
    if last:
        d["attempt"] = {"version": last.get("version"), "label": last.get("label"), "status": last.get("status")}
    if v and vdir:
        d["version"] = {"version": v.get("version"), "label": v.get("label")}
        try:
            meta = json.loads((vdir / "meta.json").read_text())
            m = meta.get("metrics", {})
            d["metrics"] = {"dims": m.get("dimensions"), "volume": m.get("volume"), "faces": m.get("face_count"),
                            "valid": (meta.get("validation") or {}).get("is_valid"), "created": meta.get("created")}
        except (OSError, ValueError):
            pass
        for fn, ext, what in OUT_FILES:
            p = vdir / fn
            if p.is_file():
                d["files"].append({"n": fn, "ext": ext, "what": what, "size": p.stat().st_size})
    rep = proj / "verify_report.txt"
    if rep.is_file():
        d["verify_mtime"] = rep.stat().st_mtime
        for line in rep.read_text(encoding="utf-8", errors="replace").splitlines():
            m = VERIFY_RE.match(line.strip())
            if m:
                d["verify"].append({"s": m.group(1), "n": m.group(2).strip(), "v": (m.group(3) or "").strip()})
    return d


# ── görüntüleyiciye koyu tema (palet v5) ─────────────────────────────────────────
VIEWER_SKIN = """<style id="pocad-skin">
body{background:#141F2B!important;color:#ECF1F5!important}
#modes{background:rgba(13,22,31,.92)!important;box-shadow:0 2px 10px rgba(0,0,0,.4)!important;border:1px solid #394A5A}
#modes button{color:#B7C3CD!important;border-right-color:#202E3C!important}
#modes button:hover{background:#202E3C!important}
#modes button.active,#modes button.spec.active{background:#39659B!important;color:#ECF1F5!important}
.label,#overlay-controls{background:rgba(13,22,31,.9)!important;color:#ECF1F5!important;box-shadow:none!important;border:1px solid #394A5A}
#divider{background:#394A5A!important}
[id$="-view"]{background:#141F2B!important;color:#ECF1F5!important}
[id$="-view"] .panel{background:#202E3C!important;color:#ECF1F5!important;box-shadow:none!important}
[id$="-view"] h3,[id$="-view"] h4,[id$="-view"] .meta,[id$="-view"] .agent-state-key,[id$="-view"] .empty-state,[id$="-view"] .change-kind{color:#B7C3CD!important}
[id$="-view"] .agent-state-value,[id$="-view"] .agent-note,[id$="-view"] .group-name,[id$="-view"] ol,[id$="-view"] .change-summary,[id$="-view"] strong{color:#ECF1F5!important}
[id$="-view"] .agent-chip,[id$="-view"] .group-row,[id$="-view"] .part-group-tag,[id$="-view"] .changes{background:#0D161F!important;border-color:#394A5A!important;color:#ECF1F5!important}
a{color:#64BFFF!important}
/* telefon: mod çubuğu tek satır, kaydırılabilir; veri olmayan modlar gizli */
#modes{left:8px!important;right:auto!important;top:8px!important;max-width:calc(100% - 16px);overflow-x:auto;scrollbar-width:none;flex-wrap:nowrap}
#modes::-webkit-scrollbar{display:none}
#modes button{white-space:nowrap;flex:none}
#modes button.disabled{display:none!important}
/* Part controls: katlanır panel (başlığa dokun), telefonda kapalı başlar */
#part-controls{top:54px!important;left:8px!important;width:min(340px,calc(100% - 16px))!important;max-height:calc(100% - 120px)!important;
  background:rgba(13,22,31,.94)!important;border-color:#394A5A!important;color:#ECF1F5!important;box-shadow:none!important}
#part-controls .head{border-bottom-color:#202E3C!important}
#part-controls h3{cursor:pointer;color:#ECF1F5!important}
#part-controls h3::after{content:" ▾";color:#B7C3CD}
#part-controls:not(.pocad-acik) h3::after{content:" ▸"}
#part-controls:not(.pocad-acik)>:not(.head){display:none!important}
#part-controls:not(.pocad-acik) .head{border-bottom:0!important}
#part-controls button,#viewer-tools button{background:#202E3C!important;color:#ECF1F5!important;border-color:#394A5A!important;box-shadow:none!important}
#part-controls button.active,#viewer-tools button[aria-pressed="true"]{background:#39659B!important}
#part-controls .part-row,#part-controls .group-row{background:#141F2B!important;border-color:#394A5A!important}
#part-controls .sub,#part-controls .foot,#part-controls .section-title{color:#B7C3CD!important}
</style>
<script>addEventListener('DOMContentLoaded',()=>{const p=document.getElementById('part-controls');if(!p)return;
if(innerWidth>=700)p.classList.add('pocad-acik');
const h=p.querySelector('.head h3');if(h)h.addEventListener('click',()=>p.classList.toggle('pocad-acik'));});</script>"""
VIEWER_SUBS = [("new THREE.Color(0xefefef)", "new THREE.Color(0x141F2B)"),
               ("color || '#c0c0c0'", "color || '#EEF3FA'")]
SKIN_PATH = re.compile(r"^/projects/[a-f0-9]{64}/artifacts/\d+/viewer\.html")

PLACEHOLDER = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<body style="margin:0;display:grid;place-items:center;height:100vh;background:#141F2B;color:#B7C3CD;
font:14px 'IBM Plex Sans',system-ui,sans-serif;text-align:center;padding:16px">
<div><div style="font:900 20px Archivo,'Arial Narrow',sans-serif;color:#ECF1F5;text-transform:uppercase;letter-spacing:.02em">Henüz model yok</div>
İlk <code style="font-family:monospace;background:#0D161F;padding:1px 5px;border-radius:4px">agentcad run</code> sonrası burada görünecek.</div></body>"""

HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-connection"}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        text = ctype.startswith("text/") or ctype == "application/json"
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if text else ""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def proxy(self):
        tgt = viewer_target()
        if tgt is None:
            return self.send(503, json.dumps({"message": "görüntüleyici henüz yok"}))
        up_port = tgt[0]
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n) if n else None
        up = f"127.0.0.1:{up_port}"
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() != "host"}
        hdrs["Host"] = up
        skin = self.command == "GET" and SKIN_PATH.match(self.path)
        if skin:
            hdrs = {k: v for k, v in hdrs.items() if k.lower() != "accept-encoding"}
        for h in ("Origin", "Referer"):
            if h in hdrs:
                hdrs[h] = hdrs[h].replace(self.headers.get("Host", ""), up)
        try:
            c = http.client.HTTPConnection("127.0.0.1", up_port, timeout=600)
            c.request(self.command, self.path, body=body, headers=hdrs)
            r = c.getresponse()
        except OSError as e:
            return self.send(502, json.dumps({"message": f"görüntüleyiciye ulaşılamadı: {e}"}))
        try:
            if skin and r.status == 200:
                html = r.read().decode("utf-8", errors="replace")
                for a, b in VIEWER_SUBS:
                    html = html.replace(a, b)
                html = html.replace("</head>", VIEWER_SKIN + "</head>", 1)
                out = html.encode("utf-8")
                self.send_response(200)
                for k, v in r.getheaders():
                    if k.lower() not in HOP and k.lower() not in ("content-length", "content-encoding"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
                return
            self.send_response(r.status, r.reason)
            for k, v in r.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.end_headers()
            while True:
                chunk = r.read1(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError:
            pass
        finally:
            c.close()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/_chat/messages":
            ms = read(inbox, "user") + read(outbox, "claude")
            ms.sort(key=lambda m: m.get("ts", 0))
            return self.send(200, json.dumps(ms, ensure_ascii=False))
        if path == "/_chat/placeholder":
            return self.send(200, PLACEHOLDER, "text/html")
        if path == "/_pocad/info":
            d = info()
            tgt = viewer_target()
            d["vbase"] = tgt[1] if tgt else None
            return self.send(200, json.dumps(d, ensure_ascii=False))
        if path == "/_pocad/file":
            name = parse_qs(urlsplit(self.path).query).get("n", [""])[0]
            _, vdir, _ = latest_version()
            if name not in {fn for fn, _, _ in OUT_FILES} or vdir is None or not (vdir / name).is_file():
                return self.send(404, json.dumps({"message": "dosya yok"}))
            ctype = "image/png" if name.endswith(".png") else "application/octet-stream"
            ext = name.rsplit(".", 1)[1]
            fname = f"{proj.name}.{ext}" if name.startswith("output.") else f"{proj.name}_onizleme.{ext}"
            return self.send(200, (vdir / name).read_bytes(), ctype,
                             {"Content-Disposition": f'attachment; filename="{fname}"'})
        if path in ("/", "/index.html"):
            tgt = viewer_target()
            page = page_file.read_text(encoding="utf-8")
            page = page.replace("__VBASE__", json.dumps(tgt[1] if tgt else None)).replace("__NAME__", proj.name)
            return self.send(200, page, "text/html")
        return self.proxy()

    def do_PUT(self):
        return self.proxy()

    def do_DELETE(self):
        return self.proxy()

    def do_PATCH(self):
        return self.proxy()

    def do_POST(self):
        if self.path != "/_chat/send":
            return self.proxy()
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            text = json.loads(self.rfile.read(n) or b"{}").get("text", "").strip()
        except ValueError:
            return self.send(400, "{}")
        if not text:
            return self.send(400, "{}")
        with lock, inbox.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "text": text[:200000]}, ensure_ascii=False) + "\n")
        self.send(200, '{"ok":true}')


print(f"cad-chat: http://127.0.0.1:{port}/  proje={proj}", flush=True)
ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
