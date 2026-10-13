#!/usr/bin/env python3
"""Explicit native MAC reset-mode contract; no elaboration or FPGA tool execution."""
import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLAG = "--native-mac-local-pad-reset-release"
SELECTED_FLAG = "--native-mac-register-selected-half"
SELECTED_PARAMETER = "NATIVE_MAC_REGISTER_SELECTED_HALF"
AUDIT = "native_mac_roles.tcl"
SESSION = "native_mac_session.tcl"
TOP = "soc_top_fpga_next_ddr"
PARAMETER = "NATIVE_MAC_LOCAL_PAD_RESET_RELEASE"
ABC_PROFILE = "timing-batch-abc-profile.json"
ABC_SHA256 = "e6f7c763591b71610f361030e2db67a1efb25fce40029a6d2e9a6bd3e5d79748"
INPUTS = ("fpga/next/board_t1.py", "fpga/next/board-t1-profile-v1.json", "fpga/next/" + ABC_PROFILE, "fpga/next/" + AUDIT, "fpga/next/" + SESSION, "fpga/next/export.py")
PRODUCTION = ("fpga/next/soc_top_fpga_next_ddr.sv", "fpga/zu15eg/native_rgmii_trispeed_quarter.sv",
              "fpga/zu15eg/trispeed_quarter_constraints.tcl")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selection(enabled, selected_half=False):
    if type(enabled) is not bool or type(selected_half) is not bool:
        raise ValueError("native MAC mode must be an explicit Boolean")
    return {"native_mac_local_pad_reset_release": enabled, "native_mac_register_selected_half": selected_half, "top": TOP,
            "generics": {PARAMETER: int(enabled), SELECTED_PARAMETER: int(selected_half)}, "applied_to_synthesized_design": False,
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
    legacy = selection(True)
    del legacy["native_mac_register_selected_half"]
    del legacy["generics"][SELECTED_PARAMETER]
    if profile["base_manifest"] != ABC_PROFILE or profile["base_manifest_sha256"] != ABC_SHA256 or \
            profile["native_options"] != [*native, FLAG] or profile["mode"] != legacy:
        raise RuntimeError("explicit T1 board profile changed; review required")
    return profile


def consumer_tcl(enabled, selected_half=False, control_lemma=False, source_files=()):
    values = f"{PARAMETER}={int(enabled)} {SELECTED_PARAMETER}={int(selected_half)}"
    reads = "\n".join('    read_verilog -sv [file join [file dirname $::valence_native_mac_mode::directory] "' +
                      name.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('[', '\\[').replace(']', '\\]') + '"]' for name in source_files)
    return f'''# Sourcing is preparation only. Actual synthesis and checkpoint collection are explicit.
namespace eval valence_native_mac_mode {{
    variable consumed
    variable optimized
    if {{![info exists consumed]}} {{set consumed 0}}
    if {{![info exists optimized]}} {{set optimized 0}}
}}
source [file join [file dirname [info script]] {SESSION}]
valence_mac_session::bind [file dirname [info script]] [list {int(enabled)} {int(selected_half)}]
namespace eval valence_native_mac_mode {{
    variable directory [file normalize [file dirname [info script]]]
    variable t1 {int(enabled)}
    variable selected {int(selected_half)}
    variable control_lemma {int(control_lemma)}
}}
proc valence_native_mac_configure_python {{mode selection {{command {{wsl.exe}}}} {{stderrDirectory {{}}}}}} {{
    return [valence_mac_session::configure $mode $selection $command $stderrDirectory]
}}
proc valence_native_mac_verify_export {{}} {{
    return [valence_mac_session::identity]
}}
proc valence_native_mac_synth_design {{args}} {{
    foreach option $args {{
        if {{$option in {{-t -to -g -ge}} || [string match -top* $option] || [string match -gen* $option]}} {{
            error {{The bound native MAC contract owns -top and -generic}}
        }}
    }}
    valence_mac_session::invalidate begin_synthesis enter
    valence_mac_session::watch
    set identity [valence_native_mac_verify_export]
{reads}
    set invocation [list -top {TOP} -generic [list {values}] {{*}}$args]
    synth_design {{*}}$invocation
    valence_mac_session::seal $identity $invocation synth
}}
proc valence_native_mac_opt_design {{args}} {{
    set prior [valence_mac_session::assert]
    valence_mac_session::invalidate begin_optimization enter
    opt_design {{*}}$args
    if {{[dict get $prior design] ne [valence_mac_session::design]}} {{error {{Optimization replaced the consumed design}}}}
    valence_mac_session::seal [dict get $prior identity] [dict get $prior invocation] postopt
}}
proc valence_native_mac_assert_mode {{{{instance u_rgmii}}}} {{
    valence_native_mac_verify_export
    source [file join $::valence_native_mac_mode::directory {AUDIT}]
    return [valence_mac_roles::audit $instance {int(enabled)} {int(selected_half)}]
}}
proc valence_native_mac_checkpoint {{stage path}} {{
    if {{$stage ni {{synth postopt}}}} {{error {{Explicit synth/postopt stage is required}}}}
    set consumed [valence_mac_session::assert $stage]
    if {{[file exists $path] || [file exists $path.mac.tsv] || [file exists $path.mac.json]}} {{error {{Use a fresh checkpoint path}}}}
    set report [valence_native_mac_assert_mode]
    valence_mac_session::assert $stage
    write_checkpoint $path
    set f [open $path.mac.tsv {{WRONLY CREAT EXCL}}]
    foreach {{key value}} [list schema valence-native-mac-consumer-v2 actual_synthesis_executed 1 \
        stage $stage top {TOP} t1 {int(enabled)} selected_half {int(selected_half)} \
        invocation [dict get $consumed invocation] export_session_identity [dict get $consumed identity] \
        session_generation [dict get $consumed generation] tool [version -short] \
        part [get_property PART [current_design]] audit $report] {{
        puts $f "$key\t[binary encode hex [encoding convertto utf-8 $value]]"
    }}
    close $f
    valence_mac_session::python --seal-consumer [list [file dirname $::valence_native_mac_mode::directory] $path]
}}

'''


def stage(root, output, enabled, selected_half=False):
    contract = selection(enabled, selected_half)
    board = output / "board"
    wrapper = board / (TOP + ".sv")
    text = wrapper.read_text()
    if text.count("parameter " + PARAMETER + " = 0") != 1 or text.count(
            ".LOCAL_PAD_RESET_RELEASE(" + PARAMETER + ")") != 1:
        raise RuntimeError("native MAC top default/parameter forwarding changed")
    if text.count("parameter " + SELECTED_PARAMETER + " = 0") != 1 or text.count(
            ".REGISTER_SELECTED_HALF(" + SELECTED_PARAMETER + ")") != 1:
        raise RuntimeError("selected-half top default/parameter forwarding changed")
    shutil.copy2(root/"fpga/next"/AUDIT, board/AUDIT)
    shutil.copy2(root/"fpga/next"/SESSION, board/SESSION)
    shutil.copy2(root/"fpga/next/board_t1.py", board/"native_mac_contract.py")
    script = board / "native-mac-mode.tcl"
    lemma = source_control_lemma(output)
    source_files = synthesis_sources(output)
    script.write_text(consumer_tcl(enabled, selected_half, lemma["proved"], source_files))
    names = ("board/" + TOP + ".sv", "board/native_rgmii_trispeed_quarter.sv",
             "board/trispeed_quarter_constraints.tcl", "board/native-mac-mode.tcl",
             "board/" + AUDIT, "board/" + SESSION, "board/native_mac_contract.py", "synthesis-files.f", "board-synthesis-files.f")
    contract.update(schema="valence-native-mac-mode-v2", status="STAGED_REQUIRES_EXPLICIT_CONSUMER",
                    files={name: sha(output/name) for name in names},
                    source_sha256={name: sha(root/name) for name in (*INPUTS, *PRODUCTION)},
                    control_equivalence=lemma,
                    synthesis_sources=source_files,
                    source_file_lists=["synthesis-files.f", "board-synthesis-files.f"],
                    requested_physical_profile="t1-%d-selected-half-%d" % (enabled, selected_half),
                    semantic_contract="selected-half-v1" if selected_half else "phase-select-v1",
                    synthesis_entry="valence_native_mac_synth_design",
                    readonly_post_synthesis_audit="valence_native_mac_assert_mode u_rgmii")
    path = board / "native-mac-mode.json"
    path.write_text(json.dumps(contract, indent=2) + "\n")
    return {"path": "board/native-mac-mode.json", "sha256": sha(path), **selection(enabled, selected_half)}


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
    if contract.get("schema") != "valence-native-mac-mode-v2" or contract.get("status") != "STAGED_REQUIRES_EXPLICIT_CONSUMER":
        raise RuntimeError("unexpected mode manifest schema/status")
    expected = selection(contract["native_mac_local_pad_reset_release"], contract["native_mac_register_selected_half"])
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
                "board/trispeed_quarter_constraints.tcl", "board/native-mac-mode.tcl",
                "board/" + AUDIT, "board/" + SESSION, "board/native_mac_contract.py", "synthesis-files.f", "board-synthesis-files.f"}
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
    if (output/"board/native-mac-mode.tcl").read_text() != consumer_tcl(expected["native_mac_local_pad_reset_release"], expected["native_mac_register_selected_half"], contract["control_equivalence"]["proved"], synthesis_sources(output)):
        raise RuntimeError("mode consumer differs from reviewed forwarding")
    media = receipt["tri_speed_native_integration"]
    media_path = output/media["manifest"]
    if sha(media_path) != media["sha256"]:
        raise RuntimeError("media source closure manifest changed")
    artifacts = json.loads(media_path.read_text())["artifacts_sha256"]
    for name, digest in artifacts.items():
        if sha(output/name) != digest:
            raise RuntimeError("media source closure changed: " + name)
    bound_sources = {**artifacts, **receipt["rtl_sha256"]}
    for name in synthesis_sources(output):
        if name not in bound_sources or sha(output/name) != bound_sources[name]:
            raise RuntimeError("actual synthesis source is unbound/changed: " + name)
    if contract["synthesis_sources"] != synthesis_sources(output):
        raise RuntimeError("synthesis source list mismatch")
    if contract["control_equivalence"] != source_control_lemma(output):
        raise RuntimeError("fresh source control lemma mismatch")
    if contract["semantic_contract"] != ("selected-half-v1" if expected["native_mac_register_selected_half"] else "phase-select-v1"):
        raise RuntimeError("mode semantic contract mismatch")
    for name, digest in receipt["rtl_sha256"].items():
        if sha(output/name) != digest:
            raise RuntimeError("RTL artifact changed: " + name)
    if sha(output/"synthesis-files.f") != receipt["synthesis_filelist_sha256"]:
        raise RuntimeError("synthesis file-list binding mismatch")
    if sha(output/"board"/SESSION) != contract["source_sha256"]["fpga/next/"+SESSION]:
        raise RuntimeError("staged session helper differs from bound source")
    if sha(output/"board/native_mac_contract.py") != contract["source_sha256"]["fpga/next/board_t1.py"] or sha(output/"board"/AUDIT) != contract["source_sha256"]["fpga/next/"+AUDIT]:
        raise RuntimeError("staged verifier/audit differs from bound source")
    return {"status": "PASS_EXPORTED_MODE_BINDING_ONLY", **expected,
            "synthesis_consumer_executed": False, "mapped_topology_checked": False}


