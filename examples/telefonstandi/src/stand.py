"""Redmi Note 13 Pro masa standı — portre + landscape, tek parça PLA, desteksiz.

Koordinatlar: X genişlik (merkez 0), Y derinlik (ön kenar Y=0, +arka), Z yukarı (tabla Z=0).
Yan profil YZ düzleminde çizilir ve X yönünde extrude edilir.
Yerel çerçeve: u = (cosθ, sinθ) sırtlık yönü, n = (−sinθ, cosθ) ekran normali,
P(a, b) = S + a·u + b·n  (a: sırtlık boyunca, b: sırtlığa dik, kullanıcıya doğru).

agentcad ile çalıştırılır:  agentcad run stand.py --label vN --export stl
(STEP dosyasını agentcad yazar; script STEP yazmaz.)
"""
import sys
from dataclasses import dataclass
from math import cos, sin, radians, sqrt
from build123d import (BuildPart, BuildSketch, Polygon, Plane, Mode, Box, Align,
                       Location, Vector, extrude, fillet, add)

SHOW_OCP = False          # True: ocp_vscode ile göster (yüklüyse)

# agentcad scripti exec ile çalıştırır; @dataclass modül kaydına ihtiyaç duyar.
if sys.modules.get(globals().get("__name__", "")) is None:
    import types
    _m = types.ModuleType(globals().get("__name__", "stand_script"))
    _m.__dict__.update(globals())
    sys.modules[_m.__name__] = _m


@dataclass
class Params:
    theta: float = 70.0
    W: float = 64.0
    D: float = 115.0
    S_y: float = 24.0
    S_z: float = 32.0
    slot_w: float = 12.0
    floor_t: float = 4.0
    lip_h: float = 5.0
    lip_t: float = 3.0
    back_len: float = 65.0
    frame_t: float = 6.0
    member_w: float = 6.0
    base_h: float = 5.0
    front_wall_t: float = 3.0
    top_bar_h: float = 8.0
    top_bar_t: float = 4.0
    rear_bar_h: float = 8.0
    rear_bar_t: float = 6.0
    notch_w: float = 14.0
    plug_len: float = 25.0
    plug_t: float = 7.0
    plug_wd: float = 12.0
    rear_cable_w: float = 14.0
    rear_cable_h: float = 7.0
    B_y: float = 52.0
    fillet_r: float = 2.0
    bed_chamfer: float = 0.6
    lip_chamfer: float = 0.8
    contact_break: float = 0.8
    top_bar_round: float = 1.5
    notch_depth: float = 30.0      # çentiğin raf yüzeyinden aşağı (−u) inişi
    ballast: bool = False
    nut_d: float = 17.0
    nut_h: float = 9.0
    # doğrulama sabitleri
    phone_L: float = 162.3
    phone_Wd: float = 75.0
    phone_T: float = 8.0
    phone_m: float = 0.190         # kg
    rho_solid: float = 1.24        # g/cm³ (dolu PLA)
    rho_print: float = 0.875       # g/cm³ (spec: 40 cm³ ≈ 35 g, 2 perimetre %15 infill)
    vol_max: float = 40000.0
    F_tip_min: float = 0.9
    cam_x_max: float = 35.0


p = Params()


# ----------------------------------------------------------------- geometri yardımcıları
def frame_vectors(p):
    t = radians(p.theta)
    u = Vector(0, cos(t), sin(t))
    n = Vector(0, -sin(t), cos(t))
    return u, n


def nodes(p):
    """§5.1 düğümleri (Y, Z) — hepsi parametrelerden türetilir."""
    u, n = frame_vectors(p)
    S = Vector(0, p.S_y, p.S_z)
    P = lambda a, b: S + u * a + n * b
    N = dict(
        S=S, F=P(0, p.slot_w), T=P(p.back_len, 0), A0=Vector(0, 0, 0),
        B=Vector(0, p.B_y, 0), R=Vector(0, p.D, 0),
        lip_fb=P(-p.floor_t, p.slot_w + p.lip_t),      # dudak alt-ön köşesi (blok alt-ön)
        shelf_rb=P(-p.floor_t, -p.member_w),           # raf arka-alt kenarı
    )
    return N, P, u, n


def yz(v):
    return (v.Y, v.Z)


