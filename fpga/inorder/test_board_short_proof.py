import unittest
from board_short_proof import BANDWIDTH37, REQUIRED_FLAGS, bandwidth37_flags


def fixture():
    checks = {"precise-privilege", "precise-privilege-negative", "ca", "ca-boundary", "fd-context",
              "coremark-o3", "coremark-o3-negative", "home-read-pair", "home-read-pair-negative",
              "mmu-handoff", "mmu-handoff-negative"}
    for n in ("pair-256-serial", "pair-256-overlap", "pair-32768-overlap"):
        checks.update((n, n+"-negative", n+"-stream", n+"-stream-negative"))
    for mode in ("bare", "sv39"):
        checks.update(("cpu-coherent-"+mode, "cpu-coherent-64k-"+mode,
                       "cpu-coherent-64k-"+mode+"-latency80"))
    return dict(status=BANDWIDTH37, cpu_flags=sorted(REQUIRED_FLAGS), cache_bytes_each=32768,
                ddr_slots=2, write_slots=1, components_only=False, physical_qualified=False,
                board_qualified=False, checks={k: "PASS" for k in checks},
                performance_gates={str(i): True for i in range(13)})


class BoardShortProofTest(unittest.TestCase):
    def test_explicit_schema(self):
        r = fixture()
        self.assertEqual(len(r["checks"]), 29)
        self.assertEqual(bandwidth37_flags(r), r["cpu_flags"])

    def test_reject_status_scope_capacity_and_gates(self):
        mutations = [("status", "FAIL"), ("status", "PASS_I1_BANDWIDTH37_COMPONENTS_ONLY"),
                     ("components_only", True), ("ddr_slots", 4), ("write_slots", 2),
                     ("cache_bytes_each", 65536), ("physical_qualified", True)]
        for key, value in mutations:
            r = fixture(); r[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                bandwidth37_flags(r)
        r = fixture(); r["performance_gates"]["0"] = False
        with self.assertRaises(ValueError): bandwidth37_flags(r)
        r = fixture(); del r["checks"]["home-read-pair-negative"]
        with self.assertRaises(ValueError): bandwidth37_flags(r)

    def test_every_new_flag_and_negative_control_is_required(self):
        for flag in REQUIRED_FLAGS:
            r = fixture(); r["cpu_flags"].remove(flag)
            with self.subTest(flag=flag), self.assertRaises(ValueError): bandwidth37_flags(r)
        r = fixture(); r["cpu_flags"].append(r["cpu_flags"][0])
        with self.assertRaises(ValueError): bandwidth37_flags(r)
        r = fixture(); r["checks"]["mmu-handoff-negative"] = "SKIPPED"
        with self.assertRaises(ValueError): bandwidth37_flags(r)


if __name__ == "__main__":
    unittest.main()
