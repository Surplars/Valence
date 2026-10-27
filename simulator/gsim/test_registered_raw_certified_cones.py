#!/usr/bin/env python3
"""Synthetic parser/cone tests only: no DUT elaboration, model, or simulation."""
import unittest

from registered_raw_certified_cones import Cones, Uncertain


def parse(body, children=""):
    return Cones("FIRRTL version 6.0.0\ncircuit Example :\n" + children +
                 "  public module Example :\n" + body, root_module="Example", prefix="dut")


PORTS = "    input clock : Clock\n    input reset : Reset\n    input raw : UInt<1>\n    output out : UInt<1>\n"


class ConeTests(unittest.TestCase):
    def reaches(self, cone, source, sink):
        return "dut." + sink in cone.reachable(["dut." + source])

    def test_alias_primitive_mux_selector(self):
        cone = parse(PORTS + "    node alias = raw\n    node selected = mux(alias, UInt<1>(0h0), UInt<1>(0h1))\n    connect out, not(selected)\n")
        self.assertTrue(self.reaches(cone, "raw", "out"))

    def test_overwritten_and_constant_disabled_edges_are_retained(self):
        cone = parse(PORTS + "    connect out, raw\n    connect out, UInt<1>(0h0)\n")
        self.assertTrue(self.reaches(cone, "raw", "out"))
        cone = parse(PORTS + "    when UInt<1>(0h0) :\n      connect out, raw\n    else :\n      connect out, UInt<1>(0h0)\n")
        self.assertTrue(self.reaches(cone, "raw", "out"))

    def test_memory_read_selector_is_not_a_storage_cut(self):
        cone = parse(PORTS + "    cmem memory : UInt<1>[2]\n    read mport rd = memory[raw], clock\n    connect out, rd\n")
        self.assertTrue(self.reaches(cone, "raw", "out"))

    def test_unknown_source_and_invalid_memory_forms_fail(self):
        for body in ("    connect out, unknown.field\n",
                     "    cmem memory : UInt<1>[2]\n    connect out, memory[raw]\n",
                     "    cmem memory : UInt<1>[2]\n    read mport rd = memory[raw], clock\n    connect rd, raw\n"):
            with self.subTest(body=body), self.assertRaises(Uncertain):
                parse(PORTS + body)

    def test_when_else_and_nested_control(self):
        cone = parse(PORTS + "    when raw :\n      when reset :\n        connect out, UInt<1>(0h0)\n      else :\n        connect out, UInt<1>(0h1)\n    else :\n      connect out, UInt<1>(0h0)\n")
        self.assertTrue(self.reaches(cone, "raw", "out"))
        self.assertTrue(self.reaches(cone, "reset", "out"))

    def test_reg_data_enable_reset_init_cut(self):
        cone = parse(PORTS + "    regreset saved : UInt<1>, clock, raw, raw\n    when raw :\n      connect saved, raw\n    connect out, saved\n")
        self.assertFalse(self.reaches(cone, "raw", "out"))
        self.assertTrue(self.reaches(cone, "raw", "saved$NEXT"))
        self.assertIn("dut.saved", cone.registers)

    def test_hierarchical_alias_and_register_cut(self):
        child = "  module Child :\n    input clock : Clock\n    input in : UInt<1>\n    output direct : UInt<1>\n    output saved : UInt<1>\n    reg q : UInt<1>, clock\n    connect q, in\n    connect direct, in\n    connect saved, q\n"
        cone = parse(PORTS + "    inst child of Child\n    connect child.clock, clock\n    connect child.in, raw\n    connect out, child.direct\n", child)
        self.assertTrue(self.reaches(cone, "raw", "out"))
        self.assertFalse(self.reaches(cone, "raw", "child.saved"))
        self.assertTrue(self.reaches(cone, "raw", "child.q$NEXT"))

    def test_flipped_bulk_connect(self):
        cone = parse("    input a : { valid : UInt<1>, flip ready : UInt<1>}\n    output b : { valid : UInt<1>, flip ready : UInt<1>}\n    connect b, a\n")
        self.assertTrue(self.reaches(cone, "a.valid", "b.valid"))
        self.assertTrue(self.reaches(cone, "b.ready", "a.ready"))
        self.assertFalse(self.reaches(cone, "a.ready", "b.ready"))

    def test_selected_queueio_bulk_and_nested_flips(self):
        child = "  module Queue :\n    output io : { flip enq : { flip ready : UInt<1>, valid : UInt<1>, bits : UInt<1>}}\n    connect io.enq.ready, UInt<1>(0h1)\n"
        cone = parse("    output io : { flip enq : { flip ready : UInt<1>, valid : UInt<1>, bits : UInt<1>}}\n    inst queue of Queue\n    connect queue.io.enq, io.enq\n", child)
        self.assertTrue(self.reaches(cone, "queue.io.enq.ready", "io.enq.ready"))
        self.assertTrue(self.reaches(cone, "io.enq.valid", "queue.io.enq.valid"))
        self.assertTrue(self.reaches(cone, "io.enq.bits", "queue.io.enq.bits"))
        self.assertFalse(self.reaches(cone, "io.enq.ready", "queue.io.enq.ready"))

    def test_flipped_dynamic_target_selector(self):
        cone = parse("    input index : UInt<1>\n    input a : { valid : UInt<1>, flip ready : UInt<1>}[2]\n    output b : { valid : UInt<1>, flip ready : UInt<1>}\n    connect b, a[index]\n")
        for sink in ("a[0].ready", "a[1].ready"):
            self.assertTrue(self.reaches(cone, "index", sink))
            self.assertTrue(self.reaches(cone, "b.ready", sink))

    def test_aggregate_mux_is_leaf_precise(self):
        cone = parse("    input raw : UInt<1>\n    input sel : UInt<1>\n    wire a : { x : UInt<1>, y : UInt<1>}\n    wire b : { x : UInt<1>, y : UInt<1>}\n    connect a.x, raw\n    connect a.y, UInt<1>(0h0)\n    connect b, a\n    node selected = mux(sel, a, b)\n")
        self.assertTrue(self.reaches(cone, "raw", "selected.x"))
        self.assertFalse(self.reaches(cone, "raw", "selected.y"))
        self.assertTrue(self.reaches(cone, "sel", "selected.y"))

    def test_dynamic_read_and_write_indices(self):
        cone = parse(PORTS + "    input index : UInt<1>\n    wire bank : UInt<1>[2]\n    connect bank[index], raw\n    connect out, bank[index]\n")
        for source in ("raw", "index"):
            for sink in ("bank[0]", "bank[1]", "out"):
                self.assertTrue(self.reaches(cone, source, sink), (source, sink))

    def test_memory_write_cut_read_address_and_enable(self):
        cone = parse(PORTS + "    input address : UInt<1>\n    input enable : UInt<1>\n    cmem memory : UInt<1>[2]\n    infer mport wr = memory[address], clock\n    connect wr, raw\n    when enable :\n      infer mport rd = memory[address], clock\n      connect out, rd\n")
        self.assertFalse(self.reaches(cone, "raw", "out"))
        self.assertTrue(self.reaches(cone, "address", "out"))
        self.assertTrue(self.reaches(cone, "enable", "out"))

    def test_same_inferred_memory_port_readwrite_fails(self):
        with self.assertRaises(Uncertain):
            parse(PORTS + "    cmem memory : UInt<1>[2]\n    infer mport p = memory[raw], clock\n    connect p, raw\n    connect out, p\n")

    def test_unsupported_or_unknown_never_silently_skipped(self):
        for line in ("connect out, mystery(raw)", "connect out, missing", "invalidate out",
                     "node x = intrinsic(foo, raw)", "wire x : Analog<1>", "smem x : UInt<1>[2]",
                     "mem x :", "attach(raw, out)", "connect out, raw garbage"):
            with self.subTest(line=line), self.assertRaises(Uncertain):
                parse(PORTS + "    " + line + "\n")

    def test_reachable_blackbox_fails(self):
        with self.assertRaises(Uncertain):
            parse(PORTS + "    inst child of Child\n", "  extmodule Child :\n    input in : UInt<1>\n")

    def test_malformed_control_fails(self):
        for lines in ("    else :\n      connect out, raw\n", "      connect out, raw\n",
                      "    when raw :\n        connect out, raw\n"):
            with self.subTest(lines=lines), self.assertRaises(Uncertain):
                parse(PORTS + lines)


if __name__ == "__main__":
    unittest.main()
