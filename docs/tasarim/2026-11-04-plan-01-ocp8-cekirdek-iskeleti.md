# Plan 01: build123d 0.13 / OCP 8 ve `pocad` paket iskeleti

Tasarım: [`2026-11-04-pocad-cekirdek-mcp.md`](2026-11-04-pocad-cekirdek-mcp.md) §12 adım 1
Superpowers adımı: writing-plans · Branch: `ccr-d7b7f275-1nefzn`

**Hedef:** Repoda `pocad` adlı bir Python paketi oluşsun. Bu paket build123d 0.13 / OCP 8 ile
çalışsın ve OCP sürüm farklarını tek bir modülde (`pocad/_ocp.py`) toplasın. CAD testleri CI'da hem
x86_64 hem ARM64'te koşsun. Sonraki PR'lar (`pocad.result`, `pocad.core`) bu temelin üstüne kurulur.

**Kapsam dışı:** oguz-atolye kodunun taşınması (Plan 02), agentcad'in kaldırılması (Plan 09).

**Geçiş notu:** Telefon kurulumu (`scripts/setup-ubuntu.sh`) agentcad kaldırılana kadar build123d
0.10 / OCP 7.8'de kalır. Bu süre boyunca iki sürüm yan yana bulunur:
- CI'daki `cad` testleri yeni çekirdeği (0.13) dener.
- `bin/` ve `scripts/stl_export.py` hem 0.10 hem 0.13'te çalışmak zorundadır.

`AGENTS.md` bu geçişi açıkça yazar.

---

## Görev 1: `pocad` paketi ve sürüm bilgisi (≈3 dk)

**Dosyalar:** `pocad/__init__.py` (yeni), `tests/test_pocad_paket.py` (yeni), `pyproject.toml`

1. Test yaz (önce kırmızı):
   ```python
   # tests/test_pocad_paket.py
   import pocad

   def test_paket_surumu_var():
       assert pocad.__version__ == "0.1.0"
   ```
2. `pytest tests/test_pocad_paket.py`: `ModuleNotFoundError` vermeli.
3. `pocad/__init__.py`:
   ```python
   """PoCAD çekirdeği: geometri, ölçüm, gate'ler ve MCP sunucusu."""
   __version__ = "0.1.0"
   ```
4. `pyproject.toml`'a `[tool.pytest.ini_options] pythonpath = ["."]` ekle. Paket kurulmadan, checkout'tan içe aktarılır.
5. **Doğrulama:** `pytest -m "not cad" -q` → hepsi yeşil.

## Görev 2: CAD gereksinimlerini 0.13 / OCP 8'e taşı (≈3 dk)

**Dosyalar:** `requirements-cad.txt`

1. İçerik:
   ```
   # pocad çekirdeği (bkz. docs/tasarim/2026-11-04-pocad-cekirdek-mcp.md K-1).
   # Telefon kurulumu agentcad kaldırılana kadar 0.10/OCP 7.8'de kalır (setup-ubuntu.sh).
   -r requirements-dev.txt
   build123d==0.13.0
   cadquery-ocp-novtk==8.0.1.1.0
   ```
   `ocp_gordon` ve `ocpsvg`, build123d'nin kendi sınırlarıyla gelir; ayrıca sabitlenmez.
2. **Doğrulama:** Temiz bir Python 3.12 venv'inde `pip install -r requirements-cad.txt`, ardından
   `python -c "import build123d, importlib.metadata as m; print(build123d.__version__, m.version('cadquery-ocp-novtk'))"`
   → `0.13.0 8.0.1.1.0`
3. **Doğrulama:** Bu venv'de `pytest -m cad`. `stl_export` testleri 0.13'te de yeşil olmalı.
   Kırmızıysa dur ve raporla; testi gevşetme.

## Görev 3: `pocad/_ocp.py`: önce testler (≈4 dk)

**Dosyalar:** `tests/test_ocp.py` (yeni)

Testleri yaz ve kırmızı olduklarını gör (modül henüz yok):
```python
"""pocad._ocp: OCP 8 isimleri tek yerden; oguz-atolye kodunun kullandığı eski adların karşılıkları."""
import pytest

pytestmark = pytest.mark.cad
bd = pytest.importorskip("build123d")

from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_OUT  # noqa: E402
from OCP.TopExp import TopExp  # noqa: E402

from pocad import _ocp  # noqa: E402


def kutu():
    return bd.Box(10, 10, 10).wrapped


def test_indexed_map_of_shape_bir_kutunun_alti_yuzunu_tutar():
    m = _ocp.IndexedMapOfShape()
    TopExp.MapShapes_s(kutu(), TopAbs_FACE, m)
    assert m.Size() == 6


def test_kenar_yuz_haritasi_her_kenara_iki_yuz_verir():
    d = _ocp.IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(kutu(), TopAbs_EDGE, TopAbs_FACE, d)
    assert d.Size() == 12
    assert all(d.FindFromIndex(i).Size() == 2 for i in range(1, 13))


@pytest.mark.parametrize("ad", ["Vertex", "Edge", "Wire", "Face", "Shell", "Solid", "Compound", "CompSolid"])
def test_downcast_fonksiyonlari_var(ad):
    assert callable(getattr(_ocp.downcast, ad))


def test_downcast_yuzu_topods_face_yapar():
    m = _ocp.IndexedMapOfShape()
    TopExp.MapShapes_s(kutu(), TopAbs_FACE, m)
    assert type(_ocp.downcast.Face(m.FindKey(1))).__name__ == "TopoDS_Face"


def test_fclass2d_yuz_ortasini_ice_disi_disa_siniflar():
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt2d

    m = _ocp.IndexedMapOfShape()
    TopExp.MapShapes_s(kutu(), TopAbs_FACE, m)
    f = _ocp.downcast.Face(m.FindKey(1))
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    c = _ocp.FClass2d(f, 1e-7)
    assert c.Perform(gp_Pnt2d((u0 + u1) / 2, (v0 + v1) / 2)) == TopAbs_IN
    assert c.Perform(gp_Pnt2d(u1 + 100, v1 + 100)) == TopAbs_OUT


def test_surumler_raporlanir():
    v = _ocp.versions()
    assert v["build123d"] == "0.13.0"
    assert v["ocp"].startswith("8.0")
```
**Doğrulama:** `pytest -m cad tests/test_ocp.py` → `ImportError: cannot import name '_ocp'` (kırmızı).

