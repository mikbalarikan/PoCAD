# Plan 03: `pocad.measure` ve mutasyon testleri (oguz-atolye'den)

Tasarım: [`2026-11-04-pocad-cekirdek-mcp.md`](2026-11-04-pocad-cekirdek-mcp.md) §12 adım 3
Kaynak: `mikbalarikan/oguz-atolye` @ `ca27b1b` · Branch: `ccr-d7b7f275-1nefzn`

**Hedef:** oguz-atolye'nin ölçüm takımını (`tools/measure/`) ve mutasyon testlerini PoCAD'e taşımak.
Mutasyon testlerinde her kontrol dört aileden birer mutantla denenir: resize, relocate, remove, degrade.
Taşınan kod OCP 8'de `pocad._ocp` üzerinden çalışır.

**Kapsam dışı:** `tools/drawing`, `tools/package`, `tools/render`. Bunlara ait mutasyon satırları (9 kontrol)
ve `PROVED_ELSEWHERE` girdileri o modüller taşınırken geri gelir.

## Taşıma kuralları
Plan 02'deki kurallar aynen geçerli:
- kaynak notu
- yalnız izinli değişiklikler
- OCP 8 adları `_ocp` üzerinden
- gizli proje adları ayıklanır (U4/U5/U8/uno10, "Usta U-" → "oguz-atolye U-")
- test gevşetilmez

Bu plana özel izinli değişiklikler:
- `MANIFEST.json`'dan drawing/package kontrollerinin satırları çıkarılır.
- `test_mutations.py`'dan bu kontrollerin `check_*` fonksiyonları ve `CODE_PREFIXES` girdileri çıkarılır.
- Manifest şeması `oguz-mutations-v1` → `pocad-mutations-v1` olur.
- `min_wall_mesh` Embree ister. Embree'nin ARM64 tekerleği yok; bu yüzden ARM64'te test, kaynaktaki
  `embree_or_skip` ile atlanır. Bu davranış kaynakta zaten var, yeni bir atlama değildir.

## Bağımlılıklar (`requirements-cad.txt`)
- `trimesh>=4`
- `rtree>=1`
- `embreex>=4.4` (yalnız x86_64 / macOS, kaynaktaki platform işaretiyle)

scipy ve numpy build123d ile gelir.

## Görevler

| # | İş | Doğrulama |
|---|---|---|
| 1 | `tests/test_measure.py`, `tests/test_mutations.py`, `tests/mutations/MANIFEST.json` taşı (önce kırmızı) | `ModuleNotFoundError: pocad.measure` |
| 2 | `requirements-cad.txt` bağımlılıkları | temiz venv'de kurulum |
| 3 | `pocad/measure/*` + OCP 8 adları `_ocp`'den | `pytest -m cad tests/test_measure.py tests/test_mutations.py` yeşil |
| 4 | `docs/BUILD123D-NOTLARI.md`: measure satırları | `test_every_test_the_notes_cite_exists` yeşil |
| 5 | Son doğrulama + bağımsız review | 0.13 venv `pytest -q`; CAD'siz ve eski venv `-m "not cad"`; ruff; `test_ocp_adlari` |

## Kabul ölçütleri
- [ ] `test_measure.py`'nin tüm testleri ve `test_mutations.py`'nin core+measure satırlarının tümü yeşil
- [ ] Manifest, kodun sunduğu her core+measure kontrolünü kapsıyor (`test_the_manifest_covers_every_check_the_code_offers`)
- [ ] Gizli proje adı yok; OCP 8 adları yalnız `_ocp.py`'de
