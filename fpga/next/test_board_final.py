#!/usr/bin/env python3
"""Source/config/real staged Tcl contract tests; no hardware or synthesis execution."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


final = module("test_final_entry", HERE / "board_final.py")
exporter = final.exporter_module()


class BoardFinalTests(unittest.TestCase):
    def preflight(self, path, options=None):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            if options is None:
                final.main(["--output", str(path)])
            else:
                exporter.main(["--output", str(path), *options])
        self.assertFalse(path.exists())
        return json.loads(stream.getvalue())

    def emit_mock(self, output):
        wrapper = (HERE / "soc_top_fpga_next_ddr.sv").read_text()
        commands = []
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
        def emit(command, **kwargs):
            commands.append(command)
            self.assertEqual(command[:4], ["mill", "-i", "IonSoC.test.runMain", "ooo.FpgaNextMain"])
            rtl = Path(command[4]); rtl.mkdir()
            instance = re.search(r"FpgaNextSocTop\s+u_soc\s*\((.*?)\);", wrapper, re.S).group(1)
            ports = re.findall(r"\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(", instance)
            (rtl / "FpgaNextSocTop.sv").write_text("// MOCK EMITTER: NOT HARDWARE EVIDENCE\nmodule FpgaNextSocTop(" + ",".join("input " + name for name in ports) + "); endmodule\n")
            (rtl / "MockLeaf.sv").write_text("// MOCK LEAF: NOT HARDWARE EVIDENCE\n")
            (rtl / "filelist.f").write_text("FpgaNextSocTop.sv\nMockLeaf.sv\n")
            for name in ("ValenceJtagDebugPort.sv", "ValenceBscanDebugPort.sv"):
                (rtl / name).write_text("// MOCK EMITTER: NOT HARDWARE EVIDENCE\n")
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(final, "exporter_module", return_value=exporter), \
                mock.patch.object(exporter.subprocess, "run", side_effect=emit), \
                mock.patch.object(exporter.subprocess, "check_output", return_value=head), \
                contextlib.redirect_stdout(io.StringIO()):
            final.main(["--output", str(output), "--emit"])
        self.assertEqual(len(commands), 1)
        return json.loads((output / "receipt.json").read_text())

    def test_single_entry_preserves_exact_cpu_options_and_capacities(self):
        spec = final.load_profile()
        with tempfile.TemporaryDirectory() as tmp:
            result = self.preflight(Path(tmp) / "absent")
        expected = json.loads((HERE / spec["cpu_profile"]["manifest"]).read_text())["native_options"]
        self.assertEqual(sorted(result["command"][5:]), sorted(expected))
        self.assertEqual(len(result["command"][5:]), spec["cpu_profile"]["native_option_count"])
        self.assertNotIn(exporter.board_t1.FLAG, result["command"])
        self.assertEqual(result["native_mac_mode"], exporter.board_t1.selection(True))
        config = result["configuration"]
        self.assertEqual(final.digest(config), spec["export_profile_sha256"])
        for key, value in {"cpu_hz": 100000000, "issue_width": 2, "rob_entries": 16,
                           "physical_registers": 48, "lsu_entries": 4, "data_translation_entries": 16,
                           "instruction_translation_entries": 8, "pte_cache_entries": 4,
                           "instruction_cache_lines": 512, "data_cache_lines": 512,
                           "cache_ways": 2, "cache_read_mshrs": 2, "cache_response_entries": 2,
                           "cache_writeback_entries": 2, "pending_virtual_store_proof_slots": 2,
                           "pending_store_early_load_credits": 2, "ddr_bytes": 2147483648,
                           "bscan_chain": 2, "experimental_trispeed_ethernet": True,
                           "shared_lane1_owner_match": True, "direct_rank1_memory_source_ids": True}.items():
            self.assertEqual(config[key], value, key)

    def test_generic_default_off_and_old_entry_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent"
            default = self.preflight(path, ["--experimental-trispeed-ethernet"])
            self.assertEqual(default["native_mac_mode"], exporter.board_t1.selection(False))
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                exporter.board_t1.main(["--output", str(path)])
            old = json.loads(stream.getvalue())
            self.assertEqual(len(old["command"][5:]), 46)
            self.assertNotIn("--shared-lane1-owner-match", old["command"])
            self.assertEqual(old["native_mac_mode"], exporter.board_t1.selection(True))

    def test_cli_rejects_cpu_mode_and_chain_overrides_before_execution(self):
        bad = [["--direct-rank1-memory-source-ids"], ["--native-mac-local-pad-reset-release"], ["--experimental-jtag-bscan=1"],
               ["--rob-entries=64"], ["--reference"], ["--out", "other"], ["--emit=true"],
               ["--registered-memory-preparation-context"], ["--cancelled-load-response-drain"],
               ["--displaced-memory-preparation-shadow"]]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(exporter.subprocess, "run", side_effect=AssertionError("execution")):
            path = Path(tmp) / "absent"
            for options in bad:
                with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    final.main(["--output", str(path), *options])
                self.assertFalse(path.exists())

    def test_changed_manifest_or_complete_configuration_fails_before_emitter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            spec = json.loads(final.MANIFEST.read_text())
            spec["cpu_profile"]["native_option_count"] += 1
            path.write_text(json.dumps(spec))
            with mock.patch.object(final, "MANIFEST", path), self.assertRaisesRegex(RuntimeError, "manifest changed"):
                final.load_profile()
            with mock.patch.object(final, "MANIFEST", path), mock.patch.object(final, "MANIFEST_SHA256", final.sha(path)), self.assertRaisesRegex(RuntimeError, "options/USER2/capacities"):
                final.load_profile()
            original = final.load_profile()
            cpu = json.loads((HERE / original["cpu_profile"]["manifest"]).read_text())
            for missing in ("--direct-rank1-memory-source-ids", "--shared-lane1-owner-match", "--pending-virtual-store-proof-slots=2",
                            "--pending-store-early-load-credits=2", "--experimental-jtag-bscan=2"):
                bad_cpu = copy.deepcopy(cpu); bad_cpu["native_options"].remove(missing)
                cpu_path = Path(tmp) / "cpu.json"; cpu_path.write_text(json.dumps(bad_cpu))
                bad = copy.deepcopy(original)
                bad["cpu_profile"].update(manifest="cpu.json", sha256=final.sha(cpu_path), native_option_count=len(bad_cpu["native_options"]))
                bad["native_options"] = [*bad_cpu["native_options"], exporter.board_t1.FLAG]
                path.write_text(json.dumps(bad))
                with self.subTest(missing=missing), mock.patch.object(final, "HERE", Path(tmp)), mock.patch.object(final, "MANIFEST", path), mock.patch.object(final, "MANIFEST_SHA256", final.sha(path)), self.assertRaisesRegex(RuntimeError, "options/USER2/capacities"):
                    final.load_profile()
            bad = copy.deepcopy(original); bad["status"] = "PENDING_CPU_QUALIFICATION"
            path.write_text(json.dumps(bad))
            with mock.patch.object(final, "MANIFEST", path), mock.patch.object(final, "MANIFEST_SHA256", final.sha(path)), self.assertRaisesRegex(RuntimeError, "not selected and reviewed"):
                final.load_profile()
            bad = copy.deepcopy(original); bad["export_sources_sha256"] = "0" * 64
            path.write_text(json.dumps(bad))
            with mock.patch.object(final, "MANIFEST", path), mock.patch.object(final, "MANIFEST_SHA256", final.sha(path)), self.assertRaisesRegex(RuntimeError, "source closure changed"):
                final.load_profile()
            bad = copy.deepcopy(original)
            bad["qualification_evidence"]["actual_profile"]["snapshot"]["core"]["tagBits"] = 32
            path.write_text(json.dumps(bad))
            with mock.patch.object(final, "MANIFEST", path), mock.patch.object(final, "MANIFEST_SHA256", final.sha(path)), self.assertRaisesRegex(RuntimeError, "runtime snapshot changed"):
                final.load_profile()
            bad = copy.deepcopy(original); bad["qualification_evidence"]["cpu_cases"]["bare"] += 1
            path.write_text(json.dumps(bad))
            with mock.patch.object(final, "MANIFEST", path), mock.patch.object(final, "MANIFEST_SHA256", final.sha(path)), self.assertRaisesRegex(RuntimeError, "CPU cases changed"):
                final.load_profile()
            spec = final.load_profile(); spec["export_profile_sha256"] = "0" * 64
            with mock.patch.object(final, "load_profile", return_value=spec), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                final.main(["--output", str(Path(tmp) / "absent")])
            self.assertFalse((Path(tmp) / "absent").exists())

    def test_mock_export_uses_real_staging_and_stays_unqualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "export"
            receipt = self.emit_mock(output)
            result = final.verify(output)
            self.assertEqual(result["status"], "PASS_FINAL_BOARD_EXPORT_BINDING_ONLY")
            self.assertFalse(result["synthesis_consumer_executed"])
            self.assertFalse(result["physical_qualification"])
            self.assertEqual((output / "board/native-mac-mode.tcl").read_text(), exporter.board_t1.consumer_tcl(True))
            self.assertEqual(receipt["profile"]["bscan_chain"], 2)
            for name in final.INPUTS:
                self.assertEqual(receipt["source_sha256"][name], final.sha(ROOT / name))

    def test_receipt_negative_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "export"
            receipt = self.emit_mock(output)
            bad_cases = []
            bad = copy.deepcopy(receipt); bad["command"].remove("--direct-rank1-memory-source-ids"); bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["profile"]["cpu_hz"] = 50000000; bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["command"].append("--reference"); bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["command"][4] = "/wrong/export/rtl"; bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["rtl_sha256"] = {}; bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["command"].remove("--shared-lane1-owner-match"); bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["source_sha256"][final.INPUTS[1]] = "0" * 64; bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["native_mac_mode"]["generics"][exporter.board_t1.PARAMETER] = 0; bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["final_board_profile"]["sha256"] = "0" * 64; bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["synthesis"] = True; bad_cases.append(bad)
            bad = copy.deepcopy(receipt); bad["board_wrapper"]["qualified"] = True; bad_cases.append(bad)
            for index, bad in enumerate(bad_cases):
                (output / "receipt.json").write_text(json.dumps(bad))
                with self.subTest(index=index), self.assertRaises(RuntimeError):
                    final.verify(output)
            (output / "receipt.json").write_text(json.dumps(receipt))
            for name in ("board/native-mac-mode.tcl", "board/require_jtag_chain.tcl",
                         "board/bscan_timing.tcl", "board/native_rgmii_trispeed_quarter.sv",
                         "rtl/FpgaNextSocTop.sv", "synthesis-files.f"):
                path = output / name; old = path.read_bytes(); path.write_bytes(old + b"\n# drift\n")
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    final.verify(output)
                path.write_bytes(old)
            self.assertEqual(final.verify(output)["status"], "PASS_FINAL_BOARD_EXPORT_BINDING_ONLY")
            filelist = output / "synthesis-files.f"; old_list = filelist.read_text()
            filelist.write_text(old_list.replace("rtl/MockLeaf.sv\n", ""))
            bad = copy.deepcopy(receipt); bad["synthesis_filelist_sha256"] = final.sha(filelist)
            (output / "receipt.json").write_text(json.dumps(bad))
            with self.assertRaisesRegex(RuntimeError, "filelist closure"):
                final.verify(output)
            filelist.write_text(old_list); (output / "receipt.json").write_text(json.dumps(receipt))
            # Coordinated rehashes must not legitimize a missing or changed gate.
            for manifest_name, field, key, summary_key in (
                ("board/trispeed-integration.json", "artifacts_sha256", "board/trispeed_board_constraints.tcl", "tri_speed_native_integration"),
                ("board/bscan-timing-contract.json", "files", "board/bscan_timing.tcl", "bscan_timing_candidate")):
                path = output / manifest_name; original = path.read_bytes()
                changed = json.loads(original); changed[field].pop(key)
                path.write_text(json.dumps(changed))
                bad = copy.deepcopy(receipt); bad[summary_key]["sha256"] = final.sha(path)
                (output / "receipt.json").write_text(json.dumps(bad))
                with self.subTest(omitted=key), self.assertRaises(RuntimeError):
                    final.verify(output)
                path.write_bytes(original)
                (output / "receipt.json").write_text(json.dumps(receipt))
            path = output / "board/native_gmac_divided_clock.sv"; original = path.read_bytes()
            path.write_bytes(original + b"\n// changed native source\n")
            manifest = output / "board/trispeed-integration.json"; old_manifest = manifest.read_bytes()
            changed = json.loads(old_manifest); changed["artifacts_sha256"]["board/native_gmac_divided_clock.sv"] = final.sha(path)
            manifest.write_text(json.dumps(changed))
            bad = copy.deepcopy(receipt); bad["tri_speed_native_integration"]["sha256"] = final.sha(manifest)
            (output / "receipt.json").write_text(json.dumps(bad))
            with self.assertRaises(RuntimeError):
                final.verify(output)
            path.write_bytes(original); manifest.write_bytes(old_manifest)
            (output / "receipt.json").write_text(json.dumps(receipt))

    def test_exact_staged_consumer_tcl_with_synthesis_mock(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "export"
            self.emit_mock(output)
            script = output / "board/native-mac-mode.tcl"
            program = 'set calls {}\nproc synth_design {args} {global calls; lappend calls $args}\n'
            program += 'source {' + str(script) + '}\nif {[llength $calls] != 0} {error {implicit synthesis}}\n'
            program += 'valence_native_mac_synth_design -part xczu15eg-ffvb1156-2-i\n'
            program += 'if {[lindex $calls 0] ne {-top soc_top_fpga_next_ddr -generic NATIVE_MAC_LOCAL_PAD_RESET_RELEASE=1 -part xczu15eg-ffvb1156-2-i}} {error {wrong consumer command}}\n'
            for args in ('-top other', '-to other', '-t other', '-generic X=1', '-gen X=1', '-ge X=1', '-g X=1'):
                program += 'if {![catch {valence_native_mac_synth_design ' + args + '}]} {error {override allowed}}\n'
            program += 'if {[llength $calls] != 1} {error {rejected option reached mock}}\nputs FINAL_CONSUMER_MOCK_PASS\n'
            result = subprocess.run(['tclsh'], input=program, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            self.assertIn('FINAL_CONSUMER_MOCK_PASS', result.stdout)


if __name__ == "__main__":
    unittest.main()
