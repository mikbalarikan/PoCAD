# Mimari

```
 Tarayıcı (telefon)                       Termux                                Ubuntu (proot)
┌──────────────────────┐  127.0.0.1:8765  ┌──────────────────────────┐        ┌──────────────────────────┐
│ istasyon sayfası     │ ───────────────▶ │ cad-chat.py              │ proxy  │ agentcad viewer_service  │
│  ├ iframe: görüntüle │ ◀─────────────── │  ├ /            sayfa     │ ─────▶ │  (127.0.0.1:<port>)      │
│  └ sohbet            │                  │  ├ /_chat/*     sohbet API│        │                          │
└──────────────────────┘                  │  └ /projects/*  → viewer │        │ agentcad run → STEP/GLB  │
                                          │                          │        │ build123d + OCP 7.8      │
        .chat/inbox.jsonl  ◀── yazar ─────┤                          │        │ Xvfb :99 (PNG önizleme)  │
        .chat/outbox.jsonl ── okur ──────▶│                          │        └──────────────────────────┘
                                          └──────────────────────────┘                 ▲
 Claude Code oturumu (proje dizininde)                                                 │
   Monitor: tail -F .chat/inbox.jsonl  → her mesaj bir bildirim                          │
   cad-reply . "…"                      → outbox.jsonl                                  │
   agentcad run model.py  (bin/agentcad sarmalayıcısı) ─────────────────────────────────┘
```

## Parçalar
| Dosya | Görev |
|---|---|
| `install.sh` | Termux tarafı: paketler, Ubuntu, `~/bin` bağlantıları |
| `scripts/setup-ubuntu.sh` | Ubuntu tarafı: micromamba, Python 3.12, conda-forge OCP 7.8, build123d/agentcad (`--no-deps`), shim'ler |
| `bin/agentcad` | Termux → Ubuntu sarmalayıcı. `$HOME` aynı yolla bağlanır (`--termux-home`); gerekirse Xvfb başlatır |
| `bin/cad-viewer` | agentcad görüntüleyici servisini ön planda tutar (proje başına `build/.agentcad/viewer`) |
| `bin/cad-chat.py` | İstasyon sunucusu: sohbet API'si, `/_pocad/info` (son sürümün ölçüleri, `verify_report.txt`, çıktılar), `/_pocad/file` (çıktı indirme), görüntüleyici için ters vekil + koyu tema enjeksiyonu |
| `bin/pocad-page.html` | İstasyon sayfası (Türkişi kimliği, palet v5). Her istekte diskten okunur; sunucuyu yeniden başlatmadan düzenlenebilir |
| `assets/pocad-logo.svg` | PoCAD logosu (vektörel, fonttan bağımsız) |
| `bin/cad-reply` | Claude'un sayfaya cevap yazması |
| `bin/pocad` | Proje yaşam döngüsü: new / start / stop / status / deliver / doctor |
| `templates/CLAUDE.md` | Her projeye kopyalanır: sohbet döngüsü, çalıştırma kuralları, tuzaklar, teslim |
| `shims/lib3mf` | lib3mf yer tutucu (3MF kapalı) |

## Neden böyle?
- **OCP 7.8, conda-forge'dan:** agentcad 0.7.1, build123d 0.10 ve cadquery-ocp 7.8'e sabitli.
  cadquery-ocp 7.8'in pip'te Linux aarch64 tekerleği yok, conda-forge'da var. pip'in
  bağımlılık çözücüsünü ikna etmek için metadata-only bir `cadquery-ocp` dist-info kaydı eklenir.
- **Ters vekil:** Görüntüleyici `X-Frame-Options: SAMEORIGIN` gönderir. Başka porttaki sayfanın
  iframe'inde "bağlanmayı reddetti" hatası verir. `cad-chat` onu kendi origin'i altında sunar.
- **Görüntüleyici adresi:** `/projects/<token>/`. Token, HMAC-SHA256(secret, build_root yolu)
  ile hesaplanır; `cad-chat` bunu config dosyasından kendisi çıkarır.
- **Sohbet = dosya:** Claude Code'a dışarıdan mesaj sokmanın en sağlam yolu, oturumun izlediği
  bir dosya (Monitor aracı). Oturum kapalıyken gelen mesajlar dosyada bekler.

## Çok telefon
- Her telefonda bir proje çalışır. Her biri ayrı bir Claude Code oturumudur.
- **Remote Control** ile oturumlar claude.ai/code ve Claude uygulamasında görünür.
  Oturumlar birbirine mesaj da gönderebilir; örneğin montajdaki delik ölçüleri bir
  telefondan diğerine iletilebilir.
- **Kullanım limiti** bütün oturumlarda ortaktır.
- **Batarya:** Sürekli şarjda kalacak telefonlarda şarjı %80'de sınırla, ekran parlaklığını düşür.
- **Ekranın açık kalması:** "Şarj olurken uyanık kal" ayarı ve `termux-wake-lock`
  (`pocad start` bunu çağırır).

## İstasyon sayfası
- Sayfa agentcad'in canlı kabuğunu değil, sürüm görüntüleyicisini (`artifacts/N/viewer.html`) doğrudan
  iframe'de açar. `state` uç noktasını kendisi yoklar; yeni sürümde kamera durumunu
  `agentcad:capture` / `agentcad:restore` mesajlarıyla korur.
- Görüntüleyici HTML'ine vekil üzerinden palet v5 koyu teması eklenir: lacivert çelik zemin, Parlak Gümüş
  parça, tek satır mod çubuğu (veri olmayan modlar gizli), katlanır Part controls.
- Renk kuralları: kırmızı (#AF1537) yalnız kimlik; yapı Çelik Mavisi; sahnede tek Parlak Set vurgusu
  (üstüne Derin yazılır); durum Geçti / Hata, her zaman işaret ve yazıyla.
