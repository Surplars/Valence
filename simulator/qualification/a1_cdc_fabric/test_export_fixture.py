#!/usr/bin/env python3
"""Small stdlib tests; optional explicit production emissions add real-file checks.

python3 -m unittest discover -s simulator/qualification/a1_cdc_fabric -v
A1_CDC_FABRIC_OFF_EMISSION=/absolute/off A1_CDC_FABRIC_ON_EMISSION=/absolute/on ...
No test discovers an old model, compiles, lowers, or runs hardware.
"""
import copy
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import export_fixture as e


def circuit(body, top="Top", annotations=None):
    return (f"FIRRTL version 6.0.0\ncircuit {top} :%[" + json.dumps(annotations or []) + "]\n" + e.LAYERS + body)


def module(name, extra="", public=False):
    return f'  {"public " if public else ""}module {name} :\n    input x : UInt<1>\n{extra}\n'


def tiny_modules():
    bus = "{ flip ready : UInt<1>, valid : UInt<1>, bits : UInt<8>}"
    common = "    input clock : Clock\n    input reset : Reset\n"
    cpu = "  module CommonA1CpuTile :\n" + common + f"    output io : {{ bus : {bus}, flip hold : UInt<1>, flip inspectRegister : UInt<5>, committedValue : UInt<64>}}\n\n"
    fabric = "  module CommonMachineFabric :\n" + common + f"    output io : {{ flip tile : {bus}, flip transportCpuEmptySynchronized : UInt<1>, flip fabricTransportEmpty : UInt<1>, flip ddrReady : UInt<1>}}\n\n"
    crossing = "  module CommonCpuClockBoundary :\n    input cpuClock : Clock\n    input fabricClock : Clock\n    input commonColdReset : AsyncReset\n" + f"    input cpu : {bus}\n    output fabric : {bus}\n"
    crossing += "".join("    output " + name + " : UInt<1>\n" for name in ("cpuLinkReady", "fabricLinkReady", "cpuTransportEmpty", "fabricTransportEmpty", "cpuEmptyInFabric", "fabricEmptyInCpu")) + "\n"
    reset = "    input clockIn : Clock\n    input asyncReset : AsyncReset\n    output resetOut : AsyncReset\n\n"
    return {e.ROOTS[0]: cpu, e.ROOTS[1]: crossing, e.ROOTS[2]: fabric,
            e.ROOTS[3]: "  module CdcResetRelease :\n" + reset,
            e.ROOTS[4]: "  module CdcResetRelease_1 :\n" + reset}


class TypeTests(unittest.TestCase):
    def test_nested_vector_flip_xor(self):
        typ = e.parse_type("{ flip request : { flip ready : UInt<1>, bits : UInt<8>[2]}, valid : UInt<1>}[2]")
        leaves = list(typ.leaves("io", "io"))
        self.assertEqual([x["direction"] for x in leaves], ["output", "input", "input", "output"] * 2)
        self.assertEqual(leaves[2]["path"], "io[0].request.bits[1]")
        self.assertEqual(leaves[2]["name"], "io_0__request__bits_1")
        self.assertEqual(leaves[2]["width"], 8)

    def test_unsupported_types(self):
        for text in ("UInt", "UInt<0>", "SInt<4>", "UInt<4>[0]", "{x: UInt<1>, x: UInt<1>}", "{flip x UInt<1>}", "UInt<1> junk", "Analog<1>", "UInt<1>[-1]"):
            with self.subTest(text=text), self.assertRaises(e.Invalid):
                e.parse_type(text)

    def test_duplicate_port(self):
        with self.assertRaises(e.Invalid):
            e.ports(module("Top", "    output x : UInt<1>\n"))

    def test_port_after_body(self):
        with self.assertRaises(e.Invalid):
            e.ports(module("Top", "    node y = x\n    output z : UInt<1>\n"))


