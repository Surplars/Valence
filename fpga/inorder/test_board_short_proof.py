import copy
import unittest
from board_short_proof import (BANDWIDTH37, BANDWIDTH38, BANDWIDTH39, BANDWIDTH40, REQUIRED_FLAGS,
    bandwidth37_flags, bandwidth38_flags, bandwidth38_audit, bandwidth39_flags, bandwidth39_audit,
    bandwidth40_flags, bandwidth40_audit)


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


def fixture38():
    r = fixture()
    r.update(status=BANDWIDTH38, source_sha256={"source": "digest"},
             artifact_sha256={"artifact": "digest"})
    r["performance_gates"] = {"coremark": True}
    for mode in ("bare", "sv39"):
        for suffix in ("", "-latency80"):
            for metric in ("read_ticks", "write_ticks", "copy_ticks"):
                r["performance_gates"]["cpu-coherent-64k-"+mode+suffix+"/"+metric] = True
    audit = dict(status="PASS_BATCH38_SHORT_AND_LEAF_MAPPING_CPU_STA_PENDING",
        receipt_sha256="digest", sources_rehashed=1, artifacts_rehashed=1, checks=29,
        performance_gates=13, identical_stream_cases=6, coremark_identical=True,
        full_board_synthesized=False, physical_qualified=False, bit_generated=False,
        configuration=dict(cpu_target_hz=300000000, cache_bytes_each=32768, ddr_slots=2,
            write_slots=1, multiclock_changed=False, flags_identical_to_batch37=True),
        state_structure=dict(register_declarations_before=6999, register_declarations_after=6999,
            directory_banks=4, directory_write_ports_before=8, directory_write_ports_after=4,
            new_control_state_bits=0, new_payload_ram_bits=0),
        directory_leaf=dict(width=20, depth=256, read_ports=6, write_ports=1,
            lut=700, lutram_lut=576, logic_lut=124, ff=0),
        dt_address_local_cone=dict(new_reply_inputs=[]),
        independent_negative=dict(old_two_write_port_leaf_rejected=True))
    return r, audit


class Batch38ProofTest(unittest.TestCase):
    def test_distinct_complete_profile(self):
        r, audit = fixture38()
        self.assertEqual(bandwidth38_flags(r), r["cpu_flags"])
        bandwidth38_audit(r, audit, "digest")
        with self.assertRaises(ValueError): bandwidth37_flags(r)
        with self.assertRaises(ValueError): bandwidth38_flags(fixture())

    def test_gate_names_not_only_count(self):
        r, _ = fixture38()
        r["performance_gates"]["unrelated"] = r["performance_gates"].pop("coremark")
        with self.assertRaises(ValueError): bandwidth38_flags(r)

    def test_single_writer_no_capacity_or_state_growth(self):
        r, base = fixture38()
        for section, key, value in (("directory_leaf", "write_ports", 2),
                ("directory_leaf", "read_ports", 5), ("directory_leaf", "ff", 5120),
                ("state_structure", "new_control_state_bits", 1),
                ("state_structure", "directory_write_ports_after", 8),
                ("configuration", "ddr_slots", 4), ("configuration", "multiclock_changed", True)):
            audit = copy.deepcopy(base); audit[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                bandwidth38_audit(r, audit, "digest")

    def test_audit_drift_and_incomplete_cone_rejected(self):
        r, base = fixture38()
        for key, value in (("receipt_sha256", "wrong"), ("sources_rehashed", 0),
                           ("coremark_identical", False), ("physical_qualified", True)):
            audit = copy.deepcopy(base); audit[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                bandwidth38_audit(r, audit, "digest")
        base["dt_address_local_cone"]["new_reply_inputs"] = ["io_physical_response_valid"]
        with self.assertRaises(ValueError): bandwidth38_audit(r, base, "digest")


class Batch39ProofTest(unittest.TestCase):
    def fixture(self):
        r, _ = fixture38()
        r["status"] = BANDWIDTH39
        for name in ("predictor-c", "write-commit-256", "write-commit-32768", "mmu-shifted"):
            r["checks"].update({name: "PASS", name+"-negative": "PASS_EXPECTED_ORACLE_REJECTION"})
        audit = dict(status="PASS_BATCH39_SHORT_NO_REGRESSION_PHYSICAL_PENDING",
            receipt_sha256="digest", sources_rehashed=1, artifacts_rehashed=1,
            checks=37, performance_gates=13, identical_stream_cases=6, coremark_identical=True,
            memory_structure_equal=True, register_declarations_equal=True, register_declarations_before=6999,
            register_declarations_after=6999, directory_write_ports=4, new_payload_ram_bits=0,
            multiclock_changed=False, physical_qualified=False, bit_generated=False)
        return r, audit

    def test_distinct_profile(self):
        r, audit = self.fixture()
        self.assertEqual(len(r["checks"]), 37)
        bandwidth39_audit(r, audit, "digest")
        with self.assertRaises(ValueError): bandwidth38_flags(r)
        with self.assertRaises(ValueError): bandwidth39_flags(fixture38()[0])

    def test_each_new_independent_check_required(self):
        r, _ = self.fixture()
        for name in ("predictor-c", "write-commit-256", "write-commit-32768", "mmu-shifted"):
            bad = copy.deepcopy(r); del bad["checks"][name+"-negative"]
            with self.subTest(name=name), self.assertRaises(ValueError): bandwidth39_flags(bad)

    def test_no_growth_or_state_drift(self):
        r, audit = self.fixture()
        for key, value in (("memory_structure_equal", False), ("register_declarations_after", 7000),
                ("directory_write_ports", 8), ("multiclock_changed", True),
                ("coremark_identical", False), ("receipt_sha256", "wrong")):
            bad = dict(audit); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): bandwidth39_audit(r, bad, "digest")


class Batch40ProofTest(unittest.TestCase):
    def fixture(self):
        r, audit = Batch39ProofTest().fixture()
        r["status"] = BANDWIDTH40
        for width in (32, 64):
            for name in ("pmp-"+str(width)+"-direct", "pmp-"+str(width)+"-registered",
                         "execute-"+str(width)):
                r["checks"].update({name: "PASS", name+"-negative": "PASS_EXPECTED_ORACLE_REJECTION"})
        audit.update(status="PASS_BATCH40_SHORT_NO_REGRESSION_PHYSICAL_PENDING", checks=49)
        return r, audit

    def test_distinct_complete_profile(self):
        r, audit = self.fixture()
        self.assertEqual(len(r["checks"]), 49)
        bandwidth40_audit(r, audit, "digest")
        with self.assertRaises(ValueError): bandwidth39_flags(r)
        with self.assertRaises(ValueError): bandwidth40_flags(Batch39ProofTest().fixture()[0])

    def test_independent_pmp_and_execute_controls_required(self):
        r, _ = self.fixture()
        for name in ("pmp-32-direct", "pmp-32-registered", "pmp-64-direct",
                     "pmp-64-registered", "execute-32", "execute-64"):
            bad = copy.deepcopy(r); del bad["checks"][name+"-negative"]
            with self.subTest(name=name), self.assertRaises(ValueError): bandwidth40_flags(bad)

    def test_regression_capacity_and_state_drift_rejected(self):
        r, audit = self.fixture()
        for key, value in (("register_declarations_equal", False), ("memory_structure_equal", False),
                           ("identical_stream_cases", 5), ("coremark_identical", False),
                           ("multiclock_changed", True), ("directory_write_ports", 8)):
            bad = dict(audit); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): bandwidth40_audit(r, bad, "digest")


if __name__ == "__main__":
    unittest.main()