## Görev 4: `pocad/_ocp.py`: en küçük uygulama (≈4 dk)

**Dosyalar:** `pocad/_ocp.py` (yeni)

```python
"""OCP sürüm farklarının tek karşılandığı yer.

OCP 8 (OCCT 8.0) koleksiyon tiplerini `OCP.collections` altına taşıdı, TopoDS
downcast'lerinden `_s` ekini kaldırdı ve `BRepTopAdaptor_FClass2d`'yi bıraktı.
pocad kodu bu adları doğrudan OCP'den değil buradan alır.
"""
import importlib.metadata as _md

from OCP.collections import (
    IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as IndexedDataMapOfShapeListOfShape,
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as IndexedMapOfShape,
)
from OCP.IntTools import IntTools_FClass2d as FClass2d
from OCP.TopoDS import TopoDS as downcast

__all__ = ["IndexedDataMapOfShapeListOfShape", "IndexedMapOfShape", "FClass2d", "downcast", "versions"]


def versions():
    """Kurulu build123d ve OCP sürümleri (raporlar ve `pocad doctor` için)."""
    return {"build123d": _md.version("build123d"), "ocp": _md.version("cadquery-ocp-novtk")}
```

**Doğrulama:** `pytest -m cad tests/test_ocp.py` yeşil, ardından `ruff check .` temiz.

## Görev 5: CI: CAD testleri x86_64 ve ARM64'te (≈3 dk)

**Dosyalar:** `.github/workflows/ci.yml`

`cad` işini bir matrise çevir:
```yaml
  cad:
    name: Testler (build123d 0.13 + OCP 8, ${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, ubuntu-24.04-arm]
```
"build123d içe aktarılabiliyor mu" adımı `python -c "from pocad import _ocp; print(_ocp.versions())"` olsun.

**Doğrulama:** Bu adım yerelde yapılamaz. YAML'ı `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
ile doğrula. Asıl doğrulama ilk PR'da CI'ın çalışmasıdır: iki işletim sistemi, iki yeşil iş.

## Görev 6: Belgeler (≈3 dk)

**Dosyalar:** `AGENTS.md`, `README.md`

- `AGENTS.md` → "Sürüm sabitleri" maddesi:
  - Yeni çekirdek (`pocad/`): build123d 0.13.0, OCP 8.0.1.1 (`cadquery-ocp-novtk`), Python 3.12.
  - Telefon kurulumu ve `bin/`: agentcad kaldırılana kadar 0.10 / OCP 7.8. `bin/` ve `scripts/` kodu iki sürümde de çalışmalı.
  - OCP'ye özgü adlar yalnız `pocad/_ocp.py` üzerinden kullanılır.
- `AGENTS.md` → "Kontroller": `requirements-cad.txt` açıklamasını "build123d 0.13 + OCP 8" yap.
- `AGENTS.md` → "Repo" tablosuna `pocad/` ve `docs/tasarim/` satırları.
- `README.md` → değişiklik yok (telefon kullanıcısı için hâlâ 0.10).

**Doğrulama:** `grep -n "0.10" AGENTS.md` yalnızca geçiş notunda geçmeli.

## Görev 7: Son doğrulama ve review (≈5 dk)

1. Python 3.12 venv'inde (requirements-cad): `ruff check . && pytest -q`. Hepsi yeşil, atlanan test yok.
   Çıktıyı PR açıklamasına koy.
2. Sistem Python'unda, CAD olmadan: `pytest -m "not cad" -q` → yeşil. CAD testleri `importorskip` ile atlanmalı, hata vermemeli.
3. `shellcheck -S warning …` (AGENTS.md'deki komut) temiz.
4. **requesting-code-review:** Taze bir alt-agent şunlara karşı inceler:
   - **(a)** Bu plana ve tasarım K-1/K-2'ye uygunluk.
   - **(b)** Kod kalitesi.

   Kritik bulgu varsa düzelt, sonra yeniden kontrol et.
5. Commit: `pocad: build123d 0.13 / OCP 8 uyumluluk modülü ve paket iskeleti`, ardından push.
   PR açılması kullanıcının onayıyla.

## Kabul ölçütleri
- [ ] `pocad/__init__.py`, `pocad/_ocp.py` var; `_ocp` dışında hiçbir pocad dosyası OCP koleksiyon/downcast adlarını doğrudan kullanmıyor
- [ ] `pytest -q` 0.13 / Python 3.12'de yeşil; CAD'siz ortamda `-m "not cad"` yeşil
- [ ] CI'da `cad` işi `ubuntu-24.04` ve `ubuntu-24.04-arm` üzerinde tanımlı
- [ ] AGENTS.md sürüm kuralları geçişi doğru anlatıyor
