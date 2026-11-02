#!/bin/bash
# PoCAD — Ubuntu (proot-distro) içinde CAD ortamı kurulumu. install.sh tarafından çağrılır.
# Tekrar çalıştırılabilir (idempotent): kurulu adımları atlar.
#
# Neden bu kadar dolambaçlı?
#  * agentcad 0.7.1 -> Python 3.10–3.12 + build123d 0.10 + cadquery-ocp 7.8 ister.
#  * cadquery-ocp 7.8'in Linux aarch64 pip tekerleği YOK; conda-forge'da `ocp=7.8.1.1` var.
#  * Bu yüzden: micromamba ile Python 3.12 + OCP (conda-forge), geri kalanı pip --no-deps,
#    pip'in "cadquery-ocp kurulu değil" itirazına karşı metadata-only bir dist-info kaydı.
#  * lib3mf'in de aarch64 tekerleği yok -> yer tutucu modül (3MF devre dışı).
set -euo pipefail
POCAD_SRC="${POCAD_SRC:-/pocad}"
ENV=/opt/mamba/envs/cad
PY_VER=3.12
OCP_VER=7.8.1.1
BUILD123D_VER=0.10.0
AGENTCAD_VER=0.7.1
GORDON_SPEC="ocp_gordon<0.3"
export DEBIAN_FRONTEND=noninteractive MAMBA_ROOT_PREFIX=/opt/mamba
say() { printf '  [ubuntu] %s\n' "$*"; }

say "sistem paketleri (Xvfb, Mesa, OpenGL)…"
apt-get update -qq
apt-get install -y -qq curl bzip2 ca-certificates git xvfb xauth libgl1 libglu1-mesa libxrender1 \
  libegl1 libgl1-mesa-dri mesa-utils >/dev/null

case "$(uname -m)" in
  aarch64|arm64) MM_ARCH=linux-aarch64 ;;
  x86_64) MM_ARCH=linux-64 ;;
  *) echo "desteklenmeyen mimari: $(uname -m)"; exit 1 ;;
esac
if [ ! -x /usr/local/bin/micromamba ]; then
  say "micromamba ($MM_ARCH)…"
  (cd /usr/local && curl -fsSL "https://micro.mamba.pm/api/micromamba/$MM_ARCH/latest" | tar -xj bin/micromamba)
fi

if [ ! -x "$ENV/bin/python" ] || ! "$ENV/bin/python" -c "import OCP" 2>/dev/null; then
  say "Python $PY_VER + OCP $OCP_VER (conda-forge) — birkaç dakika sürer…"
  micromamba create -y -q -n cad -c conda-forge "python=$PY_VER" "ocp=$OCP_VER" pip >/dev/null
fi
P="$ENV/bin"
SP=$("$P/python" -c 'import site; print(site.getsitepackages()[0])')

say "shim'ler: cadquery-ocp kaydı + lib3mf yer tutucu…"
D="$SP/cadquery_ocp-$OCP_VER.dist-info"; mkdir -p "$D"
printf 'Metadata-Version: 2.1\nName: cadquery-ocp\nVersion: %s\nSummary: PoCAD shim - OCP conda-forge ocp paketinden gelir\n' "$OCP_VER" > "$D/METADATA"
echo pocad-shim > "$D/INSTALLER"
printf '%s\n' "cadquery_ocp-$OCP_VER.dist-info/METADATA,," "cadquery_ocp-$OCP_VER.dist-info/INSTALLER,," "cadquery_ocp-$OCP_VER.dist-info/RECORD,," > "$D/RECORD"
D2="$SP/lib3mf-2.4.1.dist-info"; mkdir -p "$D2"
printf 'Metadata-Version: 2.1\nName: lib3mf\nVersion: 2.4.1\nSummary: PoCAD shim (3MF desteklenmez)\n' > "$D2/METADATA"
echo pocad-shim > "$D2/INSTALLER"; : > "$D2/RECORD"
mkdir -p "$SP/lib3mf"; cp "$POCAD_SRC/shims/lib3mf/__init__.py" "$SP/lib3mf/__init__.py"

if ! "$P/python" -c "import build123d, agentcad" 2>/dev/null; then
  say "build123d $BUILD123D_VER + agentcad $AGENTCAD_VER…"
  W=/tmp/pocad-wheels; rm -rf "$W"; mkdir -p "$W"
  "$P/pip" download -q --no-deps "build123d==$BUILD123D_VER" "$GORDON_SPEC" "agentcad==$AGENTCAD_VER" -d "$W"
  "$P/python" - "$W" > /tmp/pocad-reqs.txt <<'PYEOF'
import glob, re, sys, zipfile
skip = {"cadquery-ocp", "cadquery_ocp", "build123d", "ocp-gordon", "ocp_gordon", "lib3mf"}
out = set()
for w in glob.glob(sys.argv[1] + "/*.whl"):
    z = zipfile.ZipFile(w)
    meta = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
    for line in z.read(meta).decode().splitlines():
        if not line.startswith("Requires-Dist:") or "extra ==" in line:
            continue
        req = line.split(":", 1)[1].strip()
        name = re.split(r"[ <>=!~;\[(]", req)[0].lower()
        if name.replace("_", "-") in {s.replace("_", "-") for s in skip}:
            continue
        out.add(req)
print("\n".join(sorted(out)))
PYEOF
  "$P/pip" install -q --root-user-action=ignore -r /tmp/pocad-reqs.txt pillow
  "$P/pip" install -q --root-user-action=ignore --no-deps "$W"/*.whl
fi

"$P/pip" check >/dev/null 2>&1 || say "uyarı: pip check bağımlılık uyarısı verdi (shim'ler nedeniyle olabilir)"
"$P/python" -c "import build123d, agentcad, OCP; print('  [ubuntu] OK: build123d', build123d.__version__)"
