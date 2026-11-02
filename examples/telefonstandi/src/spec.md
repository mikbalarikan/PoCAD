# SPEC — Redmi Note 13 Pro Masa Standı (dikey + yatay), build123d

## 0. Özet
Tek parça, destek gerektirmeyen, PLA'dan basılacak bir frame/truss telefon standı. Telefon, eğik bir sırtlığa yaslanır ve alt kenarı dudaklı bir rafta durur. Aynı geometri hem portre hem landscape kullanımda çalışır. Gövde iki yan çerçeveden (truss) ve aralarındaki az sayıda çapraz elemandan oluşur. Hedef, malzemeyi minimumda tutup yeterli rijitliği sağlamak.

Çıktılar: `stand.py` (parametrik), `stand.step`, `stand.stl`, ve konsola basılan bir doğrulama raporu (bkz. §7).

## 1. Referans cihaz (zarf ölçüleri)
| Varyant | Yükseklik | Genişlik | Kalınlık | Kütle |
|---|---|---|---|---|
| Note 13 Pro 5G | 161.15 | 74.24 | 7.98 | 187 g |
| Note 13 Pro 4G | 162.24 | 74.95 | 7.98 | 188 g |

**Tasarım zarfı (her ikisini kapsar):** 162.3 × 75.0 × 8.0 mm, 190 g.
- Kamera modülü arka yüzde, sol üst köşede, gövdeden ~2 mm çıkıntılı. Kamera adası kenarlardan ~35 mm içeriye kadar uzanır (bkz. §9, ölçülecek).
- USB-C portu alt kenarın ortasında. Alt hoparlör de alt kenarda.
- Güç ve ses tuşları sağ kenarda.
- Kılıf toleransı: kalınlığa +3 mm'ye kadar izin verilir.

## 2. Koordinat sistemi (build123d)
- **X**: genişlik. Merkez X=0, toplam genişlik `W`.
- **Y**: derinlik. Ön kenar Y=0, arkaya doğru +Y.
- **Z**: yukarı. Baskı tablası Z=0.
- Yan profil YZ düzleminde çizilir ve X yönünde extrude edilir.
- Baskı yönü, modelin kullanım yönüyle aynıdır (taban tablaya oturur).

## 3. Fonksiyonel gereksinimler
1. **Portre ve landscape:** Aynı stand, telefonu hem dikey hem yatay tutar.
2. **Görüş açısı:** Telefonun arka yüzü yataydan `θ = 70°` eğimli bir düzleme yaslanır.
3. **Şarj:** Portre modda USB-C kablo takılı kullanılabilir. Bunun için rafta merkez çentik ve fiş için boşluk (keep-out) gerekir.
4. **Kamera:** Sırtlık temas bölgesi |X| ≤ 35 mm içinde kalır. Böylece landscape modda kamera adası sırtlığa değmez.
5. **Ekran örtmeme:** Dudak, telefonun ön yüzünü en fazla 5 mm örter.
6. **Devrilme:** Portre modda ekranın üst kenarına dik dokunuşta devrilme kuvveti F_tip ≥ 0.9 N olmalı (§7 hesabı). Opsiyonel balast cebi ile bu değer artırılır.
7. **Baskı:** Destek malzemesi olmadan basılabilir (§6).
8. **Malzeme:** Katı hacim ≤ 40 cm³ olmalı (yaklaşık ≤ 35 g baskı, 2 perimetre ve %15 infill ile).

## 4. Parametreler (varsayılan değerler, mm/derece)
| Ad | Değer | Açıklama |
|---|---|---|
| `theta` | 70 | Sırtlık eğimi (yataydan) |
| `W` | 64 | Toplam genişlik (X) |
| `D` | 115 | Taban derinliği (Y) |
| `S_y`, `S_z` | 24, 32 | Raf tabanı ile sırtlık düzleminin kesişim noktası S |
| `slot_w` | 12 | Raf derinliği (telefon kalınlığı + kılıf + boşluk), sırtlığa dik ölçülür |
| `floor_t` | 4 | Raf tabanı kalınlığı |
| `lip_h` | 5 | Dudak yüksekliği (raf yüzeyinden, sırtlık yönünde) |
| `lip_t` | 3 | Dudak kalınlığı |
| `back_len` | 65 | Sırtlık uzunluğu, S'den itibaren |
| `frame_t` | 6 | Yan çerçeve plaka kalınlığı (X) |
| `member_w` | 6 | Yan çerçeve elemanlarının düzlem içi genişliği |
| `base_h` | 5 | Taban rayı yüksekliği |
| `front_wall_t` | 3 | Ön duvar kalınlığı (tam genişlik) |
| `top_bar_h`, `top_bar_t` | 8, 4 | Sırtlık üst çapraz çubuğu (u yönünde yükseklik, kalınlık) |
| `rear_bar_h`, `rear_bar_t` | 8, 6 | Arka taban çapraz çubuğu |
| `notch_w` | 14 | Raf merkez kablo çentiği genişliği (X) |
| `plug_len` | 25 | USB-C fiş ve gerilim giderici uzunluğu (keep-out) |
| `plug_t`, `plug_wd` | 7, 12 | Fiş kesiti |
| `rear_cable_w`, `rear_cable_h` | 14, 7 | Arka çubuktaki kablo çıkış kesiği |
| `B_y` | 52 | Diyagonallerin tabana bağlandığı düğüm |
| `fillet_r` | 2 | Profil iç köşe yuvarlatması |
| `bed_chamfer` | 0.6 | Taban alt kenar pahı (elephant foot için) |
| `ballast` | False | Arka çubukta balast cebi (açılırsa 2× M10 somun, Ø17 × 9) |

