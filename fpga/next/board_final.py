#!/usr/bin/env python3
"""One reviewed CPU profile plus native MAC T1 and JTAG USER2.

Default: source/configuration preflight only. --emit uses the supported native
exporter. No FPGA tools run here; the staged Tcl consumer must be used explicitly.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "board-final-profile-v1.json"
MANIFEST_SHA256 = "4a3cdda058f99a660520bb1711992ac5354ef1662d81debd186b47281628bafe"
INPUTS = ("fpga/next/board_final.py", "fpga/next/board-final-profile-v1.json")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def exporter_module():
    spec = importlib.util.spec_from_file_location("final_board_export", HERE / "export.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def load_profile():
    if sha(MANIFEST) != MANIFEST_SHA256:
        raise RuntimeError("final board manifest changed; review required")
    profile = json.loads(MANIFEST.read_text())
    if profile["schema"] != "valence-board-final-profile-v1" or profile["status"] != "SOURCE_CONFIG_BOUND_NOT_PHYSICALLY_QUALIFIED":
        raise RuntimeError("final board profile is not selected and reviewed")
    cpu = profile["cpu_profile"]
    name = cpu["manifest"]
    if Path(name).name != name or not name.endswith(".json") or sha(HERE / name) != cpu["sha256"]:
        raise RuntimeError("qualified CPU manifest changed; review required")
    options = json.loads((HERE / name).read_text())["native_options"]
    required = {"--selected", "--experimental-trispeed-ethernet", "--experimental-jtag-bscan=2",
                "--shared-lane1-owner-match", "--shared-canonical-store-owner-match", "--local-payload-write-row", "--direct-rank1-memory-source-ids",
                "--direct-registered-execution-operands", "--local-payload-write-enable", "--data-translation-entries=16", "--lsu-entries=4",
                "--pending-virtual-store-proof-slots=2", "--pending-store-early-load-credits=2"}
    if len(options) != cpu["native_option_count"] or len(options) != 52 or len(set(options)) != len(options) or not required.issubset(options):
        raise RuntimeError("qualified CPU options/USER2/capacities changed")
    evidence = profile["qualification_receipt"]
    expected_path = "simulator/gsim/owner_row/evidence/public-receipt.json"
    if evidence["path"] != expected_path or sha(ROOT / expected_path) != evidence["sha256"]:
        raise RuntimeError("minimal qualification receipt changed")
    recorded = json.loads((ROOT / expected_path).read_text())
    if recorded["schema"] != "valence-owner-row-public-qualification-v1":
        raise RuntimeError("minimal qualification schema changed")
    if recorded["configuration"]["native_options"] != options or recorded["configuration"]["export_profile_sha256"] != profile["export_profile_sha256"]:
        raise RuntimeError("recorded qualified configuration changed")
    if recorded["recorded_qualification"]["cpu"]["inclusive_cycles"] != {"sv39": 191618, "bare": 194153} or recorded["recorded_qualification"]["physical_qualification"] is not False:
        raise RuntimeError("recorded qualification scope changed")
    exporter = exporter_module()
    qualified_sources = {name: value for name, value in exporter.sources().items() if name not in INPUTS}
    if digest(qualified_sources) != profile["export_sources_sha256"]:
        raise RuntimeError("final board reviewed export source closure changed")
    if profile["native_options"] != [*options, exporter.board_t1.FLAG] or profile["mode"] != exporter.board_t1.selection(True):
        raise RuntimeError("final board options/T1 mode changed")
    return profile


def check_receipt(receipt, profile, exporter, output):
    if receipt.get("status") != "PASS_RTL_EXPORT_ONLY" or receipt.get("synthesis") is not False or receipt.get("physical_qualification") is not False:
        raise RuntimeError("expected unqualified native export receipt")
    if digest(receipt["profile"]) != profile["export_profile_sha256"]:
        raise RuntimeError("final board complete configuration changed")
    command = receipt["command"]
    cpu_options = profile["native_options"][:-1]
    if command[:4] != ["mill", "-i", "IonSoC.test.runMain", "ooo.FpgaNextMain"] or len(command) < 5 or Path(command[4]).resolve() != output / "rtl" or sorted(command[5:]) != sorted(cpu_options):
        raise RuntimeError("final board native command changed")
    sources = receipt["source_sha256"]
    if sources != exporter.sources():
        raise RuntimeError("final board complete source inventory differs from current reviewed source")
    for name in (*INPUTS, "fpga/next/" + profile["cpu_profile"]["manifest"]):
        if sources.get(name) != sha(ROOT / name):
            raise RuntimeError("final board source binding mismatch: " + name)
    wrapper = receipt.get("board_wrapper", {})
    if wrapper.get("media") != "experimental-trispeed" or wrapper.get("additional_jtag_package_pins") != 0 or wrapper.get("qualified") is not False:
        raise RuntimeError("final board requires tri-speed and existing hard JTAG connector")


def check_staged_contracts(output, receipt, exporter):
    actual_rtl = {path.relative_to(output).as_posix(): sha(path)
                  for path in sorted((output / "rtl").rglob("*")) if path.is_file()}
    if actual_rtl != receipt["rtl_sha256"]:
        raise RuntimeError("final board complete RTL inventory changed")
    required_rtl = {"rtl/FpgaNextSocTop.sv", "rtl/ValenceJtagDebugPort.sv", "rtl/ValenceBscanDebugPort.sv"}
    if not required_rtl.issubset(actual_rtl):
        raise RuntimeError("final board required native top/USER2 RTL missing")
    filelist = output / "synthesis-files.f"
    if sha(filelist) != receipt["synthesis_filelist_sha256"]:
        raise RuntimeError("final board synthesis filelist changed")
    emitted_list = output / "rtl/filelist.f"
    listed = ([line.strip() for line in emitted_list.read_text().splitlines()
               if line.strip() and not line.strip().startswith("#")] if emitted_list.is_file() else [])
    if not listed:
        listed = ["FpgaNextSocTop.sv"]
    for name in ("ValenceJtagDebugPort.sv", "ValenceBscanDebugPort.sv"):
        if name not in listed:
            listed.append(name)
    expected_list = "".join("rtl/" + name + "\n" for name in listed)
    if filelist.read_text() != expected_list or any("rtl/" + name not in actual_rtl for name in listed):
        raise RuntimeError("final board synthesis filelist closure changed")
    mode = exporter.board_t1.verify(output)
    if mode["native_mac_local_pad_reset_release"] is not True:
        raise RuntimeError("final board requires explicit T1 ON")
    # Replay only the real source-staging helpers in scratch space. Exact bytes
    # and maps close both missing-entry and self-consistent rehash mutations.
    # No emitter, synthesis, or post-synthesis audit is invoked by these helpers.
    with tempfile.TemporaryDirectory(prefix="valence-final-contract-") as tmp:
        expected = Path(tmp)
        board = expected / "board"; board.mkdir()
        wrapper = exporter.bscan_board_wrapper((HERE / "soc_top_fpga_next_ddr.sv").read_text())
        (board / "soc_top_fpga_next_ddr.sv").write_text(wrapper)
        summaries = {
            "tri_speed_native_integration": exporter.media_integration.stage(ROOT, expected),
            "native_mac_mode": exporter.board_t1.stage(ROOT, expected, True),
            "bscan_timing_candidate": exporter.bscan_integration.stage(ROOT, expected, 2),
        }
        for key, value in summaries.items():
            if receipt[key] != value:
                raise RuntimeError("final board source/staging contract changed: " + key)
        for path in sorted(expected.rglob("*")):
            if path.is_file():
                name = path.relative_to(expected)
                if not (output / name).is_file() or sha(output / name) != sha(path):
                    raise RuntimeError("final board staged artifact differs from reviewed source: " + name.as_posix())
    gate = receipt["required_post_synthesis_gate"]
    expected_gate = ("# Mandatory read-only post-synthesis gate; exact cell required.\n"
        "source [file join [file dirname [info script]] check_jtag_chain.tcl]\n"
        "if {![info exists VALENCE_JTAG_OWN_CELL]} {error {Set exact VALENCE_JTAG_OWN_CELL from the open synthesized design}}\n"
        "valence_assert_jtag_chain 2 $VALENCE_JTAG_OWN_CELL\n")
    if gate["path"] != "board/require_jtag_chain.tcl" or sha(output / gate["path"]) != gate["sha256"] or (output / gate["path"]).read_text() != expected_gate or gate["status"] != "NOT_RUN_NO_VIVADO" or gate["must_pass_before_implementation_or_bitstream"] is not True:
        raise RuntimeError("final board requires exact unexecuted USER2 gate")
    if sha(output / "board/check_jtag_chain.tcl") != gate["guard_sha256"] or gate["guard_sha256"] != receipt["source_sha256"]["fpga/next/check_jtag_chain.tcl"]:
        raise RuntimeError("final board USER2 guard mismatch")


def binding(profile):
    return {"schema": "valence-board-final-export-binding-v1",
            "status": "STAGED_REQUIRES_EXPLICIT_CONSUMER", "manifest_sha256": MANIFEST_SHA256,
            "cpu_profile": profile["cpu_profile"], "export_profile_sha256": profile["export_profile_sha256"],
            "export_sources_sha256": profile["export_sources_sha256"],
            "native_options": profile["native_options"], "mode": profile["mode"],
            "synthesis_entry": "valence_native_mac_synth_design",
            "synthesis_consumer_executed": False, "physical_qualification": False}


def verify(output):
    profile = load_profile()
    receipt = json.loads((output / "receipt.json").read_text())
    exporter = exporter_module()
    check_receipt(receipt, profile, exporter, output)
    check_staged_contracts(output, receipt, exporter)
    summary = receipt["final_board_profile"]
    if summary["path"] != "board/final-board-profile.json" or sha(output / summary["path"]) != summary["sha256"]:
        raise RuntimeError("final board binding hash mismatch")
    if json.loads((output / summary["path"]).read_text()) != binding(profile):
        raise RuntimeError("final board staged profile binding changed")
    return {"status": "PASS_FINAL_BOARD_EXPORT_BINDING_ONLY", "cpu_profile": profile["cpu_profile"],
            "mode": profile["mode"], "synthesis_consumer_executed": False,
            "mapped_topology_checked": False, "physical_qualification": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--verify-export", type=Path)
    args = parser.parse_args(argv)
    if args.verify_export is not None:
        if args.output is not None or args.emit:
            parser.error("--verify-export excludes --output and --emit")
        print(json.dumps(verify(args.verify_export.resolve()), indent=2))
        return
    if args.output is None:
        parser.error("--output is required")
    profile = load_profile()
    exporter = exporter_module()
    options = ["--output", str(args.output), *(x for x in profile["native_options"] if x != "--selected")]
    if args.emit:
        options.append("--emit")
    exporter.main(options, expected_profile_sha256=profile["export_profile_sha256"])
    if args.emit:
        output = args.output.resolve()
        receipt_path = output / "receipt.json"
        receipt = json.loads(receipt_path.read_text())
        try:
            check_receipt(receipt, profile, exporter, output)
            check_staged_contracts(output, receipt, exporter)
            path = output / "board/final-board-profile.json"
            path.write_text(json.dumps(binding(profile), indent=2) + "\n")
            receipt["final_board_profile"] = {"path": "board/final-board-profile.json", "sha256": sha(path)}
        except BaseException as error:
            receipt["status"] = "FAIL"
            receipt["error"] = str(error)
            raise
        finally:
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(verify(output), indent=2))


if __name__ == "__main__":
    main()
