"""Unit tests for ``ingenium_embedded.verification_lib``.

Covers the ``Verify`` factory routing, the concrete verifier subclasses'
comparison logic and ``type_check`` validation, and the pure EVR / data-product
verification helpers. These are pure in-process computations (no I/O).
"""

import pytest

from ingenium_embedded import verification_lib as vlib
from ingenium_embedded.verification_lib import (
    Verify,
    VerifyInteger,
    VerifyFloat,
    VerifyString,
    VerifyBoolean,
    verify_query_evr_results,
    verify_data_product_condition,
)
from ingenium_embedded.ingenium_library import StepExecutionError


def _query(condition, values, actual_value=None, vtype="INTEGER", verify_on="VALUE"):
    return {
        "verification_condition": condition,
        "verification_values": list(values),
        "verify_on": verify_on,
        "actual_value": actual_value,
        "type": vtype,
    }


def _step(step_type="MANUAL_INPUT"):
    return {"step_type": step_type}


# ---------------------------------------------------------------------------
# Verify.factory routing
# ---------------------------------------------------------------------------
class TestVerifyFactory:
    def test_manual_input_integer(self):
        ver = Verify.factory(_step("MANUAL_INPUT"), _query("EQUAL", [1], 1), value_type="INTEGER")
        assert isinstance(ver, VerifyInteger)

    def test_manual_input_float(self):
        ver = Verify.factory(_step("MANUAL_INPUT"), _query("EQUAL", [1.0], 1.0, vtype="FLOAT"), value_type="FLOAT")
        assert isinstance(ver, VerifyFloat)

    def test_manual_input_string(self):
        ver = Verify.factory(_step("MANUAL_INPUT"), _query("EQUAL", ["a"], "a", vtype="STRING"), value_type="STRING")
        assert isinstance(ver, VerifyString)

    def test_manual_input_boolean(self):
        ver = Verify.factory(_step("MANUAL_INPUT"), _query("EQUAL", [True], True, vtype="BOOLEAN"), value_type="BOOLEAN")
        assert isinstance(ver, VerifyBoolean)

    def test_manual_input_unknown_type_raises(self):
        with pytest.raises(StepExecutionError):
            Verify.factory(_step("MANUAL_INPUT"), _query("EQUAL", [1], 1), value_type="WEIRD")

    def test_eha_integer(self):
        ver = Verify.factory(_step("VERIFY_EHA"), _query("EQUAL", [1]), value_type="INTEGER", eha_response={"actual_value": 1})
        assert isinstance(ver, VerifyInteger)

    def test_eha_unknown_type_raises(self):
        with pytest.raises(StepExecutionError):
            Verify.factory(_step("WAIT_EHA"), _query("EQUAL", [1]), value_type="BOOLEAN")

    def test_environment_manual_returns_float(self):
        ver = Verify.factory(_step("ENVIRONMENT_MANUAL"), _query("EQUAL", [1.0], 1.0, vtype="FLOAT"), environment_type="temperature")
        assert isinstance(ver, VerifyFloat)

    def test_unknown_step_type_raises(self):
        with pytest.raises(StepExecutionError):
            Verify.factory(_step("NOPE"), _query("EQUAL", [1], 1))


