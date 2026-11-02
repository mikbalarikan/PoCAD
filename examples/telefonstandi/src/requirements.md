# Redmi Note 13 Pro masa standı — kabul listesi (Specify)

Kaynak: kullanıcı spec'i §0–§9 (sohbet, 2026-11-02). Koordinat: X genişlik (merkez 0), Y derinlik (ön=0, +arka), Z yukarı (tabla=0).
Yerel çerçeve: u=(cosθ, sinθ) sırtlık yönü, n=(−sinθ, cosθ) ekran normali. P(a,b) = S + a·u + b·n.

| # | Gereksinim | Kontrol yöntemi |
|---|---|---|
| 1 | Tek parça, manifold, geçerli katı | agentcad `is_valid`, `expect_solids: 1` |
| 2 | Hacim ≤ 40 000 mm³ | verify(): `part.volume` |
| 3 | Portre kutu 75×162.3×8 kesişim = 0, sırtlık+raf teması < 0.05 mm | verify(): Boolean ∩ hacmi, `distance_to` |
| 4 | Landscape kutu 162.3×75×8 aynı | verify() |
| 5 | Landscape sırtlık temas bölgesi |X| ≤ 35 | verify(): sırtlık düzlemi arkasındaki 0.05 mm dilimin X sınırı |
| 6 | Fiş keep-out prizması ∩ stand = 0 | verify() |
| 7 | Aşağı bakan ve yataydan < 45° yüz yok (yatay köprü istisnası: üst çubuk altı, kablo kesik tavanları) | verify(): yüz normal örneklemesi |
| 8 | F_tip ≥ 0.9 N (portre) | verify(): R etrafında moment |
| 9 | Toplam CG 0 < Y < D (iki mod) | verify() |
| 10 | Dudak ön yüzü örtmesi ≤ 5 mm | lip_h = 5 (parametre) |
| 11 | Min duvar ≥ 2.4, eleman ≥ 6×6 | parametreler + görsel |
| 12 | Kablo çentiği |X| ≤ 7, arka kablo kesiği 14×7 | görsel + keep-out kontrolü |
| 13 | Telefon temaslı dış kenarlar ≥ 0.8 kırık, üst çubuk ön-üst R1.5, dudak ön-üst 0.8 pah, taban dış alt kenar 0.6 pah | görsel / kenar seçimi raporu |

## Varsayımlar / yorumlar (spec'te açık değil)
- Raf bloğu, sırtlık elemanının arkasına (b = −member_w) kadar uzanır; böylece sırtlıkla bütünleşir.
- "45° pah ile iner": raf bloğunun alt yüzeyi rafın arka-alt kenarından (P(−floor_t, −member_w)) 45° ile öne-aşağı inen tek düz yüzdür; bu çizgi tablaya ön duvarın içinde ulaştığı için blok, ön duvarı da içeren dolu bir kama olur.
- Kablo çentiği: |X| ≤ notch_w/2 bandında, sırtlık düzleminin önündeki (b ≥ 0) tüm malzeme, raf yüzeyinin 10 mm üstünden 30 mm altına (a ∈ [−30, 10]) kadar kaldırılır → kablo ön duvardan aşağı-öne çıkar. Keep-out prizması bu bandın içinde kalır.
- Üst çubuğun alt yüzü yatay köprü olarak yapılır (spec §6'daki tek izinli köprü).
- Çerçeve iç köşe yuvarlatması (fillet_r) yalnızca boşluğun köşenin üstünde kaldığı köşelere uygulanır; hücre tepelerindeki köşeler keskin bırakılır (aksi halde yay aşağı bakar → §6 overhang ihlali).
- Devrilme hesabında stand kütlesi, spec'in kendi oranıyla (40 cm³ ≈ 35 g → 0.875 g/cm³, baskı kütlesi) alınır; dolu PLA (1.24) ile de raporlanır.
- STEP dosyasını agentcad yazar (script STEP yazmaz); stand.step/stand.stl, doğrulanmış agentcad çıktılarından kopyalanır.
