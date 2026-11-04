"""pocad._ocp: OCP 8 isimleri tek yerden; oguz-atolye kodunun kullandığı eski adların karşılıkları."""
import pytest

pytestmark = pytest.mark.cad
bd = pytest.importorskip("build123d")
pytest.importorskip("OCP.collections", reason="pocad OCP 8 ister (geçiş dönemi: eski kurulumda OCP 7.8)")

from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_OUT  # noqa: E402
from OCP.TopExp import TopExp  # noqa: E402

from pocad import _ocp  # noqa: E402


def kutu():
    return bd.Box(10, 10, 10).wrapped


def yuzler():
    m = _ocp.IndexedMapOfShape()
    TopExp.MapShapes_s(kutu(), TopAbs_FACE, m)
    return m


def test_indexed_map_of_shape_bir_kutunun_alti_yuzunu_tutar():
    assert yuzler().Size() == 6


def test_kenar_yuz_haritasi_her_kenara_iki_yuz_verir():
    d = _ocp.IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(kutu(), TopAbs_EDGE, TopAbs_FACE, d)
    assert d.Size() == 12
    assert all(d.FindFromIndex(i).Size() == 2 for i in range(1, 13))


@pytest.mark.parametrize("ad", ["Vertex", "Edge", "Wire", "Face", "Shell", "Solid", "Compound", "CompSolid"])
def test_downcast_fonksiyonlari_var(ad):
    assert callable(getattr(_ocp.downcast, ad))


def test_downcast_yuzu_topods_face_yapar():
    assert type(_ocp.downcast.Face(yuzler().FindKey(1))).__name__ == "TopoDS_Face"


def test_fclass2d_yuz_ortasini_ice_disi_disa_siniflar():
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt2d

    f = _ocp.downcast.Face(yuzler().FindKey(1))
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    c = _ocp.FClass2d(f, 1e-7)
    assert c.Perform(gp_Pnt2d((u0 + u1) / 2, (v0 + v1) / 2)) == TopAbs_IN
    assert c.Perform(gp_Pnt2d(u1 + 100, v1 + 100)) == TopAbs_OUT


def test_surumler_raporlanir():
    v = _ocp.versions()
    assert v["build123d"] == "0.13.0"
    assert v["ocp"].startswith("8.0")