# ---------------------------------------------------------------------------
# VerifyInteger comparison logic
# ---------------------------------------------------------------------------
class TestVerifyInteger:
    def _run(self, condition, values, actual):
        ver = VerifyInteger(_step("MANUAL_INPUT"), _query(condition, values, actual))
        return ver.verify()[2]

    def test_greater_than(self):
        assert self._run("GREATER_THAN", ["5"], 10) == "PASS"
        assert self._run("GREATER_THAN", ["5"], 1) == "FAIL"

    def test_less_than(self):
        assert self._run("LESS_THAN", ["5"], 1) == "PASS"
        assert self._run("LESS_THAN", ["5"], 10) == "FAIL"

    def test_gte(self):
        assert self._run("GREATER_THAN_OR_EQUAL", ["5"], 5) == "PASS"
        assert self._run("GREATER_THAN_OR_EQUAL", ["5"], 4) == "FAIL"

    def test_lte(self):
        assert self._run("LESS_THAN_OR_EQUAL", ["5"], 5) == "PASS"
        assert self._run("LESS_THAN_OR_EQUAL", ["5"], 6) == "FAIL"

    def test_equal(self):
        assert self._run("EQUAL", ["5"], 5) == "PASS"
        assert self._run("EQUAL", ["5"], 6) == "FAIL"

    def test_not_equal(self):
        assert self._run("NOT_EQUAL", ["5"], 6) == "PASS"
        assert self._run("NOT_EQUAL", ["5"], 5) == "FAIL"

    def test_record(self):
        assert self._run("RECORD", [], 0) == "PASS"
        assert self._run("RECORD", [], None) == "FAIL"

    def test_not_present(self):
        # NOT_PRESENT is not allowed for MANUAL_INPUT; use a telemetry step type.
        ver = VerifyInteger(_step("BUS_1553"), _query("NOT_PRESENT", [], None))
        assert ver.verify()[2] == "PASS"

    def test_inclusive_range(self):
        assert self._run("INCLUSIVE_RANGE", ["1", "10"], 5) == "PASS"
        assert self._run("INCLUSIVE_RANGE", ["1", "10"], 11) == "FAIL"

    def test_exclusive_range(self):
        assert self._run("EXCLUSIVE_RANGE", ["1", "10"], 5) == "PASS"
        assert self._run("EXCLUSIVE_RANGE", ["1", "10"], 10) == "FAIL"

    def test_bad_verification_value_raises(self):
        with pytest.raises(StepExecutionError):
            VerifyInteger(_step("MANUAL_INPUT"), _query("EQUAL", ["abc"], 1))

    def test_eha_response_path(self):
        eha = {"actual_value": 9, "verification_status": ""}
        ver = VerifyInteger(_step("VERIFY_EHA"), _query("EQUAL", ["9"]), eha_response=eha)
        query, actual, status = ver.verify()
        assert status == "PASS"
        assert actual == 9


# ---------------------------------------------------------------------------
# type_check validation errors (via VerifyInteger)
# ---------------------------------------------------------------------------
class TestTypeCheckErrors:
    def test_condition_not_supported_for_type(self):
        ver = VerifyInteger(_step("MANUAL_INPUT"), _query("CONTAINS", ["1"], 1))
        with pytest.raises(StepExecutionError):
            ver.verify()

    def test_unknown_condition(self):
        ver = VerifyInteger(_step("MANUAL_INPUT"), _query("FOO", ["1"], 1))
        with pytest.raises(StepExecutionError):
            ver.verify()

    def test_missing_actual_value(self):
        ver = VerifyInteger(_step("MANUAL_INPUT"), _query("EQUAL", ["1"], None))
        with pytest.raises(StepExecutionError):
            ver.verify()

    def test_math_condition_requires_single_value(self):
        ver = VerifyInteger(_step("MANUAL_INPUT"), _query("EQUAL", ["1", "2"], 1))
        with pytest.raises(StepExecutionError):
            ver.verify()

    def test_math_condition_empty_values(self):
        ver = VerifyInteger(_step("MANUAL_INPUT"), _query("EQUAL", [], 1))
        with pytest.raises(StepExecutionError):
            ver.verify()

    def test_range_requires_two_values(self):
        ver = VerifyInteger(_step("MANUAL_INPUT"), _query("INCLUSIVE_RANGE", ["1"], 1))
        with pytest.raises(StepExecutionError):
            ver.verify()

    def test_range_too_many_values(self):
        ver = VerifyInteger(_step("MANUAL_INPUT"), _query("INCLUSIVE_RANGE", ["1", "2", "3"], 1))
        with pytest.raises(StepExecutionError):
            ver.verify()

    def test_not_present_disallowed_for_manual_input(self):
        ver = VerifyInteger(_step("MANUAL_INPUT"), _query("NOT_PRESENT", [], None))
        with pytest.raises(StepExecutionError):
            ver.verify()


# ---------------------------------------------------------------------------
# VerifyFloat / VerifyString / VerifyBoolean
# ---------------------------------------------------------------------------
class TestVerifyFloat:
    def test_equal_pass(self):
        ver = VerifyFloat(_step("MANUAL_INPUT"), _query("EQUAL", ["1.5"], 1.5, vtype="FLOAT"))
        assert ver.verify()[2] == "PASS"

    def test_bad_value_raises(self):
        with pytest.raises(StepExecutionError):
            VerifyFloat(_step("MANUAL_INPUT"), _query("EQUAL", ["abc"], 1.0, vtype="FLOAT"))