def strip(a, b, w, side=0.0):
    """a→b doğrultusunda w genişlikte şerit. side=0 ortalı, +1 sol (CCW) tarafa, −1 sağa."""
    d = (b - a).normalized()
    m = Vector(0, -d.Z, d.Y)                 # YZ'de sola dik
    o0 = m * (w * (side - 1) / 2)
    o1 = m * (w * (side + 1) / 2)
    return [yz(a + o0), yz(b + o0), yz(b + o1), yz(a + o1)]


def line_hit_z0(pt, direction):
    t = -pt.Z / direction.Z
    return pt + direction * t


# ----------------------------------------------------------------- §5.2 yan çerçeve
def side_frame_sketch(p, plane):
    N, P, u, n = nodes(p)
    S, T, B, R, A0 = N["S"], N["T"], N["B"], N["R"], N["A0"]
    mw = p.member_w
    with BuildSketch(plane) as sk:
        Polygon((0, 0), (p.D, 0), (p.D, p.base_h), (0, p.base_h), align=None)   # 1 taban rayı
        Polygon(yz(S), yz(T), yz(T - n * mw), yz(S - n * mw), align=None)       # 2 sırtlık (ön yüzü düzlemde)
        Polygon(*strip(T - n * mw, R, mw, side=-1), align=None)                 # 3 arka dikme (sırtlık arka-üst köşesinden R'ye, içe kalınlaşır)
        Polygon(*strip(S, B, mw, side=+1), align=None)                          # 4 diyagonal 1 (S'de sırtlık düzleminin arkasında)
        Polygon(*strip(T, B, mw, side=+1), align=None)                          # 5 diyagonal 2 (T'de sırtlık düzleminin arkasında kalır)
        Polygon(*strip(N["lip_fb"], A0, mw, side=+1), align=None)               # 6 ön dikme (ön yüzü blok önü)
        # tabla altını ve D arkasını kırp
        Polygon((0, 0), (p.D, 0), (p.D, 400), (0, 400), align=None, mode=Mode.INTERSECT)
        # iç köşe yuvarlatma: yalnızca boşluğun köşenin ÜSTÜNDE olduğu iç köşeler (yay yukarı bakar)
        f = sk.sketch.faces()[0]
        sel = []
        for v in sk.vertices():
            pv = Vector(v)
            es = [e for e in f.edges() if min((Vector(e.start_point()) - pv).length,
                                              (Vector(e.end_point()) - pv).length) < 1e-6]
            if len(es) != 2:
                continue
            dirs = []
            for e in es:
                q = Vector(e.end_point()) if (Vector(e.start_point()) - pv).length < 1e-6 else Vector(e.start_point())
                dirs.append((q - pv).normalized())
            bis = dirs[0] + dirs[1]
            if bis.length < 1e-6:
                continue
            bis = bis.normalized()
            test = pv + bis * 0.3
            if f.distance_to(test) < 1e-6:          # küçük açı yüzün içinde → dış (konveks) köşe
                continue
            # plane yerel → global: düzlem YZ, bis zaten global
            a_v, b_v = (pv - S).dot(u), (pv - S).dot(n)
            if b_v > -1e-3 and a_v > -p.floor_t - 1e-3:
                continue                              # telefon bölgesine dolgu ekleme
            if bis.Z > 0.3 and pv.Z > 1e-3:
                sel.append(v)
        if sel:
            fillet(sel, p.fillet_r)
    return sk.sketch


def side_frame(p, log):
    N, P, u, n = nodes(p)
    x0 = p.W / 2 - p.frame_t
    parts = []
    for xs, x_out in ((x0, p.W / 2), (-p.W / 2, -p.W / 2)):
        sk = side_frame_sketch(p, Plane.YZ.offset(xs))
        fr = extrude(sk, amount=p.frame_t)
        # telefon temaslı sırtlık ön yüz kenarları (u boyunca, b≈0)
        fr = _break_edges(fr, _edges(fr, lambda q: abs(_ab(p, q)[1]) < 1e-3 and _ab(p, q)[0] > -1e-3, along=u),
                          p.contact_break, "chamfer", log, "çerçeve sırtlık kenarları")
        # taban dış alt kenarı
        fr = _break_edges(fr, _edges(fr, lambda q: abs(q.Z) < 1e-3 and abs(q.X - x_out) < 1e-3),
                          p.bed_chamfer, "chamfer", log, "çerçeve taban pahı")
        parts.append(fr)
    return parts


