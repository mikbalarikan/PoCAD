# Plan 04: proje dizini, sürüm kaydı ve `build` (agentcad'siz)

Tasarım: [`2026-11-04-pocad-cekirdek-mcp.md`](2026-11-04-pocad-cekirdek-mcp.md) §4, §12 adım 4
Branch: `ccr-d7b7f275-1nefzn`

**Hedef:** agentcad'in proje ve sürüm yönetimini kendi kodumuzla yapmak. Akış şöyle:
1. `pocad.project` bir proje dizini kurar ve okur.
2. `pocad.build` kullanıcının `model.py`'sini **ayrı bir süreçte**, zaman sınırıyla çalıştırır.
3. Çıkan parça oguz-atolye'den taşınan araçlarla dışa aktarılır ve ölçülür:
   - STEP: `core.write_step` (AP242) + `core.compare_step`
   - STL: `core.write_stl`, ölçülen sagitta ile
   - GLB: build123d `export_gltf`
   - Ölçümler: `core.validity`, `measure.envelope`
4. Her şey `versions/vN/` altına ve `versions/registry.json`'a yazılır.

**Kapsam dışı:**
- MCP sunucusu ve `pocad` CLI (Plan 05)
- Gate tablosu ve `SPEC.md` ayrıştırma (Plan 05/07)
- Önizleme PNG (Plan 07)
- Görüntüleyici (Plan 06)

## Sözleşmeler

### `model.py`
- Sıradan bir Python betiğidir. build123d ile bir parça kurar ve onu modül düzeyinde **`result`** adlı değişkene atar.
- Kabul edilenler: build123d `Shape` (Part, Solid, Compound…) ya da `.wrapped`'i olan herhangi bir nesne.
- `result` yoksa ya da `None` ise build başarısız olur ve hata mesajı bunu açıkça söyler.

### `pocad.toml`
```toml
name = "braket"
process = "fdm"          # Aşama 1: yalnız fdm (S-2)
machine = ""             # boşsa tabla gate'i varsayımla geçer (A-##)

[export]
stl_tolerance = 0.01     # mm, mutlak (U-07)
stl_angular_tolerance = 0.1  # rad
timeout_s = 600
```

### `versions/registry.json`
```json
{"schema": "pocad-registry-v1",
 "versions": [{"n": 1, "label": "ilk deneme", "status": "built", "created": "2026-11-04T10:00:00Z",
               "duration_s": 3.2, "model_sha256": "…", "error": null}]}
```
- `status` iki değerden birini alır:
  - `built`: betik çalıştı ve dosyalar yazıldı.
  - `failed`: betik hatası, `result` yok, zaman aşımı ya da dışa aktarım hatası.
- **Geometri geçersizse build yine `built` olur.** Geçersizlik bir *ölçüm sonucudur* ve rapora yazılır; karar gate'lerindir (INCONCLUSIVE ≠ PASS).
- Kayıt dosyası atomik yazılır (geçici dosya + `os.replace`).
- Numara başarılı ya da başarısız her build'de artar.

### `versions/vN/report.json`
```json
{"schema": "pocad-report-v1", "n": 3, "label": "…", "status": "built",
 "created": "…", "model_sha256": "…", "versions": {"build123d": "0.13.0", "ocp": "8.0.1.1"},
 "files": {"output.step": {"sha256": "…", "size_bytes": 1234}, "output.stl": {…}, "output.glb": {…}},
 "results": {"solid_count": {Result.to_dict()}, "brep_valid": {…}, "naked_edges": {…},
             "envelope_size_x": {…}, …, "volume_mm3": {…}, "stl_max_sagitta": {…},
             "step_schema": {…}, "step_roundtrip_solids": {…}, …},
 "error": null, "log": "betiğin stdout/stderr kuyruğu (en fazla 20 000 karakter)"}
```

## Görevler

| # | İş | Dosyalar | Doğrulama |
|---|---|---|---|
| 1 | `pocad.project` testleri (kırmızı) | `tests/test_project.py` | `ModuleNotFoundError` |
| 2 | `pocad.project`: `init`, `open`, `Registry` (sıradaki numara, atomik kayıt) | `pocad/project.py` | `tests/test_project.py` yeşil (CAD'siz; `tomllib` stdlib) |
| 3 | `pocad.build` testleri (kırmızı, `cad`) | `tests/test_build.py` | `ModuleNotFoundError` |
| 4 | Alt süreç çalıştırıcısı: `model.py` → `result` → dışa aktarım + ölçüm → `report.json` | `pocad/build_runner.py` | — |
| 5 | `pocad.build.build(project, label)`: numara ayır, `model.py`'yi kopyala, çalıştırıcıyı zaman sınırıyla başlat, kaydı yaz | `pocad/build.py` | `tests/test_build.py` yeşil |
| 6 | Son doğrulama + bağımsız review | — | 0.13 venv `pytest -q -n auto`; CAD'siz ve eski venv `-m "not cad"`; ruff |

### `tests/test_build.py` durumları
- **Sağlam kutu:** `built`, üç dosya var, `solid_count == 1`, `brep_valid == 1`, `naked_edges == 0`, zarf 20×10×5 mm.
- **Söz dizimi hatası:** `failed`, `error` satır numarasını içerir. Kayıt numarası yine de artar.
- **`result` tanımsız:** `failed`, mesajda "result" geçer.
- **Sonsuz döngü** (`timeout_s=2`): `failed`, mesajda "zaman aşımı" geçer, süreç öldürülmüştür.
- **İki ayrı gövde:** `built`, `solid_count == 2`. Build başarısız sayılmaz; ölçüm rapora yazılır.
- **Ardışık iki build:** v1 ve v2 klasörleri ayrı; her birinde o anki `model.py` kopyası var.
- **Betik çıktısı:** `print` çıktısı `log`'a girer.

## Kabul ölçütleri
- [ ] agentcad'e hiçbir yerde bağımlılık yok
- [ ] Bir `model.py` hatası ya da çökmesi çağıran süreci etkilemiyor (alt süreç)
- [ ] `report.json` sayıları `Result.to_dict()` biçiminde; sayı uyduran yer yok
