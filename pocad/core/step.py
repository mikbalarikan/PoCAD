# kaynak: oguz-atolye tools/core/step.py @ca27b1b (MIT, PoCAD'e taşındı)
"""The one STEP writer for deliveries (D-024) and its read-back checks.

build123d 0.11.1's export_step() always writes AP214 (R03 §1: it stamps a default
header over the model), so every delivered STEP goes through this XCAF writer:
AP242 by default, AP214 on request (SYNTHESIS §3), names and colours kept, the
schema and the length unit asserted by reading the file back. The header is clean
(DELIVERY.md §4): the file name without a folder, a timestamp the caller pins so
the same geometry gives the same bytes (R04 recommendation 7), empty author,
organisation, and authorisation, and the translator and CAD kernel versions.

OCCT's writer and reader settings are process-wide statics that any earlier
export may have changed (build123d's export_step sets two of them and leaves them
set), so every write pins the ones that change the file (STATICS), every read the
ones that change the shape (READ_STATICS), and both restore them afterwards.
Assembly occurrence ids come from a counter that lasts the whole process; the
writer renumbers them, so an assembly written twice gives the same bytes.

Base: research/assets/R03/step_ap242.py, with the header set through
APIHeaderSection_MakeHeader on the writer's own model after the transfer. That
call keeps AP242 (checked by the tests); the constructor build123d uses,
MakeHeader(0), is what stamps AP214.
"""
from __future__ import annotations

import contextlib
import getpass
import hashlib
import os
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path

import build123d
import OCP
from build123d import Unit, import_step
from build123d.exporters3d import _create_xde
from OCP.APIHeaderSection import APIHeaderSection_MakeHeader
from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.Interface import Interface_ParamType, Interface_Static
from OCP.STEPCAFControl import STEPCAFControl_Controller, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_Controller, STEPControl_StepModelType
from OCP.TCollection import TCollection_HAsciiString
from OCP.XSControl import XSControl_WorkSession

from pocad.core.shapes import faces, quiet, solids, volume_mm3
from pocad.core.validity import brep_valid
from pocad.result import Result, inconclusive

SCHEMAS = {"AP242": "AP242DIS", "AP214": "AP214IS"}
# The writer statics that change the file, at OCCT 7.9's defaults; the schema is per call.
STATICS = {"write.step.unit": "MM", "xstep.cascade.unit": "MM", "step.angleunit.mode": "File",
           "write.surfacecurve.mode": "On", "write.precision.mode": "Average",
           "write.precision.val": 0.001, "write.step.nonmanifold": "Off", "write.step.assembly": "Auto",
           "write.step.vertex.mode": "Compound", "write.stepcaf.subshapes.name": "Off",
           "write.step.tessellated": "OnNoBRep"}
# The reader statics, at OCCT 7.9's defaults: with xstep.cascade.unit left at M by
# earlier code, a 40 mm part reads as 0.04.
READ_STATICS = {"xstep.cascade.unit": "MM", "step.angleunit.mode": "File", "read.precision.mode": "File",
                "read.precision.val": 0.001, "read.maxprecision.mode": "Preferred",
                "read.maxprecision.val": 1.0, "read.stdsameparameter.mode": "Off",
                "read.surfacecurve.mode": "Default", "read.encoderegularity.angle": 0.01,
                "read.step.product.mode": "ON", "read.step.product.context": "all",
                "read.step.shape.repr": "All", "read.step.assembly.level": "all",
                "read.step.shape.relationship": "ON", "read.step.shape.aspect": "ON",
                "read.step.root.transformation": "ON", "read.step.nonmanifold": "Off",
                "read.step.all.shapes": "Off", "read.step.ideas": "Off",
                "read.step.constructivegeom.relationship": "OFF", "read.step.tessellated": "On",
                "read.step.codepage": "UTF8", "read.stepcaf.subshapes.name": "Off"}
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
# Names that come back unchanged: import_step turns a space, '.', '(' or ')' into
# '_', and build123d writes non-ASCII part names without the multibyte flag.
LABEL_RE = re.compile(r"[A-Za-z0-9_-]+")
FILE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
PREPROCESSOR = f"Open CASCADE STEP processor {'.'.join(OCP.__version__.split('.')[:3])}"
ORIGINATING_SYSTEM = f"build123d {build123d.__version__}"
SI_PREFIXES = {"$": "M", ".MILLI.": "MM", ".CENTI.": "CM", ".MICRO.": "UM", ".KILO.": "KM"}
ENTITY_RE = re.compile(r"#(\d+)\s*=\s*((?:'(?:[^']|'')*'|[^';])*);")
OCCURRENCE_RE = re.compile(rb"(NEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\(\s*')\d+'")


