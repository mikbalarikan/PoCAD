# Telefon standı — Redmi Note 13 Pro (portre + landscape)

Sürüm: **v3-A** (agentcad v4_v3-A), 2026-11-02 — kullanıcı onaylı.

## Dosyalar
| Klasör | Dosya | Açıklama |
|---|---|---|
| `cikti/` | `stand.stl` | Baskı dosyası (tolerance 0.01, angular 0.1; 508 üçgen, su geçirmez — her kenar tam 2 üçgende) |
| `cikti/` | `stand.step` | CAD (agentcad tarafından yazıldı, round-trip PASS) |
| `cikti/` | `stand.glb` | 3D görüntüleme |
| `cikti/` | `onizleme.png` | 4 görünüm önizleme |
| `src/` | `stand.py` | Parametrik build123d kaynak (`Params` dataclass) |
| `src/` | `spec.md` | Orijinal tasarım spec'i (§0–§9) |
| `src/` | `requirements.md` | Kabul listesi + yorumlar/varsayımlar |
| `src/` | `verify_report.txt` | §7 doğrulama çıktısı |
| `src/` | `agentcad.toml` | agentcad proje ayarı |

## Doğrulama özeti (§7)
- Hacim **41.8 cm³** (spec sınırı 40) — kullanıcı tarafından kabul edildi. Dolu PLA 51.8 g, baskı ≈ 36.5 g.
- Telefon kutusu portre + landscape: kesişim 0, sırtlık ve raf teması 0.000 mm — PASS
- Kamera temizliği |X| ≤ 31.3 mm (≤ 35) — PASS
- Fiş keep-out kesişimi 0 — PASS
- Overhang: 0 ihlal. Yatay köprüler: üst çubuk altı (52 mm), raf altı (Z=28.2, 2×~19 mm), arka kablo tavanı (14 mm) — PASS
- Devrilme F_tip = 1.01 N (≥ 0.9; baskı kütlesiyle) — PASS
- Ayak izi CG portre Y=47.9, landscape Y=35.3 (0 < Y < 115) — PASS
- Tek katı, geçerli B-rep, STL manifold, STEP round-trip — PASS

## Spec'ten sapmalar (onaylı)
1. **Seçenek A:** Raf altında 45° dolu kama yerine yatay köprülü ince raf plakası + 3 mm tam genişlik ön duvar (hacim 55.5 → 41.8 cm³).
2. Hacim sınırı 40 → 41.8 cm³ kabul edildi.

## Yorumlar (spec'te açık olmayan)
- Kablo çentiği |X| ≤ 7 bandında rafı, dudağı ve ön duvarın üst kısmını keser; kablo öne-aşağı çıkar.
- Çerçeve iç köşe yuvarlatması (R2) yalnızca yayın yukarı baktığı köşelerde; hücre tepeleri keskin (overhang kuralı).
- Raf plakası sırtlık düzleminin 1 mm arkasına bindirilir (çizgi temasıyla oluşan manifold olmayan kenarı önler).
- STEP'i agentcad yazar; script içinde STEP yazıcı yoktur (agentcad kuralı).
- 3MF desteklenmiyor (telefonda lib3mf yok).

## Baskı
PLA, destek yok, model tabla üzerinde kullanım yönünde (Z+ yukarı). 2 perimetre, %15 infill önerilir.
Açık noktalar (§9, kumpasla teyit): kamera adası, kılıf kalınlığı (`slot_w`), USB-C fiş uzunluğu (`plug_len`, `S_z`).
Landscape kullanımda tuşlu sağ kenar yukarı gelmeli.

## Yeniden üretmek
`pocad new telefonstandi`, `src/stand.py` ve `src/spec.md` dosyalarını proje köküne kopyala, sonra proje dizininde `agentcad run stand.py --label vN --export stl` çalıştır.
