"""Tests for tool call loop detector."""
import time

import pytest

from app.pipeline.loop_detector import LoopDetectedError, LoopDetector


class TestFingerprint:
    def test_same_tool_no_args_same_fingerprint(self):
        fp1 = LoopDetector.fingerprint("give_nir", None)
        fp2 = LoopDetector.fingerprint("give_nir", None)
        assert fp1 == fp2

    def test_same_tool_same_args_same_fingerprint(self):
        fp1 = LoopDetector.fingerprint("end_call", {"reason": "done"})
        fp2 = LoopDetector.fingerprint("end_call", {"reason": "done"})
        assert fp1 == fp2

    def test_different_args_different_fingerprint(self):
        fp1 = LoopDetector.fingerprint("end_call", {"reason": "done"})
        fp2 = LoopDetector.fingerprint("end_call", {"reason": "voicemail"})
        assert fp1 != fp2

    def test_different_tools_different_fingerprint(self):
        fp1 = LoopDetector.fingerprint("give_nir", None)
        fp2 = LoopDetector.fingerprint("give_patient_name", None)
        assert fp1 != fp2

    def test_args_order_independent(self):
        fp1 = LoopDetector.fingerprint("extract_information", {"a": 1, "b": 2})
        fp2 = LoopDetector.fingerprint("extract_information", {"b": 2, "a": 1})
        assert fp1 == fp2


class TestRecord:
    def test_first_call_count_one(self):
        d = LoopDetector()
        count, fp = d.record("give_nir")
        assert count == 1
        assert len(fp) == 16

    def test_repeated_calls_count_increments(self):
        d = LoopDetector()
        c1, _ = d.record("give_nir")
        c2, _ = d.record("give_nir")
        c3, _ = d.record("give_nir")
        assert c1 == 1
        assert c2 == 2
        assert c3 == 3

    def test_different_tools_separate_counts(self):
        d = LoopDetector()
        d.record("give_nir")
        d.record("give_nir")
        c, _ = d.record("give_patient_name")
        assert c == 1  # different tool, fresh count

    def test_window_eviction(self):
        d = LoopDetector(window_seconds=0.1)
        d.record("give_nir")
        d.record("give_nir")
        time.sleep(0.15)
        c, _ = d.record("give_nir")
        # After window expiry, only the latest call counts
        assert c == 1

    def test_reset_clears_history(self):
        d = LoopDetector()
        d.record("give_nir")
        d.record("give_nir")
        d.reset()
        c, _ = d.record("give_nir")
        assert c == 1


class TestThresholds:
    def test_threshold_warn_default(self):
        assert LoopDetector().threshold_warn == 2

    def test_threshold_abort_default(self):
        assert LoopDetector().threshold_abort == 3

    def test_custom_thresholds(self):
        d = LoopDetector(threshold_warn=5, threshold_abort=10)
        assert d.threshold_warn == 5
        assert d.threshold_abort == 10


class TestLoopDetectedError:
    def test_error_fields(self):
        err = LoopDetectedError("give_nir", "abc123", 3)
        assert err.tool_name == "give_nir"
        assert err.fingerprint == "abc123"
        assert err.count == 3
        assert "give_nir" in str(err)
        assert "abc123" in str(err)
