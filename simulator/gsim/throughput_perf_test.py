#!/usr/bin/env python3
"""Cheap parser/accounting checks; does not compile or simulate hardware."""
import copy
import json
import unittest
from throughput_perf import EXPECTED_KEYS, parse_measurements, compare_measurements


def sample(cycles=12):
    return [{"name": name, "memory_latency": latency, "rob": 16, "physical": 48, "memory_entries": 2,
        "cycles": cycles, "retired": 20, "ipc": 20 / cycles,
        "zero_commit_cycles": cycles - 10, "single_commit_cycles": 0, "dual_commit_cycles": 10,
        "zero_issue_cycles": cycles - 10, "single_issue_cycles": 0, "dual_issue_cycles": 10, "issued": 20,
        "zero_rename_cycles": cycles - 10, "single_rename_cycles": 0, "dual_rename_cycles": 10,
        "rob_occupancy_sum": 4 * cycles} for name, latency in sorted(EXPECTED_KEYS)]


def output(rows):
    return "\n".join("IPC " + json.dumps(row) for row in rows) + (
        "\nGSIM short two-issue throughput + NEMU: PASS programs=12 commits=5000\n")


class ThroughputReportTest(unittest.TestCase):
    def test_explicit_thirteen_program_candidate_does_not_mutate_baseline(self):
        rows = sample()
        extra = copy.deepcopy(rows[0])
        extra["name"] = "throughput_hint_alias_loop"
        extra["memory_latency"] = 1
        rows.append(extra)
        text = output(rows).replace("programs=12", "programs=13")
        parsed = parse_measurements(text, 13, EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)})
        self.assertEqual(len(parsed), 13)
        with self.assertRaises(RuntimeError):
            parse_measurements(text)
        self.assertEqual(len(parse_measurements(output(sample()))), 12)

    def test_four_slots_require_explicit_geometry(self):
        rows = sample()
        for row in rows:
            row["memory_entries"] = 4
        with self.assertRaises(RuntimeError):
            parse_measurements(output(rows))
        geometry = {"rob": 16, "physical": 48, "memory_entries": 4}
        self.assertEqual(len(parse_measurements(output(rows), expected_geometry=geometry)), 12)
        with self.assertRaises(RuntimeError):
            parse_measurements(output(sample()), expected_geometry=geometry)
        with self.assertRaises(ValueError):
            parse_measurements(output(rows), expected_geometry={"memory_entries": 4})

    def test_complete_accounting(self):
        measured = parse_measurements(output(sample()))
        self.assertEqual(len(measured), 12)
        self.assertEqual(measured[0]["average_rob_occupancy"], 4)

    def test_missing_and_duplicate(self):
        for rows in (sample()[:-1], sample()[:-1] + [sample()[0]]):
            with self.assertRaises(RuntimeError):
                parse_measurements(output(rows))

    def test_no_completion_marker(self):
        with self.assertRaises(RuntimeError):
            parse_measurements(output(sample()).split("\nGSIM")[0])

    def test_bad_counts_or_geometry(self):
        for field, value in (("cycles", 0), ("ipc", 2), ("dual_issue_cycles", 11),
                             ("retired", 22), ("issued", 19), ("rob", 32), ("physical", 64)):
            rows = copy.deepcopy(sample())
            rows[0][field] = value
            with self.assertRaises(RuntimeError):
                parse_measurements(output(rows))

    def test_same_clock_and_break_even(self):
        result = compare_measurements(parse_measurements(output(sample(12))),
                                      parse_measurements(output(sample(15))))
        self.assertAlmostEqual(result[0]["same_clock_speedup"], 0.8)
        self.assertAlmostEqual(result[0]["candidate_clock_ratio_to_break_even"], 1.25)

    def test_different_architecture_rejected(self):
        old = parse_measurements(output(sample()))
        new = copy.deepcopy(old)
        new[0]["retired"] += 1
        with self.assertRaises(RuntimeError):
            compare_measurements(old, new)


if __name__ == "__main__":
    unittest.main()
