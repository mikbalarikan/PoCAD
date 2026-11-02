#!/data/data/com.termux/files/usr/bin/python3
"""cad-chat — tek sayfalık CAD istasyonu: canlı agentcad görüntüleyici + Claude oturumuyla sohbet.

kullanım: cad-chat.py PROJE_DIZINI [PORT]

  kullanıcı mesajları -> PROJE/.chat/inbox.jsonl   (Claude oturumu bu dosyayı izler)
  Claude cevapları    -> PROJE/.chat/outbox.jsonl  (`cad-reply PROJE "mesaj"` ile yazılır)

Görüntüleyici `X-Frame-Options: SAMEORIGIN` gönderdiği için bu sunucu onu kendi
origin'i altında ters vekil (reverse proxy) olarak sunar. Görüntüleyici portu ve proje
token'ı projenin build/.agentcad/viewer/config.json dosyasından her istekte okunur;
yani görüntüleyici sonradan başlasa veya port değişse de sayfa çalışır.
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

proj = Path(sys.argv[1]).resolve()
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
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


PLACEHOLDER = """<!doctype html><meta charset="utf-8"><body style="margin:0;display:grid;place-items:center;
height:100vh;background:#4d4d4d;color:#ddd;font:15px system-ui;text-align:center;padding:16px">
Henüz model yok — ilk <code>agentcad run</code> sonrası burada görünecek.
<script>setTimeout(()=>top.location.reload(),5000)</script></body>"""

PAGE = r"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__NAME__ · PoCAD</title>
<style>
:root{--bg:#f6f7f9;--fg:#1b1f24;--muted:#6b7280;--me:#2563eb;--cl:#ffffff;--line:#e5e7eb}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--fg:#e8eaed;--muted:#9aa0a6;--me:#3b82f6;--cl:#1e2329;--line:#2a2f36}}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font:15px system-ui,sans-serif}
body{display:flex;flex-direction:column;height:100dvh}
#v{flex:0 0 var(--vh,55%);border:0;width:100%;background:#4d4d4d}
#bar{display:flex;gap:8px;align-items:center;padding:4px 10px;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)}
#bar b{color:var(--fg)}#bar button{margin-left:auto;font-size:12px;padding:2px 8px;border:1px solid var(--line);background:transparent;color:var(--fg);border-radius:6px}
#log{flex:1;overflow-y:auto;padding:10px;display:flex;flex-direction:column;gap:8px}
.m{max-width:85%;padding:8px 11px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word;line-height:1.35}
.user{align-self:flex-end;background:var(--me);color:#fff;border-bottom-right-radius:4px}
.claude{align-self:flex-start;background:var(--cl);border:1px solid var(--line);border-bottom-left-radius:4px}
.t{display:block;font-size:10px;opacity:.6;margin-top:3px}
#f{display:flex;gap:8px;padding:8px 10px calc(8px + env(safe-area-inset-bottom,0px));border-top:1px solid var(--line)}
#q{flex:1;font:inherit;padding:10px 12px;border-radius:20px;border:1px solid var(--line);background:var(--cl);color:var(--fg);resize:none;max-height:120px}
#s{border:0;border-radius:20px;padding:0 16px;background:var(--me);color:#fff;font-weight:600}
.wait{align-self:flex-start;color:var(--muted);font-size:13px;font-style:italic}
</style></head><body>
<iframe id="v" src="__VIEWER__" allow="fullscreen"></iframe>
<div id="bar"><b>__NAME__</b><span id="st">bağlanıyor…</span><button id="sz">Model ↕</button></div>
<div id="log"></div>
<form id="f"><textarea id="q" rows="1" placeholder="Claude'a yaz…"></textarea><button id="s">➤</button></form>
<script>
const log=document.getElementById('log'),q=document.getElementById('q'),st=document.getElementById('st');
let seen=-1,sizes=['55%','30%','80%'],si=0;
document.getElementById('sz').onclick=()=>{si=(si+1)%3;document.documentElement.style.setProperty('--vh',sizes[si]);};
function fmt(ts){return new Date(ts*1000).toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'});}
async function poll(){
  try{const r=await fetch('/_chat/messages',{cache:'no-store'});const ms=await r.json();st.textContent='bağlı';
    if(ms.length!==seen){log.innerHTML='';
      ms.forEach(m=>{const e=document.createElement('div');e.className='m '+m.role;e.textContent=m.text;
        const t=document.createElement('span');t.className='t';t.textContent=fmt(m.ts);e.appendChild(t);log.appendChild(e);});
      const last=ms[ms.length-1];if(last&&last.role==='user'){const w=document.createElement('div');w.className='wait';w.textContent='Claude okuyor…';log.appendChild(w);}
      seen=ms.length;log.scrollTop=log.scrollHeight;}
  }catch(e){st.textContent='bağlantı yok';}
}
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const text=q.value.trim();if(!text)return;q.value='';
  await fetch('/_chat/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});poll();};
q.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!/Android|iPhone/.test(navigator.userAgent)){e.preventDefault();document.getElementById('f').requestSubmit();}});
setInterval(poll,2000);poll();
</script></body></html>"""

HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-connection"}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
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
        for h in ("Origin", "Referer"):
            if h in hdrs:
                hdrs[h] = hdrs[h].replace(self.headers.get("Host", ""), up)
        try:
            c = http.client.HTTPConnection("127.0.0.1", up_port, timeout=600)
            c.request(self.command, self.path, body=body, headers=hdrs)
            r = c.getresponse()
        except OSError as e:
            return self.send(502, json.dumps({"message": f"görüntüleyiciye ulaşılamadı: {e}"}))
        self.send_response(r.status, r.reason)
        for k, v in r.getheaders():
            if k.lower() not in HOP:
                self.send_header(k, v)
        self.end_headers()
        try:
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
        if self.path.startswith("/_chat/messages"):
            ms = read(inbox, "user") + read(outbox, "claude")
            ms.sort(key=lambda m: m.get("ts", 0))
            return self.send(200, json.dumps(ms, ensure_ascii=False))
        if self.path.startswith("/_chat/placeholder"):
            return self.send(200, PLACEHOLDER, "text/html")
        if self.path in ("/", "/index.html"):
            tgt = viewer_target()
            src = tgt[1] if tgt else "/_chat/placeholder"
            return self.send(200, PAGE.replace("__VIEWER__", src).replace("__NAME__", proj.name), "text/html")
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
