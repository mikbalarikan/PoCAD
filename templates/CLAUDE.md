# PoCAD projesi: {{NAME}}

Bu dizin bir **PoCAD** CAD istasyonu projesidir. Kullanıcı bir CAD mühendisi; bu telefonu
1–2 hafta boyunca yalnızca bu proje için kullanıyor. Kullanıcıyla Türkçe konuş.

Tasarım iş akışı için `AGENTS.md` ve `.claude/skills/agentcad/SKILL.md` dosyalarını oku
(agentcad: **Inspect → Specify → Build → Validate → Deliver**). Bu dosya yalnızca PoCAD'a
özgü kuralları ekler.

## 1. Oturum başında
1. Servisler çalışıyor mu bak: `pocad status {{NAME}}`. Çalışmıyorsa `pocad start {{NAME}}`.
2. Sohbet sayfasını dinlemeye başla. Kullanıcı mesajlarının çoğunu Termux'tan değil,
   tarayıcıdaki istasyon sayfasından gönderir. **Monitor** aracını şu komutla başlat
   (timeout 30 dk; süresi dolunca hemen yeniden başlat):
   ```bash
   tail -n0 -F .chat/inbox.jsonl 2>/dev/null | python3 -u -c "
   import sys,json
   for l in sys.stdin:
       try: print('CAD-CHAT mesaj:', json.loads(l)['text'].replace(chr(10),' / ')[:600], flush=True)
       except Exception: pass"
   ```
   Monitor olayı mesajı 600 karakterde keser. Tam metni her zaman dosyadan oku:
   `python3 -c "import json;print(json.loads(open('.chat/inbox.jsonl').read().splitlines()[-1])['text'])"`

## 2. Sohbet sayfasına cevap ver
- Sayfadan gelen her mesaja **sayfadan** cevap ver: `cad-reply . "mesaj"`.
  Kullanıcı Termux'tan yazdıysa Termux'tan cevap ver.
- Uzun işlerde ara durum bildir: "kuruyorum", "v2 görüntüleyicide", "şu kontrol FAIL, seçenekler…".
- Bir spec kısıtı sağlanamıyorsa sessizce değiştirme. Ölç, nedenini açıkla,
  numaralı seçenekler sun (A/B/C) ve kullanıcının seçimini bekle.
- Görüntüleyici sayfanın üst yarısında canlı güncellenir. Her başarılı `agentcad run` onu yeniler.

## 3. Çalıştırma
- `agentcad` komutu bir sarmalayıcıdır: Ubuntu (proot) içinde çalışır, JSON çıktısını stdout'a,
  ilerleme bilgisini stderr'e yazar. Bu ikisini birleştirme: `> out.json 2> err.txt`.
- Önce `--dry-run`, sonra gerçek çalıştırma: `agentcad run model.py --label vN --export stl`.
  Bir çalıştırma telefonda yaklaşık 20 saniye sürer.
- Script içinde STEP yazma. STEP'i agentcad yazar (`outputs.step`).
- Çıktıdaki `preview.png` dosyasını mutlaka oku (Read) ve kontrol et.
- Doğrulama scriptin içinde de varsa raporu stderr'e ve `verify_report.txt` dosyasına yaz.
  stdout'a yazma, agentcad'in JSON çıktısını bozar.

## 4. Bilinen tuzaklar (bu ortamda yaşandı)
- **`@dataclass` + exec:** agentcad scripti `exec` ile çalıştırır, `@dataclass` ise modül kaydı ister.
  Dataclass tanımından önce şunu ekle:
  ```python
  import sys, types
  if sys.modules.get(globals().get("__name__", "")) is None:
      _m = types.ModuleType(globals().get("__name__", "script")); _m.__dict__.update(globals())
      sys.modules[_m.__name__] = _m
  ```
- **Builder bağlamı:** `with BuildPart():` içinde oluşturulan her `Box`, `extrude(...)` vb.
  otomatik olarak parçaya EKLENİR. Kesici gövdeleri bağlamın dışında üret, Boolean'ı
  cebirle yap (`part = a + b - c`).
- **`Polygon` ve `Rectangle` varsayılan olarak ortalanır.** Mutlak koordinat için `align=None` ver.
- **`ocp_vscode`:** Statik import kontrolünde hata verir. Gerekirse `importlib.import_module` kullan.
- **Çizgi teması:** İki gövde yalnızca bir kenar boyunca değerse manifold olmayan kenar
  ("edge shared by 4 triangles") çıkar. ~1 mm bindir.
- **Kenar seçimi:** Kenar seçerken sadece uç noktalarına bakma, doğrultusunu da kontrol et
  (`_edges(..., along=...)`). Aksi halde dar açılı kenarlara pah uygulanır ve overhang ihlali doğar.
- **Konkav yuvarlatma:** Telefon veya parça temas bölgesine malzeme ekleyebilir. Bunu kesişim
  hacmiyle doğrula.
- **3MF desteklenmez:** lib3mf yerine bir yer tutucu kurulu. STEP, STL, GLB ve OBJ çalışır.

## 5. Teslim
Kullanıcı onay verince teslim et:
```bash
pocad deliver {{NAME}} build/<sürüm>   # <sürüm> = outputs.step dosyasının klasörü (ör. build/v3 veya build/v4_v3-A)
```
Komut, doğrulanmış sürümü `{{DELIVER}}/{{NAME}}/` altına kopyalar:
- `cikti/`: STL, STEP, GLB ve önizleme
- `src/`: proje kökündeki `*.py`, `*.md`, `verify_report.txt` ve `agentcad.toml`

Teslimden önce proje kökünde iki dosya hazırla:
- `spec.md`: kullanıcının spec'i
- `README.md`: doğrulama özeti, onaylı sapmalar, yorumlar ve baskı notları

Örnek bir teslim için PoCAD reposunda `examples/telefonstandi/` klasörüne bak.
