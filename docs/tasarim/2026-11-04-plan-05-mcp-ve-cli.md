# Plan 05: `pocad-mcp` sunucusu ve `pocad` CLI

Tasarım: [`2026-11-04-pocad-cekirdek-mcp.md`](2026-11-04-pocad-cekirdek-mcp.md) §5, §12 adım 5; karar S-3
Branch: `ccr-d7b7f275-1nefzn`

**Hedef:** Plan 04'ün proje ve build işlevlerini iki yoldan erişilebilir yapmak. İki yol da aynı işlevleri çağırır:
- **MCP:** Herhangi bir coding agent (Claude Code, Codex, Gemini CLI, OpenCode) stdio üzerinden bağlanır.
- **CLI:** `python -m pocad …` komutları, MCP araçlarının birebir karşılığıdır (S-3).

**Kapsam ayrımı:** Gate tablosu (`gates.toml` + `SPEC.md` gate tablosu + `gates` aracı) bu plandan ayrılıp
**Plan 05b**'ye alındı. Gerekçesi: gate satırlarının oguz-atolye `GATES.md`'den FDM alt kümesine taşınması kendi
review'unu ister. Bu plan yalnız araç altyapısını kurar.

## Mimari
```
pocad/api.py         düz Python işlevleri; JSON'a çevrilebilir dict döndürür, PocadError fırlatır
pocad/mcp_server.py  MCPServer("pocad"): api işlevlerini araç olarak kaydeder; PocadError → ToolError
pocad/cli.py         argparse alt komutları → api; çıktı insan için metin ya da --json
pocad/__main__.py    python -m pocad → cli.main
```
- MCP SDK: `mcp==2.3.0` (MIT; `pydantic-core`'un ARM64 tekerleği var).
- Sunucuyu başlatmak: `python -m pocad mcp` ya da `python -m pocad.mcp_server`.

## Araçlar (bu plan)

| Araç / komut | Girdi | Çıktı |
|---|---|---|
| `project_init` / `pocad init` | `path`, `name`, `process="fdm"`, `machine=""` | proje özeti |
| `project_status` / `pocad status` | `path` | ad, süreç, makine, son sürüm, son başarılı sürüm, sürüm sayısı, okunmamış mesaj sayısı |
| `build` / `pocad build` | `path`, `label=""` | registry satırı + rapordaki ölçümlerin kısa özeti (solid_count, brep_valid, naked_edges, zarf, hacim) |
| `export` / `pocad export` | `path`, `version=None` (son başarılı) | sürümün çıktı dosyalarının mutlak yolları, sha256 ve boyutları |
| `report` / `pocad report` | `path`, `version=None` | report.json'un tamamı |
| `chat_inbox` / `pocad inbox` | `path`, `since=0` | `ts > since` olan kullanıcı mesajları |
| `chat_reply` / `pocad reply` | `path`, `text` | `{ok, ts}`; outbox.jsonl'e yazar (cad-reply ile aynı biçim) |

- **`path`:** Mutlak ya da sunucunun çalışma dizinine göreli. Boşsa `POCAD_PROJECT` ortam değişkeni, o da yoksa çalışma dizini kullanılır.
- **Hatalar:** Proje yok, sürüm yok, kilit, geçersiz toml gibi hatalar Türkçe `PocadError` olarak fırlatılır ve MCP'de `ToolError` olur. Agent mesajı görür.
- **Çıktı biçimi:** Sayılar `Result.to_dict()` biçiminde aktarılır; özet alanları rapordan kopyalanır, yeniden hesaplanmaz.

## Görevler

| # | İş | Doğrulama |
|---|---|---|
| 1 | `tests/test_api.py` (CAD'siz kısım: init, status, export/report hataları, inbox/reply) | kırmızı |
| 2 | `pocad/api.py` | `test_api` CAD'siz yeşil |
| 3 | `tests/test_api.py` cad kısmı: build → status → export → report | yeşil |
| 4 | `tests/test_cli.py`: alt komutlar alt süreçte, `--json` çıktısı, hata çıkış kodu 1 ve Türkçe mesaj | kırmızı → yeşil |
| 5 | `pocad/cli.py`, `pocad/__main__.py` | — |
| 6 | `tests/test_mcp.py`: stdio istemciyle sunucuyu başlat, `list_tools` beklenen 7 aracı ve şemaları verir, `project_init` + `project_status` çağrısı, hata `is_error` ve Türkçe mesaj | kırmızı → yeşil |
| 7 | `pocad/mcp_server.py`; `requirements-dev.txt`'ye `mcp==2.3.0` | — |
| 8 | `AGENTS.md`'de "MCP sunucusunu bağlamak" bölümü (Claude Code `.mcp.json`, Codex `config.toml`) | — |
| 9 | Son doğrulama + bağımsız review | 0.13 venv tam takım; CAD'siz; eski venv `-m "not cad"`; ruff |

## Kabul ölçütleri
- [ ] MCP araçları ile CLI komutları aynı `api` işlevlerini çağırıyor (kod tekrarı yok)
- [ ] Gerçek bir stdio MCP istemcisiyle uçtan uca test var
- [ ] Hata mesajları agent'a Türkçe ve anlamlı ulaşıyor
