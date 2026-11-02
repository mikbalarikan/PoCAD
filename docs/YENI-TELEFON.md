# Yeni telefona PoCAD kurulumu

## 1. Telefonu hazırla (elle, ~10 dk)
1. **Termux**'u F-Droid'den kur. Play Store sürümü eskidir.
2. Termux'ta Claude Code'u kur ve giriş yap.
3. Telefonun **Wi-Fi**'a ve **şarja** bağlı olduğundan emin ol. Kurulum yaklaşık 1–1,5 GB indirir.
4. İsteğe bağlı: Geliştirici seçenekleri → **Şarj olurken uyanık kal**. Varsa
   pil ayarlarından **şarjı %80'de sınırla** özelliğini aç.

## 2. Claude'a şu mesajı yapıştır
```
PoCAD kurulumu yap: https://github.com/mikbalarikan/PoCAD
1. pkg install -y git && git clone https://github.com/mikbalarikan/PoCAD ~/PoCAD
2. README.md ve docs/ dosyalarını oku.
3. ~/PoCAD/install.sh'yi çalıştır (uzun sürer, arka planda çalıştır ve bitince haber ver).
4. Bitince termux-setup-storage için izin penceresini aç, ben "İzin ver"e basacağım.
5. pocad doctor ile kontrol et.
6. "pocad new <proje-adı>" ile projeyi oluştur ve istasyon sayfasını aç;
   proje adını bana sor.
7. Sonra proje dizininde çalışmaya geç: CLAUDE.md'deki kurallara göre sohbet sayfasını
   Monitor ile dinlemeye başla ve design spec'imi bekle.
```

## 3. Proje oturumu
Kurulumdan sonraki günlerde telefonu açınca:
```bash
cd ~/cad/<proje> && claude
```
Claude, `CLAUDE.md` sayesinde servisleri başlatır (`pocad start`) ve sohbet sayfasını dinler.
İstasyon sayfası: `pocad url <proje>`.

## 4. Kontrol listesi
- [ ] `pocad doctor` → "PoCAD hazır."
- [ ] İstasyon sayfası açılıyor, üstte "Henüz model yok" ya da model görünüyor
- [ ] Sayfadan yazılan "deneme" mesajına Claude sayfadan cevap veriyor
- [ ] `/sdcard/PoCAD` yazılabilir (termux-setup-storage yapıldı)
