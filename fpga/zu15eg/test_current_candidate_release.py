"""Synthetic host contracts only; no Vivado, board or runtime qualification."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from release_inputs import FRESH_STATUS, HELPERS, ROM, load_release_inputs
import verify_current_candidate_release as release
from prepare_native_release_contract import bridge_fields

PARAMS = ["100000000", "staged-fetch-turnover", "460800", "rv64gc", "50000000", "50000000",
          "250000000", "2147483648", "512", "512", "4", "16", "2", "2", "1", "--compact-tags"]
REPORT = """CDC-15  Warning  1  hidden vendor boundary
Source Clock: mmcm_clkout0
Destination Clock: clk_out1_clk_wiz_ddr
CDC Type: Safely Timed
  1  CDC-15  Warning  hidden vendor boundary  0  False Path  <hidden>  <hidden>
"""
RX_REPORT = """CDC-1  Critical  1  scalar held payload
Source Clock: clk_out1_clk_wiz_ddr
Destination Clock: centered_rx_clock.rx_source
CDC Type: Safely Timed
  1  CDC-1  Critical  scalar held payload  0  Max Delay Datapath Only  u_soc/nativeBank/gmac/rxStop/command/held_reg/C  u_soc/nativeBank/gmac/rxStop/command/captured_reg/D
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return path


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


class CurrentCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.repo, self.root = self.directory / "repo", self.directory / "candidate"
        self.repo.mkdir(); self.root.mkdir()
        source = put(self.repo, "src/main/scala/core/ooo/BoardSocTop.scala", 'val ramBase = BigInt("80200000", 16)\n')
        bridge_source = put(self.repo, "src/main/scala/ip/bus/ClockDomainCrossing.scala", "synthetic bridge source\n")
        sources = {p.relative_to(self.repo).as_posix(): release.sha(p) for p in (source, bridge_source)}
        auditor = Path(__file__).resolve().parents[1] / "firmware/audit_bootrom.py"
        put(self.repo, "fpga/firmware/audit_bootrom.py", auditor.read_bytes())
        put(self.repo, "fpga/zu15eg/report_ram_concurrency.tcl", "original read-only report\n")
        source_manifest = self.repo / (HELPERS + "integrated-source-sha256.json")
        save(source_manifest, sources)
        script_digest = release.sha(self.repo / "fpga/zu15eg/report_ram_concurrency.tcl")
        put(self.root, "board/fixture.sv", "synthetic board\n")
        put(self.root, "scripts/report_ram_concurrency.tcl", "original read-only report\n")
        blocks = {"_GEN": [("requestHeld_" + f, "source_request_bits_" + f)
                            for f in ("address", "write", "size", "data", "byteEnable")],
                  "_GEN_0": [("reply_" + f, "responseHeld_" + f) for f in ("data", "error")],
                  "_GEN_1": [("request_" + f, "requestHeld_" + f)
                              for f in ("address", "write", "size", "data", "byteEnable")],
                  "_GEN_2": [("responseHeld_" + f, "destination_response_bits_" + f) for f in ("data", "error")]}
        rtl = "\n".join((
            "wire        _GEN = source_request_ready_0 & source_request_valid;",
            "wire        _GEN_0 = _responseSync_levelOut != seen & busy & ~valid;",
            "wire        _GEN_1 = _requestSync_levelOut != seen_1 & ~valid_1 & ~waiting;",
            "wire        _GEN_2 = destination_response_ready_0 & destination_response_valid;"))
        for control, fields in blocks.items():
            rtl += "\nif (" + control + ") begin\n" + "\n".join(a + " <= " + b + ";" for a, b in fields) + "\nend\n"
        rtl_path = put(self.root, "rtl/RegisterClockDomainBridge.sv", rtl)
        self.export = dict(status="PASS_EXPORT_IDENTITY_FUNCTIONAL_SCOPE_ONLY", variants={"integrated-off":
            dict(cpu_precheck=False, parameters_after_output=PARAMS,
                 rtl_sha256={"RegisterClockDomainBridge.sv": release.sha(rtl_path)})},
            source_map={"scripts/report_ram_concurrency.tcl":
                        dict(repo_path="fpga/zu15eg/report_ram_concurrency.tcl", sha256=script_digest)})
        save(self.repo / (HELPERS + "EXPORT-RECEIPT.json"), self.export)
        fixed_folders = ["mig", *("ip-build/" + tree + "/sources_1/ip/" + name
            for tree in ("board_ip.srcs", "board_ip.gen") for name in ("clk_wiz_ddr", "axi_clock_converter_ddr"))]
        expected = {"sha256": {}}
        for folder in fixed_folders:
            path = put(self.root, folder + "/fixture", "fixed " + folder)
            expected["sha256"][path.relative_to(self.root).as_posix()] = release.sha(path)
        data = b"Valence Bootrom V0.1\r\n\0monitor> \0locked> \0EXTERNAL STATE LOCKED; BOARD RESET REQUIRED\r\n\0"
        binary = put(self.root, "firmware/bootrom.bin", data)
        coe = put(self.root, "firmware/bootrom.coe", "synthetic COE bound by exact hash")
        words = [int.from_bytes(data.ljust(131072, b"\0")[n:n + 4], "little") for n in range(0, 131072, 4)]
        put(self.root, ROM + ".mif", "".join(format(word, "032b") + "\n" for word in words))
        rom_dcp = put(self.root, ROM + ".dcp", "synthetic BMG checkpoint")
        for path in (binary, coe):
            expected["sha256"][path.relative_to(self.root).as_posix()] = release.sha(path)
        expected["rom_word_audit"] = {"binaryBytes": len(data)}
        save(self.repo / (HELPERS + "expected-local-inputs.json"), expected)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "commit", "-qm", "synthetic"], check=True)
        commit = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.inputs = dict(status=FRESH_STATUS, variant="integrated-off", cpu_precheck=False,
            source_binding=dict(status="PASS", commit=commit, source_files=len(sources), manifest_sha256=release.sha(source_manifest)),
            parameters_after_output=PARAMS, fixed_ip_files_reused_by_exact_hash=len(fixed_folders),
            historical_rom_binary_reproduced=True, historical_rom_dcp_reused=False, cpu_checkpoint_reused=False,
            rom_word_audit=dict(profile="menu", binaryBytes=len(data), binarySha256=release.sha(binary),
                                mifWordsMatched=32768, romDcpSha256=release.sha(rom_dcp)),
            candidate_sha256={p.relative_to(self.root).as_posix(): release.sha(p) for p in self.root.rglob("*") if p.is_file()})
        self.write_inputs()

    def tearDown(self):
        self.temp.cleanup()

    def write_inputs(self):
        save(self.root / "inputs.json", self.inputs)

    def check_inputs(self):
        return load_release_inputs(self.root, self.repo)

    def test_current_schema_pass_and_frozen_manifest_unchanged(self):
        before = (self.root / "inputs.json").read_bytes()
        result = self.check_inputs()
        self.assertEqual((result["ram_base"], result["end_exclusive"]), ("0x80200000", "0x100200000"))
        self.assertEqual(result["cpu_hz"], 100000000)
        self.assertEqual((self.root / "inputs.json").read_bytes(), before)

    def test_later_reporting_script_does_not_rebind_hardware(self):
        put(self.repo, "fpga/zu15eg/report_ram_concurrency.tcl", "new read-only report revision\n")
        result = self.check_inputs()
        self.assertEqual(result["hardware_source_commit"], self.inputs["source_binding"]["commit"])

    def test_source_tamper(self):
        put(self.repo, "src/main/scala/core/ooo/BoardSocTop.scala", "changed hardware")
        with self.assertRaises(ValueError): self.check_inputs()

    def test_extra_production_source(self):
        put(self.repo, "src/main/scala/Extra.scala", "extra hardware")
        with self.assertRaises(ValueError): self.check_inputs()

    def test_omitted_source_binding(self):
        del self.inputs["source_binding"]; self.write_inputs()
        with self.assertRaises(KeyError): self.check_inputs()

    def test_wrong_source_manifest(self):
        self.inputs["source_binding"]["manifest_sha256"] = "0" * 64; self.write_inputs()
        with self.assertRaises(ValueError): self.check_inputs()

    def test_unknown_schema_cannot_fall_back_to_legacy(self):
        self.inputs["status"] = "LEGACY"; self.write_inputs()
        with self.assertRaises(ValueError): self.check_inputs()

    def test_changed_or_omitted_clock_parameter(self):
        for params in (PARAMS[:4] + ["10000000"] + PARAMS[5:], PARAMS[:4] + PARAMS[5:]):
            self.inputs["parameters_after_output"] = params; self.write_inputs()
            with self.assertRaises(ValueError): self.check_inputs()

    def test_conflicting_legacy_profile(self):
        self.inputs["cpu_hz"] = 200000000; self.write_inputs()
        with self.assertRaises(ValueError): self.check_inputs()

    def test_rom_declared_proof_changed(self):
        self.inputs["rom_word_audit"]["romDcpSha256"] = "0" * 64; self.write_inputs()
        with self.assertRaises(ValueError): self.check_inputs()

    def test_rom_padding_tamper_even_with_updated_inventory(self):
        path = self.root / (ROM + ".mif")
        data = path.read_text(); path.write_text(data[:-33] + "1" * 32 + "\n")
        self.inputs["candidate_sha256"][ROM + ".mif"] = release.sha(path); self.write_inputs()
        with self.assertRaises(ValueError): self.check_inputs()

    def test_deleted_fixed_ip_even_with_updated_inventory(self):
        name = "mig/fixture"; (self.root / name).unlink()
        del self.inputs["candidate_sha256"][name]; self.write_inputs()
        with self.assertRaises(ValueError): self.check_inputs()

    def test_extra_rtl_even_with_updated_inventory(self):
        path = put(self.root, "rtl/Extra.sv", "extra RTL")
        self.inputs["candidate_sha256"]["rtl/Extra.sv"] = release.sha(path); self.write_inputs()
        with self.assertRaises(ValueError): self.check_inputs()

    def test_omitted_candidate_hash(self):
        del self.inputs["candidate_sha256"]["board/fixture.sv"]; self.write_inputs()
        with self.assertRaises(ValueError): self.check_inputs()

    def test_legacy_schema_still_returned_for_legacy_validators(self):
        legacy = dict(status="STAGED_DDR2G_RV64GC_CHECKED_EXPORT_NOT_ROUTED", isa="rv64gc")
        save(self.root / "inputs.json", legacy)
        self.assertEqual(self.check_inputs(), legacy)

    def contract_fixture(self):
        dcp = put(self.root, "implementation/routed.dcp", "synthetic own routed checkpoint")
        run = dcp.parent
        timing = "| Design State : Routed\n| Design Timing Summary\n 0.028 0.000 0 100 0.010 0.000 0 100 0.081 0.000 0 100\n"
        for name in release.REQUIRED_REPORTS:
            put(run, name, timing if name == "timing_summary.rpt" else REPORT if name == "cdc.rpt" else "synthetic report")
        facts = (f"CHECKPOINT={dcp}\nPART=xczu15eg-ffvb1156-2-i\nCOMMON_RELEASE_MODULES=37\nLEVEL_MODULES=45\n"
                 "QUARTER_TX_COMMON_WORD_RESET_EPOCH_PASS\nFIFO_PAYLOAD_PATHS txFifo COUNT=38\n"
                 "FIFO_PAYLOAD_PATHS rxFifo COUNT=38\nMIG_VENDOR_TARGET RIU_ADDR EXACT=84 EXPANDED=84\n"
                 "MIG_VENDOR_TARGET RIU_WR_DATA EXACT=224 EXPANDED=224\nREAD_ONLY_STRUCTURAL_FACTS_COMPLETE_NOT_CDC_SIGNOFF\n")
        truth = f"CHECKPOINT={dcp}\nPASS_TXCONFIG_BIT3_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE\n"
        facts_path = put(self.directory, "facts.txt", facts)
        truth_path = put(self.directory, "truth.txt", truth)
        proof = dict(status="RV64GC100_ROUTED_TIMING_MET_CDC_BOARD_REVIEW_PENDING", dcp_sha256=release.sha(dcp),
            hardware_source_commit=self.inputs["source_binding"]["commit"], candidate_manifest_sha256=release.sha(self.root / "inputs.json"),
            source_integrated=True, bit_requested=True, routed_timing_met=True, ddr_bytes=0x80000000,
            candidate_input_drift={}, current_source_drift=[], runtime_errors=[], runtime_critical_warnings=[], drc_errors_or_critical=[],
            board=release.summary(timing), routing=dict(all_routed=True), clock_coverage={name: True for name in release.COVERAGE},
            bus_skew=dict(checks=27, failures=0, minimum_slack_ns=0.1),
            io=dict(tx=dict(setup_ns=0.1, hold_ns=0.1), rx=dict(setup_ns=0.1, hold_ns=0.1)),
            divider_release=dict(setup_ns=0.1, hold_ns=0.1),
            artifact_sha256={name: release.sha(run / name) for name in release.REQUIRED_REPORTS})
        proof_path = self.directory / "proof.json"; save(proof_path, proof)
        output = self.directory / "contract"
        release.prepare(SimpleNamespace(candidate=self.root, repo=self.repo, out=output, routed_proof=proof_path,
                                        cdc_facts=facts_path, mailbox_truth=truth_path))
        return output / "qualified-contract.json", dcp

    def test_current_full_synthetic_contract(self):
        contract, dcp = self.contract_fixture()
        result = release.validate(contract, dcp)
        self.assertEqual(result["reviewed_cdc_findings"], 1)
        self.assertFalse(result["independent_protocol_runtime_verified"])

    def test_wrong_dcp(self):
        contract, dcp = self.contract_fixture()
        other = put(self.directory, "other/routed.dcp", dcp.read_bytes())
        with self.assertRaises(ValueError): release.validate(contract, other)

    def test_changed_current_cdc_report(self):
        contract, dcp = self.contract_fixture()
        changed = put(self.directory, "current-cdc.rpt", REPORT.replace("mmcm_clkout0", "other_clock"))
        with self.assertRaises(ValueError): release.validate(contract, dcp, changed)

    def test_evidence_tamper(self):
        contract, dcp = self.contract_fixture()
        put(self.directory, "facts.txt", "tampered")
        with self.assertRaises(ValueError): release.validate(contract, dcp)

    def test_omitted_cdc_review_finding(self):
        contract, dcp = self.contract_fixture()
        path = contract.parent / "cdc_review.json"
        review = release.load(path); review["findings"] = []; save(path, review)
        value = release.load(contract); value["evidence"]["cdc_review"]["sha256"] = release.sha(path); save(contract, value)
        with self.assertRaises(ValueError): release.validate(contract, dcp)

    def test_route_clock_gate_fails_even_if_evidence_rehashed(self):
        contract, dcp = self.contract_fixture()
        path = self.directory / "proof.json"
        proof = release.load(path); proof["clock_coverage"]["no_clock"] = False; save(path, proof)
        value = release.load(contract); value["evidence"]["routed_proof"]["sha256"] = release.sha(path); save(contract, value)
        with self.assertRaises(ValueError): release.validate(contract, dcp)

    def test_rx_stop_requires_actual_truth_and_exact_clocks(self):
        row = release.cdc_inventory(RX_REPORT)[0]
        facts = row["destination"]
        truth = "PASS_RXSTOP_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE"
        self.assertEqual(release.current_classification(row, facts, truth)[0], "held_payload_mailbox")
        with self.assertRaises(ValueError): release.current_classification(row, facts, "")
        row["destination_clock"] = "other"
        with self.assertRaises(ValueError): release.current_classification(row, facts, truth)

    def test_hidden_vendor_class_does_not_cover_native_or_critical(self):
        row = release.cdc_inventory(REPORT)[0]
        for key, value in (("severity", "Critical"), ("source", "visible/native/C"),
                           ("source_clock", "other"), ("clock_relationship", "Asynchronous")):
            changed = dict(row, **{key: value})
            with self.assertRaises(ValueError): release.current_classification(changed, "", "")


if __name__ == "__main__":
    unittest.main()
