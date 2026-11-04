"""OCP 8'de değişen adlar pocad içinde yalnız pocad/_ocp.py'de geçer (AGENTS.md: OCP adları)."""
import re

from conftest import ROOT

ESKI_ADLAR = re.compile(r"\bTopoDS\.\w+_s\b|\bTopTools_Indexed\w*MapOfShape\w*|\bBRepTopAdaptor_FClass2d\b")


def kaynaklar():
    for base in ("pocad", "tests/fixtures"):
        for p in sorted((ROOT / base).rglob("*.py")):
            if p.name != "_ocp.py":
                yield p


def test_ocp_adlari_yalniz_uyumluluk_modulunde():
    bulunan = [f"{p.relative_to(ROOT)}:{i}: {m.group(0)}"
               for p in kaynaklar()
               for i, satir in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
               for m in ESKI_ADLAR.finditer(satir)]
    assert bulunan == []


def test_denetim_eski_adi_yakalar(tmp_path):
    assert ESKI_ADLAR.search("TopoDS.Face_s(x)") and ESKI_ADLAR.search("TopTools_IndexedMapOfShape()")
    assert not ESKI_ADLAR.search("downcast.Face(x)")
