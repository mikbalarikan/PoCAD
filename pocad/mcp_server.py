"""pocad-mcp: PoCAD araçlarını herhangi bir coding agent'a MCP (stdio) üzerinden sunar.

Başlatmak: `python -m pocad mcp` (ya da `python -m pocad.mcp_server`). Araçlar pocad.api
işlevlerinin ince sarmalayıcılarıdır; CLI komutlarıyla birebir aynı işi yaparlar.
Beklenen hatalar (PocadError) agent'a Türkçe mesajla ToolError olarak döner.
"""
from __future__ import annotations

import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pocad import __version__, api

INSTRUCTIONS = """PoCAD: build123d ile parametrik CAD. Proje dizininde model.py parçayı `result`
değişkenine atar; `build` onu yeni bir sürüm olarak kurar, STEP/STL/GLB'ye aktarır ve ölçer.
Sayılar her zaman ölçümdür (status MEASURED ya da INCONCLUSIVE); INCONCLUSIVE asla geçti değildir.
`path` boşsa POCAD_PROJECT ya da sunucunun çalışma dizini kullanılır. Kullanıcı istasyon
sayfasından yazar: `chat_inbox` ile oku, `chat_reply` ile cevap ver."""

app = MCPServer("pocad", version=__version__, instructions=INSTRUCTIONS)


def _tool(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except api.PocadError as exc:
            raise ToolError(str(exc)) from exc
        except OSError as exc:                       # izin, disk dolu, yol bir dosya … agent sebebi görsün
            raise ToolError(f"dosya sistemi hatası: {type(exc).__name__}: {exc}") from exc
    return app.tool()(wrapper)


@_tool
def project_init(path: str, name: str, process: str = "fdm", machine: str = "") -> dict:
    """Yeni bir PoCAD projesi kurar (pocad.toml, SPEC.md, model.py, versions/, .chat/).
    name: harf, rakam, '-' ve '_'; process: şimdilik yalnız 'fdm'; machine: yazıcı profili (boş olabilir)."""
    return api.project_init(path, name=name, process=process, machine=machine)


@_tool
def project_status(path: str = "") -> dict:
    """Projenin durumu: son sürüm, son başarılı sürüm, sürüm sayısı, okunmamış kullanıcı mesajı sayısı.
    Oturum başında ve bir işi devralırken çağır."""
    return api.project_status(path)


@_tool
def build(path: str = "", label: str = "") -> dict:
    """model.py'yi yeni bir sürüm olarak kurar (ayrı süreçte, zaman sınırıyla): AP242 STEP, STL, GLB
    ve ölçümler (solid_count, brep_valid, naked_edges, zarf, hacim, STL sagitta). Başarısızsa `error`
    kullanıcının koduna işaret eder. Geometrinin geçersiz olması build hatası değildir; ölçüme bak."""
    return api.build(path, label=label)


@_tool
def export(path: str = "", version: int | None = None) -> dict:
    """Bir sürümün (verilmezse son başarılı sürümün) çıktı dosyaları: mutlak yol, sha256, boyut."""
    return api.export(path, version=version)


@_tool
def report(path: str = "", version: int | None = None) -> dict:
    """Bir sürümün (verilmezse son başarılı sürümün) report.json'u: tüm ölçümler, log, hata."""
    return api.report(path, version=version)


@_tool
def chat_inbox(path: str = "", since: float = 0.0) -> dict:
    """İstasyon sayfasından gelen kullanıcı mesajları; `since` (ts) sonrasındakiler."""
    return api.chat_inbox(path, since=since)


@_tool
def chat_reply(text: str, path: str = "") -> dict:
    """İstasyon sayfasına cevap yazar (en fazla 200 000 karakter). Uzun işlerde ara durum bildirmek
    için de kullan."""
    return api.chat_reply(text, path=path)


def main() -> None:
    app.run("stdio")


if __name__ == "__main__":
    main()
