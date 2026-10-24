import copy
import unittest

from a1_frontend_stage import compare


class FrontendStageComparisonTest(unittest.TestCase):
    def setUp(self):
        self.baseline = {
            "status": "PASS_BOUNDED_A1_FRONTEND_SUPPLY_ONLY",
            "configuration": {"cache": 8}, "serviceLaw": {"latency": 7},
            "compiler": "locked", "gsimSha256": "locked",
            "scenarios": {"ram": {"work_cycles": 332, "verified": 128, "faults": 0,
                                   "vlatency_sum": 348, "consumed2": 64,
                                   "get_extent_hash": 123, "total_cycles_with_drain": 351}},
        }

    def test_exact_match(self):
        self.assertTrue(compare(self.baseline, copy.deepcopy(self.baseline))[0]["identical"])

    def test_every_observation_change_is_visible(self):
        for key in self.baseline["scenarios"]["ram"]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.baseline)
                changed["scenarios"]["ram"][key] += 1
                result = compare(self.baseline, changed)[0]
                self.assertFalse(result["identical"])
                self.assertEqual(set(result["differences"]), {key})

    def test_missing_and_extra_metrics_fail(self):
        for add in (False, True):
            changed = copy.deepcopy(self.baseline)
            if add:
                changed["scenarios"]["ram"]["new_counter"] = 0
            else:
                del changed["scenarios"]["ram"]["faults"]
            self.assertFalse(compare(self.baseline, changed)[0]["identical"])

    def test_unmatched_inputs_or_scenarios_fail(self):
        for key in ("configuration", "serviceLaw", "compiler", "gsimSha256", "status", "scenarios"):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.baseline)
                changed[key] = {}
                with self.assertRaises(RuntimeError):
                    compare(self.baseline, changed)


if __name__ == "__main__":
    unittest.main()
