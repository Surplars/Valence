#!/usr/bin/env python3
"""Source-model and comparator rejection tests; no compiled model execution."""
import copy
from pathlib import Path
import unittest

from source_reference import (MASK, RAM_BASE, ROM_BASE, Op, ReferenceError,
                              SourceProgram, compare_transcripts)

SOURCE = Path(__file__).resolve().parents[5] / "simulator/gsim/payloads/branch-program.S"


def program(body):
    return SourceProgram(".option norvc\n.option norelax\n.section .text\n.global _start\n_start:\n" + body + "\n.Lend:\n")


class SourceSemanticsTests(unittest.TestCase):
    def test_original_source_success_and_boot_retained(self):
        p = SourceProgram(SOURCE.read_text())
        result = p.run()
        self.assertEqual(result["events"][0]["pc"], ROM_BASE)
        self.assertEqual(result["events"][1]["nextPc"], RAM_BASE)
        self.assertEqual(result["regs"][31], RAM_BASE)
        self.assertEqual(result["roi_begin_index"], 2)
        self.assertTrue(all(event["instruction"] != 0 for event in result["events"]))
        self.assertEqual(result["terminal"]["pc"], p.labels["benchmark_terminal"])
        self.assertEqual(result["events"][result["roi_end_index"]]["instruction"], 0x13)
        self.assertEqual(result["events"][-1]["pc"], p.labels["benchmark_complete"])

    def test_integer_encodings(self):
        cases = [("addi x1, x0, -1", 0xFFF00093), ("xor x5, x1, x2", 0x0020C2B3),
                 ("ori x5, x0, -1", 0xFFF06293), ("jalr x7, 0(x7)", 0x000383E7)]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(program(body).words[RAM_BASE], expected)

    def test_addi_wrap_and_zero_register(self):
        p = program("addi x1, x1, 1\naddi x0, x1, 7")
        regs = [0] * 32
        regs[1] = MASK
        p.execute(p.ops[RAM_BASE], regs)
        self.assertEqual(regs[1], 0)
        event = p.execute(p.ops[RAM_BASE + 4], regs)
        self.assertEqual(regs[0], 0)
        self.assertEqual((event["rd"], event["writes"], event["data"]), (0, False, 0))

    def test_ori_sign_extension(self):
        p = program("ori x1, x0, -1")
        regs = [0] * 32
        p.execute(p.ops[RAM_BASE], regs)
        self.assertEqual(regs[1], MASK)

    def test_auipc_signed_upper(self):
        p = program("auipc x1, 0xfffff")
        regs = [0] * 32
        p.execute(p.ops[RAM_BASE], regs)
        self.assertEqual(regs[1], RAM_BASE - 4096)

    def test_pcrel_high_rounds_and_low_signs(self):
        p = program("auipc x1, %pcrel_hi(target)\naddi x1, x1, %pcrel_lo(_start)\n.rept 512\naddi x0, x0, 0\n.endr\ntarget:\naddi x2, x0, 1")
        first, second = p.ops[RAM_BASE], p.ops[RAM_BASE + 4]
        self.assertEqual(p.immediate(first, first.operands[1]), 1)
        self.assertLess(p.immediate(second, second.operands[2]), 0)
        regs = [0] * 32
        p.execute(first, regs)
        p.execute(second, regs)
        self.assertEqual(regs[1], p.labels["target"])

    def test_jalr_same_source_destination_reads_old_value_and_clears_bit0(self):
        p = program("jalr x7, 0(x7)")
        regs = [0] * 32
        regs[7] = RAM_BASE + 9
        event = p.execute(p.ops[RAM_BASE], regs)
        self.assertEqual(event["nextPc"], RAM_BASE + 8)
        self.assertEqual(regs[7], RAM_BASE + 4)

    def test_jalr_bit1_misalignment_rejected(self):
        p = program("jalr x7, 0(x7)")
        regs = [0] * 32
        regs[7] = RAM_BASE + 3
        with self.assertRaisesRegex(ReferenceError, "misaligned"):
            p.execute(p.ops[RAM_BASE], regs)
        self.assertEqual(regs[7], RAM_BASE + 3)

    def test_all_branch_predicates_at_signed_unsigned_boundaries(self):
        pairs = [(MASK, 1), (1 << 63, 0), ((1 << 63) - 1, 1 << 63), (0, 0)]
        expected = {
            "beq": [False, False, False, True], "bne": [True, True, True, False],
            "blt": [True, True, False, False], "bge": [False, False, True, True],
            "bltu": [False, False, True, False], "bgeu": [True, True, False, True],
        }
        for name, answers in expected.items():
            for (left, right), taken in zip(pairs, answers):
                with self.subTest(branch=name, left=left, right=right):
                    p = program(f"{name} x1, x2, target\naddi x0, x0, 0\ntarget:\naddi x0, x0, 0")
                    regs = [0] * 32
                    regs[1], regs[2] = left, right
                    event = p.execute(p.ops[RAM_BASE], regs)
                    self.assertEqual(event["nextPc"], p.labels["target"] if taken else RAM_BASE + 4)
                    self.assertFalse(event["writes"])

    def test_only_taken_branch_checks_target_alignment(self):
        p = program("beq x1, x2, target\ntarget:\naddi x0, x0, 0")
        p.labels["target"] = RAM_BASE + 2
        regs = [0] * 32
        regs[1] = 1
        self.assertEqual(p.execute(p.ops[RAM_BASE], regs)["nextPc"], RAM_BASE + 4)
        regs[2] = 1
        with self.assertRaisesRegex(ReferenceError, "misaligned"):
            p.execute(p.ops[RAM_BASE], regs)

    def test_wrong_path_illegal_word_fails_closed(self):
        with self.assertRaisesRegex(ReferenceError, "unexpected .word"):
            program(".word 0").run()

    def test_early_ebreak_fails_closed(self):
        with self.assertRaisesRegex(ReferenceError, "unexpected ebreak"):
            program("ebreak").run()

    def test_loop_bound_fails_closed(self):
        p = program("addi x0, x0, 0\nloop:\njal x0, loop")
        with self.assertRaisesRegex(ReferenceError, "instruction bound"):
            p.run(50)

    def test_required_marker_absence_and_order(self):
        p = program("addi x1, x0, 1")
        del p.labels["roi_end"]
        with self.assertRaisesRegex(ReferenceError, "marker missing"):
            p.run()
        p = program("addi x1, x0, 1")
        p.labels["roi_end"] = p.labels["benchmark_terminal"]
        with self.assertRaisesRegex(ReferenceError, "marker address order"):
            p.run()

    def test_duplicate_roi_begin_rejected(self):
        p = program("jal x0, _start")
        with self.assertRaisesRegex(ReferenceError, "duplicate ROI begin"):
            p.run()

    def test_unsupported_isa_and_source_directive_rejected(self):
        with self.assertRaisesRegex(ReferenceError, "unsupported source operation"):
            program("mul x1, x2, x3")
        with self.assertRaisesRegex(ReferenceError, "unsupported option"):
            program(".option rvc\naddi x1, x0, 1")

    def test_bad_repeats_and_immediate_range_rejected(self):
        with self.assertRaisesRegex(ReferenceError, "unmatched .endr"):
            program(".endr")
        with self.assertRaisesRegex(ReferenceError, "unterminated .rept"):
            program(".rept 2\naddi x1, x0, 1")
        with self.assertRaisesRegex(ReferenceError, "I immediate range"):
            program("addi x1, x0, 4096")


class TranscriptCheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold = SourceProgram(SOURCE.read_text()).run()

    def test_exact_acceptance(self):
        compare_transcripts(self.gold, copy.deepcopy(self.gold))

    def test_every_event_field_mutation_rejected(self):
        for field in ("pc", "instruction", "nextPc", "rd", "writes", "data"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.gold)
                changed["events"][10][field] ^= 1
                with self.assertRaisesRegex(ReferenceError, f"event 10 {field}"):
                    compare_transcripts(self.gold, changed)

    def test_missing_extra_reordered_events_rejected(self):
        for mode in ("missing", "extra", "reordered"):
            with self.subTest(mode=mode):
                changed = copy.deepcopy(self.gold)
                if mode == "missing":
                    del changed["events"][10]
                elif mode == "extra":
                    changed["events"].insert(10, changed["events"][10])
                else:
                    changed["events"][10], changed["events"][11] = changed["events"][11], changed["events"][10]
                with self.assertRaises(ReferenceError):
                    compare_transcripts(self.gold, changed)

    def test_state_roi_count_and_terminal_metadata_rejected(self):
        for field in ("regs", "retired", "roi_begin_index", "roi_end_index", "pc", "cause", "tval"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.gold)
                if field == "regs":
                    changed["regs"][11] ^= 1
                elif field in ("pc", "cause", "tval"):
                    changed["terminal"][field] ^= 1
                else:
                    changed[field] += 1
                with self.assertRaises(ReferenceError):
                    compare_transcripts(self.gold, changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
