# kaynak: oguz-atolye tools/result.py @ca27b1b (MIT, PoCAD'e taşındı)
"""The result contract of every tools measurement, and the one gate comparison. Standard library only.

A measurement returns a `Result`: the measured number (a count, a length, or 1 / 0
for a yes-or-no fact), its unit, where it was measured (`at`), the parameters it
used, and a status, MEASURED or INCONCLUSIVE with the reason (D-026). No
measurement reads a threshold (D-009): the caller compares with `gate()`, passing
the limit from the spec and the tolerance band from GATES.md (L-21). A raised
exception or a missing value is INCONCLUSIVE, and INCONCLUSIVE is never a pass
(PLAYBOOK rule 2).

`gate()` returns a `Gate` whose `row()` is one row of the verdict's gate table
(pocad/schemas/verdict.schema.json), so a check script can hand its results to
the REPORT or the verdict without retyping a number.
"""
from __future__ import annotations

import functools
import math
import numbers
import re
from dataclasses import dataclass, field
from typing import Any, Callable

MEASURED, INCONCLUSIVE = "MEASURED", "INCONCLUSIVE"
PASS, PASS_ASSUMED, FAIL = "PASS", "PASS_ASSUMED", "FAIL"
OPERATORS = (">=", "<=", "==", "in")
ASSUMPTION_RE = re.compile(r"A-\d{2,}")
MEASUREMENTS: dict[str, str] = {}     # check name -> module: every check the code offers


@dataclass(frozen=True)
class Result:
    """One measured value. `detail` holds supporting facts that are never compared."""

    name: str
    measured: float | int | None
    unit: str
    at: Any = None
    params: dict = field(default_factory=dict)
    status: str = MEASURED
    reason: str = ""
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in (MEASURED, INCONCLUSIVE):
            raise ValueError(f"status is MEASURED or INCONCLUSIVE, not {self.status!r}")
        if self.status == INCONCLUSIVE and not self.reason:
            raise ValueError("an INCONCLUSIVE result names its reason")
        if self.status == MEASURED:
            value = self.measured
            if _is_bool(value):
                object.__setattr__(self, "measured", int(value))
            elif not _finite(value):
                raise ValueError(f"{self.name}: a MEASURED result needs a finite number, "
                                 f"not {value!r}")
            else:                                  # a numpy number becomes a plain one (JSON)
                object.__setattr__(self, "measured", _plain_number(value))

    @property
    def ok(self) -> bool:
        return self.status == MEASURED

    def to_dict(self) -> dict:
        return {"name": self.name, "measured": self.measured, "unit": self.unit,
                "at": _plain(self.at), "params": _plain(self.params), "status": self.status,
                "reason": self.reason, "detail": _plain(self.detail)}


def inconclusive(name: str, unit: str, reason: str, **params) -> Result:
    return Result(name, None, unit, params=params, status=INCONCLUSIVE, reason=reason)


def register(name: str, module: str) -> None:
    """Record a check the code offers, so the mutation manifest can be held to it."""
    MEASUREMENTS[name] = module


def measurement(name: str, unit: str) -> Callable:
    """Decorate a measurement: any exception becomes INCONCLUSIVE with its reason, so
    nothing returns a default number in place of a failure (R04's toolkit contract)."""
    def wrap(function: Callable[..., Result]) -> Callable[..., Result]:
        register(name, function.__module__)

        @functools.wraps(function)
        def inner(*args, **kwargs) -> Result:
            try:
                result = function(*args, **kwargs)
            except Exception as exc:                       # noqa: BLE001: the contract
                return inconclusive(name, unit, f"{type(exc).__name__}: {exc}")
            if not isinstance(result, Result):
                return inconclusive(name, unit, f"{function.__name__} returned {type(result).__name__}")
            return result
        return inner
    return wrap


def measurement_set(name: str, results: dict[str, tuple[str, str]]) -> Callable:
    """Decorate a check that measures several values at once and returns them keyed as
    `results` ({key: (result name, unit)}). An exception makes every value
    INCONCLUSIVE with its reason, and so does a value the function did not return.
    The set is one check, registered as `name`."""
    def wrap(function: Callable[..., dict]) -> Callable[..., dict[str, Result]]:
        register(name, function.__module__)

        @functools.wraps(function)
        def inner(*args, **kwargs) -> dict[str, Result]:
            try:
                out = function(*args, **kwargs)
            except Exception as exc:                       # noqa: BLE001: the contract
                reason = f"{type(exc).__name__}: {exc}"
                return {k: inconclusive(n, u, reason) for k, (n, u) in results.items()}
            out = out if isinstance(out, dict) else {}
            return {k: out[k] if isinstance(out.get(k), Result) and out[k].name == n
                    else inconclusive(n, u, f"{function.__name__} did not measure {k}")
                    for k, (n, u) in results.items()}
        inner.results = results
        return inner
    return wrap


