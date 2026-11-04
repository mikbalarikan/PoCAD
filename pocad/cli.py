"""pocad: PoCAD komut satırı. Her alt komut bir MCP aracının karşılığıdır (pocad.api).

    python -m pocad init YOL --name AD [--process fdm] [--machine M]
    python -m pocad status [YOL]
    python -m pocad build [YOL] [--label ETİKET]
    python -m pocad export [YOL] [--version N]
    python -m pocad report [YOL] [--version N]
    python -m pocad inbox [YOL] [--since TS]
    python -m pocad reply YOL METİN
    python -m pocad mcp                 MCP sunucusunu stdio üzerinde başlatır

YOL verilmezse POCAD_PROJECT, o da yoksa çalışma dizini kullanılır. --json makine için
çıktı verir. Beklenen hatalarda çıkış kodu 1'dir ve mesaj stderr'e "pocad: …" diye yazılır;
başarısız bir build de 1 ile çıkar.
"""
from __future__ import annotations

import argparse
import json
import sys

from pocad import api


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pocad", description="PoCAD: agent'tan bağımsız CAD araçları")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="KOMUT")

    def cmd(name, help_, path_optional=True):
        s = sub.add_parser(name, help=help_)
        s.add_argument("path", nargs="?" if path_optional else None, default="", metavar="YOL")
        s.add_argument("--json", action="store_true", help="JSON çıktı")
        return s

    s = cmd("init", "yeni proje kur", path_optional=False)
    s.add_argument("--name", required=True)
    s.add_argument("--process", default="fdm")
    s.add_argument("--machine", default="")
    cmd("status", "projenin durumu")
    cmd("build", "model.py'yi yeni sürüm olarak kur").add_argument("--label", default="")
    cmd("export", "sürümün çıktı dosyaları").add_argument("--version", type=int)
    cmd("report", "sürümün report.json'u").add_argument("--version", type=int)
    cmd("inbox", "istasyon sayfasından gelen mesajlar").add_argument("--since", type=float, default=0.0)
    s = cmd("reply", "istasyon sayfasına cevap yaz", path_optional=False)
    s.add_argument("text", metavar="METİN")
    sub.add_parser("mcp", help="MCP sunucusunu stdio üzerinde başlat")
    return ap


def _text(cmd: str, out: dict) -> str:
    if cmd in ("init", "status"):
        lines = [f"{out['name']}  ({out['process']})  {out['path']}"]
        if cmd == "status":
            latest, built = out["latest"], out["latest_built"]
            lines.append(f"{out['versions']} sürüm; son: " + (f"v{latest['n']} {latest['status']}" if latest else "yok")
                         + "; son başarılı: " + (f"v{built['n']}" if built else "yok"))
            lines.append(f"okunmamış mesaj: {out['unread_messages']}")
        return "\n".join(lines)
    if cmd == "build":
        head = f"v{out['n']} {out['status']} ({out['duration_s']} sn)"
        if out["error"]:
            return head + "\n" + out["error"]
        rows = [f"  {k}: {v['measured']} {v['unit']}" + ("" if v["status"] == "MEASURED" else f" [{v['status']}]")
                for k, v in out["summary"].items()]
        return "\n".join([head, *rows])
    if cmd == "export":
        return "\n".join([f"v{out['n']}"] + [f"  {f['path']}  {f['size_bytes']} B" for f in out["files"].values()])
    if cmd == "inbox":
        return "\n".join(f"[{m['ts']:.0f}] {m['text']}" for m in out["messages"]) or "mesaj yok"
    if cmd == "reply":
        return "gönderildi"
    return json.dumps(out, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "mcp":
        from pocad import mcp_server
        mcp_server.main()
        return 0
    try:
        if args.cmd == "init":
            out = api.project_init(args.path, name=args.name, process=args.process, machine=args.machine)
        elif args.cmd == "status":
            out = api.project_status(args.path)
        elif args.cmd == "build":
            out = api.build(args.path, label=args.label)
        elif args.cmd == "export":
            out = api.export(args.path, version=args.version)
        elif args.cmd == "report":
            out = api.report(args.path, version=args.version)
        elif args.cmd == "inbox":
            out = api.chat_inbox(args.path, since=args.since)
        else:
            out = api.chat_reply(args.path, args.text)
    except api.PocadError as exc:
        print(f"pocad: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else _text(args.cmd, out))
    return 1 if args.cmd == "build" and out["status"] != "built" else 0


if __name__ == "__main__":
    sys.exit(main())