class FirTests(unittest.TestCase):
    def test_complete_nested_closure(self):
        text = circuit(module("Top", "    when x :\n      inst q of Child\n") + module("Child", "    inst leaf of Leaf\n") + module("Leaf"))
        self.assertEqual(e.closure(e.parse_fir(text).modules, ("Top",)), {"Top", "Child", "Leaf"})

    def test_invalid_modules_and_dependencies(self):
        bad = [module("Top") + module("Top"), module("Top", "    inst q of Missing\n"),
               module("Top", "    inst q of Top\n"), module("Top", "    inst q of Top unknown\n"),
               module("Top", "    inst q of Child\n    inst q of Child\n") + module("Child"),
               module("Top") + "  intmodule Other :\n"]
        for body in bad:
            with self.subTest(body=body), self.assertRaises(e.Invalid):
                e.parse_fir(circuit(body))

    def test_unsupported_layers_version_annotations(self):
        good = circuit(module("Top"))
        bad = [good.replace("6.0.0", "7.0.0"), good.replace('    layer Assert, bind, "verification/assert" :\n', ""),
               circuit(module("Top"), annotations=[{"class": "Unknown", "target": "~|Top"}]),
               circuit(module("Top"), annotations=[{"class": "firrtl.AttributeAnnotation", "target": "~Other|Top>x", "description": "x"}]),
               circuit(module("Top"), annotations=[{"class": "firrtl.AttributeAnnotation", "target": "~|Missing>x", "description": "x"}])]
        for text in bad:
            with self.subTest(text=text[:80]), self.assertRaises(e.Invalid):
                e.parse_fir(text)

    def test_assertion_inventory_preserves_text(self):
        statement = '        intrinsic(circt_chisel_ifelsefatal<format = "Assertion failed: test\\n", label = "chisel3_builtin">, c, x, x)'
        body = module("Top", "    layerblock Verification :\n      layerblock Assert :\n" + statement + "\n")
        inv = e.assertion_inventory({"Top": body}, {"Top"})
        self.assertEqual(inv["sites"][0]["statement"], statement)
        for bad in (body.replace("layerblock Assert", "layerblock Assume"), body.replace("intrinsic(circt_chisel_ifelsefatal", "intrinsic(unknown"), body + "    attach(x, x)\n"):
            with self.assertRaises(e.Invalid):
                e.assertion_inventory({"Top": bad}, {"Top"})

    def test_vendor_dependency_rejected(self):
        with self.assertRaises(e.Invalid):
            e.assertion_inventory({"Vendor": "  extmodule Vendor :\n    input x : UInt<1>\n"}, {"Vendor"})


class WiringTests(unittest.TestCase):
    def test_wrapper_complete_drivers(self):
        top, ports, wiring = e.make_wrapper(tiny_modules())
        self.assertEqual(len(wiring), len({x["destination"] for x in wiring}))
        self.assertIn("    connect fabric.io.fabricTransportEmpty, crossing.fabricTransportEmpty", top)
        self.assertIn("    connect crossing.commonColdReset, startupReset", top)
        self.assertIn("    connect cpu.io.hold, UInt<1>(0)", top)
        self.assertEqual(next(x for x in ports if x["name"] == "core__inspectRegister")["direction"], "input")
        self.assertTrue(all(x["direction"] == "output" for x in ports if x["name"].startswith("cpu__")))

    def test_wrong_direction_or_width(self):
        for old, new in (("flip tile", "tile"), ("bits : UInt<8>", "bits : UInt<9>")):
            modules = tiny_modules()
            modules[e.ROOTS[2]] = modules[e.ROOTS[2]].replace(old, new)
            with self.assertRaises(e.Invalid):
                e.make_wrapper(modules)

    def test_added_input_connected_or_rejected(self):
        modules = tiny_modules()
        modules[e.ROOTS[1]] += "    input extra : UInt<1>\n"
        with self.assertRaisesRegex(e.Invalid, "unconnected"):
            e.make_wrapper(modules)

    def test_duplicate_flattened_name(self):
        modules = tiny_modules()
        modules[e.ROOTS[0]] = modules[e.ROOTS[0]].replace("committedValue : UInt<64>", "a__b : UInt<1>, a : { b : UInt<1>}")
        with self.assertRaises(e.Invalid):
            e.make_wrapper(modules)

    def test_production_empty_reset_override_detected(self):
        body = module("Top", "\n".join(e.PRODUCTION_ASSEMBLY) + "\n")
        expected = e.selected_assembly(body)
        self.assertEqual(expected, e.PRODUCTION_ASSEMBLY)
        for old, new in (("crossing.commonColdReset, startupReset", "crossing.commonColdReset, commonColdReset"),
                         ("fabric.io.fabricTransportEmpty, crossing.fabricTransportEmpty", "fabric.io.fabricTransportEmpty, UInt<1>(1)"),
                         ("and(io.bootEnable, io.ddrReady)", "io.bootEnable"),
                         ("fabric.io.ddrReady, io.ddrReady", "fabric.io.ddrReady, UInt<1>(1)")):
            self.assertNotEqual(e.selected_assembly(body.replace(old, new)), expected)
        self.assertNotEqual(e.selected_assembly(body + "    connect crossing.cpu.valid, UInt<1>(0)\n"), expected)