@dataclass(frozen=True)
class Gate:
    """One gate row, compared; `row()` is the verdict schema's gate item."""

    gate: str
    measured: float | int | None
    unit: str
    required: str
    margin: float | None
    at: str | None
    status: str
    method: str
    assumes: tuple[str, ...] = ()
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.status in (PASS, PASS_ASSUMED)

    def row(self) -> dict:
        return {"gate": self.gate, "measured": self.measured, "unit": self.unit,
                "required": self.required, "margin": self.margin, "at": self.at,
                "status": self.status, "method": self.method, "assumes": list(self.assumes)}


def gate(gate_id: str, result: Result, op: str, limit, *, band: float,
         assumes: tuple[str, ...] | list[str] = (), required: str | None = None) -> Gate:
    """Compare one measurement with one limit.

    op is >=, <=, ==, or "in" (limit is then (low, high)). band is the one
    tolerance band, in the result's unit, from GATES.md (L-21): it absorbs
    floating-point noise at the limit (a measured 1.9999999 against >= 2.0) and
    nothing else. It has no default, so a check always states it. The margin is the
    signed distance to the nearest limit, positive inside; for == it is minus the
    distance from the value. The band is not part of the margin, so a value that
    passes inside the band shows the small negative margin by which it missed the
    limit. A PASS that rests on ledger rows is PASS_ASSUMED with those rows
    (PLAYBOOK rule 5); assumes is a list of A-## ids.
    """
    if op not in OPERATORS:
        raise ValueError(f"op is one of {', '.join(OPERATORS)}, not {op!r}")
    if not _finite(band) or band < 0:
        raise ValueError(f"band must be a number >= 0, not {band!r}")
    if op == "in":
        if not (isinstance(limit, (tuple, list)) and len(limit) == 2 and all(map(_finite, limit))
                and limit[0] <= limit[1]):
            raise ValueError(f"an 'in' limit is (low, high) with low <= high, not {limit!r}")
        low, high = map(_plain_number, limit)
        text = required or f"in [{low}, {high}]"
    else:
        if not _finite(limit):
            raise ValueError(f"the limit must be a finite number, not {limit!r}")
        limit = _plain_number(limit)
        text = required or f"{op} {limit}"
    band = _plain_number(band)
    if isinstance(assumes, str):
        raise ValueError(f"assumes is a list of A-## ids, not {assumes!r}")
    assumes = tuple(assumes)
    if not all(isinstance(a, str) and ASSUMPTION_RE.fullmatch(a) for a in assumes):
        raise ValueError(f"assumes is a list of A-## ids, not {list(assumes)!r}")
    at = _where(result.at)
    if result.status != MEASURED or result.measured is None:
        return Gate(gate_id, None, result.unit, text, None, at, INCONCLUSIVE, result.name,
                    tuple(assumes), result.reason or "no measured value")
    m = result.measured
    if op == ">=":
        margin, ok = m - limit, m >= limit - band
    elif op == "<=":
        margin, ok = limit - m, m <= limit + band
    elif op == "==":
        margin, ok = -abs(m - limit), abs(m - limit) <= band
    else:
        margin, ok = min(m - low, high - m), low - band <= m <= high + band
    status = (PASS_ASSUMED if assumes else PASS) if ok else FAIL
    return Gate(gate_id, m, result.unit, text, _clean(margin), at, status, result.name,
                tuple(assumes))


def _is_bool(value) -> bool:
    """True for a Python bool and for numpy's (named bool_ in numpy 1, bool in 2)."""
    return isinstance(value, bool) or (type(value).__module__ == "numpy"
                                       and type(value).__name__ in ("bool", "bool_"))


def _finite(value) -> bool:
    """A real, finite number: int, float, or a numpy number; never a bool."""
    return isinstance(value, numbers.Real) and not _is_bool(value) and math.isfinite(value)


def _plain_number(value):
    return int(value) if isinstance(value, numbers.Integral) else float(value)


def _clean(value: float) -> float:
    """Round away float noise in a margin (1.2 - 1.0 reads 0.2), but never the sign of a
    margin smaller than the rounding; the measured value itself is never rounded."""
    rounded = round(value, 9) + 0.0
    return rounded if rounded or not value else value


def _where(at) -> str | None:
    if at is None:
        return None
    if isinstance(at, (tuple, list)) and len(at) == 3 and all(isinstance(v, (int, float)) for v in at):
        return "(" + ", ".join(f"{v:.4f}" for v in at) + ") mm"
    return str(at)


def _plain(value):
    """JSON-safe copy: tuples and arrays become lists, numpy numbers plain ones, and a
    number that is not finite None."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) or type(value).__name__ == "ndarray":
        return [_plain(v) for v in value]
    if _is_bool(value):
        return bool(value)
    if isinstance(value, numbers.Real):
        return _plain_number(value) if math.isfinite(value) else None
    return value
