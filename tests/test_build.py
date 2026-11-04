"""pocad.build: model.py ayrı süreçte çalışır, çıktılar ölçülür, sürüm kaydı tutulur."""
import json

import pytest

pytestmark = pytest.mark.cad
pytest.importorskip("build123d")
pytest.importorskip("OCP.collections", reason="pocad OCP 8 ister")

from pocad import build, project  # noqa: E402

KUTU = "from build123d import Box\nresult = Box(20, 10, 5)\n"


def proje(tmp_path, model=KUTU, **export):
    p = project.init(tmp_path / "p", name="p")
    p.model.write_text(model, encoding="utf-8")
    if export:
        toml = p.root / "pocad.toml"
        text = toml.read_text()
        for k, v in export.items():
            text = text.replace(f"{k} = {project.DEFAULT_EXPORT[k]}", f"{k} = {v}")
        toml.write_text(text)
    return project.open_project(p.root)


def rapor(p, n):
    return json.loads((p.version_dir(n) / "report.json").read_text(encoding="utf-8"))


def olcum(rep, name):
    return rep["results"][name]["measured"]


def test_saglam_kutu_insa_edilir_ve_olculur(tmp_path):
    p = proje(tmp_path)
    out = build.build(p, "ilk")
    assert out["status"] == "built", out["error"]
    assert out["n"] == 1
    vdir = p.version_dir(1)
    for f in ("output.step", "output.stl", "output.glb", "model.py", "report.json"):
        assert (vdir / f).is_file(), f
    rep = rapor(p, 1)
    assert rep["schema"] == "pocad-report-v1" and rep["status"] == "built"
    assert (olcum(rep, "solid_count"), olcum(rep, "brep_valid"), olcum(rep, "naked_edges")) == (1, 1, 0)
    assert [round(olcum(rep, f"envelope_size_{a}"), 6) for a in "xyz"] == [20, 10, 5]
    assert olcum(rep, "volume_mm3") == pytest.approx(1000.0)
    assert olcum(rep, "step_schema") == 1 and olcum(rep, "step_roundtrip_solids") == 1
    assert rep["results"]["stl_max_sagitta"]["status"] == "MEASURED"
    assert rep["files"]["output.step"]["sha256"] and rep["versions"]["build123d"] == "0.13.0"
    assert p.registry().versions()[0]["status"] == "built"


def test_soz_dizimi_hatasi_basarisiz_kaydedilir_ve_numara_artar(tmp_path):
    p = proje(tmp_path, model="from build123d import Box\nresult = Box(20, 10\n")
    out = build.build(p, "bozuk")
    assert out["status"] == "failed"
    assert "SyntaxError" in out["error"] and "line 2" in out["error"]
    assert rapor(p, 1)["status"] == "failed"
    p.model.write_text(KUTU)
    assert build.build(p, "düzeldi")["n"] == 2
    assert [v["status"] for v in p.registry().versions()] == ["failed", "built"]


def test_result_tanimsizsa_aciklayan_hata(tmp_path):
    out = build.build(proje(tmp_path, model="x = 1\n"), "boş")
    assert out["status"] == "failed" and "result" in out["error"]


def test_result_sekil_degilse_aciklayan_hata(tmp_path):
    out = build.build(proje(tmp_path, model="result = 42\n"), "sayı")
    assert out["status"] == "failed" and "result" in out["error"] and "int" in out["error"]


def test_zaman_asiminda_surec_oldurulur(tmp_path):
    p = proje(tmp_path, model="while True:\n    pass\n", timeout_s=2)
    out = build.build(p, "sonsuz")
    assert out["status"] == "failed" and "zaman aşımı" in out["error"]
    assert out["duration_s"] < 30


def test_iki_govde_insa_edilir_ama_olcum_bunu_soyler(tmp_path):
    model = ("from build123d import Box, Compound, Pos\n"
             "result = Compound([Box(5, 5, 5), Pos(20, 0, 0) * Box(5, 5, 5)])\n")
    p = proje(tmp_path, model=model)
    out = build.build(p, "iki")
    assert out["status"] == "built", out["error"]
    assert olcum(rapor(p, 1), "solid_count") == 2


def test_her_surum_kendi_model_kopyasini_tutar(tmp_path):
    p = proje(tmp_path)
    build.build(p, "a")
    p.model.write_text(KUTU.replace("Box(20, 10, 5)", "Box(30, 10, 5)"))
    build.build(p, "b")
    assert "Box(20, 10, 5)" in (p.version_dir(1) / "model.py").read_text()
    assert "Box(30, 10, 5)" in (p.version_dir(2) / "model.py").read_text()
    assert round(olcum(rapor(p, 2), "envelope_size_x"), 6) == 30


def test_betik_ciktisi_loga_girer(tmp_path):
    p = proje(tmp_path, model="print('merhaba atölye')\n" + KUTU)
    build.build(p, "log")
    assert "merhaba atölye" in rapor(p, 1)["log"]


def test_betik_proje_dizininde_calisir(tmp_path):
    """model.py yanındaki bir dosyayı göreli yolla okuyabilir (ör. ölçü tablosu)."""
    p = proje(tmp_path, model="from pathlib import Path\nw = float(Path('w.txt').read_text())\n"
              "from build123d import Box\nresult = Box(w, 10, 5)\n")
    (p.root / "w.txt").write_text("12")
    assert build.build(p, "göreli")["status"] == "built"
    assert round(olcum(rapor(p, 1), "envelope_size_x"), 6) == 12


