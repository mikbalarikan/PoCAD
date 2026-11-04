"""stl_export: STEP → STL ve su geçirmezlik kontrolü. build123d gerektirir (`-m cad`)."""
import subprocess
import sys

import pytest

from conftest import SCRIPTS

pytestmark = pytest.mark.cad
bd = pytest.importorskip("build123d")


def export(src, dst):
    return subprocess.run([sys.executable, str(SCRIPTS / "stl_export.py"), str(src), str(dst)],
                          capture_output=True, text=True)


def test_kapali_govde_su_gecirmez(tmp_path):
    step = tmp_path / "kutu.step"
    part = bd.Box(20, 10, 5) - bd.Cylinder(2, 5)
    bd.export_step(part, str(step))
    r = export(step, tmp_path / "kutu.stl")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "su geçirmez" in r.stdout
    assert (tmp_path / "kutu.stl").stat().st_size > 0


def test_acik_kabuk_sorunlu_olarak_raporlanir(tmp_path):
    step = tmp_path / "yuzey.step"
    kutu = bd.Box(10, 10, 10)
    bd.export_step(bd.Compound([bd.Shell(kutu.faces()[:-1])]), str(step))  # üst yüzü eksik kutu
    r = export(step, tmp_path / "yuzey.stl")
    assert r.returncode == 1
    assert "SORUNLU" in r.stdout
