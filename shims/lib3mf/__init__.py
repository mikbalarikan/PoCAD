"""PoCAD shim: lib3mf'in Linux aarch64 için pip paketi yok.

build123d `mesher.py` modül yüklenirken lib3mf sembollerine dokunur; bu yer tutucu
import'u başarılı kılar. 3MF içe/dışa aktarımı kullanılırsa açık bir hata verir.
STEP / STL / GLB / OBJ etkilenmez.
"""


class _Stub:
    def __init__(self, name="lib3mf"):
        self._n = name

    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return _Stub(self._n + "." + n)

    def __call__(self, *a, **k):
        raise RuntimeError("3MF desteklenmiyor (PoCAD: lib3mf yok): " + self._n)

    def __hash__(self):
        return hash(self._n)

    def __eq__(self, o):
        return isinstance(o, _Stub) and o._n == self._n

    def __repr__(self):
        return "<lib3mf stub " + self._n + ">"


Lib3MF = _Stub("Lib3MF")


def get_wrapper(*a, **k):
    raise RuntimeError("3MF desteklenmiyor (PoCAD: lib3mf yok)")
