# kaynak: oguz-atolye tools/tests/test_result.py @ca27b1b (MIT, PoCAD'e taşındı)
"""pocad/result.py: the result contract and the one gate comparison (D-026, L-21)."""
from __future__ import annotations

import json
import re

import pytest

from conftest import ROOT
from pocad.result import FAIL, INCONCLUSIVE, PASS, PASS_ASSUMED, Result, gate, inconclusive, measurement


def wall(value, at=(1.0, 2.0, 3.0)):
    return Result("min_wall", value, "mm", at=at)


def test_the_band_absorbs_float_noise_at_the_limit_and_nothing_more():
    assert gate("W-1", wall(1.9999999), ">=", 2.0, band=1e-6).status == PASS      # L-21
    assert gate("W-1", wall(1.9999999), ">=", 2.0, band=0).status == FAIL
    assert gate("W-1", wall(1.99), ">=", 2.0, band=1e-6).status == FAIL
    assert gate("W-1", wall(2.0000001), "<=", 2.0, band=1e-6).status == PASS
    assert gate("W-1", wall(2.01), "<=", 2.0, band=1e-6).status == FAIL
    assert gate("N-1", Result("n", 1, "count"), "==", 1, band=0).status == PASS
    assert gate("N-1", Result("n", 2, "count"), "==", 1, band=0).status == FAIL
    assert gate("R-1", wall(1.5), "in", (1.0, 2.0), band=0).status == PASS
    assert gate("R-1", wall(2.5), "in", (1.0, 2.0), band=0).status == FAIL


def test_the_margin_is_signed_positive_inside():
    assert gate("W-1", wall(2.5), ">=", 2.0, band=0).margin == 0.5
    assert gate("W-1", wall(1.5), ">=", 2.0, band=0).margin == -0.5
    assert gate("W-1", wall(1.5), "<=", 2.0, band=0).margin == 0.5
    assert gate("R-1", wall(1.2), "in", (1.0, 2.0), band=0).margin == 0.2


def test_inconclusive_is_never_a_pass():
    empty = inconclusive("min_wall", "mm", "no opposed hits")
    for op, limit in ((">=", 0.0), ("<=", 1e9), ("in", (-1e9, 1e9))):
        result = gate("W-1", empty, op, limit, band=1e3, assumes=["A-01"])
        assert result.status == INCONCLUSIVE and not result.passed
        assert result.measured is None and result.margin is None


def test_assumptions_make_a_pass_conditional_and_leave_a_fail_alone():
    assert gate("W-1", wall(3), ">=", 2, band=0, assumes=["A-02"]).status == PASS_ASSUMED
    assert gate("W-1", wall(1), ">=", 2, band=0, assumes=["A-02"]).status == FAIL


def test_the_band_is_always_stated():
    with pytest.raises(TypeError):
        gate("W-1", wall(3), ">=", 2)                                             # noqa
    with pytest.raises(ValueError):
        gate("W-1", wall(3), ">=", 2, band=-1)
    with pytest.raises(ValueError):
        gate("W-1", wall(3), "~=", 2, band=0)


def test_a_gate_row_is_a_verdict_schema_row():
    schema = json.loads((ROOT / "pocad" / "schemas" / "verdict.schema.json").read_text(encoding="utf-8"))
    item = schema["properties"]["gates"]["items"]
    row = gate("W-1", wall(2.5), ">=", 2.0, band=0, assumes=["A-01"]).row()
    assert set(row) == set(item["required"]) == set(item["properties"])
    assert row["status"] in item["properties"]["status"]["enum"]
    assert row["at"] == "(1.0000, 2.0000, 3.0000) mm"
    assert json.loads(json.dumps(row)) == row
    gate_id = re.compile(item["properties"]["gate"]["pattern"])
    assert gate_id.search(row["gate"]) and gate_id.search("C-01a")
    assert not gate_id.search("U-02 (b) driver envelope")                 # one §5 ID per row
    target = re.compile(schema["properties"]["target"]["pattern"])
    assert target.search("lid_v02") and not target.search("lid_v01 (v02 geometry)")
    unit = re.compile(item["properties"]["unit"]["pattern"])
    assert unit.search(row["unit"]) and not unit.search("mm per 10 deg")


def test_results_refuse_to_carry_a_fake_number():
    with pytest.raises(ValueError):
        Result("x", None, "mm")                                   # MEASURED without a number
    with pytest.raises(ValueError):
        Result("x", float("nan"), "mm")
    with pytest.raises(ValueError):
        Result("x", None, "mm", status=INCONCLUSIVE)             # no reason given
    assert Result("x", True, "bool").measured == 1


