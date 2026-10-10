"""Small receipt sensitivity tests; no Scala, generated model or tool setup."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("board_gate", Path(__file__).with_name("run_board.py"))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def window(name):
    # Four literal edges: empty; AR+AW; stalled R with accepted W;
    # final accepted R while B remains pending. One narrow two-byte read.
    return {"window": name, "cycles": 4, "outstanding_sample": "pre_edge_accepted_owners",
            "ar": {"fire": 1, "valid_not_ready": 0, "no_offer": 3},
            "aw": {"fire": 1, "valid_not_ready": 0, "no_offer": 3},
            "r": {"fire": 1, "valid_not_ready": 1, "no_offer": 2},
            "w": {"fire": 1, "valid_not_ready": 0, "no_offer": 3},
            "accepted_r_wire_bytes": 8, "accepted_r_requested_payload_bytes": 2,
            "accepted_w_wire_bytes": 8, "accepted_w_strobe_bytes": 3,
            "read_outstanding_histogram": {"0": 2, "1": 2},
            "write_outstanding_histogram": {"0": 2, "1": 2},
            "read_outstanding_cycle_sum": 2, "write_outstanding_cycle_sum": 2,
            "read_outstanding_peak": 1, "write_outstanding_peak": 1,
            "r_backpressure_cycles": 1}


class ReceiptControls(unittest.TestCase):
    def test_manual_narrow_transfer_and_held_b_receipt(self):
        gate.verify_metrics({name: window(name) for name in ("kernel", "flush")})

    def test_reject_dropped_stall_cycle(self):
        metrics = {name: window(name) for name in ("kernel", "flush")}
        metrics["kernel"]["r"]["valid_not_ready"] = 0
        with self.assertRaisesRegex(gate.core.GateError, "cycle conservation"):
            gate.verify_metrics(metrics)

    def test_reject_wire_bytes_mislabeled_as_narrow_payload(self):
        metrics = {name: window(name) for name in ("kernel", "flush")}
        metrics["kernel"]["accepted_r_wire_bytes"] = 2
        with self.assertRaisesRegex(gate.core.GateError, "wire byte count"):
            gate.verify_metrics(metrics)

    def test_reject_missing_accepted_write_tail(self):
        metrics = {name: window(name) for name in ("kernel", "flush")}
        metrics["kernel"]["write_outstanding_histogram"] = {"0": 3, "1": 1}
        with self.assertRaisesRegex(gate.core.GateError, "histogram conservation"):
            gate.verify_metrics(metrics)

    def test_complete_sparse_comparison_rejects_extra_write_outside_dense_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for variant in ("old-only", "off", "on"):
                output = root / "cases" / variant
                output.mkdir(parents=True)
                for name in ("guest.bin", "initial-memory.bin", "final-memory.bin"):
                    (output / name).write_bytes(bytes([0x13, 0, 0, 0]))
                for name in ("initial-memory-sparse.json", "final-memory-sparse.json"):
                    (output / name).write_text('{"65536":19}\n')
            gate.verify_same_guest_and_memory(root)
            (root / "cases/on/final-memory-sparse.json").write_text('{"0":1,"65536":19}\n')
            with self.assertRaisesRegex(gate.core.GateError, "full-memory image differs"):
                gate.verify_same_guest_and_memory(root)

    def test_missing_flush_window_is_not_a_pass(self):
        with self.assertRaisesRegex(gate.core.GateError, "complete kernel/flush"):
            gate.verify_metrics({"kernel": window("kernel")})


if __name__ == "__main__":
    unittest.main()