class ExportError(RuntimeError):
    """An export that did not produce the file it promised. Never swallowed."""


@dataclass(frozen=True)
class Written:
    """A file a writer produced: where, its SHA-256, its format, what it carries, and
    the measurements the writer made on it (`checks`, each a Result to gate)."""

    path: Path
    sha256: str
    format: str
    size_bytes: int
    detail: dict = field(default_factory=dict)
    checks: dict[str, Result] = field(default_factory=dict)


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_step(shape, path: Path | str, *, timestamp: str, schema: str = "AP242",
               name: str | None = None) -> Written:
    """Write `shape` (a part, or a Compound of labelled parts) as STEP.

    IN   shape: a build123d Shape; child labels and colours are kept. Labels are
           letters, digits, '_' and '-' (LABEL_RE), or empty.
         path: the .step file to write; its folder is created.
         timestamp: yyyy-mm-ddThh:mm:ss for the header, pinned by the caller.
         schema: "AP242" (default) or "AP214" (on the client's request).
         name: the header's file name, plain ASCII; defaults to the file's own name.
    OUT  Written, with the header read back in detail["header"].
    ERR  ValueError on a bad argument; ExportError when OCCT refuses, the schema or
         the length unit read back differs, or the header carries a path, user, or
         machine name. The file is written under a temporary name and moved into
         place only after those checks, so a refused file never stays on disk.
    """
    if schema not in SCHEMAS:
        raise ValueError(f"schema is one of {', '.join(SCHEMAS)}, not {schema!r}")
    if not TIMESTAMP_RE.fullmatch(timestamp):
        raise ValueError(f"timestamp is yyyy-mm-ddThh:mm:ss, not {timestamp!r}")
    path = Path(path)
    label = name or path.name
    if not FILE_NAME_RE.fullmatch(label):
        raise ValueError(f"the header name is a plain ASCII file name "
                         f"(letters, digits, '.', '_', '-'), not {label!r}")
    bad = [n for n in node_labels(shape) if n and not LABEL_RE.fullmatch(n)]
    if bad:
        raise ValueError(f"part labels use letters, digits, '_' and '-' only: {bad}")
    if getattr(shape, "parent", None) is not None:
        raise ValueError("this part sits in an assembly (it has a parent), and OCCT cannot transfer it "
                         "on its own: write the assembly, or build the part again for its own file")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    doc = _create_xde(shape, Unit.MM, auto_naming=True)
    try:
        with quiet(), pinned({**STATICS, "write.step.schema": SCHEMAS[schema]}):
            writer = STEPCAFControl_Writer(XSControl_WorkSession(), False)
            writer.SetColorMode(True)
            writer.SetNameMode(True)
            writer.SetLayerMode(True)
            if not writer.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs):
                raise ExportError("the XCAF transfer failed")
            header = APIHeaderSection_MakeHeader(writer.ChangeWriter().Model())
            if not header.IsDone():
                raise ExportError("the STEP header could not be set")
            text = TCollection_HAsciiString
            header.SetName(text(label))
            header.SetTimeStamp(text(timestamp))
            header.SetAuthorValue(1, text(""))
            header.SetOrganizationValue(1, text(""))
            header.SetPreprocessorVersion(text(PREPROCESSOR))
            header.SetOriginatingSystem(text(ORIGINATING_SYSTEM))
            header.SetAuthorisation(text(""))
            status = writer.Write(str(partial))
        if status != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise ExportError(f"STEP write failed: {path.name}")
        _renumber_occurrences(partial)
        got = read_schema(partial)
        if got != schema:
            raise ExportError(f"{path.name}: the header says {got}, expected {schema}")
        unit = read_length_unit(partial)
        if unit != "MM":
            raise ExportError(f"{path.name}: the length unit is {unit}, expected MM")
        head = read_header(partial)
        leaks = header_leaks(head)
        if leaks:
            raise ExportError(f"{path.name}: the header carries {', '.join(leaks)}")
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return Written(path, file_sha256(path), schema, path.stat().st_size,
                   detail={"header": head, "timestamp": timestamp, "length_unit": unit})


