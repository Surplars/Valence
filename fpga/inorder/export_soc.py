#!/usr/bin/env python3
"""Export an exact short-tested I1 pipeline profile; attribute-only RAM binding, explicit STA target."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def stamp(text, module, width, depth, style):
    declaration = rf"(?m)^  reg\s+\[{width-1}:0\]\s+Memory\[0:{depth-1}\];"
    if len(re.findall(rf"(?m)^module {re.escape(module)}\(", text)) != 1 or len(re.findall(declaration, text)) != 1:
        raise RuntimeError("exact CIRCT RAM leaf shape changed: " + module)
    # Attach to the actual array; parent hierarchy attributes do not propagate to nested leaves.
    attribute = "rom_style" if module == "storage_512x64" else "ram_style"
    return re.sub(declaration, lambda m: f'  (* {attribute} = "{style}" *)\n' + m.group(0), text, count=1)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--cdc-receipt", type=Path, help="Matching short xsim evidence for optional timing-cut transport")
    ap.add_argument("--pipeline", choices=("compact5", "balanced7", "fpga8"))
    ap.add_argument("--resume-package", type=Path,
                    help="resume reports only from an exact SV/XDC/source-matched synthesized F/D shell")
    ap.add_argument("--target-mhz", type=int, choices=(100, 200, 300),
                    help="STA constraint only; does not reconfigure UART/timer nominal timebase or qualify a board clock")
    args = ap.parse_args()
    receipt_path = args.receipt.resolve()
    receipt = json.loads(receipt_path.read_text())
    legacy = receipt["status"] == "PASS_I1_RV64IMAC_ROM_OPENSBI_S_SHORT_ONLY"
    batch = receipt["status"] == "PASS_PARAMETERIZED_5_7_8_STAGE_SHORT_ONLY"
    timing_cuts = receipt["status"] == "PASS_I1_PARAMETERIZED_FD_JTAG_TIMING_CUTS_SHORT_ONLY"
    fd = receipt["status"] == "PASS_I1_PARAMETERIZED_FD_JTAG_SHORT_ONLY" or timing_cuts
    if not legacy and not batch and not fd:
        ap.error("passing exact I1 IMAC or parameterized pipeline short acceptance required")
    if (batch or fd) and (not args.pipeline or args.target_mhz is None):
        ap.error("pipeline batch export requires explicit --pipeline and --target-mhz; never silently lower the target")
    if legacy and args.pipeline not in (None, "compact5"):
        ap.error("legacy receipt qualifies only compact5")
    profile = args.pipeline or "compact5"
    target_mhz = args.target_mhz if args.target_mhz is not None else 100
    if fd:
        if profile != "fpga8" or receipt["jtag_chain"] != 2:
            ap.error("this F/D+JTAG receipt qualifies only the selected fpga8 / USER2 combination")
        for gate in ("numerical-f", "numerical-fd", "compressed-fd", "fpga8-fd-corpus",
                     "fpga8-fd-context-memory", "f-only-corpus", "f-only-context-d-illegal",
                     "fd-jtag-download-context", "fd-jtag-crc-retry-context", "shell-user2",
                     "default-off-integer32", "default-off-integer64", "fd-scalar-privilege",
                     "fd-bare-stream", "fd-sv39-stream"):
            if gate not in receipt["checks"]:
                ap.error("missing F/D+JTAG qualification: " + gate)
        pipeline = receipt["pipeline"]
        flags = receipt["soc_flags"]
    elif batch:
        for gate in (profile + "-ca-cross-page", profile + "-ca-page-end", profile + "-privilege",
                     profile + "-bare-stream", profile + "-sv39-stream", "pmp-csr", "atomic32", "atomic64",
                     "route-registers", "route-memory", "bootrom", profile + "-integer64",
                     profile + "-O3-l1", profile + "-O3-l12"):
            if gate not in receipt["checks"]:
                ap.error("missing pipeline acceptance gate: " + gate)
        pipeline = receipt["profiles"][profile]
        flags = [*receipt["soc_flags"], "--pipeline=" + profile]
    else:
        pipeline = receipt["pipeline"]
        flags = receipt["flags"]
    for name, digest in receipt["source_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("source drift since short acceptance: " + name)
    for name, digest in receipt["artifact_sha256"].items():
        if sha(receipt_path.parent / name) != digest:
            ap.error("acceptance artifact drift: " + name)
    expected = {"--c", "--a", "--sv39", "--pmp=8", "--tlb=4", "--icache=2048", "--dcache=2048",
                "--predictor=128", "--dsp-tiled", "--early-memory-issue", "--overlap-write-lookup"}
    if batch:
        expected.add("--pipeline=" + profile)
    if fd:
        expected.update(("--pipeline=fpga8", "--f", "--d", "--soc-jtag"))
    if timing_cuts:
        expected.add("--timing-cuts")
        if receipt.get("execution_datapath") and receipt["execution_datapath"] != "DISABLED":
            for width in (32, 64):
                for enabled in (0, 1):
                    gate = "timing-ex-datapath-" + str(width) + "-" + str(enabled)
                    if gate not in receipt["checks"] or gate + "-negative" not in receipt["checks"]:
                        ap.error("missing independent EX datapath qualification: " + gate)
            if "default-off-no-m64" not in receipt["checks"]:
                ap.error("missing optional M/F/D hardware-off qualification")
        if receipt.get("instruction_pma") and receipt["instruction_pma"] != "DISABLED":
            for gate in ("timing-if-pma-4-aligned-1", "timing-if-pma-4-shifted-1",
                         "timing-if-pma-4-board-1", "timing-if-pma-2-aligned-1",
                         "timing-if-pma-8-aligned-1", "timing-if-pma-16-aligned-1",
                         "timing-if-pma-4-aligned-0", "timing-read-pma-cache-32-512",
                         "timing-read-pma-cache-64-512", "timing-read-pma-cache-64-0"):
                if gate not in receipt["checks"] or gate + "-negative" not in receipt["checks"]:
                    ap.error("missing instruction PMA qualification: " + gate)
        if receipt.get("fast_data_translation"):
            expected.add("--fast-data-translation")
            for gate in ("timing-data-auth-on", "timing-data-auth-off",
                         "timing-data-auth-on-negative", "timing-data-auth-off-negative",
                         "fd-auth-off-bare-stream", "fd-auth-off-sv39-stream"):
                if gate not in receipt["checks"]:
                    ap.error("missing paired fast data authorization qualification: " + gate)
        if receipt.get("overlap_data_retirement"):
            expected.add("--overlap-data-retirement")
            if receipt.get("read_only_data_retirement"):
                expected.add("--read-only-data-retirement")
            if not receipt.get("retirement_paired_performance"):
                ap.error("missing matched one-owner retirement performance comparison")
            for gate in ("timing-data-retirement-fast", "timing-data-retirement-slow",
                         "timing-data-retirement-fast-negative", "timing-data-retirement-slow-negative",
                         "fd-retirement-off-bare-stream", "fd-retirement-off-sv39-stream"):
                if gate not in receipt["checks"]:
                    ap.error("missing retirement overlap qualification: " + gate)
        for gate in ("timing-route-0", "timing-route-1", "timing-axi", "timing-O3-l1", "timing-O3-l12",
                     "timing-window-32", "timing-window-64", "timing-window-32-negative", "timing-window-64-negative",
                     "timing-late-recovery32", "timing-late-recovery64",
                     "timing-predictor-c", "timing-predictor-c-negative",
                     "timing-axi-capture", "timing-axi-capture-bad-id",
                     "timing-parcels-32", "timing-parcels-64", "fd-ca-cross-page", "fd-ca-page-end",
                     "timing-cache-32-512-0", "timing-cache-64-512-0",
                     "timing-cache-64-512-1", "timing-cache-64-0-0"):
            if gate not in receipt["checks"]:
                ap.error("missing timing-cut qualification: " + gate)
        if not args.cdc_receipt:
            ap.error("matching short double-clock xsim receipt required")
        cdc = json.loads(args.cdc_receipt.read_text())
        if cdc["status"] != "PASS_I1_HALF_CYCLE_CDC_XSIM_ONLY" or any(
                cdc["cases"].get(name) != "PASS_UNCHANGED_PROTOCOL_ORACLE" for name in
                ("dmi_cdc", "bscan_user", "bscan_qualification")):
            ap.error("missing passing I1 CDC protocol evidence")
        for name, digest in cdc["source_sha256"].items():
            if sha(ROOT / name.replace("\\", "/")) != digest:
                ap.error("CDC source drift: " + name)
        for name, digest in cdc["artifact_sha256"].items():
            if sha(args.cdc_receipt.parent / name.replace("\\", "/")) != digest:
                ap.error("CDC artifact drift: " + name)
    if set(flags) != expected or len(flags) != len(expected):
        ap.error("unexpected profile; explicitly review RAM shapes and GSIM/synthesis matching")
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh RTL directory required")
    output.mkdir(parents=True)
    firtool_identity = None
    with (output / "export.log").open("w") as log:
        entry = "inorder.FiveStageFpgaShellMain" if fd else "inorder.FiveStageSocRtlMain"
        extra = ["--soc-user-chain=2"] if fd else []
        subprocess.run(["mill", "-i", "OrbitalI1.test.runMain", entry,
                        str(output), "64", *flags, *extra], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
        if fd:
            # Re-elaborate and byte-check the actual qualified shell. The shared
            # arbiter's assertion uses a packed array; banning that SV syntax
            # makes firtool fail, whereas Vivado supports it. No DUT edit or
            # alternate untested front end is needed for this formatting choice.
            fir = output / "FiveStageFpgaShell.fir"
            if sha(fir) != receipt["artifact_sha256"]["shell-user2/FiveStageFpgaShell.fir"]:
                raise RuntimeError("physical shell CHIRRTL differs from qualification")
            firtool = Path.home() / ".cache/llvm-firtool/1.135.0/bin/firtool"
            version = subprocess.check_output([str(firtool), "--version"], text=True)
            if "CIRCT firtool-1.135.0" not in version:
                raise RuntimeError("pinned Chisel 7.3.0 firtool version required")
            firtool_identity = {"path": str(firtool), "sha256": sha(firtool), "version": version.strip(),
                                "lowering_options": "disallowLocalVariables",
                                "preserve_values": "named",
                                "shell_chirrtl_sha256": sha(fir)}
            subprocess.run([str(firtool), str(fir), "--split-verilog",
                            "--lowering-options=disallowLocalVariables", "--preserve-values=named", "-o", str(output)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    parent = (output / "SynchronousRegisterFile.sv").read_text()
    register_leaf = "mem_32x64" if fd else "bank_32x64"
    if len(re.findall(re.escape(register_leaf) + r"\s+bank(?:_1)?_ext\s*\(", parent)) != 2:
        raise RuntimeError("exact two RF bank bindings changed")
    raw = output / "raw-memory-leaves"
    raw.mkdir()
    annotations = {}
    memories = [(register_leaf, 64, 32, "block"),
                                       ("data_256x64", 64, 256, "block"),
                                       ("tags_32x53", 53, 32, "distributed"),
                                       ("entries_128x125", 125, 128, "distributed"),
                                       ("storage_512x64", 64, 512, "block")]
    if fd:
        fpr = (output / "SynchronousFloatingRegisterFile.sv").read_text()
        # CIRCT deduplicates the identical 32x64 leaf definition, not its
        # physical instances: two GPR replicas plus three FPR replicas remain.
        if len(re.findall(re.escape(register_leaf) + r"\s+fpBank(?:_[12])?_ext\s*\(", fpr)) != 3:
            raise RuntimeError("three synchronous FPR bank bindings changed")
    for module, width, depth, style in memories:
        leaf = output / (module + ".sv")
        original = leaf.read_text()
        shutil.copyfile(leaf, raw / leaf.name)
        leaf.write_text(stamp(original, module, width, depth, style))
        annotations[module] = {"style": style, "raw_sha256": sha(raw / leaf.name),
                               "stamped_sha256": sha(leaf), "change": "array attribute only, identical logic/latency"}
    rom_source = ROOT / "src/main/resources/inorder/bootrom.hex"
    shutil.copyfile(rom_source, output / "bootrom.hex")
    substitutions = 0
    for path in output.glob("*.sv"):
        text = path.read_text()
        count = text.count('"src/main/resources/inorder/bootrom.hex"')
        if count:
            text = text.replace('"src/main/resources/inorder/bootrom.hex"', '"bootrom.hex"')
            path.write_text(text)
            substitutions += count
    if substitutions != 1:
        raise RuntimeError("unexpected BootROM inline initialization binding")
    sv = "\n".join(p.read_text() for p in output.glob("*.sv"))
    if "io_romInitialize" in sv:
        raise RuntimeError("test-only ROM write port survived physical RTL export")
    for name in ("soc_ooc.xdc", "synth_soc.tcl"):
        shutil.copyfile(HERE / name, output / name)
    if fd:
        # Exact source-controlled USER2 event-clock/CDC gate; no blanket asynchronous clock groups.
        recipe = "bscan_timing_i1.tcl" if timing_cuts else "bscan_timing.tcl"
        shutil.copyfile(HERE / recipe, output / "bscan_timing.tcl")
        shutil.copyfile(ROOT / "fpga/next/check_jtag_chain.tcl", output / "check_jtag_chain.tcl")
        shutil.copyfile(HERE / "synth_fd_jtag.tcl", output / "synth_soc.tcl")
        if timing_cuts:
            synth = output / "synth_soc.tcl"
            synth.write_text(synth.read_text().replace("zu15eg-user2-tck50-positive-v1",
                             "zu15eg-user2-tck50-halfcycle-i1-v2"))
        names = (("ValenceI1BscanDebugPort.sv", "ValenceI1DmiCdc.sv") if timing_cuts else
                 ("ValenceBscanDebugPort.sv", "ValenceJtagDebugPort.sv"))
        for name in names:
            source = ROOT / ("src/main/resources/inorder" if timing_cuts else "src/main/resources/debug") / name
            target = output / name
            if target.exists():
                emitted = target.read_text().removeprefix("// Generated by CIRCT firtool-1.135.0\n")
                if emitted.rstrip("\n") != source.read_text().rstrip("\n"):
                    raise RuntimeError("exported BSCAN resource differs: " + name)
            # Retain the exact source bytes after verifying the only CIRCT
            # differences (banner and final newline), not alternative logic.
            shutil.copyfile(source, target)
    constraint = output / "soc_ooc.xdc"
    text = constraint.read_text()
    if text.count("-period 10.000 ") != 1:
        raise RuntimeError("STA clock template shape changed")
    text = text.replace("-period 10.000 ", "-period " + format(1000 / target_mhz, ".9f") + " ")
    text = text.replace("100 MHz estimate", str(target_mhz) + " MHz estimate")
    if fd:
        shell = (output / "FiveStageFpgaShell.sv").read_text()
        if len(re.findall(r"\binput\s+io_clockIn\b", shell)) != 1:
            raise RuntimeError("physical shell CPU clock port shape changed")
        text = text.replace("[get_ports clock]", "[get_ports io_clockIn]").replace("NAME != clock", "NAME != io_clockIn")
    constraint.write_text(text)
    reused_synthesis = None
    if args.resume_package:
        if not fd:
            ap.error("checkpoint report resume currently supports the qualified F/D shell only")
        previous = args.resume_package.resolve()
        previous_manifest = json.loads((previous / "manifest.json").read_text())
        for name, digest in previous_manifest["files_sha256"].items():
            if sha(previous / name) != digest:
                raise RuntimeError("previous frozen artifact drift: " + name)
        for key, value in (("source_sha256", receipt["source_sha256"]), ("flags", flags),
                           ("top", "FiveStageFpgaShell"), ("target_hz", target_mhz * 1000000)):
            if previous_manifest[key] != value:
                raise RuntimeError("checkpoint configuration/source mismatch: " + key)
        for path in output.glob("*"):
            if path.suffix in (".sv", ".xdc") or path.name == "bootrom.hex":
                if sha(path) != sha(previous / path.name):
                    raise RuntimeError("checkpoint synthesis input mismatch: " + path.name)
        if {p.name for p in output.glob("*.sv")} != {p.name for p in previous.glob("*.sv")}:
            raise RuntimeError("checkpoint module set mismatch")
        prior_log = previous / "vivado_synth.log"
        if "synth_design completed successfully" not in prior_log.read_text():
            raise RuntimeError("no completed synthesis in checkpoint provenance")
        checkpoint = previous / "reports/synthesized.dcp"
        shutil.copyfile(checkpoint, output / "reused_synthesized.dcp")
        provenance = output / "checkpoint-provenance"
        provenance.mkdir()
        shutil.copyfile(previous / "manifest.json", provenance / "manifest.json")
        shutil.copyfile(prior_log, provenance / "vivado_synth.log")
        reused_synthesis = {"package": str(previous), "checkpoint_sha256": sha(checkpoint),
                            "manifest_sha256": sha(previous / "manifest.json"), "log_sha256": sha(prior_log),
                            "gate": "EXACT_ALL_SV_XDC_ROM_CONFIG_SOURCE_IDENTITY_REPORTS_ONLY"}
    for name, digest in receipt["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("source changed while exporting RTL: " + name)
    exporter_files = [Path(__file__), HERE / "soc_ooc.xdc", HERE / "synth_soc.tcl"]
    if fd:
        exporter_files += [HERE / "synth_fd_jtag.tcl", HERE / ("bscan_timing_i1.tcl" if timing_cuts else "bscan_timing.tcl"),
                          ROOT / "fpga/next/check_jtag_chain.tcl"]
    manifest = {"status": "PASS_TESTED_I1_SOC_RTL_EXPORT_ONLY",
                "top": "FiveStageFpgaShell" if fd else "FiveStageSoc",
                "part": "xczu15eg-ffvb1156-2-i", "target_hz": target_mhz * 1000000,
                "hardware_nominal_timebase_hz": 100000000, "clock_constraint_is_not_clock_ip": True,
                "pipeline_profile": profile, "pipeline": pipeline, "flags": flags, "receipt": str(receipt_path),
                "jtag_chain": 2 if fd else None, "floating_enabled": fd,
                "cdc_receipt": ({"path": str(args.cdc_receipt.resolve()), "sha256": sha(args.cdc_receipt),
                                "scope": "pin-event/CDC short xsim, not UNISIM or board signoff"}
                                if timing_cuts else None),
                "firtool": firtool_identity,
                "reused_synthesis": reused_synthesis,
                "receipt_sha256": sha(receipt_path), "source_sha256": receipt["source_sha256"],
                "annotations": annotations, "rom_sha256": sha(rom_source),
                "synthesis_defines": ["ENABLE_INITIAL_MEM_"],
                "randomize_memory_or_registers": False,
                "simulation_difference": "test-only ROM writes under reset omitted; physical readmemh uses same hex",
                "synthesis_scope": ("I1 F/D SoC + shared USER2 transport, OOC; no MIG/board/clock IP qualification"
                                    if fd else "whole I1 SoC internal timing; no board/MIG/AXI CDC/Clock IP/JTAG PHY"),
                "linux_boot_qualified": False, "physical_qualified": False,
                "exporter_sha256": {str(p.relative_to(ROOT)): sha(p) for p in exporter_files},
                "files_sha256": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"status": manifest["status"], "output": str(output)}), flush=True)
if __name__ == "__main__":
    main()
