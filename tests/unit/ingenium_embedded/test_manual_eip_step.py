"""Unit tests for ``ingenium_embedded.manual_eip_step`` (electrical inspection).

Covers the ``convert_units`` helper and the full ``run`` validation + range
verification logic. No external collaborators are involved beyond the standard
step decorator (Redis mocked by the shared fixture).
"""

import sys

from ingenium_embedded import manual_eip_step as step_mod

from mocks.test_helpers import make_step


class TestConvertUnits:
    def test_kiloohm_scaling(self):
        assert step_mod.convert_units("KiloOhm", "KiloOhm", 1, 2, 3) == (1000, 2000, 3000)

    def test_megaohm_scaling(self):
        assert step_mod.convert_units("MegaOhm", "MegaOhm", 1, 2, 3) == (1000000, 2000000, 3000000)

    def test_volt_scaling(self):
        assert step_mod.convert_units("Volt", "Volt", 1, 2, 3) == (1000, 2000, 3000)

    def test_ohm_no_scaling(self):
        assert step_mod.convert_units("Ohm", "Ohm", 1, 2, 3) == (1, 2, 3)


def _entry(**over):
    e = {"actual_value": "5", "unit": "Ohm", "min_value": "0", "max_value": "10"}
    e.update(over)
    return e


def _step(entries):
    return make_step("MANUAL_EIP", {"entries": entries})


class TestManualEipRun:
    def test_in_range_pass(self):
        result = step_mod.run(_step([_entry(actual_value="5", min_value="0", max_value="10")]))
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_out_of_range_fail(self):
        result = step_mod.run(_step([_entry(actual_value="50", min_value="0", max_value="10")]))
        assert result["execution"]["meta_data"]["status"] == "FAIL"

    def test_no_min_max_defaults_pass(self):
        result = step_mod.run(_step([_entry(actual_value="123", min_value=None, max_value=None)]))
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_missing_actual_value(self):
        result = step_mod.run(_step([_entry(actual_value=None)]))
        assert result["execution"]["meta_data"]["status"] == "ERROR"
        assert result["execution"]["meta_data"]["error"]["error_type"] == "USER_INPUT_ERROR"

    def test_overload_ok_with_ohm(self):
        # OL maps to float max; with an infinite max it should PASS.
        result = step_mod.run(_step([_entry(actual_value="OL", unit="Ohm", min_value="0", max_value=None)]))
        assert result["execution"]["meta_data"]["status"] == "PASS"

    def test_overload_wrong_units(self):
        result = step_mod.run(_step([_entry(actual_value="OL", unit="Volt")]))
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_lowercase_ol_rejected(self):
        result = step_mod.run(_step([_entry(actual_value="ol", unit="Ohm")]))
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_non_numeric_actual_value(self):
        result = step_mod.run(_step([_entry(actual_value="abc")]))
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_non_numeric_min_value(self):
        result = step_mod.run(_step([_entry(min_value="abc")]))
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_non_numeric_max_value(self):
        result = step_mod.run(_step([_entry(max_value="abc")]))
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_ohm_volt_mismatch(self):
        result = step_mod.run(_step([_entry(unit="Ohm", measured_unit="Volt")]))
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_volt_ohm_mismatch(self):
        result = step_mod.run(_step([_entry(unit="Volt", measured_unit="Ohm")]))
        assert result["execution"]["meta_data"]["status"] == "ERROR"

    def test_unit_conversion_applied(self):
        # 1 KiloOhm measured, range 500-1500 Ohm -> 1000 Ohm is in range.
        entry = _entry(actual_value="1", unit="Ohm", measured_unit="KiloOhm", min_value="500", max_value="1500")
        result = step_mod.run(_step([entry]))
        assert result["execution"]["meta_data"]["status"] == "PASS"
