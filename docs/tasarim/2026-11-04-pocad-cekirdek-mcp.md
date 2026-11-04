# Tasarım: PoCAD çekirdeği ve MCP sunucusu (Aşama 1)

Tarih: 2026-11-04 · Durum: **ONAYLANDI 2026-11-04** · Superpowers adımı: brainstorming → tasarım belgesi

## 1. Amaç

agentcad'i kaldırıp yerine kendi altyapımızı koymak. Kaynaklar:

- **oguz-atolye:** `tools/` (ölçüm, geçerlilik, dışa aktarım, çizim), Result/gate sözleşmesi, `GATES.md`,
  tasarımcı/denetçi doktrini, `gateway/`
- **agentic_STL-to-CAD:** `stl-re-*` skill'leri ve script'leri
- **PoCAD:** kurulum, istasyon sayfası, sohbet köprüsü

Bunların hepsi PoCAD reposunda tek çatı altında, **agent'tan bağımsız bir MCP sunucusu** ve
**agentskills formatında skill'ler** olarak toplanır. Hangi coding agent bağlanırsa bağlansın
(Claude Code, Codex, Gemini CLI, OpenCode) aynı araçları ve aynı kuralları görür.

### Aşama 1'in kapsamı
- Python paketi `pocad` (çekirdek, ölçüm, gate, proje/sürüm yönetimi)
- MCP sunucusu `pocad-mcp` (tasarım hattı araçları)
- Yeni görüntüleyici (three.js, GLB, sürüm şeridi); agentcad görüntüleyicisinin yerine
- Tasarımcı ve denetçi skill'leri, proje şablonu (`AGENTS.md`)
- Telefon kurulumunun sadeleşmesi (micromamba, conda ve shim'ler gider)
- Tersine mühendislik (RE) hattı: **Aşama 1b**, tasarım hattı bittikten sonra

### Kapsam dışı (sonraki aşamalar)
- Android uygulaması (Aşama 2)
- API anahtarı modu ve gömülü agent döngüsü (`gateway/` taşınması, Aşama 2)
- Blender render, video hattı, teknik çizim PDF'i ve müşteri paketi (masaüstü özellikleri, sonra)

## 2. Kararlar

| # | Karar | Gerekçe |
|---|---|---|
| K-1 | **build123d 0.13.0 + OCP 8.0 (`cadquery-ocp-novtk`)** | OCP 7.9+ ARM64 Linux tekerleği PyPI'de var; conda/micromamba gerekmez. STL-to-CAD zaten 0.13 ile test edildi. |
| K-2 | **Python 3.12**, Ubuntu 24.04'ün kendi Python'u + venv | Telefonda ek Python indirmeye gerek yok. 0.13 3.11–3.14 destekliyor. oguz-atolye 3.13'e sabitliydi; testler 3.12'de doğrulanacak. |
| K-3 | **Tek repo (PoCAD)** | Tek CI, tek sürüm sabiti, tek değişiklik akışı. |
| K-4 | **Kişiliksiz ürün** | Oğuz karakteri ve `persona-guard` taşınmaz. Doktrindeki "Usta" rolü = **kullanıcı**. |
| K-5 | **agentcad tamamen çıkar** | Sürüm kilidi kalkar; görüntüleyici ve sürüm yönetimi bizim olur. |
| K-6 | **Müşteri ve marka verisi taşınmaz** | `library/`, `reference-jobs/`, `golden-examples/`, `examples/` (STL-to-CAD) gizli kalır. Test parçaları sentetik ve parametrik üretilir. |
| K-7 | **Taşınan kod MIT lisansıyla PoCAD'e girer** | İki reponun sahibi aynı kişi. Her taşınan dosyanın başında kaynak notu bulunur. |

### 2.1 Sürüm doğrulaması (2026-11-04, x86_64, Python 3.13)

build123d 0.13.0 + cadquery-ocp-novtk 8.0.1.1 ile mevcut testler:

| Test takımı | Sonuç |
|---|---|
| oguz-atolye `tools/tests`, değişiklik yapmadan | Test modülleri içe aktarılamıyor (OCP 8'de isimler değişmiş) |
| oguz-atolye `tools/tests`, uyumluluk katmanıyla | **986 geçti, 2 kaldı.** Kalan ikisi `0.11.1` sürüm dizesini bekleyen testler. |
| STL-to-CAD `stl-re-deliver` testleri | 33/33 geçti |
| STL-to-CAD `stl-re-measure-intent` testleri | 28/28 geçti |

OCP 8'deki değişiklikler:
- `TopoDS.Face_s` vb. → `TopoDS.Face`
- `TopTools_IndexedMapOfShape` / `…DataMapOfShapeListOfShape` → `OCP.collections.*`
- `BRepTopAdaptor_FClass2d` → `IntTools_FClass2d`

Bunlar `pocad/_ocp.py` adlı tek bir uyumluluk modülünde toplanır; taşınan kod OCP'yi doğrudan değil bu modül üzerinden kullanır.
Python 3.12 ve ARM64 doğrulaması 12. bölümün 1. adımıdır.

## 3. Mimari

```
 Agent (Claude Code / Codex / …)                    PoCAD (Ubuntu proot ya da masaüstü Linux/macOS)
┌──────────────────────────────┐   MCP (stdio)   ┌──────────────────────────────────────────────┐
│ AGENTS.md + skills/          │ ──────────────▶ │ pocad-mcp                                    │
│  pocad-design, pocad-review  │ ◀────────────── │  ├ proje: init, status, spec                 │
│  (stl-re-* → Aşama 1b)       │                 │  ├ build: model.py → alt süreçte çalıştır    │
└──────────────────────────────┘                 │  ├ measure / gates / section / preview       │
                                                 │  └ export / deliver / reply                  │
 İstasyon sayfası (tarayıcı)                     │                                              │
┌──────────────────────────────┐   HTTP 127.0.0.1│ pocad.station (cad-chat'in devamı)           │
│ three.js görüntüleyici (GLB) │ ◀────────────── │  ├ /_chat/*  sohbet (inbox/outbox.jsonl)     │
│ sürüm şeridi · sohbet · gate │                 │  ├ /_pocad/info, /_pocad/file                │
└──────────────────────────────┘                 │  └ /v/<n>/output.glb  (vekil yok, doğrudan)  │
                                                 └──────────────────────────────────────────────┘
                                                   pocad.core · pocad.measure · pocad.result (+ build123d/OCP)
```

### 3.1 Paket düzeni
```
pocad/
  __init__.py
  _ocp.py            YENİ: OCP 8 isimleri için tek uyumluluk noktası
  result.py          ← oguz tools/result.py  (Result, gate; değişmeden)
  core/              ← oguz tools/core       (validity, step, mesh, boolean, fillet, shapes)
  measure/           ← oguz tools/measure    (wall, props, features, draft, radial, assembly …)
  project.py         YENİ: proje dizini, sürüm kaydı (agentcad'in yerine)
  build.py           YENİ: model.py'yi alt süreçte çalıştırma, dışa aktarım, rapor
  gates/             GATES alt kümesi: gates.toml (makine okur) + GATES.md (insan okur)
  machines/          ← oguz atolye/machines/*.toml (yazıcı hacimleri)
  station/           ← bin/cad-chat.py + pocad-page.html + viewer (three.js)
  mcp/server.py      YENİ: MCP araçları
skills/
  pocad-design/SKILL.md   ← designer-doctrine (sadeleştirilmiş)
  pocad-review/SKILL.md   ← reviewer-doctrine (sadeleştirilmiş)
templates/              proje şablonu: AGENTS.md, CLAUDE.md (@AGENTS.md), SPEC.md
bin/                    cad-reply (geçiş süresince); agentcad sarmalayıcısı ve bash `pocad` → kaldırılır
pocad/cli.py            `pocad` komutu (Python), MCP araçlarının komut satırı karşılığı (S-3)
```

## 4. Proje dizini (agentcad'in yerine)

```
~/cad/<proje>/
  pocad.toml          ad, süreç (fdm/sla/cnc), makine, gate profili, dışa aktarım toleransı
  SPEC.md             şartname: gereksinimler + varsayım defteri (A-##) + gate tablosu
  model.py            parametrik build123d betiği; `result` değişkenine parçayı atar
  versions/
    registry.json     [{n, label, status, created, inputs_sha256}]
    v3/
      model.py        o sürümün kopyası (yeniden üretilebilirlik)
      output.step     AP242 (pocad.core.write_step)
      output.stl      pocad.core.write_stl, ölçülen sagitta ile
      output.glb      görüntüleyici için
      preview.png     4 görünüm (matplotlib, Xvfb gerekmez)
      report.json     validity + ölçümler + gate satırları (Result/Gate.row())
  reviews/RV01.json   denetçi kararı (verdict şeması)
  .chat/              inbox.jsonl, outbox.jsonl (mevcut sözleşme korunur)
```

- **Sürüm numarası** başarılı ya da başarısız her build'de artar. Başarısız build'in `report.json`'unda hata ve iz kaydı bulunur.
- **Önizleme** matplotlib ile, B-rep'ten üretilen mesh üzerinden çizilir. Bu sayede Xvfb, Mesa ve OpenGL gereksinimi kalkar.

## 5. MCP araçları (tasarım hattı)

Her araç JSON döndürür. Sayılar her zaman `Result`/`Gate` biçimindedir: "ölçülemedi" (INCONCLUSIVE) asla PASS sayılmaz.

| Araç | Girdi | Çıktı | Not |
|---|---|---|---|
| `project_init` | ad, süreç, makine | proje yolu | `pocad.toml`, `SPEC.md` şablonu, `.chat/` |
| `project_status` | proje | son sürüm, gate özeti, bekleyen mesajlar | oturum başında ve devralmada (resume) |
| `build` | proje, etiket | sürüm no, validity, ölçüler, dosyalar, hata | `model.py` **alt süreçte**, zaman sınırıyla çalışır; OCC çökmesi sunucuyu düşürmez |
| `gates` | proje, sürüm | gate tablosu (PASS / PASS_ASSUMED / FAIL / INCONCLUSIVE) | eşikler `SPEC.md` + `gates.toml`'dan |
| `measure` | proje, sürüm, ölçüm adı, parametreler | Result | `min_wall`, `envelope`, `bore_census`, `clearance` … |
| `section` | proje, sürüm, düzlem, ofset | PNG yolu | denetçinin görsel kontrolü |
| `preview` | proje, sürüm | PNG yolu | 4 görünüm |
| `export` | proje, sürüm, biçimler, tolerans | dosyalar + round-trip kontrolü | U-04, U-07 |
| `review_record` | proje, sürüm, karar JSON'u | RV## yolu | şemaya karşı doğrular |
| `deliver` | proje, sürüm | teslim klasörü | yalnız APPROVED ya da kullanıcı kabulüyle |
| `chat_inbox` / `chat_reply` | proje, since / metin | mesajlar / ok | istasyon sohbeti, agent'tan bağımsız |

**Ayrılık ilkesi (oguz-atolye PLAYBOOK §1):** denetçinin skill'i `model.py`'yi okumayı yasaklar ve
yalnız `measure`, `gates`, `section` araçlarını dışa aktarılmış dosyalar üzerinde kullanır. Bu
yasak skill'de yazılıdır. Claude Code'da ek olarak bir hook ile zorlanır (oguz `reviewer_guard`
uyarlanır); diğer agent'larda yalnız talimattır.

## 6. Gate'ler

- `pocad/gates/gates.toml`: oguz-atolye `GATES.md`'nin **Aşama 1 alt kümesi**, makine okunur biçimde.
  - **§U:** U-01 (geçerli tek gövde), U-02 (zarf), U-04 (temiz dışa aktarım), U-07 (STL toleransı)
  - **§D (FDM):** D-01a/b (duvar), D-02 (tabla), D-04a–d (delik ve boşluklar), D-06a (en küçük detay)
  - Satırlar `Kaynak` ve `Güven` sütunlarını korur.
- `SPEC.md` gate tablosu bu satırları seçer ve limitleri doldurur. **Varsayıma dayanan PASS, `PASS (varsayım: A-##)` olarak raporlanır.**
- `tools.result.gate()` tek karşılaştırma noktasıdır. `band` parametresinin varsayılanı yoktur.

## 7. Roller ve iş akışı (kişiliksiz)

```
SPEC     ana oturum: kullanıcıyla şartname + varsayım defteri      → KULLANICI onaylar
PLAN     tasarımcı (taze alt-agent): özellik sırası, 1-3 konsept   → KULLANICI seçer
BUILD    tasarımcı: model.py → build → gates (kendi ölçümü)
REVIEW   denetçi (taze alt-agent, mümkünse başka model ailesi): bağımsız ölçüm → RV##
         APPROVED → DELIVER · REVISE → KULLANICI karar verir (yeni tur / sapmayı kabul / dur)
DELIVER  export + teslim klasörü                                   → KULLANICI
```

- **Tek denetim, sonra kullanıcı karar verir** (oguz-atolye ilke 4). Otomatik döngü yoktur.
  STL-to-CAD'deki "en fazla 3 döngü" kuralıyla çelişir; bkz. §11 S-1.
- Alt-agent desteklemeyen agent'larda roller aynı oturumda sırayla çalışır. Denetim yine "kodu okumadan,
  dosyalardan ölç" kuralıyla yapılır; bu durum rapora yazılır.

## 8. Görüntüleyici

- three.js (sabit sürüm, MIT, repoya gömülü; internet gerektirmez) + `GLTFLoader` + `OrbitControls`
- Sürüm değişince kamera korunur (bugünkü `agentcad:capture/restore` davranışı).
- Palet v5 koyu tema doğrudan sayfada; vekil ve HTML enjeksiyonu gerekmez. `X-Frame-Options` sorunu ortadan kalkar.
- Kesit görünümü: Aşama 1'de `section` aracının PNG'si, sonra three.js clipping plane.

## 9. Kurulumun sadeleşmesi

`scripts/setup-ubuntu.sh`:

| Bugün | Sonra |
|---|---|
| micromamba, conda-forge `ocp=7.8.1.1` | `apt install python3.12-venv` |
| `cadquery-ocp` metadata shim'i, lib3mf shim'i | `python3.12 -m venv /opt/pocad` |
| `--no-deps` pip kurulumları | `pip install -r requirements.lock` (hash'li, ARM64 tekerlekleri) |
| Xvfb, Mesa | önizleme matplotlib ile → gerekmez |

3MF: lib3mf'in ARM64 tekerleği hâlâ yok; 3MF Aşama 1'de de kapalı kalır.

## 10. Taşıma kuralları ve testler

1. **Her modül testleriyle birlikte taşınır.** oguz `tools/tests` (fixtures/parts.py, mutations/MANIFEST.json)
   0.13'te yeşil olmadan modül alınmaz. Kırılan test düzeltilir, silinmez.
2. **Kaynak notu:** dosya başında `# kaynak: oguz-atolye tools/core/validity.py @ca27b1b`.
3. **Sentetik veri:** gizli projelerden geometri, isim ya da sayı girmez.
4. **CI'a ARM64 işi eklenir:** GitHub'ın `ubuntu-24.04-arm` koşucusu (açık repolarda ücretsiz).
   Telefonla aynı mimaride CAD testleri koşar.
5. **MCP sözleşme testleri:** her araç için örnek çağrı → JSON şeması doğrulaması, hatalı girdi → anlamlı hata.
6. **Uçtan uca test:** kutu-braket örneği `project_init → build → gates → review_record → deliver`.

## 11. Kullanıcı kararları (2026-11-04)

- **S-1 Denetim döngüsü: ONAY.** Tasarım hattında tek denetim, sonra kullanıcı karar verir; otomatik döngü yok.
  RE hattındaki "en fazla 3 döngü" kuralı Aşama 1b'de ayrıca kararlaştırılır.
- **S-2 Gate kapsamı: ONAY.** Aşama 1'de yalnız FDM (§U + §D). Plastik enjeksiyon, CNC ve diğer
  DFM kuralları sonraki bir aşamada eklenecek; `gates.toml` buna uygun olarak süreç başına bölümlere ayrılır.
- **S-3 CLI: ONAY.** `pocad` Python CLI'ya dönüşür; komutlar MCP araçlarının birebir karşılığıdır.

## 12. Uygulama sırası (her biri ayrı küçük PR)

1. Sürüm doğrulaması: `pocad/_ocp.py` + oguz `tools/tests` 0.13 ve Python 3.12'de (x86 ve ARM64 CI). x86 ve Python 3.13'te ön deneme yapıldı, bkz. §2.1
2. `pocad.result` + `pocad.core` + testleri
3. `pocad.measure` + testleri
4. `pocad.project` + `pocad.build` (agentcad'siz build ve sürüm kaydı)
5. `pocad-mcp`: project_*, build, gates, export
6. Görüntüleyici + istasyonun yeni sürüm yapısına geçişi
7. measure / section / preview / review_record / deliver araçları
8. Skill'ler (pocad-design, pocad-review) + proje şablonu
9. `setup-ubuntu.sh` sadeleşmesi, agentcad'in kaldırılması, belgeler
10. Uçtan uca test + telefonda gerçek cihaz denemesi