Yardımcı vektörler (YZ düzleminde):
- `u = (cosθ, sinθ)`: sırtlık yönü, yukarı.
- `n = (−sinθ, cosθ)`: ekran normali, kullanıcıya doğru.

## 5. Geometri

### 5.1 Türetilmiş düğümler (θ = 70° için yaklaşık değerler)
- **S** = (24, 32): raf yüzeyi ile sırtlık düzleminin kesişimi.
- **F** = S + slot_w·n ≈ (12.7, 36.1): raf ön ucu, dudak dibi.
- **T** = S + back_len·u ≈ (46.2, 93.1): sırtlık üst ucu.
- **A0** = (0, 0): ön taban köşesi.
- **B** = (B_y, 0) = (52, 0): diyagonal taban düğümü.
- **R** = (D, 0) = (115, 0): arka taban köşesi.

Bu değerler kodda parametrelerden hesaplanmalı, sabit girilmemeli.

### 5.2 Yan çerçeveler (2 adet)
Her biri `frame_t` kalınlıkta YZ profili olarak çizilir. X = ±(W/2 − frame_t/2) konumuna yerleştirilir.

Elemanlar `member_w` genişliğinde şeritlerdir (build123d `trace()` veya segment başına offset).

Truss topolojisi, düğümler arası:
1. **Taban rayı:** A0 → R. Yükseklik `base_h`, tablaya oturur.
2. **Sırtlık:** S → T. Elemanın ön yüzü tam olarak sırtlık düzlemi üzerinde olmalı; eleman bu düzlemin arkasına (−n yönüne) kalınlaşır.
3. **Arka dikme:** T → R.
4. **Diyagonal 1:** S → B.
5. **Diyagonal 2:** T → B.
6. **Ön dikme:** Dudak alt-ön köşesi → A0. Bu eleman ön duvarla çakışır.

İç köşelerde `fillet_r` yuvarlatma uygulanır. Ortaya çıkan tüm hücreler üçgen olmalı (rijitlik için).

### 5.3 Çapraz elemanlar (tam genişlik W, yan çerçeveleri birleştirir)
1. **Raf bloğu:**
   - Üst yüzey S–F çizgisidir. Kalınlığı `floor_t` (−u yönünde).
   - F noktasında `lip_t` × `lip_h` boyutunda dudak bulunur. Dudağın ön-üst kenarında 0.8 mm pah olmalı.
   - Raf altı overhang olmasın: blok alt yüzeyi, rafın arka-alt kenarından ön duvara 45° (veya daha dik) bir pah ile iner.
2. **Ön duvar:** Dudağın alt-ön kenarından A0'a uzanan plaka, kalınlığı `front_wall_t`.
3. **Sırtlık üst çubuğu:** T noktasında, ön yüzü sırtlık düzleminde. Boyut `top_bar_h` × `top_bar_t`. Üst-ön kenarı R1.5 yuvarlatılır (telefonu çizmemesi için).
4. **Arka taban çubuğu:** R noktasında, tablaya oturur. Boyut `rear_bar_h` × `rear_bar_t`.

### 5.4 Kesikler
1. **Kablo çentiği:** Raf bloğu ve dudak boyunca, |X| ≤ notch_w/2 aralığında tam boy kesik. Kesik ön duvarın üst kısmını da alarak aşağıya açılır.
2. **Fiş keep-out:** Merkez bantta (|X| ≤ plug_wd/2 + 1), şu prizmanın içinde hiçbir malzeme olmamalı:
   - Başlangıç: S + (slot_w/2)·n noktası, raf yüzeyi seviyesi.
   - Yön: −u boyunca `plug_len`.
   - Kesit: (`plug_t` + 2) × (`plug_wd` + 2).
