"""pocad-mcp: gerçek bir stdio MCP istemcisiyle uçtan uca (sunucu alt süreçte)."""
import json
import os
import sys

import pytest

from conftest import ROOT

mcp = pytest.importorskip("mcp")
anyio = pytest.importorskip("anyio")

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

ARACLAR = {"project_init", "project_status", "build", "export", "report", "chat_inbox", "chat_reply"}


def calistir(senaryo):
    """Sunucuyu `python -m pocad mcp` ile başlatır, senaryoyu bir oturumla çalıştırır."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])}
    params = StdioServerParameters(command=sys.executable, args=["-m", "pocad", "mcp"], env=env)

    async def main():
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            return await senaryo(s)

    return anyio.run(main)


def veri(sonuc):
    assert not sonuc.is_error, sonuc.content[0].text
    return json.loads(sonuc.content[0].text)


def test_araclar_listelenir_ve_semalari_var():
    async def senaryo(s):
        return (await s.list_tools()).tools

    tools = {t.name: t for t in calistir(senaryo)}
    assert set(tools) == ARACLAR
    init = tools["project_init"]
    assert {"path", "name"} <= set(init.input_schema["required"])
    assert init.description and "proje" in init.description.lower()
    assert all(t.description for t in tools.values())


def test_init_status_reply_inbox(tmp_path):
    yol = str(tmp_path / "braket")

    async def senaryo(s):
        init = veri(await s.call_tool("project_init", {"path": yol, "name": "braket"}))
        await s.call_tool("chat_reply", {"path": yol, "text": "hazırım"})
        st = veri(await s.call_tool("project_status", {"path": yol}))
        gelen = veri(await s.call_tool("chat_inbox", {"path": yol}))
        return init, st, gelen

    init, st, gelen = calistir(senaryo)
    assert init["name"] == "braket" and st["versions"] == 0 and gelen == {"messages": []}
    assert "hazırım" in (tmp_path / "braket" / ".chat" / "outbox.jsonl").read_text(encoding="utf-8")


def test_hata_agenta_turkce_ulasir(tmp_path):
    async def senaryo(s):
        return await s.call_tool("project_status", {"path": str(tmp_path)})

    sonuc = calistir(senaryo)
    assert sonuc.is_error and "pocad.toml" in sonuc.content[0].text


@pytest.mark.cad
def test_build_ve_export_mcp_uzerinden(tmp_path):
    pytest.importorskip("build123d")
    pytest.importorskip("OCP.collections", reason="pocad OCP 8 ister")
    yol = str(tmp_path / "p")

    async def senaryo(s):
        veri(await s.call_tool("project_init", {"path": yol, "name": "p"}))
        b = veri(await s.call_tool("build", {"path": yol, "label": "mcp"}))
        e = veri(await s.call_tool("export", {"path": yol}))
        return b, e

    b, e = calistir(senaryo)
    assert b["status"] == "built" and b["summary"]["brep_valid"]["measured"] == 1
    assert set(e["files"]) == {"output.step", "output.stl", "output.glb"}
