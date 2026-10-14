"""Host-only fail-closed tests. Never launches a compiler, simulator or hardware tool."""
import argparse
import contextlib
import io
import runpy
import sys
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("r16_gate", HERE / "run_r16_shared_address.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = gate.catalog()

    def test_exact_profile(self):
        off, on = self.data["actualCore"]["off"], self.data["actualCore"]["on"]
        self.assertEqual(len(off), 177)
        self.assertEqual(on, dict(off, sharedMemoryAddressState=True))
        for key, value in (("robEntries", 16), ("physicalRegs", 48), ("renameWidth", 2), ("tagBits", 64),
                           ("reconstructIssueTokenIndex", False), ("memoryProofFrontier", False)):
            self.assertEqual(off[key], value)

    def test_public_files_byte_exact(self):
        gate.check_hashes(gate.PUBLIC_ROOT, self.data["publicInputs"])
        for path, entry in self.data["byteExactPublicationMap"].items():
            self.assertEqual(gate.sha(gate.PUBLIC_ROOT / path), entry["sha256"])

    def test_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in ("../escape", "/absolute", "ok/../../bad", ""):
                with self.assertRaises(ValueError):
                    gate.local(root, value)
            (root / "bad").symlink_to(root.parent)
            with self.assertRaises(ValueError):
                gate.local(root, "bad/escape")

    def test_inventory_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "original").write_text("input")
            (root / "link").symlink_to(root / "original")
            with self.assertRaisesRegex(ValueError, "symlink"):
                gate.inventory(root)

    def test_changed_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "x.scala").write_text("original")
            declaration = {"x.scala": gate.sha(root / "x.scala")}
            (root / "x.scala").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed input"):
                gate.check_hashes(root, declaration)

    def test_missing_classpath_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                gate.validate_classpath(Path(directory), self.data)

    def classpath(self, root):
        entries = []
        for name, role, files in (("main", "main", ["soc/core/ooo/IntegerBackend.class"]),
                                  ("test", "test", ["ooo/TimingReady73Profile$.class"])):
            for item in files:
                target = root / name / item
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"pinned class")
            entries.append({"path": name, "role": role, "files": gate.inventory(root / name)})
        return {"classpath": entries}

    def test_unlisted_class_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = self.classpath(root)
            gate.validate_classpath(root, data)
            (root / "main/extra.class").write_bytes(b"unexpected")
            with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                gate.validate_classpath(root, data)

    def test_dependency_application_fallback_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = self.classpath(root)
            with zipfile.ZipFile(root / "bad.jar", "w") as archive:
                archive.writestr("soc/core/ooo/IntegerBackend.class", "fallback")
            data["classpath"].append({"path": "bad.jar", "role": "dependency", "sha256": gate.sha(root / "bad.jar")})
            with self.assertRaisesRegex(ValueError, "fallback"):
                gate.validate_classpath(root, data)

    def test_duplicate_application_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = self.classpath(root)
            target = root / "test/soc/core/ooo/IntegerBackend.class"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"shadow")
            data["classpath"][1]["files"] = gate.inventory(root / "test")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                gate.validate_classpath(root, data)

    def result(self, counts=None):
        return "RESULT " + " ".join(f"{key}={value}" for key, value in
                                   (counts or self.data["expectedCounts"]).items()) + "\n"

    def test_positive_requires_all_fixed_witness_counts(self):
        self.assertEqual(gate.check_runtime(0, self.result(), self.data["expectedCounts"]), self.data["expectedCounts"])
        for key in ("triple", "dual", "atomic", "killedCapture", "virtualStores", "prechecked",
                    "noncanonicalLoads", "replayEvents", "reuse", "rows", "requests", "responses"):
            changed = dict(self.data["expectedCounts"], **{key: 0})
            with self.assertRaisesRegex(ValueError, "counts changed"):
                gate.check_runtime(0, self.result(changed), self.data["expectedCounts"])

    def test_exit_and_result_fail_closed(self):
        for code, text in ((1, self.result()), (0, ""), (0, self.result() + self.result()),
                           (0, self.result() + "FAIL problem")):
            with self.assertRaises(ValueError):
                gate.check_runtime(code, text, self.data["expectedCounts"])

    def test_sanitizer_and_assertion_not_oracle(self):
        for marker in gate.BAD_RUNTIME:
            with self.assertRaisesRegex(ValueError, "not an independent oracle"):
                gate.check_runtime(1, "FAIL independent row payload mismatch\n" + marker,
                                   self.data["expectedCounts"], True)

    def test_exact_negative_only(self):
        gate.check_runtime(1, "FAIL independent row payload mismatch\n", {}, True)
        for code, text in ((0, "FAIL independent row payload mismatch"),
                           (2, "FAIL independent row payload mismatch"), (1, "FAIL timeout"),
                           (1, "PASS\nFAIL independent row payload mismatch")):
            with self.assertRaises(ValueError):
                gate.check_runtime(code, text, {}, True)

    def test_trace_schema(self):
        data = {"expectedCounts": {"cycles": 1}, "snapshotWords": 276}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace"
            path.write_text("0 observation\n" + " ".join(["0"] * 276) + "\n")
            gate.check_trace(path, data, exact=False)
            for content in ("", "0 observation\n0\n", "1 observation\n" + " ".join(["0"] * 276)):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    gate.check_trace(path, data, exact=False)

    def test_trace_digest(self):
        data = {"expectedCounts": {"cycles": 1}, "snapshotWords": 276, "expectedTraceSha256": "0" * 64}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace"
            path.write_text("0 observation\n" + " ".join(["0"] * 276) + "\n")
            with self.assertRaisesRegex(ValueError, "qualified fixed-seed"):
                gate.check_trace(path, data)

    def test_complete_scalar_abi(self):
        self.assertEqual(self.data["scalarAbi"]["off"], self.data["scalarAbi"]["on"])
        self.assertEqual(len(self.data["scalarAbi"]["off"]), 382)
        self.assertEqual(sum("_BitInt(128) get_io_pmpState_region" in s for s in self.data["scalarAbi"]["off"]), 32)
        self.assertTrue(any("instruction0$$valid" in s for s in self.data["scalarAbi"]["off"]))
        self.assertTrue(any("observation$$live" in s for s in self.data["scalarAbi"]["off"]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.h"
            path.write_text("\n".join(self.data["scalarAbi"]["off"]))
            gate.validate_abi({"off": path}, self.data)
            path.write_text(path.read_text().replace("set_io_commitEnable", "set_wrong_abi"))
            with self.assertRaisesRegex(ValueError, "ABI changed"):
                gate.validate_abi({"off": path}, self.data)

    def test_full_width_snapshot_contract(self):
        contract = gate.read(gate.SUPPORT / "snapshot-contract.json")
        self.assertEqual(contract["fields"], 244)
        self.assertEqual(contract["serialized_words"], 276)
        self.assertEqual(sum(row["declared_width"] == 65 for row in contract["outputs"]), 32)
        for row in contract["outputs"]:
            self.assertEqual(row["serialized_words"], (row["declared_width"] + 63) // 64)
        source = (gate.SUPPORT / "snapshot.h").read_text()
        self.assertEqual(source.count(">> 64"), 32)
        self.assertIn("#define SNAPSHOT_HIGH_BIT_NEGATIVE 0", source)

    def test_serializer_bit64_negative(self):
        contract = gate.read(gate.SUPPORT / "snapshot-contract.json")
        high_index = 0
        for row in contract["outputs"]:
            if row["output"] == "io_pmpState_regionEnd_0":
                high_index += 1
                break
            high_index += row["serialized_words"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "off.trace", root / "on.trace"
            words = ["0"] * 276
            left.write_text("".join(str(cycle) + " observation\n" + " ".join(words) + "\n" for cycle in range(1930)))
            right.write_bytes(left.read_bytes())
            argv = [str(gate.SUPPORT / "compare.py"), str(left), str(right)]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as text:
                runpy.run_path(argv[0], run_name="__main__")
                self.assertIn("PASS_FULL_WIDTH_TRACE_PAIR", text.getvalue())
            words[high_index] = "1"
            right.write_text("".join(str(cycle) + " observation\n" + " ".join(words) + "\n" for cycle in range(1930)))
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as text:
                with self.assertRaises(SystemExit) as error:
                    runpy.run_path(argv[0], run_name="__main__")
                self.assertEqual(error.exception.code, 1)
                self.assertIn("FAIL_FULL_WIDTH_TRACE_DIFFERENCE", text.getvalue())

    def test_comparator_empty_pair_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "off.trace", root / "on.trace"
            left.write_text("")
            right.write_text("")
            argv = [str(gate.SUPPORT / "compare.py"), str(left), str(right)]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(AssertionError):
                    runpy.run_path(argv[0], run_name="__main__")

    def test_fresh_source_and_dependency_inventory(self):
        self.assertEqual(sum(p.startswith("src/main/scala/") for p in self.data["sources"]), 207)
        self.assertEqual(sum(p.startswith("src/test/scala/") for p in self.data["sources"]), 37)
        self.assertEqual(sum(p.endswith(".scala") for p in self.data["freshCompileInputs"]), 18)
        self.assertEqual(len(self.data["freshDependencyJars"]), 43)
        self.assertEqual(gate.SOURCE_BASELINE["commit"], "2fa6a4b320814ad2b142d5bf0009c1d2d5475233")

    def test_fresh_dependency_does_not_admit_application_classes(self):
        compiler = gate.fresh_compiler()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dependency.jar"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("soc/core/ooo/IntegerBackend.class", b"old application")
            data = {"freshDependencyJars": {path.name: gate.sha(path)}}
            with self.assertRaisesRegex(ValueError, "fallback"):
                compiler.jar_entry(path, data)

    def test_fresh_dependency_hash_drift(self):
        compiler = gate.fresh_compiler()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dependency.jar"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("library/Dependency.class", b"dependency")
            data = {"freshDependencyJars": {path.name: gate.sha(path)}}
            compiler.jar_entry(path, data)
            with path.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                compiler.jar_entry(path, data)

    def test_fresh_source_closure_rejects_added_production_file(self):
        compiler = gate.fresh_compiler()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "src/main/scala/Extra.scala"
            path.parent.mkdir(parents=True)
            path.write_text("class Extra")
            data = {"sources": {}, "freshCompileInputs": {}}
            with patch.object(compiler.gate, "validate_repo"), patch.object(compiler.gate, "check_hashes"):
                with self.assertRaisesRegex(ValueError, "source closure changed"):
                    compiler.source_closure(root, data)

    def test_fresh_old_classpath_receipt_rejected(self):
        compiler = gate.fresh_compiler()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate.write(root / "classes.json", {"schema": "r16-fresh-classes-v1",
                       "status": "PASS_FRESH_ISOLATED_CLASSES", "oldApplicationClasspath": True,
                       "productionRecompiled": False})
            with patch.object(compiler, "source_closure", return_value={}):
                with self.assertRaisesRegex(ValueError, "cannot inherit"):
                    compiler.verify(root, root, self.data)

    def test_fresh_and_frozen_input_modes_cannot_mix(self):
        args = argparse.Namespace(classes_dir=Path("new-classes"), frozen_root=Path("old-classes"))
        with self.assertRaisesRegex(ValueError, "never both"):
            gate.selected_inputs(args, self.data)

    def test_fresh_missing_tool_digest_rejected(self):
        with self.assertRaisesRegex(ValueError, "fresh build requires"):
            gate.fresh_tool(argparse.Namespace(java=Path("java"), java_sha256=None), "java")

    def test_no_implicit_tools(self):
        args = argparse.Namespace(java=None)
        with self.assertRaisesRegex(ValueError, "explicit --java"):
            gate.tool(args, self.data, "java")

    def test_build_receipt_rejects_incomplete_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate.write(root / "build.json", {"schema": "exact-r16-shared-address-build-v1", "status": "FAIL"})
            with patch.object(gate, "validate_inputs", return_value=[]):
                with self.assertRaisesRegex(ValueError, "completed bounded build"):
                    gate.validate_build(argparse.Namespace(build_dir=root), self.data)


if __name__ == "__main__":
    unittest.main()
