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
    PROFILE = "vivado-2025.1-xczu15eg"

    def model(self):
        return runner.select_model(self.PROFILE)

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
        rows = runner.cases("unisim", self.model())
        self.assertEqual(len(rows), 10)
        params = rows[0]["parameters"]
        self.assertEqual({k: params[k] for k in ("MODEL_PROFILE_TAG", "MODEL_IR_LENGTH",
                         "MODEL_USER1", "MODEL_USER2", "MODEL_IDCODE")},
                         dict(MODEL_PROFILE_TAG=202501, MODEL_IR_LENGTH=12,
                              MODEL_USER1=0x0a4, MODEL_USER2=0x0e4, MODEL_IDCODE=0x04a52093))
        commands = runner.command_plan(rows[0], ["test.sv", "glbl.v"], True)
        self.assertIn("unisims_ver", commands[1])
        self.assertIn("xil_defaultlib.glbl", commands[1])
        self.assertEqual(commands[1][commands[1].index("-mt")+1], "off")
        for key, value in params.items():
            self.assertIn(key + "=" + str(value), commands[1])

    def test_wrong_profile_identity_is_rejected(self):
        for key, value in (("name", "physical-bsdl"), ("part", "XCZU9EG"),
                           ("profile_tag", 0), ("ir_length", 16), ("user1", 0x902),
                           ("user2", 0x903), ("idcode", 0x04750093), ("source_sha256", {})):
            with self.subTest(field=key):
                model = self.model()
                model[key] = value
                with self.assertRaises(ValueError):
                    runner.cases("unisim", model)
        self.assertEqual(self.model()["source_sha256"], runner.MODEL_PROFILES[self.PROFILE]["source_sha256"])

    def test_installed_model_hashes_are_pinned(self):
        model = self.model()
        runner.validate_vendor_hashes(model, model["source_sha256"])
        for key in model["source_sha256"]:
            for replacement in (None, "0" * 64):
                hashes = dict(model["source_sha256"])
                if replacement is None:
                    del hashes[key]
                else:
                    hashes[key] = replacement
                with self.assertRaisesRegex(ValueError, "hash/profile mismatch"):
                    runner.validate_vendor_hashes(model, hashes)

    def test_profile_log_requires_exact_part_ir_opcodes_and_full_id(self):
        log = ("BSCAN_UNISIM_PROFILE_ONLY part=XCZU15EG ir_length=12 "
               "user1=000000a4 user2=000000e4 idcode=04a52093\n")
        runner.validate_profile_log(self.model(), log)
        for bad in ("", log + log, log.replace("XCZU15EG", "XCZU9EG"),
                    log.replace("length=12", "length=16"), log.replace("000000a4", "00000902"),
                    log.replace("000000e4", "00000903"), log.replace("04a52093", "04750093"),
                    log.replace("04a52093", "14a52093"), log.replace("04a52093", "xxxxxxxx")):
            with self.assertRaisesRegex(ValueError, "runtime profile mismatch"):
                runner.validate_profile_log(self.model(), bad)

    def test_each_identity_negative_requires_its_own_oracle(self):
        rows = runner.cases("unisim", self.model())
        positive = rows[0]["parameters"]
        for row in rows[5:]:
            with self.subTest(case=row["name"]):
                self.assertEqual(sum(row["parameters"][key] != positive[key]
                                     for key in row["parameters"]), 1)
                self.assertEqual(runner.classify_run(row, 0, "Fatal: " + row["reject"]),
                                 "EXPECTED_ORACLE_REJECTION")
                for log in ("Fatal: unrelated", row["reject"],
                            "Fatal: " + row["reject"] + "\nBSCAN_UNISIM_PASS"):
                    with self.assertRaises(RuntimeError):
                        runner.classify_run(row, 1, log)

    def test_legacy_physical_id_check_would_reject_installed_model(self):
        # Reproduce the old assertion's result; this is Python, not an HDL run.
        self.assertNotEqual(0x04a52093 & 0x0fffffff, 0x04750093)
        row = runner.cases("unisim", self.model())[-1]
        self.assertEqual(row["name"], "vendor_bad_legacy_physical_id")
        self.assertEqual(row["parameters"]["MODEL_IDCODE"], 0x04750093)
        self.assertEqual(row["reject"], "UNISIM_IDCODE_MISMATCH")

    def test_three_distinct_vendor_clock_scenarios(self):
        rows = runner.cases("unisim", self.model())[:3]
        self.assertEqual(len({(r["parameters"]["SYS_HALF"],r["parameters"]["TCK_LOW"],
                              r["parameters"]["TCK_HIGH"]) for r in rows}), 3)

    def test_exact_50ns_vendor_case_and_qualification_suite(self):
        rows = runner.cases("unisim", self.model())
        matched = [row for row in rows if row["name"] == "vendor_phase_3"]
        self.assertEqual(len(matched), 1)
        params = matched[0]["parameters"]
        # The tick helper includes 2 ns after falling TCK.
        self.assertEqual(params["TCK_LOW"] + 2, 25)
        self.assertEqual(params["TCK_HIGH"], 25)
        logical = runner.cases("bscan-qualification")
        self.assertEqual(len(logical), 2)
        self.assertEqual(logical[0]["marker"], "PASS BSCAN_FAULT_PHASE")
        for row in logical:
            self.assertNotIn("unisims_ver", runner.command_plan(row, row["sources"], False)[1])

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

    def test_vendor_preparation_binds_profile_without_claiming_execution(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner.subprocess,"run",side_effect=AssertionError("execution")):
            out = Path(tmp) / "prepared"
            with contextlib.redirect_stdout(io.StringIO()):
                runner.main(["--suite", "unisim", "--model-profile", self.PROFILE, "--output", str(out)])
            report = json.loads((out / "receipt.json").read_text())
            self.assertEqual(report["model_profile"], self.model())
            self.assertEqual(report["status"], "PREPARED_NOT_RUN")
            self.assertFalse(report["installed_model_profile_hashes_verified"])
            self.assertFalse(report["installed_model_runtime_profile_verified"])
            self.assertFalse(report["runtime_executed"])
            self.assertEqual(len(report["cases"]), 10)

    def test_cli_rejects_missing_unknown_or_conflicting_profile_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner.subprocess,"run",side_effect=AssertionError("execution")):
            for extra in ([], ["--model-profile", "physical-bsdl"],
                          ["--model-ir-length", "12", "--model-user1", "0x0a4", "--model-user2", "0x0e4"],
                          *[["--model-profile", self.PROFILE, option, value] for option, value in (
                              ("--model-ir-length", "16"), ("--model-user1", "0x902"),
                              ("--model-user2", "0x903"), ("--model-idcode", "0x04750093"))]):
                with self.subTest(options=extra), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                    runner.main(["--suite", "unisim", "--output", str(Path(tmp) / "out"), *extra])
            self.assertFalse((Path(tmp) / "out").exists())

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
        for check in ("MODEL_IR_LENGTH!==tap.IRLength", "MODEL_IDCODE!==tap.IDCODEval_sig",
                      "MODEL_USER1!==(tap.USER1_INSTR", "MODEL_USER2!==(tap.USER2_INSTR"):
            self.assertIn(check,text)
        self.assertNotIn("32'h04750093",text)
        self.assertNotIn("32'h0fffffff",text)

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

    def test_wrong_installed_hash_is_rejected_before_any_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); install = self.fake_install(base / "install"); out = base / "out"
            for name in ("glbl.v", "unisims/JTAG_SIME2.v", "unisims/BSCANE2.v"):
                p = install / "data/verilog/src" / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("MOCK_ONLY_WRONG_HASH")
            with patch.object(runner.subprocess, "run", side_effect=AssertionError("execution")):
                with self.assertRaisesRegex(ValueError, "hash/profile mismatch"):
                    runner.main(["--suite", "unisim", "--model-profile", self.PROFILE,
                                 "--output", str(out), "--run", "--vivado-root", str(install)])
            self.assertFalse(out.exists())

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