class FileTests(unittest.TestCase):
    def test_duplicate_json_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.json"
            path.write_text('{"x": 1, "x": 2}')
            with self.assertRaises(e.Invalid):
                e.read_json(path)

    def test_stale_file_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "class"
            path.write_text("before")
            pins = {str(path): e.sha_file(path)}
            e.verify_hashes(pins, "test")
            path.write_text("after")
            with self.assertRaises(e.Invalid):
                e.verify_hashes(pins, "test")

    def test_no_overwrite_before_inspection(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(e, "inspect") as inspect:
            with self.assertRaises(e.Invalid):
                e.export("unused", Path(directory))
            inspect.assert_not_called()

    def test_read_git_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git/refs/heads").mkdir(parents=True)
            (root / ".git/HEAD").write_text("ref: refs/heads/main\n")
            commit = "a" * 40
            (root / ".git/refs/heads/main").write_text(commit + "\n")
            self.assertEqual(e.current_commit(root), commit)


class PairTests(unittest.TestCase):
    def pair(self):
        a = {"selection": "read-baseline", "provenance": {"hash": "same"}, "cpuPrivateIdentitySha256": "same",
             "identitySha256": "off", "rootClosures": {"CPU": ["CPU"]},
             "bodySha256": {"CPU": "same", e.HOME: "off"}, "sourceFirSha256": "off"}
        for key in ("wrapperSha256", "publicSchemaSha256", "connections", "layersSha256", "retainedAnnotations", "productionAssembly"):
            a[key] = "same"
        b = copy.deepcopy(a)
        b.update(selection="probe-acquire", identitySha256="on", sourceFirSha256="on")
        b["bodySha256"][e.HOME] = "on"
        return (None, None, [], a), (None, None, [], b)

    def test_only_home_differs(self):
        self.assertEqual(e.check_pair(*self.pair())["changedBodies"], [e.HOME])

    def test_pair_negative_controls(self):
        for field in ("provenance", "cpuPrivateIdentitySha256", "rootClosures", "wrapperSha256", "connections"):
            first, second = self.pair()
            second[3][field] = "different"
            with self.subTest(field=field), self.assertRaises(e.Invalid):
                e.check_pair(first, second)
        first, second = self.pair()
        second[3]["bodySha256"]["CPU"] = "changed"
        with self.assertRaises(e.Invalid):
            e.check_pair(first, second)


OFF = os.environ.get("A1_CDC_FABRIC_OFF_EMISSION")
ON = os.environ.get("A1_CDC_FABRIC_ON_EMISSION")


@unittest.skipUnless(OFF and ON, "explicit production emission pair not supplied")
class ProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.off = e.inspect(OFF)
        cls.on = e.inspect(ON)

    def test_fresh_pair(self):
        self.assertEqual(e.check_pair(self.off, self.on)["changedBodies"], [e.HOME])
        self.assertEqual(self.off[3]["definitions"], 374)
        self.assertEqual(len(self.off[2]), 612)

    def test_complete_identity_mutation_rejected(self):
        # Repair all outer artifact hashes: rejection must come from identity
        # semantics, not merely a stale outer checksum.
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            for name in ("microarchitecture-identity.json", "resolved-soc-config.json"):
                (dest / name).write_bytes((Path(ON) / name).read_bytes())
            # Copy only this one bounded FIR; existing emission bytes stay untouched.
            (dest / "CommonMachinePlatform.fir").write_bytes((Path(ON) / "CommonMachinePlatform.fir").read_bytes())
            identity = e.read_json(dest / "microarchitecture-identity.json")
            identity["effectiveCore"]["robEntries"] = "32"
            identity["identitySha256"] = e.digest({k: v for k, v in identity.items() if k != "identitySha256"})
            (dest / "microarchitecture-identity.json").write_text(json.dumps(identity))
            profile = e.read_json(Path(ON) / "emission-profile.json")
            profile["cpuMicroarchitecture"] = identity
            profile["artifacts"] = {str(dest / name): e.sha_file(dest / name) for name in
                                    ("microarchitecture-identity.json", "resolved-soc-config.json", "CommonMachinePlatform.fir")}
            (dest / "emission-profile.json").write_text(json.dumps(profile))
            with self.assertRaisesRegex(e.Invalid, "microarchitecture identity"):
                e.inspect(dest)

    def test_repaired_hash_wiring_mutation_rejected(self):
        controls = (
            ("connect fabric.io.fabricTransportEmpty, crossing.fabricTransportEmpty", "connect fabric.io.fabricTransportEmpty, UInt<1>(0)"),
            ("connect fabric.io.ddrReady, io.ddrReady", "connect fabric.io.ddrReady, UInt<1>(1)"),
            ("connect fabric.io.ddrAxi.r, io.ddrAxi.r", "connect io.ddrAxi.r, fabric.io.ddrAxi.r"),
        )
        for old, new in controls:
            with self.subTest(connection=old), tempfile.TemporaryDirectory() as directory:
                dest = Path(directory)
                for name in ("microarchitecture-identity.json", "resolved-soc-config.json"):
                    (dest / name).write_bytes((Path(ON) / name).read_bytes())
                text = (Path(ON) / "CommonMachinePlatform.fir").read_text()
                self.assertEqual(text.count(old), 1)
                (dest / "CommonMachinePlatform.fir").write_text(text.replace(old, new))
                profile = e.read_json(Path(ON) / "emission-profile.json")
                profile["artifacts"] = {str(dest / name): e.sha_file(dest / name) for name in
                                        ("microarchitecture-identity.json", "resolved-soc-config.json", "CommonMachinePlatform.fir")}
                (dest / "emission-profile.json").write_text(json.dumps(profile))
                with self.assertRaisesRegex(e.Invalid, "startup/reset/bus/empty"):
                    e.inspect(dest)

    def test_real_receipt_binding_controls(self):
        profile = e.read_json(Path(ON) / "emission-profile.json")
        receipt_path = next(Path(p) for p in profile["sources"] if p.endswith(".json"))
        original_read = e.read_json
        for mutation in ("schema", "exit", "sourceCommit", "sourceInputs", "compiledClasspath", "runClasspathEntries"):
            receipt = original_read(receipt_path)
            if mutation == "schema":
                receipt[mutation] = "legacy-exit-only"
            elif mutation == "exit":
                receipt[mutation] = False
            elif mutation == "sourceCommit":
                receipt[mutation] = "0" * 40
            elif mutation == "runClasspathEntries":
                receipt[mutation] = []
            else:
                receipt[mutation] = {}

            def mutated_read(path):
                return receipt if Path(path) == receipt_path else original_read(path)

            with self.subTest(field=mutation), patch.object(e, "read_json", side_effect=mutated_read), self.assertRaises(e.Invalid):
                e.verify_provenance(Path(ON))

    def test_real_port_and_layer_controls(self):
        text = (Path(ON) / "CommonMachinePlatform.fir").read_text()
        original = e.parse_fir(text)
        for old, new in (("flip hold : UInt<1>", "hold : UInt<1>"),
                         ("flip inspectRegister : UInt<5>", "flip inspectRegister : UInt<6>")):
            changed = copy.copy(original)
            changed.modules = dict(original.modules)
            changed.modules[e.ROOTS[0]] = changed.modules[e.ROOTS[0]].replace(old, new)
            with self.assertRaisesRegex(e.Invalid, "public port schema"):
                e.validate_assembly(changed)
        changed = copy.copy(original)
        changed.modules = dict(original.modules)
        changed.modules[original.name] = changed.modules[original.name].replace("layerblock Assert", "layerblock Assume")
        with self.assertRaisesRegex(e.Invalid, "assertion intrinsic/layer"):
            e.validate_assembly(changed)


if __name__ == "__main__":
    unittest.main()