def synthesis_sources(output):
    names = []
    for filename in ("synthesis-files.f", "board-synthesis-files.f"):
        for name in (output/filename).read_text().splitlines():
            if not name or name.startswith("#"):
                continue
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or any(x in name for x in "\r\n\x00") or not (output/path).is_file():
                raise RuntimeError("unsafe/missing bound synthesis source: " + name)
            if name in names:
                raise RuntimeError("duplicate bound synthesis source: " + name)
            names.append(name)
    return names


def source_control_lemma(output):
    """A byte-exact reviewed source lemma, freshly matched to this export.

    The complete lowered encoder/parent are admitted, never a port excerpt or
    old checkpoint certificate. Unknown lowered forms get no merge permission.
    These hashes describe source only; the mapped chain is proved separately.
    """
    required = {"rtl/TriSpeedRgmiiTx.sv": "6374714496e0b23b174ac542027eefc59370c13cd5a0eb85de9af58e77af79a7",
                "rtl/TriSpeedManagedGmac.sv": "4d1f5c7f520f1cff5fe2a45bc510a9d269448f7e9e285450c2c8936cc7bf043e",
                "board/native_rgmii_trispeed_quarter.sv": "32b96761f2019806b6e03d9d885595449d2b057a30b6bb9ca204a34162ce96fc"}
    actual = {name: sha(output/name) for name in required if (output/name).is_file()}
    proved = actual == required
    # In the complete admitted encoder, both control D bits are the same
    # automatic scalar enable, with the same positive clock, reset and zero
    # state. The physical adapter has reset low=high=0. Given equal encoder
    # controls and low=high, enumerate every reset/phase/source/prior state.
    vectors = 0
    if proved:
        for reset in (0, 1):
            for phase in (0, 1):
                for source in (0, 1):
                    for prior in (0, 1):
                        low = 0 if reset else (prior if phase else source)
                        high = 0 if reset else (prior if phase else source)
                        if low != high:
                            raise RuntimeError("selected control reset/alias induction failed")
                        vectors += 1
    return {"schema": "valence-selected-control-source-lemma-v1", "proved": proved,
            "status": "PROVED_SOURCE_EQUALITY_ONLY" if proved else "UNKNOWN_SOURCE_NO_DEAD_FALL_PERMISSION",
            "source_sha256": actual, "reset_phase_induction_vectors": vectors,
            "claim": "equal_encoder_controls_imply_equal_selected_control_states",
            "mapped_chain_checked": False, "physical_qualification": False}


