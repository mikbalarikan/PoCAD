<img src="assets/pocad-logo.svg" alt="PoCAD" width="220">

# PoCAD — Phone CAD istasyonu

Eski bir Android telefonu, **Claude Code + build123d + agentcad** ile çalışan tek projelik bir
CAD iş istasyonuna çevirir. Bir telefon bir projeye ayrılır: ekranda canlı 3D model ve
Claude ile sohbet yan yana durur. Uygulama değiştirmeden tasarımı yönetirsin.

```
┌───────────────────────────┐
│  canlı 3D model           │  ← agentcad görüntüleyici; her başarılı build'de yenilenir
│  (döndür / yakınlaştır)   │
├───────────────────────────┤
│ Claude: v3 hazır, hacim…  │  ← Claude'un cevapları
│ [ mesajını yaz…    ] [➤]  │  ← yazdığın doğrudan Claude Code oturumuna gider
└───────────────────────────┘
```

- **CAD çekirdeği:** build123d 0.10 (OpenCascade 7.8), Python 3.12. Telefonun içindeki bir
  Ubuntu ortamında (proot) çalışır; root gerekmez.
- **Tasarım iş akışı:** [agentcad](https://github.com/jdilla1277/agentcad) 0.7.1
  (Inspect → Specify → Build → Validate → Deliver). STEP, STL ve GLB çıktısı, 4 görünümlü
  önizleme, geometri doğrulaması ve sürüm geçmişi sağlar.
- **İstasyon sayfası** (`cad-chat`): Görüntüleyici ve sohbet tek sayfada.
  Mesajlar dosya üzerinden Claude oturumuna gider; Claude `cad-reply` ile cevap verir.
  Tasarım Türkişi Engineering kimliğinde (palet v5, maskot B · Kumpas, PoCAD logosu):
  sürüm şeridi (ölçüler, hacim, doğrulama damgası), Sohbet / Doğrulama (`verify_report.txt`) /
  Çıktılar (dokununca indirilir) sekmeleri, Parlak Set'ten proje başına vurgu rengi ve
  arayüze not bırakmak için **İşaretle** modu (agentation usulü; not, seçicisiyle sohbete gider).
- **Teslim:** `pocad deliver` komutu `/sdcard/PoCAD/<proje>/` klasörüne `cikti/` (STL/STEP/GLB)
  ve `src/` (kaynak + spec) dosyalarını koyar.

İlk proje örneği: [`examples/telefonstandi`](examples/telefonstandi/). Redmi Note 13 Pro için
desteksiz basılan truss telefon standı.

## Gereksinimler
- Android 7+ ve **ARM64** (aarch64) telefon. Yaklaşık 3 GB boş alan; 4 GB+ RAM önerilir.
- [Termux](https://f-droid.org/packages/com.termux/) (F-Droid sürümü)
- Termux'ta çalışan Claude Code

## Kurulum
```bash
pkg install -y git
git clone https://github.com/mikbalarikan/PoCAD ~/PoCAD
cd ~/PoCAD && ./install.sh
termux-setup-storage          # teslim klasörü /sdcard/PoCAD için (bir kez)
source ~/.bashrc
pocad doctor                  # kontrol
```
`install.sh` tekrar çalıştırılabilir. Adımlar:
1. Termux paketlerini kurar: `proot-distro`, `python`, `git`, `curl`, `termux-tools`.
2. `proot-distro` ile Ubuntu kurar.
3. Ubuntu içinde ([`scripts/setup-ubuntu.sh`](scripts/setup-ubuntu.sh)) şunları kurar:
   Xvfb ve Mesa, micromamba, Python 3.12 + **conda-forge `ocp=7.8.1.1`**, ardından
   build123d 0.10.0, agentcad 0.7.1 ve `ocp_gordon<0.3` (`--no-deps` ile), bir de iki shim.
4. `bin/` altındaki komutları `~/bin` klasörüne bağlar.
5. Kurulumu kontrol eder (`pocad doctor`).

Yeni bir telefonda Claude'a ne yazacağını [`docs/YENI-TELEFON.md`](docs/YENI-TELEFON.md) anlatıyor.

## Kullanım
```bash
pocad new braket              # ~/cad/braket oluşturur, istasyon sayfasını tarayıcıda açar
cd ~/cad/braket && claude     # Claude Code; proje CLAUDE.md'si sohbet döngüsünü ve kuralları tanımlar
```
Ardından istasyon sayfasından spec'ini gönder. Claude modeli kurar, görüntüleyici güncellenir,
sorular ve seçenekler sohbete gelir. Onay verdiğinde Claude teslimi yapar:
```bash
pocad deliver braket build/v3_final     # → /sdcard/PoCAD/braket/{cikti,src,README.md}
```

| Komut | Ne yapar |
|---|---|
| `pocad new AD` | Proje oluşturur (agentcad init, CLAUDE.md) ve istasyonu başlatır |
| `pocad start AD [PORT]` | Görüntüleyici ve sohbet sunucusunu arka planda başlatır, sayfayı açar |
| `pocad stop AD` | Servisleri durdurur |
| `pocad status` | Projelerin servis durumunu ve adreslerini gösterir |
| `pocad deliver AD SÜRÜM` | Doğrulanmış sürümü teslim klasörüne kopyalar (STL su geçirmezlik kontrolüyle) |
| `pocad doctor` | Kurulumu kontrol eder |
| `agentcad …` | Ubuntu içindeki agentcad'i çağırır (Xvfb otomatik) |
| `cad-reply DİZİN "mesaj"` | Claude'un sohbet sayfasına yazması için |

Ortam değişkenleri: `POCAD_PROJECTS` (varsayılan `~/cad`), `POCAD_DELIVER` (varsayılan
`/sdcard/PoCAD`), `POCAD_STL_TOL` / `POCAD_STL_ANG` (varsayılan `0.01` / `0.1`),
`POCAD_NO_BROWSER=1`.

## Çok telefonlu kurulum
Her telefona aynı repoyu kur, her telefonda **bir** proje çalıştır. Claude Code'un
**Remote Control** özelliğiyle bütün oturumları claude.ai veya Claude uygulamasından da
izleyebilirsin. Ayrıntılar ve öneriler (şarj, ekranın açık kalması, kullanım limiti):
[`docs/MIMARI.md`](docs/MIMARI.md).

## Sınırlar
- 3MF desteklenmez (lib3mf'in aarch64 paketi yok); STEP, STL, GLB ve OBJ çalışır.
- CadQuery uyumluluk modu kurulmaz.
- Telefon işlemcisi basit ve orta karmaşıklıktaki parçalar için uygun. Büyük montajlar yavaştır.
- Servisler Termux açık kaldıkça çalışır.

Sorunlar ve çözümleri: [`docs/SORUN-GIDERME.md`](docs/SORUN-GIDERME.md)

## Lisans
PoCAD betikleri MIT lisanslıdır ([LICENSE](LICENSE)). agentcad (Apache-2.0), build123d (Apache-2.0)
ve OCP/OpenCascade (LGPL) kendi lisanslarıyla, kurulum sırasında kaynaklarından indirilir.
Bu repo onların kodunu içermez.
