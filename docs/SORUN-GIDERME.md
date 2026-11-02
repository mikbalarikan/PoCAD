# Sorun giderme

| Belirti | Neden | Çözüm |
|---|---|---|
| Sayfada "127.0.0.1 bağlanmayı reddetti" | Görüntüleyici başka porttan iframe'de açıldı (X-Frame-Options), ya da görüntüleyici servisi kapalı | Sayfayı her zaman `pocad url` adresinden aç. `pocad status`; kapalıysa `pocad start AD` |
| Üstte "Henüz model yok" | Henüz başarılı bir `agentcad run` yok | İlk build'den sonra sayfa kendiliğinden yenilenir |
| `agentcad viewer status` → running: false | `agentcad viewer open` servisi proot oturumu kapanınca ölür | `pocad start` (cad-viewer servisi ayakta tutar) |
| pip: `cadquery-ocp 7.8 bulunamadı` | aarch64 tekerleği yok | `scripts/setup-ubuntu.sh`'yi tekrar çalıştır (shim kaydını yeniler) |
| `TopoDS has no attribute 'Vertex'` / `No module named 'OCP.collections'` | Yanlış OCP sürümü (build123d 0.11+ veya ocp_gordon 0.3+ geldi) | Sürümler sabit: build123d 0.10.0, `ocp_gordon<0.3`. Ortamı sil (`rm -rf /opt/mamba/envs/cad`, Ubuntu içinde) ve tekrar kur |
| `AttributeError: 'NoneType' object has no attribute '__dict__'` | `@dataclass` + agentcad `exec` | templates/CLAUDE.md §4'teki modül kaydı kalıbı |
| Fazladan katı gövde, ters işlem | `with BuildPart():` içinde üretilen kesiciler parçaya eklendi | Kesicileri bağlam dışında üret, `a + b - c` cebiri kullan |
| `invalid_geometry … edge shared by 4 triangles` | İki gövde sadece bir kenarda temas ediyor | ~1 mm bindirme |
| `Import error: module 'ocp_vscode' not found` | agentcad statik import kontrolü | `importlib.import_module("ocp_vscode")` |
| PNG önizleme hatası (X11/GLX) | Sanal ekran yok | `bin/agentcad` Xvfb'yi otomatik başlatır; Ubuntu'da `xvfb` paketi kurulu mu bak |
| Termux'tan `/sdcard` okunamıyor | Depolama izni yok | `termux-setup-storage` → İzin ver |
| Sohbet mesajı Claude'a gelmiyor | Monitor süresi dolmuş veya başlatılmamış | Claude'a "sohbet sayfasını dinle" de. CLAUDE.md §1'deki komut |
| Uzun mesaj Claude'da kesik görünüyor | Monitor olayı 600 karakterle sınırlı | Normal: Claude tam metni `.chat/inbox.jsonl`'dan okur |