# ----------------------------------------------------------------- §5.3 çapraz elemanlar
def shelf_bottom_z(p):
    """Raf plakasının yatay alt yüzü (köprü): S'de sırtlığa dik floor_t kalınlık."""
    N, P, u, n = nodes(p)
    return P(-p.floor_t, -1.0).Z


def front_block_poly(p):
    """Seçenek A (kullanıcı onayı): raf + dudak ince plaka, alt yüzü yatay köprü;
    önde tam genişlik front_wall_t kalınlıkta ön duvar plakayı tablaya taşır."""
    N, P, u, n = nodes(p)
    S, F, A0 = N["S"], N["F"], N["A0"]
    fb = N["lip_fb"]                                   # dudak alt-ön köşesi = ön duvar üst-ön
    zb = shelf_bottom_z(p)
    d = (fb - A0)                                      # ön duvar ön yüz doğrultusu
    k = d.Y / d.Z                                      # dy/dz
    off = p.front_wall_t * sqrt(1 + k * k)             # yatay ofset (dik kalınlık front_wall_t)
    wall_in = lambda z: (k * z + off, z)
    ov = 1.0                                           # sırtlık elemanına bindirme (çizgi temasını önler)
    rear_top = P(0, -ov)
    rear_bot = P(-p.floor_t, -ov)
    pts = [yz(rear_top), yz(F), yz(P(p.lip_h, p.slot_w)), yz(P(p.lip_h, p.slot_w + p.lip_t)),
           yz(fb), (0.0, 0.0), wall_in(0.0), wall_in(zb), (rear_bot.Y, zb)]
    return pts


def top_bar_poly(p):
    N, P, u, n = nodes(p)
    T = N["T"]
    lo = P(p.back_len - p.top_bar_h, 0)
    # yatay alt yüz (köprü): lo'dan +Y yönünde b = −top_bar_t düzlemine kadar
    # b=−t çizgisi: P(a, −t); Z eşitliği → a
    a_hit = (lo.Z - (p.S_z + n.Z * -p.top_bar_t)) / u.Z
    back = P(a_hit, -p.top_bar_t)
    return [yz(T), yz(lo), yz(back), yz(P(p.back_len, -p.top_bar_t))]


def _extrude_x(poly, half):
    with BuildSketch(Plane.YZ) as sk:
        Polygon(*poly, align=None)
    return extrude(sk.sketch, amount=half, both=True)


def cross_members(p, log):
    N, P, u, n = nodes(p)
    hw = p.W / 2
    # raf bloğu + dudak + ön duvar (45° alt yüzlü kama)
    blk = _extrude_x(front_block_poly(p), hw)
    L = P(p.lip_h, p.slot_w + p.lip_t)
    blk = _break_edges(blk, _edges(blk, lambda q: abs(q.Y - L.Y) < 1e-3 and abs(q.Z - L.Z) < 1e-3),
                       p.lip_chamfer, "chamfer", log, "dudak ön-üst pah")
    on_shelf = lambda q: (abs(_ab(p, q)[0]) < 1e-3 and -1e-3 < _ab(p, q)[1] <= p.slot_w + 1e-3)
    on_lip = lambda q: (p.slot_w - 1e-3 <= _ab(p, q)[1] <= p.slot_w + p.lip_t + 1e-3 and -1e-3 <= _ab(p, q)[0] <= p.lip_h + 1e-3)
    blk = _break_edges(blk, _edges(blk, lambda q: abs(abs(q.X) - hw) < 1e-3 and (on_shelf(q) or on_lip(q)), along=Vector(0, n.Y, n.Z), loose=True),
                       p.contact_break, "chamfer", log, "raf/dudak uç kenarları")
    blk = _break_edges(blk, _bed_edges(blk, p, y_line=0.0), p.bed_chamfer, "chamfer", log, "raf bloğu taban pahı")
    # sırtlık üst çubuğu: çerçeveler arası (+0.5 mm bindirme), ön-üst kenar R1.5
    T = N["T"]
    top = _extrude_x(top_bar_poly(p), hw - p.frame_t + 0.5)
    top = _break_edges(top, _edges(top, lambda q: abs(q.Y - T.Y) < 1e-3 and abs(q.Z - T.Z) < 1e-3),
                       p.top_bar_round, "fillet", log, "üst çubuk ön-üst R")
    # arka taban çubuğu
    rear = _extrude_x([(p.D - p.rear_bar_t, 0), (p.D, 0), (p.D, p.rear_bar_h), (p.D - p.rear_bar_t, p.rear_bar_h)], hw)
    rear = _break_edges(rear, _bed_edges(rear, p, y_line=p.D), p.bed_chamfer, "chamfer", log, "arka çubuk taban pahı")
    return [blk, top, rear]


