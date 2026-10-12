#!/usr/bin/env python3
"""Explicit native MAC reset-mode contract; no elaboration or FPGA tool execution."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLAG = "--native-mac-local-pad-reset-release"
TOP = "soc_top_fpga_next_ddr"
PARAMETER = "NATIVE_MAC_LOCAL_PAD_RESET_RELEASE"
ABC_PROFILE = "timing-batch-abc-profile.json"
ABC_SHA256 = "e6f7c763591b71610f361030e2db67a1efb25fce40029a6d2e9a6bd3e5d79748"
INPUTS = ("fpga/next/board_t1.py", "fpga/next/board-t1-profile-v1.json", "fpga/next/" + ABC_PROFILE)
PRODUCTION = ("fpga/next/soc_top_fpga_next_ddr.sv", "fpga/zu15eg/native_rgmii_trispeed_quarter.sv",
              "fpga/zu15eg/trispeed_quarter_constraints.tcl")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selection(enabled):
    if type(enabled) is not bool:
        raise ValueError("native MAC mode must be an explicit Boolean")
    return {"native_mac_local_pad_reset_release": enabled, "top": TOP,
            "generics": {PARAMETER: int(enabled)}, "applied_to_synthesized_design": False,
            "requires_explicit_synthesis_consumer": True, "physical_qualification": False}


def load_profile():
    base = HERE/ABC_PROFILE
    if sha(base) != ABC_SHA256:
        raise RuntimeError("published ABC manifest changed; review required")
    native = json.loads(base.read_text())["native_options"]
    required = {"--selected", "--experimental-trispeed-ethernet", "--experimental-jtag-bscan=2",
                "--registered-pending-store-query", "--registered-canonical-store-event",
                "--aligned-fetch-permission-stage", "--pending-virtual-store-proof-slots=2",
                "--pending-store-early-load-credits=2", "--tagged-store-returns"}
    if len(native) != 46 or len(set(native)) != 46 or not required.issubset(native):
        raise RuntimeError("published ABC options/USER2/proof capacity changed")
    profile = json.loads((HERE/"board-t1-profile-v1.json").read_text())
    if profile["base_manifest"] != ABC_PROFILE or profile["base_manifest_sha256"] != ABC_SHA256 or \
            profile["native_options"] != [*native, FLAG] or profile["mode"] != selection(True):
        raise RuntimeError("explicit T1 board profile changed; review required")
    return profile


def consumer_tcl(enabled):
    mode = int(enabled)
    return f'''# Generated mode contract. Sourcing this file does not synthesize or alter a design.
# A caller must explicitly use the synthesis entry and then the read-only audit.
namespace eval valence_native_mac_mode {{
    variable directory [file dirname [info script]]
}}
proc valence_native_mac_synth_design {{args}} {{
    foreach option $args {{
        if {{$option in {{-t -to -g -ge}} || [string match -top* $option] || [string match -gen* $option]}} {{
            error {{The bound native MAC contract owns -top and -generic}}
        }}
    }}
    synth_design -top {TOP} -generic {PARAMETER}={mode} {{*}}$args
}}
proc valence_native_mac_assert_mode {{{{instance u_rgmii}}}} {{
    source [file join $::valence_native_mac_mode::directory trispeed_quarter_constraints.tcl]
    valence_trispeed_quarter_audit $instance {mode}
}}
'''


def stage(root, output, enabled):
    contract = selection(enabled)
    board = output / "board"
    wrapper = board / (TOP + ".sv")
    text = wrapper.read_text()
    if text.count("parameter " + PARAMETER + " = 0") != 1 or text.count(
            ".LOCAL_PAD_RESET_RELEASE(" + PARAMETER + ")") != 1:
        raise RuntimeError("native MAC top default/parameter forwarding changed")
    script = board / "native-mac-mode.tcl"
    script.write_text(consumer_tcl(enabled))
    names = ("board/" + TOP + ".sv", "board/native_rgmii_trispeed_quarter.sv",
             "board/trispeed_quarter_constraints.tcl", "board/native-mac-mode.tcl")
    contract.update(schema="valence-native-mac-mode-v1", status="STAGED_REQUIRES_EXPLICIT_CONSUMER",
                    files={name: sha(output/name) for name in names},
                    source_sha256={name: sha(root/name) for name in (*INPUTS, *PRODUCTION)},
                    synthesis_entry="valence_native_mac_synth_design",
                    readonly_post_synthesis_audit="valence_native_mac_assert_mode u_rgmii")
    path = board / "native-mac-mode.json"
    path.write_text(json.dumps(contract, indent=2) + "\n")
    return {"path": "board/native-mac-mode.json", "sha256": sha(path), **selection(enabled)}


def verify(output):
    """Check an export's recorded choice and staged bytes; never claim it was consumed."""
    receipt = json.loads((output/"receipt.json").read_text())
    summary = receipt["native_mac_mode"]
    if summary["path"] != "board/native-mac-mode.json":
        raise RuntimeError("unexpected mode contract path")
    path = output/summary["path"]
    if sha(path) != summary["sha256"]:
        raise RuntimeError("mode manifest hash mismatch")
    contract = json.loads(path.read_text())
    if contract.get("schema") != "valence-native-mac-mode-v1" or contract.get("status") != "STAGED_REQUIRES_EXPLICIT_CONSUMER":
        raise RuntimeError("unexpected mode manifest schema/status")
    expected = selection(contract["native_mac_local_pad_reset_release"])
    for key, value in expected.items():
        if json.dumps(contract.get(key), sort_keys=True) != json.dumps(value, sort_keys=True) or \
                json.dumps(summary.get(key), sort_keys=True) != json.dumps(value, sort_keys=True):
            raise RuntimeError("mode choice/top/generic mismatch: " + key)
    if receipt.get("status") != "PASS_RTL_EXPORT_ONLY":
        raise RuntimeError("expected completed native export receipt")
    if receipt.get("board_wrapper", {}).get("media") != "experimental-trispeed":
        raise RuntimeError("mode requires the matched tri-speed wrapper")
    wrapper = receipt["board_wrapper"]
    if wrapper.get("path") != "board/" + TOP + ".sv" or wrapper.get("source") != PRODUCTION[0] or \
            wrapper.get("sha256") != contract["files"].get(wrapper["path"]) or \
            wrapper.get("source_sha256") != contract["source_sha256"].get(PRODUCTION[0]):
        raise RuntimeError("mode wrapper receipt mismatch")
    required = {"board/" + TOP + ".sv", "board/native_rgmii_trispeed_quarter.sv",
                "board/trispeed_quarter_constraints.tcl", "board/native-mac-mode.tcl"}
    if set(contract["files"]) != required:
        raise RuntimeError("mode artifact closure changed")
    for name, digest in contract["files"].items():
        if sha(output/name) != digest:
            raise RuntimeError("mode artifact changed: " + name)
    for name in (*INPUTS, *PRODUCTION):
        if contract["source_sha256"].get(name) != receipt["source_sha256"].get(name):
            raise RuntimeError("mode source binding mismatch: " + name)
    for source in PRODUCTION[1:]:
        if contract["files"]["board/" + Path(source).name] != contract["source_sha256"][source]:
            raise RuntimeError("staged native source differs from bound source: " + source)
    if (output/"board/native-mac-mode.tcl").read_text() != consumer_tcl(expected["native_mac_local_pad_reset_release"]):
        raise RuntimeError("mode consumer differs from reviewed forwarding")
    return {"status": "PASS_EXPORTED_MODE_BINDING_ONLY", **expected,
            "synthesis_consumer_executed": False, "mapped_topology_checked": False}


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
    spec = importlib.util.spec_from_file_location("t1_export", HERE/"export.py")
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    options = ["--output", str(args.output), *(x for x in profile["native_options"] if x != "--selected")]
    if args.emit:
        options.append("--emit")
    exporter.main(options)


if __name__ == "__main__":
    main()
