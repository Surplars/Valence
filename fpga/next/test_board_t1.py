#!/usr/bin/env python3
"""Host-only T1 export/consumer tests. The emitter and Vivado command are mocks."""
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

exporter = module("t1_test_export", HERE/"export.py")
t1 = exporter.board_t1


class BoardT1Tests(unittest.TestCase):
    def preflight(self, options, path):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            exporter.main(["--output", str(path), *options])
        self.assertFalse(path.exists())
        return json.loads(stream.getvalue())

    def emit_mock(self, output, mode, bscan=False):
        wrapper = (HERE/"soc_top_fpga_next_ddr.sv").read_text()
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
        def emit(command, **kwargs):
            rtl = Path(command[4]); rtl.mkdir()
            instance = re.search(r"FpgaNextSocTop\s+u_soc\s*\((.*?)\);", wrapper, re.S).group(1)
            ports = re.findall(r"\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(", instance)
            (rtl/"FpgaNextSocTop.sv").write_text("module FpgaNextSocTop(" +
                ",".join("input " + name for name in ports) + "); endmodule\n")
            if bscan:
                for name in ("ValenceJtagDebugPort.sv", "ValenceBscanDebugPort.sv"):
                    (rtl/name).write_text("// mock emitter only, no RTL execution\n")
            return subprocess.CompletedProcess(command, 0)
        options = ["--output", str(output), "--emit", "--experimental-trispeed-ethernet"]
        if mode: options.append(t1.FLAG)
        if bscan: options.extend(["--experimental-jtag-bscan", "2"])
        with mock.patch.object(exporter.subprocess, "run", side_effect=emit), \
                mock.patch.object(exporter.subprocess, "check_output", return_value=head), \
                contextlib.redirect_stdout(io.StringIO()):
            exporter.main(options)
        return json.loads((output/"receipt.json").read_text())

    def test_default_off_and_on_do_not_change_scala_configuration_or_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"absent"
            off = self.preflight(["--experimental-trispeed-ethernet"], p)
            on = self.preflight(["--experimental-trispeed-ethernet", t1.FLAG], p)
            self.assertEqual(off["configuration"], on["configuration"])
            self.assertEqual(off["command"], on["command"])
            self.assertNotIn(t1.FLAG, on["command"])
            self.assertEqual(off["native_mac_mode"], t1.selection(False))
            self.assertEqual(on["native_mac_mode"], t1.selection(True))
            self.assertIsNone(self.preflight([], p)["native_mac_mode"])

    def test_bad_flags_fail_before_output_or_emitter(self):
        bad = [[t1.FLAG], ["--experimental-trispeed-ethernet", t1.FLAG, t1.FLAG],
               ["--experimental-trispeed-ethernet", "--native-mac-local-pad-reset"],
               *[["--experimental-trispeed-ethernet", t1.FLAG+"="+value] for value in ("0", "1", "true", "false")]]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(exporter.subprocess, "run", side_effect=AssertionError("execution")):
            for options in bad:
                with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    exporter.main(["--output", str(Path(tmp)/"absent"), *options])
                self.assertFalse((Path(tmp)/"absent").exists())

    def test_explicit_board_preset_preserves_all_published_abc_options(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as stream:
            t1.main(["--output", str(Path(tmp)/"absent")])
            result = json.loads(stream.getvalue())
            self.assertEqual(result["native_mac_mode"], t1.selection(True))
            self.assertTrue(result["configuration"]["experimental_trispeed_ethernet"])
            self.assertEqual(result["configuration"]["bscan_chain"], 2)
            base = json.loads((HERE/t1.ABC_PROFILE).read_text())["native_options"]
            self.assertEqual(len(base), 46)
            self.assertEqual(set(result["command"][5:]), set(base))
            self.assertEqual(len(result["command"][5:]), 46)
            for key in ("registered_pending_store_query", "registered_canonical_store_event", "aligned_fetch_permission_stage"):
                self.assertTrue(result["configuration"][key])
            self.assertEqual(result["configuration"]["pending_virtual_store_proof_slots"], 2)
            self.assertEqual(result["configuration"]["pending_store_early_load_credits"], 2)
            self.assertFalse((Path(tmp)/"absent").exists())

    def test_mock_export_matrix_binds_top_generic_and_production_bytes(self):
        for mode in (False, True):
            for bscan in (False, True):
                with self.subTest(mode=mode, bscan=bscan), tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp)/"export"
                    receipt = self.emit_mock(out, mode, bscan)
                    report = t1.verify(out)
                    self.assertEqual(report["generics"], {t1.PARAMETER:int(mode)})
                    self.assertFalse(report["synthesis_consumer_executed"])
                    self.assertFalse(report["mapped_topology_checked"])
                    self.assertFalse(receipt["physical_qualification"])
                    for name in ("native_rgmii_trispeed_quarter.sv", "trispeed_quarter_constraints.tcl"):
                        self.assertEqual((out/"board"/name).read_bytes(), (ROOT/"fpga/zu15eg"/name).read_bytes())

    def test_readonly_verifier_rejects_missing_changed_or_mismatched_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/"export"; receipt = self.emit_mock(out, True)
            for key, value in [("generics", {t1.PARAMETER:0}), ("top", "soc_top_gmac_ddr"),
                               ("native_mac_local_pad_reset_release", False)]:
                bad = copy.deepcopy(receipt); bad["native_mac_mode"][key] = value
                (out/"receipt.json").write_text(json.dumps(bad))
                with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "mode choice/top/generic"):
                    t1.verify(out)
            (out/"receipt.json").write_text(json.dumps(receipt))
            script = out/"board/native-mac-mode.tcl"; script.write_text(script.read_text()+"# drift\n")
            with self.assertRaisesRegex(RuntimeError, "mode artifact changed"):
                t1.verify(out)

    def test_tcl_consumer_is_explicit_and_cannot_override_top_or_generic(self):
        for mode in (False, True):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); script = root/"native-mac-mode.tcl"; script.write_text(t1.consumer_tcl(mode))
                (root/"trispeed_quarter_constraints.tcl").write_text('proc valence_trispeed_quarter_audit {root expected} {puts "AUDIT $root $expected"}\n')
                text = 'set calls {}\nproc synth_design {args} {global calls; lappend calls $args}\n'
                text += 'source {'+str(script)+'}\nif {[llength $calls] != 0} {error {implicit synthesis}}\n'
                text += 'valence_native_mac_synth_design -part xczu15eg-ffvb1156-2-i\n'
                text += f'if {{[lindex $calls 0] ne {{-top {t1.TOP} -generic {t1.PARAMETER}={int(mode)} -part xczu15eg-ffvb1156-2-i}}}} {{error {{wrong generic}}}}\n'
                for args in ['-top other', '-to other', '-t other', '-generic X=1', '-gen X=1',
                             '-ge X=1', '-g X=1', '-top=other']:
                    text += 'if {![catch {valence_native_mac_synth_design '+args+'}]} {error {override allowed}}\n'
                text += 'if {[llength $calls]!=1} {error {rejected call reached synthesis}}\nvalence_native_mac_assert_mode\nputs CONSUMER_PASS\n'
                result = subprocess.run(['tclsh'], input=text, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                self.assertIn('CONSUMER_PASS', result.stdout)
                self.assertIn('AUDIT u_rgmii '+str(int(mode)), result.stdout)


if __name__ == "__main__":
    unittest.main()
