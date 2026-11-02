"""STEP -> STL (belirtilen tessellation toleranslarıyla) + basit su geçirmezlik kontrolü.

kullanım: python stl_export.py girdi.step çıktı.stl [tolerance=0.01] [angular=0.1]
Her kenarın tam iki üçgen tarafından paylaşıldığını doğrular; değilse çıkış kodu 1.
"""
import collections
import struct
import sys

from build123d import export_stl, import_step

src, dst = sys.argv[1], sys.argv[2]
tol = float(sys.argv[3]) if len(sys.argv) > 3 else 0.01
ang = float(sys.argv[4]) if len(sys.argv) > 4 else 0.1

export_stl(import_step(src), dst, tolerance=tol, angular_tolerance=ang)

data = open(dst, "rb").read()
tris = []
if data[:5] == b"solid" and b"facet" in data[:400]:
    v = []
    for line in data.decode(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("vertex"):
            v.append(tuple(round(float(x), 5) for x in line.split()[1:]))
            if len(v) == 3:
                tris.append(v)
                v = []
else:
    n = struct.unpack("<I", data[80:84])[0]
    for i in range(n):
        f = struct.unpack("<12f", data[84 + 50 * i: 84 + 50 * i + 48])
        tris.append([tuple(round(x, 5) for x in f[3 + 3 * k: 6 + 3 * k]) for k in range(3)])

edges = collections.Counter()
for t in tris:
    for a, b in ((0, 1), (1, 2), (2, 0)):
        edges[tuple(sorted((t[a], t[b])))] += 1
bad = sum(1 for c in edges.values() if c != 2)
print(f"STL: {len(tris)} üçgen, {len(edges)} kenar, hatalı kenar {bad} → {'su geçirmez' if bad == 0 else 'SORUNLU'}")
sys.exit(0 if bad == 0 else 1)