def _renumber_occurrences(path: Path) -> None:
    """Number the NEXT_ASSEMBLY_USAGE_OCCURRENCE ids 1, 2, 3 in file order. OCCT
    takes them from a counter that lasts the whole process; nothing refers to them."""
    data = path.read_bytes()
    count = iter(range(1, 1 << 30))
    fixed = OCCURRENCE_RE.sub(lambda m: m.group(1) + str(next(count)).encode() + b"'", data)
    if fixed != data:
        path.write_bytes(fixed)


@contextlib.contextmanager
def pinned(values: dict):
    """Set OCCT statics for the duration of a write or a read, then restore what was
    there. The statics exist only once the STEP controllers are initialised."""
    STEPCAFControl_Controller.Init_s()
    STEPControl_Controller.Init_s()
    saved = {}
    try:
        for key, value in values.items():
            if not Interface_Static.IsPresent_s(key):
                raise ExportError(f"OCCT has no static {key}")
            kind = _kind(key)
            saved[key] = (kind, {"real": Interface_Static.RVal_s, "int": Interface_Static.IVal_s,
                                 "text": Interface_Static.CVal_s}[kind](key))
            done = (Interface_Static.SetRVal_s(key, float(value)) if kind == "real"
                    else Interface_Static.SetCVal_s(key, str(value)))
            if not done:
                raise ExportError(f"OCCT refused {key}={value}")
        yield
    finally:
        for key, (kind, value) in saved.items():
            {"real": Interface_Static.SetRVal_s, "int": Interface_Static.SetIVal_s,
             "text": Interface_Static.SetCVal_s}[kind](key, value)


def _kind(key: str) -> str:
    """How a static's value is saved and restored: an enum by its index, since
    SetIVal takes any index back while SetCVal only takes the enum's own words."""
    kind = Interface_Static.Static_s(key).Type()
    if kind == Interface_ParamType.Interface_ParamReal:
        return "real"
    if kind in (Interface_ParamType.Interface_ParamEnum, Interface_ParamType.Interface_ParamInteger):
        return "int"
    return "text"


def _header_text(path: Path | str) -> str:
    with open(path, "rb") as handle:
        head = handle.read(64 * 1024).decode("latin-1")
    end = head.find("ENDSEC;")
    if not head.startswith("ISO-10303-21;") or end < 0:
        raise ValueError(f"{Path(path).name} is not a STEP file with a header section")
    return head[:end]


def read_schema(path: Path | str) -> str:
    """AP242, AP214, AP203, or UNKNOWN, from the FILE_SCHEMA of the header."""
    flat = re.sub(r"\s+", "", _header_text(path))
    match = re.search(r"FILE_SCHEMA\(\((.*?)\)\);", flat)
    schema = match.group(1).upper() if match else ""
    if "10303442" in schema or "10303242" in schema or "AP242" in schema:
        return "AP242"
    if "10303214" in schema or "AUTOMOTIVE_DESIGN" in schema:
        return "AP214"
    if "CONFIG_CONTROL_DESIGN" in schema:
        return "AP203"
    return "UNKNOWN"