def session_identity(output):
    output = output.resolve()
    verify(output)
    binding = {name: sha(output/name) for name in ("receipt.json", "board/native-mac-mode.json", "synthesis-files.f", "board-synthesis-files.f")}
    return hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()


def consumer_receipt(output, checkpoint, *, seal=False):
    """Bind same-session command/audit observations; never infer provenance from a DCP name."""
    output, checkpoint = output.resolve(), checkpoint.resolve()
    mode = verify(output)
    fields = {}
    for line in Path(str(checkpoint)+".mac.tsv").read_text().splitlines():
        key, encoded = line.split("\t")
        if key in fields:
            raise RuntimeError("duplicate consumer field")
        fields[key] = bytes.fromhex(encoded).decode("utf-8")
    expected = {"schema": "valence-native-mac-consumer-v2", "actual_synthesis_executed": "1",
                "top": TOP, "t1": str(mode["generics"][PARAMETER]),
                "selected_half": str(mode["generics"][SELECTED_PARAMETER])}
    if any(fields.get(k) != v for k, v in expected.items()) or fields.get("stage") not in ("synth", "postopt"):
        raise RuntimeError("actual consumer mode/stage mismatch")
    if fields.get("export_session_identity") != session_identity(output) or not fields.get("session_generation", "").isdigit():
        raise RuntimeError("consumer was not sealed to this export session")
    generics = " ".join(f"{k}={v}" for k, v in mode["generics"].items())
    prefix = f"-top {TOP} -generic {{{generics}}}"
    if not (fields.get("invocation", "") == prefix or fields.get("invocation", "").startswith(prefix+" ")) or any(x in ("-t", "-to", "-g", "-ge") or x.startswith(("-top", "-gen")) for x in fields["invocation"][len(prefix):].split()):
        raise RuntimeError("actual synth invocation does not own the exact two generics")
    marker = "PASS_MAC_ROLE_SEMANTICS t1=%s selected_half=%s" % (fields["t1"], fields["selected_half"])
    if not fields.get("tool") or not fields.get("part") or not fields.get("audit", "").startswith(marker):
        raise RuntimeError("missing tool/part/new mapped semantic audit")
    report = {**fields, "status": "PASS_SOURCE_BOUND_MAPPED_ROLES_NOT_TIMING_QUALIFICATION",
              "checkpoint_sha256": sha(checkpoint), "export_receipt_sha256": sha(output/"receipt.json"),
              "mode_manifest_sha256": sha(output/"board/native-mac-mode.json"),
              "synthesis_filelist_sha256": sha(output/"synthesis-files.f"),
              "board_filelist_sha256": sha(output/"board-synthesis-files.f"),
              "observation_sha256": sha(Path(str(checkpoint)+".mac.tsv")),
              "physical_qualification": False}
    path = Path(str(checkpoint)+".mac.json")
    if seal:
        with path.open("x") as stream:
            stream.write(json.dumps(report, indent=2)+"\n")
    elif json.loads(path.read_text()) != report:
        raise RuntimeError("sealed consumer/checkpoint/export changed")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--verify-export", type=Path)
    parser.add_argument("--session-identity", type=Path)
    parser.add_argument("--seal-consumer", type=Path, nargs=2, metavar=("EXPORT", "CHECKPOINT"))
    parser.add_argument("--verify-consumer", type=Path, nargs=2, metavar=("EXPORT", "CHECKPOINT"))
    args = parser.parse_args(argv)
    if args.session_identity is not None:
        if args.output is not None or args.emit or args.verify_export or args.seal_consumer or args.verify_consumer:
            parser.error("session identity is exclusive")
        print(session_identity(args.session_identity))
        return
    if args.seal_consumer or args.verify_consumer:
        if args.output is not None or args.emit or args.verify_export or (args.seal_consumer and args.verify_consumer):
            parser.error("consumer verification is exclusive")
        paths = args.seal_consumer or args.verify_consumer
        print(json.dumps(consumer_receipt(*paths, seal=bool(args.seal_consumer)), indent=2))
        return
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