# ── sağlamlık (Plan 04 review) ───────────────────────────────────────────────
def test_utf8_olmayan_cikti_build_i_cokertmez(tmp_path):
    p = proje(tmp_path, model="import sys\nsys.stdout.buffer.write(b'\\xff\\xfe bozuk\\n')\n" + KUTU)
    out = build.build(p, "bayt")
    assert out["status"] == "built", out["error"]
    assert "bozuk" in rapor(p, 1)["log"]


def test_yarim_kalmis_surum_klasoru_numarayi_kilitlemez(tmp_path):
    p = proje(tmp_path)
    p.version_dir(1).mkdir(parents=True)             # çökmüş bir build'den kalan klasör
    out = build.build(p, "sonraki")
    assert out["n"] == 2 and out["status"] == "built"
    assert build.build(p, "bir sonraki")["n"] == 3


def test_hazirlik_hatasi_da_basarisiz_surum_olarak_kaydedilir(tmp_path):
    p = proje(tmp_path)
    p.model.unlink()
    out = build.build(p, "modelsiz")
    assert out["status"] == "failed" and "model.py yok" in out["error"]
    p.model.write_text(KUTU)
    assert build.build(p, "model geldi")["status"] == "built"
    assert [v["status"] for v in p.registry().versions()] == ["failed", "built"]


def surec_var(pid):
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_modelin_biraktigi_surec_buildi_bekletmez_ve_durdurulur(tmp_path):
    model = ("import subprocess, sys\n"
             "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
             "open('pid.txt', 'w').write(str(child.pid))\n" + KUTU)
    p = proje(tmp_path, model=model, timeout_s=60)
    out = build.build(p, "torun")
    assert out["status"] == "built", out["error"]
    assert out["duration_s"] < 50
    pid = int((p.root / "pid.txt").read_text())
    import time
    for _ in range(50):
        if not surec_var(pid):
            break
        time.sleep(0.1)
    assert not surec_var(pid)


def test_zaman_asiminda_torun_surecler_de_durdurulur(tmp_path):
    model = ("import subprocess, sys, time\n"
             "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
             "open('pid.txt', 'w').write(str(child.pid))\n"
             "time.sleep(300)\n")
    p = proje(tmp_path, model=model, timeout_s=3)
    out = build.build(p, "asım")
    assert out["status"] == "failed" and "zaman aşımı" in out["error"]
    import time
    pid = int((p.root / "pid.txt").read_text())
    for _ in range(50):
        if not surec_var(pid):
            break
        time.sleep(0.1)
    assert not surec_var(pid)


@pytest.mark.parametrize("model,beklenen", [
    ("import os\nos._exit(3)\n", "çıkış kodu 3"),
    ("import ctypes\nctypes.string_at(0)\n", "SIGSEGV"),
])
def test_yorumlayici_cokmesi_kaydedilir(tmp_path, model, beklenen):
    out = build.build(proje(tmp_path, model=model), "çökme")
    assert out["status"] == "failed" and beklenen in out["error"]


def test_basarisiz_buildde_yarim_ciktilar_silinir(tmp_path):
    p = proje(tmp_path, model=KUTU + "import time\ntime.sleep(300)\n", timeout_s=2)
    build.build(p, "asım")
    assert not any((p.version_dir(1) / f).exists() for f in build.OUTPUTS)
    assert rapor(p, 1)["files"] == {}


def test_ayni_anda_ikinci_build_aciklayan_hatayla_reddedilir(tmp_path):
    import os
    p = proje(tmp_path)
    (p.versions_dir / ".build.lock").write_text(str(os.getpid()))
    with pytest.raises(build.BuildBusy, match="başka bir build"):
        build.build(p, "ikinci")
    (p.versions_dir / ".build.lock").write_text("999999999")    # ölmüş süreçten kalan kilit
    assert build.build(p, "kilit eskimiş")["status"] == "built"


def test_main_blogundaki_result_icin_ipucu(tmp_path):
    model = "if __name__ == '__main__':\n    " + KUTU.replace("\n", "\n    ")
    out = build.build(proje(tmp_path, model=model), "main")
    assert out["status"] == "failed" and "__main__" in out["error"]


def test_proje_kokundeki_json_py_calistiriciyi_bozamaz(tmp_path):
    p = proje(tmp_path, model="import helper\n" + KUTU)
    (p.root / "json.py").write_text("raise RuntimeError('gölge modül')\n")
    (p.root / "helper.py").write_text("W = 1\n")
    assert build.build(p, "gölge")["status"] == "built"


def test_buildi_baslatan_surec_olurse_model_de_durdurulur(tmp_path):
    """Agent oturumu kapanınca MCP sunucusu ölür; çalıştırıcı sahipsiz ve zaman sınırsız kalmamalı."""
    import os
    import signal
    import subprocess
    import sys
    import time

    from conftest import ROOT
    p = proje(tmp_path, model="import os, time\nopen('pid.txt', 'w').write(str(os.getpid()))\n"
              "time.sleep(300)\n" + KUTU, timeout_s=600)
    kod = f"from pocad import build, project\nbuild.build(project.open_project({str(p.root)!r}), 'yetim')\n"
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    sunucu = subprocess.Popen([sys.executable, "-c", kod], env=env)
    pid_dosyasi = p.root / "pid.txt"
    for _ in range(200):
        if pid_dosyasi.exists() and pid_dosyasi.read_text():
            break
        time.sleep(0.1)
    model_pid = int(pid_dosyasi.read_text())
    sunucu.send_signal(signal.SIGKILL)
    sunucu.wait()
    for _ in range(100):
        if not surec_var(model_pid):
            break
        time.sleep(0.1)
    assert not surec_var(model_pid)
    p.model.write_text(KUTU)
    out = build.build(p, "sonraki")                           # ölü kilit ve yarım sürüm engel olmaz
    assert out["status"] == "built" and out["n"] == 2