def read_header(path: Path | str) -> dict:
    """The FILE_NAME fields of the header."""
    text = _header_text(path)
    start = text.find("FILE_NAME(")
    if start < 0:
        raise ValueError("no FILE_NAME in the header")
    items, i = _step_items(text, start + len("FILE_NAME("))
    keys = ("name", "time_stamp", "author", "organization", "preprocessor_version",
            "originating_system", "authorization")
    if len(items) != len(keys):
        raise ValueError(f"FILE_NAME has {len(items)} fields, expected {len(keys)}")
    return dict(zip(keys, items, strict=True))


def _step_items(text: str, i: int) -> tuple[list, int]:
    """Parse a comma-separated STEP list of strings and nested lists up to its ')'."""
    items: list = []
    while i < len(text):
        c = text[i]
        if c in " \t\r\n,":
            i += 1
        elif c == "'":
            j, chars = i + 1, []
            while True:
                if text[j] == "'" and text[j + 1:j + 2] == "'":
                    chars.append("'")
                    j += 2
                elif text[j] == "'":
                    break
                else:
                    chars.append(text[j])
                    j += 1
            items.append("".join(chars))
            i = j + 1
        elif c == "(":
            inner, i = _step_items(text, i + 1)
            items.append(inner)
        elif c == ")":
            return items, i + 1
        elif c == "$":
            items.append(None)
            i += 1
        else:
            raise ValueError(f"unexpected {c!r} in the STEP header")
    raise ValueError("unterminated list in the STEP header")


def read_length_unit(path: Path | str) -> str:
    """The length unit of the file's geometry contexts: MM, M, CM, UM, KM, a
    converted unit's own name (INCH, FOOT), MIXED when they disagree, or UNKNOWN."""
    data = Path(path).read_text(encoding="latin-1")
    entities = {int(n): body for n, body in ENTITY_RE.findall(data[data.find("DATA;"):])}
    units = set()
    for body in entities.values():
        match = re.search(r"GLOBAL_UNIT_ASSIGNED_CONTEXT\s*\(\s*\(([^)]*)\)", body)
        if not match:
            continue
        for ref in re.findall(r"#(\d+)", match.group(1)):
            unit = re.sub(r"\s+", "", entities.get(int(ref), "")).upper()
            if "LENGTH_UNIT(" not in unit:
                continue
            converted = re.search(r"CONVERSION_BASED_UNIT\('([^']*)'", unit)
            si = re.search(r"SI_UNIT\((\$|\.\w+\.),\.METRE\.\)", unit)
            units.add(converted.group(1) if converted else
                      SI_PREFIXES.get(si.group(1), "UNKNOWN") if si else "UNKNOWN")
    if len(units) == 1:
        return units.pop()
    return "MIXED" if units else "UNKNOWN"


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:                          # noqa: BLE001: no USER and no passwd entry
        return ""


def header_leaks(head: dict) -> list[str]:
    """What must not be in a delivered header: a folder, a user, or a machine name."""
    leaks = []
    if re.search(r"[\\/:]", head.get("name") or ""):
        leaks.append(f"a path in FILE_NAME ({head['name']!r})")
    for key in ("author", "organization"):
        if any(v for v in head.get(key) or []):
            leaks.append(f"a filled {key} field")
    if head.get("authorization"):
        leaks.append("a filled authorization field")
    fields = [head.get("name") or "", *(head.get("author") or []), *(head.get("organization") or []),
              head.get("authorization") or ""]
    words = f" {_words(' '.join(str(f) for f in fields))} "
    user = _user()
    for who in {user, platform.node()}:
        if who and len(who) > 2 and f" {_words(who)} " in words:
            leaks.append(f"the {'user' if who == user else 'machine'} name")
    return leaks


