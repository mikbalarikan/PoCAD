# PoCAD geliştirme rehberi (coding agent'lar için)

Bu dosya **PoCAD reposunun kendisini geliştiren** agent'lar içindir (Claude Code, Codex,
Gemini CLI, OpenCode…). Kullanıcı projelerine kopyalanan agent kuralları
`templates/CLAUDE.md` dosyasındadır; ikisini karıştırma.

Kullanıcıyla, commit mesajlarında ve belgelerde **Türkçe** yaz. Kod tanımlayıcıları
mevcut stile uyar.

## Repo
| Yol | İçerik |
|---|---|
| `install.sh`, `scripts/setup-ubuntu.sh` | Termux + Ubuntu (proot) kurulumu |
| `bin/` | `pocad`, `agentcad` sarmalayıcısı, `cad-chat.py` istasyon sunucusu, `cad-reply`, istasyon sayfası |
| `scripts/stl_export.py` | STEP → STL + su geçirmezlik kontrolü |
| `templates/CLAUDE.md` | Her kullanıcı projesine kopyalanan agent kuralları |
| `pocad/` | Yeni çekirdek paketi (build123d 0.13 / OCP 8); `pocad/_ocp.py` OCP sürüm farkları |
| `tests/` | pytest testleri |
| `docs/` | Mimari, sorun giderme, yeni telefon kurulumu |
| `docs/tasarim/` | Onaylı tasarım belgeleri ve uygulama planları (Superpowers) |

Mimarinin ayrıntısı: `docs/MIMARI.md`. Değişiklik yapmadan önce oku.

## İş akışı: Superpowers
Bu repo [obra/superpowers](https://github.com/obra/superpowers) yöntemini kullanır.
Claude Code'da `.claude/settings.json` eklentiyi otomatik önerir (`/plugin` ile onayla).
Diğer agent'larda bir kez kur: Codex CLI'da `/plugins` → "superpowers"; diğerleri için
superpowers README'sindeki kurulum bölümüne bak.

Her özellik ya da düzeltme şu sırayla ilerler:
1. **brainstorming:** Ne yapılacağını kullanıcıyla netleştir. Büyük işlerde tasarım belgesini
   `docs/tasarim/YYYY-AA-GG-<konu>.md` olarak yaz ve onay al.
2. **using-git-worktrees:** Ayrı branch/worktree aç, testlerin temiz geçtiğini doğrula.
3. **writing-plans:** 2–5 dakikalık görevlere böl; her görevde dosya yolu ve doğrulama adımı olsun.
4. **subagent-driven-development:** Her görev için yeni alt-agent, ardından iki aşamalı review
   (önce spec'e uygunluk, sonra kod kalitesi).
5. **test-driven-development:** Önce başarısız test, sonra en küçük kod, sonra yeşil.
6. **requesting-code-review:** Kritik bulgu varsa ilerleme.
7. **verification-before-completion** ve **finishing-a-development-branch:** "Bitti" demeden
   önce aşağıdaki kontrolleri çalıştır ve çıktısını göster.

Küçük, tek dosyalık düzeltmelerde 1 ve 3 kısaltılabilir; test ve review kısaltılmaz.

## Kontroller
```bash
pip install -r requirements-dev.txt          # pytest + ruff
ruff check .
pytest -m "not cad"                           # hızlı testler, CAD çekirdeği gerekmez
pip install -r requirements-cad.txt           # build123d 0.13 + OCP 8 (x86_64/aarch64 Linux, macOS)
pytest -m cad                                 # CAD testleri
shellcheck -S warning install.sh bin/pocad bin/agentcad bin/cad-viewer scripts/*.sh
```
CI (`.github/workflows/ci.yml`) bunların hepsini her PR'da çalıştırır. Kırmızı CI ile merge yok;
test atlatmak, silmek ya da `skip` eklemek yasak.

## Test yazma kuralları
- `bin/` betikleri Termux shebang'i taşır ve modül düzeyinde çalışır. Testler onları
  `sys.executable` ile **alt süreç** olarak başlatır (`tests/conftest.py` → `Station`).
- Sahte proje yapısı için `conftest.add_version()` kullan (`build/agentcad.json` + sürüm klasörü).
- build123d isteyen testler `pytestmark = pytest.mark.cad` taşır.
- Gerçek telefon gerektiren davranışlar (proot, Xvfb, `termux-*`, `/sdcard`) CI'da test edilemez.
  Bunları PR açıklamasında "cihazda denendi: …" diye yaz.

## Değişmez kurallar
- **Sürüm sabitleri (geçiş dönemi):**
  - Yeni çekirdek `pocad/`: build123d 0.13.0, OCP 8.0.1.1 (`cadquery-ocp-novtk`), Python 3.12
    (`requirements-cad.txt`, CI'da x86_64 ve ARM64).
  - Telefon kurulumu ve `bin/`: agentcad kaldırılana kadar (Plan 09) agentcad 0.7.1,
    build123d 0.10.0, OCP 7.8.1.1, `ocp_gordon<0.3` (`scripts/setup-ubuntu.sh`).
    `bin/` ve `scripts/` kodu iki sürümde de çalışmalı.
  - Bir sabiti değiştirirsen ilgili dosyaları ve README'yi birlikte güncelle.
- **OCP adları:** OCP koleksiyon tipleri, TopoDS downcast'leri ve sürümle değişen diğer adlar
  yalnız `pocad/_ocp.py` üzerinden kullanılır.
- **Shebang'ler:** `bin/` içindeki `#!/data/data/com.termux/...` satırlarına dokunma.
- **Güvenlik:** `cad-chat` yalnızca `127.0.0.1`'e bağlanır; `/_pocad/file` izin listesiyle çalışır.
  Bu sınırları gevşeten değişiklik, test ve açık gerekçe ister.
- **Arayüz kimliği:** İstasyon sayfası Türkişi Engineering palet v5'e uyar (`docs/MIMARI.md`).
- Gizli bilgi (API anahtarı, token) repoya girmez.