# ----------------------------------------------------------------- §5.4 kesikler
def keepout_poly(p):
    N, P, u, n = nodes(p)
    c = p.slot_w / 2
    h = (p.plug_t + 2) / 2
    return [yz(P(0, c - h)), yz(P(0, c + h)), yz(P(-p.plug_len, c + h)), yz(P(-p.plug_len, c - h))]


def keepout_solid(p):
    with BuildSketch(Plane.YZ) as sk:
        Polygon(*keepout_poly(p), align=None)
    return extrude(sk.sketch, amount=p.plug_wd / 2 + 1, both=True)


def cuts(p):
    N, P, u, n = nodes(p)
    out = []
    # 1 kablo çentiği: sırtlık düzleminin önü (b ≥ 0), a ∈ [−notch_depth, lip_h+5]
    big = p.slot_w + p.lip_t + 40
    with BuildSketch(Plane.YZ) as sk:
        Polygon(yz(P(-p.notch_depth, 0)), yz(P(p.lip_h + 5, 0)),
                yz(P(p.lip_h + 5, big)), yz(P(-p.notch_depth, big)), align=None)
    out.append(extrude(sk.sketch, amount=p.notch_w / 2, both=True))
    # 2 fiş keep-out
    out.append(keepout_solid(p))
    # 3 arka kablo çıkışı
    out.append(Box(p.rear_cable_w, p.rear_bar_t + 2, p.rear_cable_h,
                   align=(Align.CENTER, Align.MAX, Align.MIN)).moved(Location((0, p.D + 1, 0))))
    # 4 balast cebi
    if p.ballast:
        for xs in (-p.W / 4, p.W / 4):
            out.append(Box(p.nut_d, p.nut_d, p.nut_h, align=(Align.CENTER, Align.CENTER, Align.MAX))
                       .moved(Location((xs, p.D - p.rear_bar_t / 2, p.rear_bar_h))))
    return out


# ----------------------------------------------------------------- §5.5 kenar işlemleri
def _ab(p, q):
    N, P, u, n = nodes(p)
    d = Vector(q) - N["S"]
    return d.dot(u), d.dot(n)


def _edges(solid, pred, along=None, loose=False):
    """İki ucu da pred'i sağlayan düz kenarlar; along verilirse o doğrultuya paralel olanlar."""
    out = []
    for e in solid.edges():
        a, b = Vector(e.start_point()), Vector(e.end_point())
        if not (pred(a) and pred(b)):
            continue
        if along is not None:
            d = b - a
            if d.length < 1e-6 or abs(abs(d.normalized().dot(Vector(along).normalized())) - 1) > (1e-2 if loose else 1e-4):
                continue
        out.append(e)
    return out


def _bed_edges(solid, p, y_line):
    """Tabla temas yüzünün dış kenarları: Y=y_line boyunca X'e paralel kenar + X=±W/2'deki Y'ye paralel kenarlar."""
    hw = p.W / 2
    on_bed = lambda q: abs(q.Z) < 1e-3
    return (_edges(solid, lambda q: on_bed(q) and abs(q.Y - y_line) < 1e-3, along=Vector(1, 0, 0)) +
            _edges(solid, lambda q: on_bed(q) and abs(abs(q.X) - hw) < 1e-3, along=Vector(0, 1, 0)))


def _break_edges(part, edges, amount, kind, log, label):
    if not edges:
        log.append(f"{label}: kenar yok")
        return part
    op = (lambda s, es: s.fillet(amount, es)) if kind == "fillet" else (lambda s, es: s.chamfer(amount, None, es))
    try:
        res = op(part, edges)
        log.append(f"{label}: {len(edges)}×{kind} {amount}")
        return res
    except Exception:
        pass
    done = 0
    for e in edges:                      # tek tek dene
        try:
            match = [x for x in part.edges() if (Vector(x.center()) - Vector(e.center())).length < 1e-4]
            if match:
                part = op(part, match)
                done += 1
        except Exception:
            pass
    log.append(f"{label}: {done}/{len(edges)} {kind} {amount}")
    return part


