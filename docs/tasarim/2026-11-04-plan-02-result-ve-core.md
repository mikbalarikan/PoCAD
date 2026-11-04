# Plan 02: `pocad.result` ve `pocad.core` (oguz-atolye'den, testleriyle)

Tasarım: [`2026-11-04-pocad-cekirdek-mcp.md`](2026-11-04-pocad-cekirdek-mcp.md) §12 adım 2
Kaynak: `mikbalarikan/oguz-atolye` @ `ca27b1b` · Branch: `ccr-d7b7f275-1nefzn`

**Hedef:** oguz-atolye'nin ölçüm sözleşmesini (`tools/result.py`) ve geometri çekirdeğini
(`tools/core/`) testleriyle birlikte PoCAD'e taşımak. Taşınan kod OCP 8'de `pocad._ocp` üzerinden çalışır.

**Kapsam dışı:** `tools/measure`, mutasyon testleri (Plan 03), `drawing`, `package`, `render`, `jobstate`.

## Taşıma kuralları (tasarım §10)
- Her dosyanın başına bir kaynak notu eklenir: `# kaynak: oguz-atolye <yol> @ca27b1b (MIT, PoCAD'e taşındı)`.
- İçerik değişmez; değişebilecek olanlar yalnız şunlar:
  - içe aktarma yolları (`tools.` → `pocad.`)
  - OCP 8 adları (`pocad._ocp`)
  - ortam değişkeni (`OGUZ_WORK` → `POCAD_WORK`, isteğe bağlı) ve geçici klasör öneki (`oguz-analyzer-` → `pocad-analyzer-`)
  - sürüm dizesi testleri (0.11.1 → 0.13.0)
  - şema adı (`oguz-verdict-v1` → `pocad-verdict-v1`)
- Kod yorumlarındaki D-/R-/U-/L- numaraları oguz-atolye karar kayıtlarına aittir. Silinmez; `pocad/core/__init__.py` bunu not eder.
- Gizli proje adları ve müşteri işleri belgelere girmez.
- Bir test kırılırsa test gevşetilmez; kodun ya da OCP 8 uyumunun düzeltilmesi gerekir.

## Görevler

| # | İş | Dosyalar | Doğrulama |
|---|---|---|---|
| 1 | Testleri ve sentetik parçaları taşı (önce kırmızı) | `tests/test_result.py`, `tests/test_core.py`, `tests/fixtures/{__init__,parts}.py` | `pytest tests/test_result.py tests/test_core.py` → `ModuleNotFoundError: pocad.result` |
| 2 | `pocad/result.py` | — | `pytest tests/test_result.py` yeşil (stdlib; CAD'siz işte de koşar) |
| 3 | Karar şeması | `pocad/schemas/verdict.schema.json` | `test_result` şema testleri yeşil |
| 4 | `pocad/env.py` (`POCAD_WORK`) | — | `validity` içe aktarılabiliyor |
| 5 | `pocad/core/*` + OCP 8 adları `_ocp`'den | `shapes`, `fillet`, `validity`, `_analyzer`, `boolean`, `mesh`, `step`, `__init__` | `pytest -m cad tests/test_core.py` yeşil |
| 6 | build123d tuzak notları | `docs/BUILD123D-NOTLARI.md` (yalnız core/result testlerini anan satırlar, gizli adlar ayıklanmış) | `test_every_test_the_notes_cite_exists` yeşil |
| 7 | `_ocp` dışında OCP 8 adı kullanılmadığını denetleyen test | `tests/test_ocp.py` | `pocad/` içinde `TopoDS.*_s`, `TopTools_Indexed*`, `BRepTopAdaptor_FClass2d` yok |
| 8 | Son doğrulama + bağımsız review | — | 0.13 venv: `pytest -q`; CAD'siz: `-m "not cad"`; eski venv: `-m "not cad"`; `ruff check .` |

## Kabul ölçütleri
- [ ] oguz-atolye `test_result.py` (16) ve `test_core.py` (70) testlerinin hepsi PoCAD'de, OCP 8'de yeşil; atlanan ya da gevşetilen test yok
- [ ] `pocad/` içinde OCP 8'e özgü adlar yalnız `_ocp.py`'de
- [ ] Her taşınan dosyada kaynak notu var; gizli proje adı yok