def test_a_raising_measurement_is_inconclusive_not_zero():
    @measurement("broken", "mm")
    def broken(shape):
        raise RuntimeError("boolean failed")

    @measurement("sloppy", "mm")
    def sloppy(shape):
        return 0.0

    for result in (broken(None), sloppy(None)):
        assert result.status == INCONCLUSIVE and result.measured is None and result.reason
    assert "boolean failed" in broken(None).reason


def test_a_margin_keeps_its_sign_however_small():
    tiny = gate("W-1", wall(2.0 - 4e-10), ">=", 2.0, band=0)
    assert tiny.status == FAIL and tiny.margin < 0
    assert gate("R-1", wall(1.2), "in", (1.0, 2.0), band=0).margin == 0.2          # noise rounded away


def test_the_band_is_not_part_of_the_margin():
    """A value that passes inside the band shows by how much it missed the limit."""
    inside = gate("W-1", wall(1.9999999), ">=", 2.0, band=1e-6)
    assert inside.status == PASS and inside.margin < 0
    near = gate("N-1", Result("n", 1.0000004, "count"), "==", 1, band=1e-6)
    assert near.status == PASS and near.margin < 0
    assert gate("N-1", Result("n", 1, "count"), "==", 1, band=0).margin == 0


@pytest.mark.parametrize("op,limit", [
    ("<=", float("nan")), (">=", float("-inf")), (">=", True), ("==", "2"),
    ("in", (2.0, 1.0)), ("in", (1.0,)), ("in", (0.0, float("inf"))),
])
def test_a_limit_is_a_finite_number(op, limit):
    with pytest.raises(ValueError, match="limit"):
        gate("W-1", wall(3.0), op, limit, band=0)


@pytest.mark.parametrize("assumes", ["A-01", ["A-1"], ["B-01"], [1]])
def test_assumes_is_a_list_of_ledger_ids(assumes):
    with pytest.raises(ValueError, match="assumes"):
        gate("W-1", wall(3.0), ">=", 2.0, band=0, assumes=assumes)


def test_every_measurement_registers_its_name():
    from pocad.result import MEASUREMENTS

    @measurement("registered_for_the_test", "mm")
    def probe(shape):
        return Result("registered_for_the_test", 1.0, "mm")

    assert MEASUREMENTS["registered_for_the_test"] == __name__
    del MEASUREMENTS["registered_for_the_test"]


def test_gate_takes_any_iterable_of_ids_and_numpy_numbers():
    import numpy as np
    passed = gate("W-1", wall(np.float64(3.0)), ">=", np.int64(2), band=np.float64(0),
                  assumes=(a for a in ["A-01"]))
    assert passed.status == PASS_ASSUMED and passed.assumes == ("A-01",)
    assert json.loads(json.dumps(passed.row())) == passed.row()
    assert type(Result("n", np.int64(3), "count").measured) is int


def test_numpy_bools_and_numbers_become_plain_values():
    import numpy as np
    assert Result("flag", np.bool_(True), "bool").measured == 1
    located = Result("w", 1.0, "mm", at=(np.float32(1.5), np.float64(2.0), np.int64(3)))
    assert json.loads(json.dumps(located.to_dict()))["at"] == [1.5, 2.0, 3]


def test_a_measurement_set_is_one_check_with_the_same_contract():
    from pocad.result import MEASUREMENTS, measurement_set
    keys = {"a": ("set_a", "mm"), "b": ("set_b", "count")}

    @measurement_set("set_for_the_test", keys)
    def good():
        return {"a": Result("set_a", 1.0, "mm"), "b": Result("set_b", 2, "count")}

    @measurement_set("set_for_the_test", keys)
    def broken():
        raise RuntimeError("no solid")

    @measurement_set("set_for_the_test", keys)
    def partial():
        return {"a": Result("wrong_name", 1.0, "mm")}

    assert {k: r.measured for k, r in good().items()} == {"a": 1.0, "b": 2}
    assert all(r.status == INCONCLUSIVE and "no solid" in r.reason for r in broken().values())
    assert [r.name for r in broken().values()] == ["set_a", "set_b"]
    assert all(r.status == INCONCLUSIVE and "did not measure" in r.reason for r in partial().values())
    assert MEASUREMENTS.pop("set_for_the_test") == __name__