def edge_finish(part, p, log):
    """Birleşim sonrası: kablo çentiği kenarları (telefonun oturduğu raf/dudak üzerinde)."""
    N, P, u, n = nodes(p)
    on_shelf = lambda q: (abs(_ab(p, q)[0]) < 1e-3 and -1e-3 < _ab(p, q)[1] <= p.slot_w + p.lip_t + 1e-3)
    on_lip = lambda q: (p.slot_w - 1e-3 <= _ab(p, q)[1] <= p.slot_w + p.lip_t + 1e-3 and -1e-3 <= _ab(p, q)[0] <= p.lip_h + 1e-3)
    es = _edges(part, lambda q: abs(abs(q.X) - p.notch_w / 2) < 1e-3 and (on_shelf(q) or on_lip(q)))
    return _break_edges(part, es, p.contact_break, "chamfer", log, "kablo çentiği kenarları")


# ----------------------------------------------------------------- montaj
def build(p, log=None):
    log = [] if log is None else log
    pieces = side_frame(p, log) + cross_members(p, log)      # builder bağlamı dışında üretilir
    part = pieces[0]
    for q in pieces[1:]:
        part = part + q
    for c in cuts(p):
        part = part - c
    part = edge_finish(part, p, log)
    return part


# ----------------------------------------------------------------- §7 doğrulama
def phone_box(p, landscape):
    N, P, u, n = nodes(p)
    S = N["S"]
    pl = Plane(origin=(0, S.Y, S.Z), x_dir=(1, 0, 0), z_dir=(0, n.Y, n.Z))   # y_dir = u
    wx, lu = (p.phone_L, p.phone_Wd) if landscape else (p.phone_Wd, p.phone_L)
    return pl * Box(wx, lu, p.phone_T, align=(Align.CENTER, Align.MIN, Align.MIN))


def _ivol(a, b):
    try:
        r = a & b
        return sum(s.volume for s in r.solids()) if r is not None else 0.0
    except Exception:
        return float("nan")


