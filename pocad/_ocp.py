"""OCP sürüm farklarının tek karşılandığı yer.

OCP 8 (OCCT 8.0) koleksiyon tiplerini `OCP.collections` altına taşıdı, TopoDS
downcast'lerinden `_s` ekini kaldırdı ve `BRepTopAdaptor_FClass2d`'yi bıraktı.
pocad kodu bu adları doğrudan OCP'den değil buradan alır.
"""

import importlib.metadata as _md

from OCP.collections import (
    IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as IndexedDataMapOfShapeListOfShape,
)
from OCP.collections import (
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as IndexedMapOfShape,
)
from OCP.IntTools import IntTools_FClass2d as FClass2d
from OCP.TopoDS import TopoDS as downcast

__all__ = ["IndexedDataMapOfShapeListOfShape", "IndexedMapOfShape", "FClass2d", "downcast", "versions"]


def versions():
    """Kurulu build123d ve OCP sürümleri (raporlar ve `pocad doctor` için)."""
    return {"build123d": _md.version("build123d"), "ocp": _md.version("cadquery-ocp-novtk")}