class TestVerifyString:
    def test_equal(self):
        ver = VerifyString(_step("MANUAL_INPUT"), _query("EQUAL", ["hi"], "hi", vtype="STRING"))
        assert ver.verify()[2] == "PASS"

    def test_not_equal(self):
        ver = VerifyString(_step("MANUAL_INPUT"), _query("NOT_EQUAL", ["hi"], "bye", vtype="STRING"))
        assert ver.verify()[2] == "PASS"

    def test_record(self):
        ver = VerifyString(_step("MANUAL_INPUT"), _query("RECORD", [], "x", vtype="STRING"))
        assert ver.verify()[2] == "PASS"

    def test_contains(self):
        ver = VerifyString(_step("MANUAL_INPUT"), _query("CONTAINS", ["ell"], "hello", vtype="STRING"))
        assert ver.verify()[2] == "PASS"


class TestVerifyBoolean:
    def test_equal(self):
        ver = VerifyBoolean(_step("MANUAL_INPUT"), _query("EQUAL", [True], True, vtype="BOOLEAN"))
        assert ver.verify()[2] == "PASS"

    def test_not_equal(self):
        ver = VerifyBoolean(_step("MANUAL_INPUT"), _query("NOT_EQUAL", [True], False, vtype="BOOLEAN"))
        assert ver.verify()[2] == "PASS"

    def test_record(self):
        ver = VerifyBoolean(_step("MANUAL_INPUT"), _query("RECORD", [], True, vtype="BOOLEAN"))
        assert ver.verify()[2] == "PASS"


# ---------------------------------------------------------------------------
# verify_query_evr_results
# ---------------------------------------------------------------------------
class TestVerifyQueryEvrResults:
    def _run(self, condition, total, value):
        obj = {"total_count": total, "verification_value": value, "verification_condition": condition}
        return verify_query_evr_results(obj)["verification_status"]

    def test_greater_than(self):
        assert self._run("GREATER_THAN", 5, 3) == "PASS"
        assert self._run("GREATER_THAN", 2, 3) == "FAIL"

    def test_less_than(self):
        assert self._run("LESS_THAN", 2, 3) == "PASS"

    def test_gte(self):
        assert self._run("GREATER_THAN_OR_EQUAL", 3, 3) == "PASS"

    def test_lte(self):
        assert self._run("LESS_THAN_OR_EQUAL", 3, 3) == "PASS"

    def test_equal(self):
        assert self._run("EQUAL", 3, 3) == "PASS"
        assert self._run("EQUAL", 4, 3) == "FAIL"

    def test_not_equal(self):
        assert self._run("NOT_EQUAL", 4, 3) == "PASS"

    def test_record(self):
        assert self._run("RECORD", 0, 0) == "PASS"

    def test_string_value_for_numeric_condition_fails(self):
        assert self._run("GREATER_THAN", 5, "three") == "FAIL"


# ---------------------------------------------------------------------------
# verify_data_product_condition
# ---------------------------------------------------------------------------
class TestVerifyDataProductCondition:
    def _run(self, condition, total, value):
        dp = {"total_count": total, "verification_value": value, "verification_condition": condition}
        return verify_data_product_condition(dp)["verification_status"]

    def test_greater_than(self):
        assert self._run("GREATER_THAN", 5, 3) == "PASS"

    def test_less_than(self):
        assert self._run("LESS_THAN", 1, 3) == "PASS"

    def test_gte(self):
        assert self._run("GREATER_THAN_OR_EQUAL", 3, 3) == "PASS"

    def test_lte(self):
        assert self._run("LESS_THAN_OR_EQUAL", 3, 3) == "PASS"

    def test_equal(self):
        assert self._run("EQUAL", 3, 3) == "PASS"

    def test_record_true(self):
        assert self._run("RECORD", 2, 0) == "PASS"

    def test_record_zero_fails(self):
        assert self._run("RECORD", 0, 0) == "FAIL"
