"""pocad.project: proje dizini, pocad.toml ve sürüm kaydı (CAD gerektirmez)."""
import json

import pytest

from pocad import project


def test_init_proje_iskeletini_kurar(tmp_path):
    p = project.init(tmp_path / "braket", name="braket")
    root = tmp_path / "braket"
    assert p.root == root.resolve()
    for name in ("pocad.toml", "SPEC.md", "model.py", "versions/registry.json", ".chat/inbox.jsonl",
                 ".chat/outbox.jsonl"):
        assert (root / name).is_file(), name
    assert p.name == "braket" and p.process == "fdm"
    assert p.export == {"stl_tolerance": 0.01, "stl_angular_tolerance": 0.1, "timeout_s": 600}


def test_init_mevcut_projenin_ustune_yazmaz(tmp_path):
    project.init(tmp_path / "braket", name="braket")
    (tmp_path / "braket" / "model.py").write_text("# benim modelim\n")
    with pytest.raises(FileExistsError):
        project.init(tmp_path / "braket", name="braket")
    assert (tmp_path / "braket" / "model.py").read_text() == "# benim modelim\n"


@pytest.mark.parametrize("bad", ["", "a/b", "..", "x y", "ç" * 3])
def test_gecersiz_proje_adi_reddedilir(tmp_path, bad):
    with pytest.raises(ValueError):
        project.init(tmp_path / "p", name=bad)


def test_desteklenmeyen_surec_reddedilir(tmp_path):
    with pytest.raises(ValueError, match="fdm"):
        project.init(tmp_path / "p", name="p", process="cnc")


def test_open_toml_degerlerini_okur(tmp_path):
    project.init(tmp_path / "p", name="p", machine="bambu-lab-p2s")
    toml = tmp_path / "p" / "pocad.toml"
    toml.write_text(toml.read_text().replace("timeout_s = 600", "timeout_s = 30"))
    p = project.open_project(tmp_path / "p")
    assert p.machine == "bambu-lab-p2s"
    assert p.export["timeout_s"] == 30


def test_open_proje_olmayan_dizinde_hata(tmp_path):
    with pytest.raises(FileNotFoundError, match="pocad.toml"):
        project.open_project(tmp_path)


def test_kayit_bos_baslar_ve_numaralar_artar(tmp_path):
    p = project.init(tmp_path / "p", name="p")
    reg = p.registry()
    assert reg.versions() == [] and reg.next_number() == 1
    reg.record({"n": 1, "label": "a", "status": "failed"})
    reg.record({"n": 2, "label": "b", "status": "built"})
    assert reg.next_number() == 3
    assert [v["n"] for v in project.open_project(tmp_path / "p").registry().versions()] == [1, 2]
    data = json.loads((tmp_path / "p" / "versions" / "registry.json").read_text())
    assert data["schema"] == "pocad-registry-v1"


def test_kayit_ayni_numarayi_iki_kez_almaz(tmp_path):
    reg = project.init(tmp_path / "p", name="p").registry()
    reg.record({"n": 1, "label": "a", "status": "built"})
    with pytest.raises(ValueError):
        reg.record({"n": 1, "label": "tekrar", "status": "built"})


def test_kayit_atomik_yazilir_gecici_dosya_kalmaz(tmp_path):
    reg = project.init(tmp_path / "p", name="p").registry()
    for n in range(1, 6):
        reg.record({"n": n, "label": str(n), "status": "built"})
    assert sorted(x.name for x in (tmp_path / "p" / "versions").iterdir()) == ["registry.json"]


def test_son_basarili_surum(tmp_path):
    reg = project.init(tmp_path / "p", name="p").registry()
    assert reg.latest_built() is None
    reg.record({"n": 1, "label": "a", "status": "built"})
    reg.record({"n": 2, "label": "b", "status": "failed"})
    assert reg.latest_built()["n"] == 1
    assert p_dir(tmp_path, 1).name == "v1"


def p_dir(tmp_path, n):
    return project.open_project(tmp_path / "p").version_dir(n)


@pytest.mark.parametrize("satir,eski,beklenen", [
    ('timeout_s = "abc"', "timeout_s = 600", "export.timeout_s"),
    ("timeout_s = 0", "timeout_s = 600", "export.timeout_s"),
    ("stl_tolerance = -1", "stl_tolerance = 0.01", "export.stl_tolerance"),
    ('process = "cnc"', 'process = "fdm"', "process"),
    ('name = "../x"', 'name = "p"', "name"),
    ("name = [", 'name = "p"', "TOML okunamadı"),
])
def test_pocad_toml_dogrulanir(tmp_path, satir, eski, beklenen):
    project.init(tmp_path / "p", name="p")
    toml = tmp_path / "p" / "pocad.toml"
    text = toml.read_text()
    assert eski in text
    toml.write_text(text.replace(eski, satir, 1))
    with pytest.raises(ValueError, match=beklenen):
        project.open_project(tmp_path / "p")


@pytest.mark.parametrize("icerik", ["{bozuk", "[]", '{"schema": "pocad-registry-v1"}',
                                    '{"schema": "pocad-registry-v1", "versions": [{"x": 1}]}'])
def test_bozuk_kayit_aciklayan_hata_verir(tmp_path, icerik):
    p = project.init(tmp_path / "p", name="p")
    (p.versions_dir / "registry.json").write_text(icerik)
    with pytest.raises(ValueError, match="registry.json"):
        p.registry().versions()
