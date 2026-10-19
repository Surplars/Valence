#!/usr/bin/env python3
"""Small host-only runner contract tests; never build or execute a DUT."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("bringup", Path(__file__).with_name("bringup.py"))
bringup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bringup)


class BringupTests(unittest.TestCase):
    def test_default_plan_never_starts_child(self):
        with mock.patch.object(bringup.subprocess, "Popen", side_effect=AssertionError("unexpected child")):
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(bringup.main([]), 0)
        plan = json.loads(stream.getvalue())
        self.assertFalse(plan["executed"])
        self.assertEqual(plan["profiles"]["ooo-board-rom"]["status"], "blocked")
        self.assertEqual(plan["profiles"]["i1-compact-rom"]["status"], "executable_fixture")
        self.assertEqual(plan["profiles"]["i1-compact-rom"]["flags"][0], "--no-m")

    def test_unknown_profile_fails(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            bringup.main(["--run", "performance-candidate"])

    def test_experimental_catalog_cannot_select_execution(self):
        config = json.loads(bringup.PROFILES.read_text())
        self.assertEqual(len(config["experimental_entries"]), 3)
        for entry in config["experimental_entries"]:
            self.assertFalse(entry["selected_by_bringup"])
            self.assertFalse(entry["physical_qualified"])
            self.assertNotIn(entry["name"], config["profiles"])

    def test_run_requires_named_profile(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            bringup.main(["--run"])

    def test_run_requires_fresh_destination(self):
        args = bringup.parser().parse_args(["--run", "i1-compact-rom", "--output", str(bringup.ROOT)])
        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
            bringup.execute(args, {})

    def test_blocked_profile_does_not_start_child(self):
        with mock.patch.object(bringup.subprocess, "Popen", side_effect=AssertionError("unexpected child")):
            with contextlib.redirect_stderr(io.StringIO()) as stream:
                self.assertEqual(bringup.main(["--preflight", "ooo-board-rom"]), 1)
        self.assertIn("configurationCheck", stream.getvalue())

    def test_positive_requires_all_chain_markers(self):
        line = ("FIVE_STAGE_SOC_PASS cycles=35000 retired=100 axi_reads=80 axi_writes=20 "
                "rom_retired=40 jtag=0 retry=0 ddr_2g_uart_loopback_msip_mtip_plic_mmio_axi_fault=PASS")
        self.assertEqual(bringup.validate_positive(line)["rom_retired"], 40)
        for bad in ("", line.replace("rom_retired=40", "rom_retired=0"),
                    line.replace("axi_reads=80", "axi_reads=0"), line.replace("jtag=0", "jtag=1"),
                    line.replace("_axi_fault=PASS", "_axi_fault=FAIL")):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                bringup.validate_positive(bad)

    def test_disk_floor_blocks_before_child(self):
        with mock.patch.object(bringup, "free_bytes", return_value=bringup.FLOOR_BYTES - 1), \
                mock.patch.object(bringup.subprocess, "Popen") as child:
            with self.assertRaisesRegex(RuntimeError, "before"):
                bringup.Guard().run("denied", ["false"])
        child.assert_not_called()

    def test_guard_preserves_expected_negative_and_log(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bringup, "free_bytes", return_value=bringup.FLOOR_BYTES + 1):
            guard = bringup.Guard(Path(tmp))
            text = guard.run("negative", [sys.executable, "-c", "print('oracle rejected'); raise SystemExit(1)"],
                             expected=1)
            self.assertIn("oracle rejected", text)
            self.assertEqual(guard.records[0]["exit"], 1)
            self.assertTrue((Path(tmp) / "negative.log").exists())
            self.assertTrue((Path(tmp) / "negative.json").exists())

    def test_guard_timeout_preserves_log(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bringup, "free_bytes", return_value=bringup.FLOOR_BYTES + 1):
            guard = bringup.Guard(Path(tmp))
            with self.assertRaisesRegex(RuntimeError, "timeout"):
                guard.run("timeout", [sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.01)
            self.assertIsNotNone(guard.records[0]["error"])
            self.assertTrue((Path(tmp) / "timeout.json").exists())

    def test_qualification_hashes_and_modified_source_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, binary, cxx = root / "source", root / "gsim", root / "clang"
            source.mkdir()
            (source / "patch.cpp").write_text("patched source")
            binary.write_text("qualified binary")
            cxx.write_text("qualified compiler")
            lock = {"revision": "revision", "repository": "repository"}
            receipt = {"upstream_revision": "revision", "upstream_repository": "repository",
                       "historical_gate_modified": False, "binary_sha256": bringup.sha(binary),
                       "compiler_sha256": bringup.sha(cxx), "patch_sha256": "patch",
                       "patched_sources": {"patch.cpp": bringup.sha(source / "patch.cpp")},
                       "focused_executions": ["PASS"], "upstream_runtime_harnesses": ["checked"],
                       "sanitizers": "address,undefined"}
            args = (source, binary, cxx, "revision", ["patch.cpp"], "patch", lock)
            bringup.validate_qualification(receipt, *args)
            for key, value in (("binary_sha256", "bad"), ("compiler_sha256", "bad"),
                               ("historical_gate_modified", True), ("patch_sha256", "bad"),
                               ("patched_sources", {"another.cpp": "bad"}),
                               ("focused_executions", []), ("upstream_revision", "bad")):
                altered = copy.deepcopy(receipt)
                altered[key] = value
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    bringup.validate_qualification(altered, *args)
            (source / "patch.cpp").write_text("changed after qualification")
            with self.assertRaisesRegex(RuntimeError, "source hash mismatch"):
                bringup.validate_qualification(receipt, *args)

    def test_classpath_requires_main_and_absolute_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = Path(tmp) / "cp.txt"
            cp.write_text("relative")
            with self.assertRaisesRegex(RuntimeError, "absolute"):
                bringup.classpath_manifest(cp)
            cp.write_text(str(Path(tmp) / "missing.jar"))
            with self.assertRaisesRegex(RuntimeError, "missing"):
                bringup.classpath_manifest(cp)
            cp.write_text(str(Path(tmp)))
            with self.assertRaisesRegex(RuntimeError, "lacks compiled"):
                bringup.classpath_manifest(cp)

    def test_classpath_drift_detects_recompiled_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compiled = root / "inorder/FiveStageSocGsimMain.class"
            compiled.parent.mkdir()
            compiled.write_bytes(b"original compiled fixture")
            cp = root / "cp.txt"
            cp.write_text(str(root))
            _, saved = bringup.classpath_manifest(cp)
            bringup.verify_classpath_unchanged(saved)
            compiled.write_bytes(b"concurrent recompile")
            with self.assertRaisesRegex(RuntimeError, "classpath drift"):
                bringup.verify_classpath_unchanged(saved)

    def test_selected_emitter_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compiled = root / "ooo/BaselineBoardGsimMain.class"
            compiled.parent.mkdir()
            compiled.write_bytes(b"compiled OoO fixture")
            cp = root / "cp.txt"
            cp.write_text(str(root))
            _, manifest = bringup.classpath_manifest(cp, "ooo.BaselineBoardGsimMain")
            self.assertEqual(manifest["main"], "ooo.BaselineBoardGsimMain")
            bringup.verify_classpath_unchanged(manifest)
            with self.assertRaisesRegex(RuntimeError, "lacks compiled inorder"):
                bringup.classpath_manifest(cp, "inorder.FiveStageSocGsimMain")

    def test_execution_dispatch_preserves_i1_default(self):
        with mock.patch.object(bringup, "run_i1", return_value="I1") as i1, \
                mock.patch.object(bringup, "run_ooo", return_value="OoO") as ooo:
            original = {"main": "inorder.FiveStageSocGsimMain"}
            self.assertEqual(bringup.run_profile(original, "argument"), "I1")
            i1.assert_called_once_with(original, "argument")
            ooo.assert_not_called()
            explicit = {"flow": "ooo_local_rom"}
            self.assertEqual(bringup.run_profile(explicit, "argument"), "OoO")
            ooo.assert_called_once_with(explicit, "argument")
            with self.assertRaisesRegex(RuntimeError, "unknown execution flow"):
                bringup.run_profile({"flow": "implicit_performance"})

    def test_ooo_contract_rejects_clock_and_protocol_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            rom = Path(tmp) / "rom.bin"
            rom.write_bytes(b"ROM")
            contract = {"cpu_hz": 40000000, "timebase_hz": 40000000, "uart_divisor": 1,
                        "uart_reference_hz": 24000000, "uart_baud": 1500000, "uart_contract_checked": True,
                        "boot_menu": False, "netboot": False, "jtag_download": False, "ddr_bytes": None,
                        "boot_ui": "plain", "download_autostart": True, "manual_image_launch": False,
                        "image_limit": 0xfc000, "bootrom_sha256": bringup.sha(rom),
                        "external_return_policy": "reset_required_unknown_peripheral_ownership"}
            bringup.validate_ooo_contract(contract, rom)
            for key, value in (("cpu_hz", 100000000), ("uart_baud", 460800), ("uart_divisor", 7),
                               ("manual_image_launch", True), ("boot_menu", True),
                               ("external_return_policy", "unlocked"), ("bootrom_sha256", "wrong")):
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    bringup.validate_ooo_contract({**contract, key: value}, rom)

    def test_ooo_positive_requires_all_stages_and_explicit_irq_limit(self):
        text = "\n".join((
            "reset ROM banner / ROM instruction-byte oracle: PASS",
            "whole-image bad CRC / no unverified execution / manual launch removed: PASS",
            "chunk CRC retry / RAM image byte oracle / AUTOBOOT sample guest: PASS",
            "APP RETURN / download and manual-launch lock: PASS",
            "hardware reset / fresh AUTOBOOT / byte-half-word-doubleword loads / RAM signature: PASS",
            "IRQ delivery chain: NOT COVERED", "DDR / Linux / frequency / physical board: NOT COVERED",
            "GSIM functional board baseline: PASS cycles=100 romCommits=20 ramCommits=30 ramReads=4 "
            "ramWrites=5 checkedReadBytes=32 uartBytes=40 uartDivisor=1 ramBytes=1048576"))
        self.assertEqual(bringup.validate_ooo_positive(text)["ramCommits"], 30)
        for bad in (text.replace("IRQ delivery chain: NOT COVERED", "IRQ PASS"),
                    text.replace("ramReads=4", "ramReads=0"),
                    text.replace("cycles=100", "cycles=30000001"),
                    text.replace("AUTOBOOT sample guest: PASS", "AUTOBOOT sample guest: FAIL"),
                    text + "\nruntime error: invalid memory"):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                bringup.validate_ooo_positive(bad)


if __name__ == "__main__":
    unittest.main()