3. **Arka kablo çıkışı:** Arka taban çubuğunun merkezinde, tabla seviyesinden başlayan `rear_cable_w` × `rear_cable_h` kesik.
4. **Balast cebi (opsiyonel):** `ballast = True` ise arka çubukta, üstten açık 2 adet somun cebi. Bu durumda çubuk yüksekliği gerektiği kadar artırılır.

### 5.5 Kenar işlemleri
- Tabla temas yüzeyinin dış kenarlarına `bed_chamfer` uygulanır.
- Telefona temas eden tüm kenarlar en az 0.8 mm pah veya yuvarlatma ile kırılır.

## 6. Baskı kısıtları (DFM)
- **Yön:** Z+ yukarı. Taban rayları, ön duvar alt kenarı ve arka çubuk tablaya oturur.
- **Overhang:** Aşağı bakan tüm yüzeyler yataydan en az 45° olmalı. Tek istisna yatay köprülerdir.
- **Köprü:** Yatay köprü açıklığı ≤ 52 mm olabilir (yan çerçeveler arası). Yatay köprüler yalnızca sırtlık üst çubuğu ve kablo kesiklerinin tavanında kabul edilir.
- **Minimum ölçüler:** Duvar kalınlığı ≥ 2.4 mm (0.4 nozzle ile 3 hat). Eleman kesiti ≥ 6 × 6 mm.
- **Yüzey:** Tek parça, manifold, iç boşluksuz katı. STL çözünürlüğü: tolerance 0.01, angular 0.1.

## 7. Doğrulama (kod sonunda otomatik çalışmalı, PASS/FAIL basmalı)
1. **Hacim:** Katı hacim ≤ 40 000 mm³. Sonucu ve PLA kütlesini (ρ = 1.24) yazdır.
2. **Telefon kutusu çakışması:**
   - Portre: 75.0 × 162.3 × 8 mm kutu, arka yüzü sırtlık düzleminde, alt kenarı raf yüzeyinde, X'te ortalanmış. Stand ile kesişim hacmi 0 olmalı.
   - Landscape: 162.3 × 75.0 × 8 mm kutu, aynı koşullar. Kesişim hacmi 0 olmalı.
   - Her iki durumda kutunun sırtlığa ve rafa temas ettiği (mesafe < 0.05 mm) doğrulanmalı.
3. **Kamera temizliği:** Landscape modda sırtlık temas bölgesi |X| ≤ 35 içinde kalmalı.
4. **Fiş keep-out:** §5.4 maddesindeki prizma ile stand arasındaki kesişim hacmi 0 olmalı.
5. **Overhang:** Tüm yüz normalleri taranır. Aşağı bakan ve yataydan < 45° olan yüzlerden yatay köprü olmayanlar listelenir; liste boş olmalı.
6. **Devrilme (portre):**
   - Kuvvet F, S + 150·u noktasına ekrana dik (−n yönünde) uygulanır.
   - Arka kenar R etrafında moment dengesi kurulur. Restoring kütle = telefon (0.19 kg) + stand kütlesi.
   - Telefon CG'si S + 4·n + 80·u noktasındadır.
   - F_tip ≥ 0.9 N olmalı. Sağlanmıyorsa önce `D` artırılır, sonra `ballast` açılır.
7. **Ayak izi:** Telefon dahil toplam CG'nin YZ izdüşümü 0 < Y < D aralığında olmalı (her iki modda).

## 8. Kod yapısı
- Tek dosya `stand.py`, build123d builder mode kullanılır.
- Tüm parametreler dosyanın başında bir dataclass içinde toplanır.
- Fonksiyonlar: `side_frame()`, `cross_members()`, `cuts()`, `build()`, `verify(part)`, `export(part)`.
- Hiçbir ölçü hard-code edilmez. Düğümler §5.1'deki formüllerle hesaplanır.
- `ocp_vscode` ile `show()` çağrısı opsiyonel, bir flag ile açılıp kapanır.

## 9. Açık noktalar (kullanıcı kumpas ile teyit edecek)
- Kamera adasının çıkıntısı ve kenarlara olan mesafesi.
- Kullanılacak kılıfın kalınlığı. Gerekirse `slot_w` güncellenir.
- Kullanılacak USB-C kablonun fiş uzunluğu. Gerekirse `plug_len` ve `S_z` güncellenir; S_z artırılırsa fiş için daha fazla boşluk açılır.
- Landscape kullanımda tuşlu sağ kenar yukarı gelecek şekilde yerleştirilmeli. Aksi halde güç/ses tuşları rafa basabilir.