def _words(text: str) -> str:
    """Lower-case words separated by single spaces, split at punctuation, at a
    lower-to-upper case change, and between letters and digits:
    'maryaBracket_v01.step' -> 'marya bracket v 01 step'."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])", " ", text)
    return " ".join(re.split(r"[^0-9a-z]+", text.casefold())).strip()


def read_step(path: Path | str):
    """The file as a build123d shape (import_step, quietly, the reader statics pinned)."""
    with quiet(), pinned(READ_STATICS):
        return import_step(str(path))


def labels(shape) -> list[str]:
    """Labels of the leaves: the part names a STEP file carries."""
    children = list(getattr(shape, "children", ()) or ())
    if children:
        return [name for child in children for name in labels(child)]
    return [shape.label] if getattr(shape, "label", "") else []


def node_labels(shape) -> list[str]:
    """The label of every node of the shape tree, the assembly's own included."""
    children = list(getattr(shape, "children", ()) or ())
    return [getattr(shape, "label", "") or ""] + [n for child in children for n in node_labels(child)]


ROUNDTRIP = {"schema": ("step_schema", "bool"), "solids": ("step_roundtrip_solids", "count"),
             "volume_delta": ("step_roundtrip_volume_delta", "mm3"),
             "faces_delta": ("step_roundtrip_faces_delta", "count"),
             "labels": ("step_roundtrip_labels", "bool"), "valid_after": ("step_roundtrip_valid", "bool")}


def step_roundtrip(shape, path: Path | str, *, timestamp: str, schema: str = "AP242") -> dict[str, Result]:
    """Write with write_step, re-import, and compare (R04 function 11): compare_step
    on the file just written. A write that fails makes every result INCONCLUSIVE."""
    try:
        write_step(shape, path, timestamp=timestamp, schema=schema)
    except Exception as exc:                                   # noqa: BLE001: a check never raises
        return _inconclusive_roundtrip(f"{type(exc).__name__}: {exc}")
    return compare_step(shape, path, schema=schema)


def compare_step(shape, path: Path | str, *, schema: str = "AP242") -> dict[str, Result]:
    """Re-import a STEP file and compare it with the shape it was written from,
    keyed as ROUNDTRIP. Gate each result: schema == 1, solids == the part's count
    (1 for a part file), volume_delta <= the band, faces_delta == 0, labels == 1,
    valid_after == 1."""
    try:
        back = read_step(path)
        found = read_schema(path)
        common = {"sha256": file_sha256(path), "path": Path(path).name}
        built_labels, back_labels = labels(shape), labels(back)
        valid = brep_valid(back)
        name, unit = ROUNDTRIP["valid_after"]
        return {
            "schema": Result("step_schema", int(found == schema), "bool",
                             params={"schema": schema}, detail={"found": found, **common}),
            "solids": Result("step_roundtrip_solids", len(solids(back)), "count",
                             detail={"built": len(solids(shape)), **common}),
            "volume_delta": Result("step_roundtrip_volume_delta",
                                   abs(volume_mm3(back) - volume_mm3(shape)), "mm3",
                                   detail={"built_mm3": volume_mm3(shape),
                                           "reimported_mm3": volume_mm3(back), **common}),
            "faces_delta": Result("step_roundtrip_faces_delta",
                                  abs(len(faces(back)) - len(faces(shape))), "count",
                                  detail={"built": len(faces(shape)), "reimported": len(faces(back))}),
            "labels": Result("step_roundtrip_labels", int(sorted(built_labels) == sorted(back_labels)),
                             "bool", detail={"built": built_labels, "reimported": back_labels}),
            "valid_after": (Result(name, valid.measured, unit, detail=valid.detail) if valid.ok
                            else inconclusive(name, unit, valid.reason)),
        }
    except Exception as exc:                                   # noqa: BLE001: a check never raises
        return _inconclusive_roundtrip(f"{type(exc).__name__}: {exc}")


def _inconclusive_roundtrip(reason: str) -> dict[str, Result]:
    return {key: inconclusive(name, unit, reason) for key, (name, unit) in ROUNDTRIP.items()}
