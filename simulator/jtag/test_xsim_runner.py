import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("jtag_xsim", Path(__file__).with_name("run_xsim.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class XsimRunnerTests(unittest.TestCase):
    def test_protocol_is_not_vendor(self):
        rows = runner.cases("protocol")
        self.assertEqual(len(rows), 7)
        self.assertIn("bscan_pin_model", [r["name"] for r in rows])
        for row in rows:
            cmds = runner.command_plan(row, row["sources"], False)
            self.assertNotIn("unisims_ver", cmds[1])

    def test_unisim_requires_explicit_installed_profile(self):
        for model in (None, dict(ir_length=0, user1=2, user2=3),
                      dict(ir_length=6, user1=2, user2=64), dict(ir_length=12, user1=2, user2=2)):
            with self.assertRaises(ValueError):
                runner.cases("unisim", model)

    def test_unisim_model_profile_is_not_forced_to_physical_bsdl(self):
        # Synthetic caller values test plumbing only; no installed model claimed.
        for width in (12, 16):
            rows = runner.cases("unisim", dict(ir_length=width, user1=0x902, user2=0x903))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["parameters"]["MODEL_IR_LENGTH"], width)
            self.assertTrue(rows[-1]["reject"])
            commands = runner.command_plan(rows[0], ["test.sv", "glbl.v"], True)
            self.assertIn("unisims_ver", commands[1])
            self.assertIn("xil_defaultlib.glbl", commands[1])
            self.assertEqual(commands[1][commands[1].index("-mt")+1], "off")

    def test_three_distinct_vendor_clock_scenarios(self):
        rows = runner.cases("unisim", dict(ir_length=16, user1=2, user2=3))[:3]
        self.assertEqual(len({(r["parameters"]["SYS_HALF"],r["parameters"]["TCK_LOW"],
                              r["parameters"]["TCK_HIGH"]) for r in rows}), 3)

    def test_drain_has_negative_reset_owner_and_three_clock_ratios(self):
        rows = runner.cases("loader-drain")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]["parameters"]["BAD_RESET_OWNER"], 1)
        self.assertEqual(rows[-1]["reject"], "DRAIN_OWNER_ORACLE")

    def test_positive_needs_clean_runtime_marker(self):
        row=runner.cases("protocol")[0]
        self.assertEqual(runner.classify_run(row,0,"PASS JTAG arcs=32"),"PASS")
        for rc,text in ((1,"PASS JTAG arcs=32"),(0,"nothing"),(0,"PASS JTAG arcs=32\nFatal: stale")):
            with self.assertRaises(RuntimeError): runner.classify_run(row,rc,text)

    def test_negative_needs_its_own_oracle_and_no_pass(self):
        row=runner.cases("loader-drain")[-1]
        self.assertEqual(runner.classify_run(row,0,"Fatal: DRAIN_OWNER_ORACLE"),"EXPECTED_ORACLE_REJECTION")
        for text in ("Fatal: syntax error", "DRAIN_OWNER_ORACLE",
                     "DRAIN_OWNER_ORACLE\nLOADER_CDC_DRAIN_PASS",
                     "Fatal: DRAIN_OWNER_ORACLE\nERROR: unrelated failure"):
            with self.assertRaises(RuntimeError):runner.classify_run(row,1,text)

    def test_preparation_invokes_no_program_and_copies_exact_sources(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner.subprocess,"run",side_effect=AssertionError("execution")):
            out=Path(tmp)/"prepared"
            with contextlib.redirect_stdout(io.StringIO()):
                runner.main(["--suite","protocol","--output",str(out)])
            report=json.loads((out/"receipt.json").read_text())
            self.assertEqual(report["status"],"PREPARED_NOT_RUN")
            self.assertFalse(report["runtime_executed"])
            self.assertFalse(report["vendor_primitive_executed"])
            for name,digest in report["input_sha256"].items():
                self.assertEqual(runner.sha(out/"inputs"/name),digest)

    def test_existing_output_rejected_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner.subprocess,"run",side_effect=AssertionError("execution")):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                runner.main(["--suite","protocol","--output",tmp])

    def test_run_without_explicit_installation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner.subprocess,"run",side_effect=AssertionError("execution")):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                runner.main(["--suite","protocol","--output",str(Path(tmp)/"out"),"--run"])

    def test_loader_requires_source_bound_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            (out/"native-loader.json").write_text('{"schema":"wrong","timeout_cycles":64}')
            with self.assertRaises(ValueError):runner.validate_loader(out)
            (out/"native-loader.json").write_text(json.dumps({"schema":"valence-native-loader-v1","timeout_cycles":64,
                "ram_base":"0x80200000","ram_end":"0x80201000"}))
            with self.assertRaisesRegex(ValueError,"source binding"):runner.validate_loader(out)

    def test_vendor_bench_has_real_primitives_and_no_replacement_models(self):
        text=(runner.HERE/"bscan_unisim_tb.sv").read_text()
        self.assertIn('JTAG_SIME2 #(.PART_NAME("XCZU15EG"))',text)
        self.assertIn('BSCANE2 #(.JTAG_CHAIN(1))',text)
        self.assertIn('ValenceBscanDebugPort #(.ENABLE(1),.JTAG_CHAIN(2))',text)
        self.assertNotIn('module BSCANE2',text)
        self.assertNotIn('force ',text)
        for marker in ("UNISIM_DRCK_UPDATE_PHASE_ORACLE","UNISIM_READBACK_ORACLE","UNISIM_PROFILE_MISMATCH"):
            self.assertIn(marker,text)

    def fake_install(self, directory):
        directory.mkdir()
        (directory/"bin").mkdir()
        for name in ("xvlog","xelab","xsim"):
            (directory/"bin"/(name+(".bat" if runner.os.name=="nt" else ""))).write_text("MOCK_ONLY")
        return directory

    def test_staged_drift_fails_even_when_mock_runtime_prints_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);install=self.fake_install(base/"install");out=base/"out"
            def mock_run(command, **kwargs):
                log="MOCK_ONLY version"
                if Path(command[0]).stem=="xsim" and "-runall" in command:
                    row=next(r for r in runner.cases("protocol") if r["name"]==Path(kwargs["cwd"]).name)
                    log=row["marker"]
                    (out/"inputs"/"simulator/jtag/jtag_debug_tb.sv").write_text("changed staged input")
                return SimpleNamespace(returncode=0,stdout=log)
            with patch.object(runner.subprocess,"run",side_effect=mock_run):
                with self.assertRaisesRegex(RuntimeError,"staged simulation input"):
                    runner.main(["--suite","protocol","--output",str(out),"--run","--vivado-root",str(install)])
            self.assertEqual(json.loads((out/"receipt.json").read_text())["status"],"FAILED")

    def test_vendor_source_drift_fails_after_mock_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);install=self.fake_install(base/"install");out=base/"out"
            model=install/"data/verilog/src/unisims/JTAG_SIME2.v"
            for name in ("glbl.v","unisims/JTAG_SIME2.v","unisims/BSCANE2.v"):
                p=install/"data/verilog/src"/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text("MOCK_ONLY")
            def mock_run(command, **kwargs):
                if Path(command[0]).stem=="xsim" and "-runall" in command:
                    model.write_text("CHANGED_MOCK_ONLY")
                    return SimpleNamespace(returncode=0,stdout="BSCAN_UNISIM_PROFILE_ONLY")
                return SimpleNamespace(returncode=0,stdout="MOCK_ONLY")
            with patch.object(runner.subprocess,"run",side_effect=mock_run):
                with self.assertRaisesRegex(RuntimeError,"installed model source"):
                    runner.main(["--suite","unisim-profile","--output",str(out),"--run","--vivado-root",str(install)])
            self.assertEqual(json.loads((out/"receipt.json").read_text())["status"],"FAILED")

    def test_compile_failure_is_never_a_negative_runtime_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);install=self.fake_install(base/"install");out=base/"out"
            def mock_run(command, **kwargs):
                fail="-sv" in command
                return SimpleNamespace(returncode=1 if fail else 0,stdout="DRAIN_OWNER_ORACLE compile error")
            with patch.object(runner.subprocess,"run",side_effect=mock_run):
                with self.assertRaisesRegex(RuntimeError,"xvlog failed"):
                    runner.main(["--suite","protocol","--output",str(out),"--run","--vivado-root",str(install)])
            report=json.loads((out/"receipt.json").read_text())
            self.assertEqual(report["status"],"FAILED")
            self.assertFalse(report["runtime_attempted"])


if __name__=="__main__":unittest.main()