def verify(part, p, log=()):
    N, P, u, n = nodes(p)
    S, R = N["S"], N["R"]
    out = []
    ok_all = True

    def rep(name, ok, detail):
        nonlocal ok_all
        ok_all &= bool(ok)
        out.append(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    V = part.volume
    m_solid = V / 1000 * p.rho_solid
    m_print = V / 1000 * p.rho_print
    rep("1 Hacim", V <= p.vol_max, f"{V/1000:.1f} cm³ (sınır {p.vol_max/1000:.0f}); dolu PLA {m_solid:.1f} g, baskı ≈ {m_print:.1f} g")

    for mode, land in (("portre", False), ("landscape", True)):
        box = phone_box(p, land)
        iv = _ivol(part, box)
        back = [f for f in box.faces() if f.normal_at().dot(n) < -0.99][0]
        bott = [f for f in box.faces() if f.normal_at().dot(u) < -0.99][0]
        d_back = part.distance_to(back)
        d_bott = part.distance_to(bott)
        rep(f"2 Telefon kutusu ({mode})", abs(iv) < 1e-3 and d_back < 0.05 and d_bott < 0.05,
            f"kesişim {iv:.4f} mm³, sırtlık mesafesi {d_back:.3f} mm, raf mesafesi {d_bott:.3f} mm")

    # 3 kamera: landscape kutunun arka yüzüne 0.05 mm içinde kalan stand malzemesinin X sınırı
    pl = Plane(origin=(0, S.Y, S.Z), x_dir=(1, 0, 0), z_dir=(0, n.Y, n.Z))
    slab = pl * Box(400, p.phone_Wd, 0.05, align=(Align.CENTER, Align.MIN, Align.MAX))
    try:
        c = part & slab
        bb = c.bounding_box()
        xmax = max(abs(bb.min.X), abs(bb.max.X))
        rep("3 Kamera temizliği", xmax <= p.cam_x_max, f"sırtlık temas bölgesi |X| ≤ {xmax:.1f} mm (sınır {p.cam_x_max})")
    except Exception as e:
        rep("3 Kamera temizliği", False, f"hesaplanamadı ({e})")

    iv = _ivol(part, keepout_solid(p))
    rep("4 Fiş keep-out", abs(iv) < 1e-3, f"kesişim {iv:.4f} mm³")

    # 5 overhang
    bad = []
    bridges = []
    for f in part.faces():
        worst = 1.0
        worst_pt = None
        for uu in (0.1, 0.3, 0.5, 0.7, 0.9):
            for vv in (0.1, 0.3, 0.5, 0.7, 0.9):
                try:
                    pt = f.position_at(uu, vv)
                    nz = f.normal_at(pt).Z
                except Exception:
                    continue
                if nz < worst:
                    worst, worst_pt = nz, pt
        if worst_pt is None or worst >= -0.7072:
            continue
        bb = f.bounding_box()
        if bb.max.Z < 1e-3:
            continue                                   # tabla yüzü
        if worst < -0.999 and bb.size.Z < 1e-3:
            bridges.append(f"Z={bb.min.Z:.2f} genişlik {bb.size.X:.1f}")
            continue                                   # yatay köprü (aşağıda konum kontrolü)
        bad.append(f"Z≈{worst_pt.Z:.1f} Y≈{worst_pt.Y:.1f} X≈{worst_pt.X:.1f} (normal_z={worst:.2f}, alan {f.area:.1f})")
    # yatay köprüler yalnızca üst çubuk altı veya kablo kesik tavanı olabilir
    tb_z = P(p.back_len - p.top_bar_h, 0).Z
    allowed = {round(tb_z, 2), round(p.rear_cable_h, 2), round(shelf_bottom_z(p), 2)}   # A: raf altı köprüsü
    wrong_bridges = [b for b in bridges if round(float(b.split()[0][2:]), 2) not in allowed]
    rep("5 Overhang", not bad and not wrong_bridges,
        f"{len(bad)} ihlal; köprüler: {', '.join(bridges) or 'yok'}" + ("" if not bad else " | " + "; ".join(bad[:8])))

    # 6 devrilme (portre): R etrafında moment, kuvvet S+150u'da −n yönünde
    g = 9.81
    Pf = S + u * 150
    Fdir = n * -1
    arm_F = (Pf.Y - R.Y) * Fdir.Z - (Pf.Z - R.Z) * Fdir.Y          # (r × F)_x birim kuvvet için
    cg_ph = S + n * 4 + u * 80
    cg_st = part.center()
    m_st = m_print / 1000
    restoring = g * (p.phone_m * (R.Y - cg_ph.Y) + m_st * (R.Y - cg_st.Y))   # N·mm
    F_tip = restoring / abs(arm_F) if arm_F < 0 else float("inf")
    F_tip_solid = g * (p.phone_m * (R.Y - cg_ph.Y) + m_solid / 1000 * (R.Y - cg_st.Y)) / abs(arm_F)
    rep("6 Devrilme (portre)", F_tip >= p.F_tip_min,
        f"F_tip = {F_tip:.2f} N (baskı kütlesi {m_print:.0f} g ile; dolu PLA ile {F_tip_solid:.2f} N), sınır {p.F_tip_min} N")

    # 7 ayak izi
    for mode, land in (("portre", False), ("landscape", True)):
        cg_p = S + n * 4 + u * ((p.phone_Wd if land else p.phone_L) / 2)
        cy = (p.phone_m * cg_p.Y + m_st * cg_st.Y) / (p.phone_m + m_st)
        rep(f"7 Ayak izi ({mode})", 0 < cy < p.D, f"toplam CG Y = {cy:.1f} mm (0 < Y < {p.D})")

    out.append("Kenar işlemleri: " + " | ".join(log))
    out.append("SONUÇ: " + ("TÜMÜ PASS" if ok_all else "FAIL VAR"))
    return ok_all, "\n".join(out)


def export(part):
    """STEP/STL teslimi agentcad üzerinden yapılır (agentcad run stand.py --export stl);
    script içinde STEP yazıcı çağrılmaz. Doğrulanmış çıktılar stand.step / stand.stl olarak kopyalanır."""
    return None


# ----------------------------------------------------------------- çalıştır
log = []
stand = build(p, log)
ok, report = verify(stand, p, log)
print(report, file=sys.stderr)
try:
    with open("verify_report.txt", "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
except OSError:
    pass

if SHOW_OCP:
    try:
        import importlib
        importlib.import_module("ocp_vscode").show(stand)
    except ImportError:
        print("ocp_vscode yüklü değil", file=sys.stderr)

show_object(stand, id="stand", name="Telefon standı", options={"expect_solids": 1})
