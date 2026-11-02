#!/data/data/com.termux/files/usr/bin/bash
# PoCAD kurulumu — Android telefonda (Termux) build123d + agentcad CAD istasyonu.
#
#   git clone https://github.com/mikbalarikan/PoCAD ~/PoCAD && cd ~/PoCAD && ./install.sh
#
# Tekrar çalıştırılabilir; kurulu adımlar atlanır. Toplam indirme ~1–1.5 GB, süre 15–30 dk.
set -euo pipefail
REPO="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
# proot-distro sürümüne göre konum değişir (installed-rootfs/ veya containers/)
ubuntu_installed() {
  [ -d "$PREFIX/var/lib/proot-distro/containers/ubuntu" ] || [ -d "$PREFIX/var/lib/proot-distro/installed-rootfs/ubuntu" ]
}
warn() { printf '\033[1;33m!  %s\033[0m\n' "$*"; }

[ -n "${PREFIX:-}" ] && [ -d /data/data/com.termux ] || { echo "Bu betik Termux içinde çalışmalı."; exit 1; }

step "1/5 Termux paketleri"
pkg update -y >/dev/null 2>&1 || true
pkg install -y proot-distro python git curl termux-tools >/dev/null
echo "   tamam"

step "2/5 Ubuntu (proot-distro)"
if ubuntu_installed; then
  echo "   zaten kurulu"
else
  proot-distro install ubuntu
fi

step "3/5 CAD ortamı (Python 3.12 + OCP 7.8 + build123d 0.10 + agentcad 0.7.1)"
proot-distro login ubuntu --bind "$REPO:/pocad" -- env POCAD_SRC=/pocad bash /pocad/scripts/setup-ubuntu.sh

step "4/5 PoCAD komutları (~/bin)"
mkdir -p "$HOME/bin"
chmod +x "$REPO"/bin/* "$REPO"/install.sh
for f in agentcad cad-viewer cad-chat.py cad-reply pocad; do
  ln -sf "$REPO/bin/$f" "$HOME/bin/$f"
done
grep -q 'HOME/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"
export PATH="$HOME/bin:$PATH"
echo "   pocad, agentcad, cad-viewer, cad-chat.py, cad-reply → ~/bin"

step "5/5 Depolama ve kontrol"
if [ ! -w /sdcard ] 2>/dev/null; then
  warn "Telefon hafızasına yazma izni yok. Teslim klasörü (/sdcard/PoCAD) için şunu çalıştırın: termux-setup-storage"
fi
mkdir -p "$HOME/cad"
pocad doctor || true

cat <<'EOF'

PoCAD kuruldu. Sonraki adımlar:
  source ~/.bashrc
  pocad new ornek-proje        # proje oluşturur, istasyon sayfasını tarayıcıda açar
  cd ~/cad/ornek-proje && claude   # bu dizinde Claude Code başlatın; CLAUDE.md talimatları otomatik yüklenir

Ayrıntılar: README.md ve docs/
EOF
