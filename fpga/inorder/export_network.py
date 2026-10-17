#!/usr/bin/env python3
"""Export the exact short-tested32KiB TL-C network candidate; no synthesis or bit."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def parallel_instruction_bindings(cache_sources):
    """Bind actual per-way instances, not firtool's deduplicated leaf name."""
    bindings = {}
    expected = {(bank, way) for bank in range(8) for way in range(2)}
    pattern = re.compile(r"(?m)^\s*(\w+)\s+(dataWays_(\d+)_(\d+)_ext)\s*\(")
    for module, text in cache_sources.items():
        instances = pattern.findall(text)
        if not instances:
            continue
        if len(instances) != 16 or {(int(b), int(w)) for _, _, b, w in instances} != expected:
            raise RuntimeError("incomplete parallel instruction SRAM instance geometry: " + module)
        for leaf, instance, _, _ in instances:
            bindings.setdefault(leaf + ".sv", []).append({"module": module, "instance": instance})
    if not bindings:
        raise RuntimeError("parallel instruction SRAM instances missing")
    return bindings


def memory_style(name, width, depth, parallel_leaves):
    stem = Path(name).stem
    if width == 64 and ((depth == 512 and stem.startswith(("data", "storage"))) or
                       (depth == 256 and name in parallel_leaves)):
        return "block"
    if width == 64 and depth == 32 and stem.startswith(("mem", "bank")):
        return "block"
    if stem.startswith(("tagBanks", "directoryBanks", "entries_128")):
        return "distributed"
    return None


def user_stopped_diagnostic_scope(receipt, summary, reference, receipt_digest):
    """Explicit STA-only scope; never promote an interrupted receipt to PASS."""
    if receipt.get("status") != "FAIL" or "command failed (-15)" not in receipt.get("error", ""):
        raise ValueError("only the explicitly user-stopped run may use diagnostic export")
    if (summary.get("status") != "TARGET_CPU_CONFIGURATION_PASS_FULL_SUITE_USER_STOPPED" or
            summary.get("raw_receipt_sha256") != receipt_digest or
            summary.get("target_cpu_configuration_pass") is not True or
            summary.get("full_suite_pass") is not False or
            summary.get("completed_checks") != len(receipt["checks"])):
        raise ValueError("stopped-scope summary does not match the untouched raw receipt")
    if reference.get("status") != "PASS_I1_TLC_CPU_SHORT_ONLY_PHYSICAL_PENDING":
        raise ValueError("independent passing performance reference required")
    if receipt["cpu_flags"]["cpu-coherent"] != reference["cpu_flags"]["cpu-coherent"]:
        raise ValueError("diagnostic CPU flags differ from matched reference")
    target = [k for k in reference["checks"] if k.startswith("cpu-coherent")]
    if not target or any(receipt["checks"].get(k) != reference["checks"][k] for k in target):
        raise ValueError("all actual-CPU target gates must pass and exactly match the reference")
    if receipt["benchmarks"]["cpu-coherent"] != reference["benchmarks"]["cpu-coherent"]:
        raise ValueError("diagnostic target performance/trace/CRC/traffic mismatch")
    streams = [k for k in target if reference["checks"][k].startswith("I1_PRIVILEGED_STREAM_PASS ")]
    if len(streams) != 12:
        raise ValueError("twelve matched target Bare/Sv39 stream cohorts required")
    return {"scope": "USER_REQUESTED_DIAGNOSTIC_SYNTHESIS_ONLY",
            "raw_receipt_status": receipt["status"], "full_short_qualified": False,
            "completed_checks": len(receipt["checks"]),
            "planned_checks": summary["planned_checks"],
            "remaining_checks": summary["remaining_checks_not_completed"],
            "target_stream_cohorts_exact_match": len(streams),
            "target_benchmark_exact_match": True}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--cdc-receipt", required=True, type=Path)
    ap.add_argument("--managed-clock-receipt", required=True, type=Path)
    ap.add_argument("--user-stopped-diagnostic-summary", type=Path,
                    help="Explicit STA-only export of a user-stopped run; NEVER full short qualification")
    ap.add_argument("--diagnostic-performance-reference", type=Path)
    args = ap.parse_args()
    receipt = json.loads(args.receipt.read_text())
    diagnostic = None
    if args.user_stopped_diagnostic_summary:
        if not args.diagnostic_performance_reference:
            ap.error("diagnostic scope requires an independent passing performance reference")
        try:
            diagnostic = user_stopped_diagnostic_scope(
                receipt, json.loads(args.user_stopped_diagnostic_summary.read_text()),
                json.loads(args.diagnostic_performance_reference.read_text()), sha(args.receipt))
        except (ValueError, KeyError) as error:
            ap.error(str(error))
        diagnostic.update({
            "summary": str(args.user_stopped_diagnostic_summary.resolve()),
            "summary_sha256": sha(args.user_stopped_diagnostic_summary),
            "performance_reference": str(args.diagnostic_performance_reference.resolve()),
            "performance_reference_sha256": sha(args.diagnostic_performance_reference)})
    elif args.diagnostic_performance_reference:
        ap.error("diagnostic reference requires explicit user-stopped diagnostic summary")
    if ((not diagnostic and receipt["status"] != "PASS_I1_TLC_CPU_SHORT_ONLY_PHYSICAL_PENDING") or
            receipt["cache_bytes_each"] != 32768):
        ap.error("passing exact32KiB profile required")
    if not receipt.get("coherent_control_cuts"):
        ap.error("this profile requires explicitly qualified coherent control cuts")
    checks = receipt["checks"]
    required = [*("postmul-numerical-" + f for f in ("f", "fd")),
                "packet-dma-bounded-8k", "packet-dma-bounded-8k-negative",
                "packet-dma-bounded-2g", "packet-dma-bounded-2g-negative",
                "pmp-page-split-32", "pmp-page-split-64",
                "pmp-translation-data", "pmp-translation-instruction",
                "pair-cut-ways2-bytes32768", "network-shell"]
    required += ["cpu-coherent" + suffix for suffix in
                 ("-bare", "-sv39", "-64k-bare", "-64k-sv39",
                  "-precise-privilege", "-precise-privilege-negative",
                  "-ca", "-ca-negative", "-ca-page-end",
                  "-fd-corpus", "-fd-corpus-negative", "-fd-context")]
    required += ["device-frontend-" + mode + suffix for mode in ("direct", "cuts")
                 for suffix in ("", "-negative")]
    required += [model + suffix for model in ("cpu-coherent", "cpu-frozen-baseline")
                 for suffix in ("-coremark-o3", "-coremark-o3-negative", "-fetch-control")]
    revision = receipt.get("coherent_control_revision")
    if revision == "registered-id-class-prepared-native-payload-local-metadata":
        if not all(receipt.get(k) for k in
                   ("registered_id_serial_class", "prepared_native_requests", "local_cache_metadata")):
            ap.error("ID class/native payload/cache metadata qualification missing")
        required += ["serial-class", "serial-class-negative"]
        if "I1_SERIAL_CLASS_PASS cases=98304 compressed=65536 configs=7" not in checks.get("serial-class", ""):
            ap.error("independent full compressed/parameter-off serial class gate missing")
        for mode in ("default", "prepared"):
            name = "native-queue-" + mode
            required += [name + suffix for suffix in ("", "-negative", "-credit", "-credit-negative")]
            if "I1_PREPARED_QUEUE_PASS stimulus_cycles=20000 resets=11" not in checks.get(name, ""):
                ap.error("independent two-slot payload/credit/latency/reset gate missing")
        revision = "parallel-backend-capacity-owner-payload-free-translation-probe"
    if revision == "parallel-backend-capacity-owner-payload-free-translation-probe":
        if not receipt.get("parallel_backend_control"):
            ap.error("parallel backend control qualification missing")
        required += ["backend-control", "backend-control-negative",
                     "backend-control-owner", "backend-control-owner-negative"]
        for gate in ("backend-control", "backend-control-owner"):
            if "I1_BACKEND_CONTROL_PASS capacity_cases=128 owner_cases=512" not in checks.get(gate, ""):
                ap.error("missing independent backend capacity/closest owner proof")
        revision = "parallel-parcel-translation-disjoint-if-control"
    if revision == "parallel-parcel-translation-disjoint-if-control":
        if not receipt.get("parallel_instruction_candidates") or not receipt.get("disjoint_instruction_transitions"):
            ap.error("parallel parcel/IF-control qualification missing")
        required += ["if-candidates-" + window + suffix for window in ("aligned", "shifted", "board")
                     for suffix in ("", "-negative", "-pma", "-pma-negative")]
        for window in ("aligned", "shifted", "board"):
            if "I1_INSTRUCTION_CANDIDATES_PASS candidate_select_mask=3" not in checks.get(
                    "if-candidates-" + window, ""):
                ap.error("missing independent selected/unselected instruction candidate proof")
        # New front-end cuts are a strict superset of ALL previous RAM/Home/
        # DDR/PLIC/MMIO/numerical gates. Manifest retains the actual revision.
        revision = "parallel-instruction-ram-retained-home-context-prepared-ddr-payload"
    if revision in ("early-if-payload-existing-addr-branch-selection-parallel-mmio-dma-field-enables",
                    "local-completion-status-registered-mem-class-speculative-ex-local-dma-stop",
                    "split-if-authorization-retained-bypass-registered-probe-parallel-metadata",
                    "retained-victim-home-owner-indices-parallel-irq-raw-write-payload",
                    "parallel-instruction-ram-retained-home-context-prepared-ddr-payload"):
        required += ["peripheral-decode-" + mode + suffix
                     for mode in ("direct", "cuts", "cuts-disabled") for suffix in ("", "-negative")]
        required += ["peripheral-decode-" + mode + "-payload" + suffix
                     for mode in ("direct", "cuts") for suffix in ("", "-negative")]
        for name in ("packet-dma-bounded-8k", "packet-dma-bounded-2g"):
            if "ETHERNET_DMA_MMIO_DECODE_PASS" not in checks.get(name, ""):
                ap.error("missing full64 MMIO alias/size/mask descriptor-side-effect gate")
    if revision in ("local-completion-status-registered-mem-class-speculative-ex-local-dma-stop",
                    "split-if-authorization-retained-bypass-registered-probe-parallel-metadata",
                    "retained-victim-home-owner-indices-parallel-irq-raw-write-payload",
                    "parallel-instruction-ram-retained-home-context-prepared-ddr-payload"):
        # The generic postmul gate below requires each positive's negative.
        required += ["postmul-numerical-" + mode + "-completion" for mode in ("f", "fd")]
        required += ["mdu-local-completion-" + str(width) + suffix
                     for width in (32, 64) for suffix in ("", "-negative")]
        for mode in ("f", "fd"):
            if "local_completion_flush_separation=1" not in checks.get("postmul-numerical-" + mode, ""):
                ap.error("missing actual completed-owner/flush separation observation")
        for name in ("packet-dma-bounded-8k", "packet-dma-bounded-2g"):
            if "ETHERNET_DMA_LOCAL_STOP_PASS" not in checks.get(name, ""):
                ap.error("missing independent RX_STOP descriptor/alias/size/mask gate")
    if revision in ("split-if-authorization-retained-bypass-registered-probe-parallel-metadata",
                    "retained-victim-home-owner-indices-parallel-irq-raw-write-payload",
                    "parallel-instruction-ram-retained-home-context-prepared-ddr-payload"):
        required += ["coherent-if-pma-" + str(capacity) + suffix
                     for capacity in (256, 32768)
                     for suffix in ("", "-negative", "-hint", "-hint-negative")]
        for capacity in (256, 32768):
            if "hits32_cycles=33" not in checks.get("coherent-if-pma-" + str(capacity), ""):
                ap.error("missing true read-only coherent IF SRAM hit latency/II proof")
    if revision in ("retained-victim-home-owner-indices-parallel-irq-raw-write-payload",
                    "parallel-instruction-ram-retained-home-context-prepared-ddr-payload"):
        required += ["plic-irq-presence" + suffix for suffix in ("", "-negative", "-irq", "-irq-negative")]
        for name in ("plic-irq-presence", "plic-irq-presence-irq"):
            if "irq_sweep_masks=256 thresholds=8" not in checks.get(name, ""):
                ap.error("missing independent PLIC IRQ/claim/threshold/context sweep")
    if revision == "parallel-instruction-ram-retained-home-context-prepared-ddr-payload":
        if not receipt.get("parallel_instruction_way_reads") or not receipt.get("prepared_ddr_payload"):
            ap.error("selected parallel instruction RAM/prepared DDR profile missing")
        required += ["line-read-shared-flow-2-burst" + str(burst) + suffix
                     for burst in (8, 16)
                     for suffix in ("", "-negative", "-tags", "-tags-negative",
                                    "-rlast", "-rlast-negative", "-rid", "-rid-negative")]
    bandwidth = bool(receipt.get("coherent_bandwidth"))
    whole_line = bool(receipt.get("coherent_whole_line"))
    if whole_line:
        required += ["line-read-shared-2-burst" + str(burst) + suffix + negative
                     for burst in (8, 16) for suffix in ("", "-tags", "-rlast", "-rid")
                     for negative in ("", "-negative")]
        required += ["cpu-whole-line-off" + suffix for suffix in
                     ("-bare", "-sv39", "-64k-bare", "-64k-sv39",
                      "-coremark-o3", "-coremark-o3-negative", "-fetch-control")]
        if "I1_ADJACENT_METADATA_PASS" not in checks.get("pair-bandwidth-ways2-bytes32768-ordered", ""):
            ap.error("missing adjacent pending dirty/LRU handoff oracle")
    if bandwidth:
        required += ["device-frontend-compact", "device-frontend-compact-negative",
                     "pair-bandwidth-ways2-bytes32768-ordered",
                     "pair-bandwidth-ways2-bytes32768-ordered-ordinary-stream"]
        required += [model + "-64k-" + mode + "-latency" + str(delay)
                     for model in ("cpu-coherent", "cpu-frozen-baseline")
                     for mode in ("bare", "sv39") for delay in (40, 80)]
        if receipt.get("fast_data_translation"):
            required += ["pmp-translation-data-fast",
                         "cpu-structural-only-coremark-o3", "cpu-structural-only-fetch-control"]
    if diagnostic:
        deferred = [name for name in required if name == "network-shell" or name.startswith(
            ("cpu-whole-line-off", "cpu-structural-only", "cpu-frozen-baseline"))]
        diagnostic["deferred_formal_export_gates"] = sorted(set(deferred))
        diagnostic["fresh_network_elaboration_scope"] = "CHIRRTL_IDENTITY_ONLY_NOT_BEHAVIOR_OR_CDC"
        required = [name for name in required if name not in deferred]
    if any(name not in checks for name in required):
        ap.error("missing affected short gate")
    for name in required:
        if name.startswith(("postmul", "pmp-", "pair-")) and name + "-negative" not in checks:
            ap.error("missing independent negative control: " + name)
    for name, digest in receipt["source_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("source drift: " + name)
    for name, digest in receipt["artifact_sha256"].items():
        if sha(args.receipt.parent / name) != digest:
            ap.error("short artifact drift: " + name)
    cdc = json.loads(args.cdc_receipt.read_text())
    if cdc["status"] != "PASS_I1_HALF_CYCLE_CDC_XSIM_ONLY":
        ap.error("passing USER2 event/CDC evidence required")
    for name, digest in cdc["source_sha256"].items():
        if sha(ROOT / name.replace("\\", "/")) != digest:
            ap.error("USER2 source drift: " + name)
    for name, digest in cdc["artifact_sha256"].items():
        if sha(args.cdc_receipt.parent / name.replace("\\", "/")) != digest:
            ap.error("USER2 artifact drift: " + name)
    clocks = json.loads(args.managed_clock_receipt.read_text())
    if clocks["status"] != "PASS_I1_BALANCED_CLOCK_CDC_SHORT":
        ap.error("passing actual balanced BUFG/retention/mailbox short proof required")
    for name, digest in clocks["source_sha256"].items():
        if sha(ROOT / name.replace("\\", "/")) != digest:
            ap.error("managed-clock source drift: " + name)
    for name, digest in clocks["artifact_sha256"].items():
        if sha(args.managed_clock_receipt.parent / name.replace("\\", "/")) != digest:
            ap.error("managed-clock artifact drift: " + name)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cpu_flags = receipt["cpu_flags"]["cpu-coherent"]
    flags = [f for f in cpu_flags if f != "--soc-no-bootrom"] + [
        "--soc-network", "--soc-jtag", "--soc-user-chain=2"]
    with (output / "export.log").open("w") as log:
        if diagnostic:
            fresh = output / "network-elaboration-reference"
            subprocess.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.I1NetworkFpgaShellMain",
                            str(fresh), "64", *flags], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
            expected = sha(fresh / "I1NetworkFpgaShell.fir")
            diagnostic["fresh_network_fir_sha256"] = expected
        else:
            expected = receipt["artifact_sha256"]["network-elaboration/I1NetworkFpgaShell.fir"]
        subprocess.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.I1NetworkFpgaShellMain",
                        str(output), "64", *flags], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        fir = output / "I1NetworkFpgaShell.fir"
        if sha(fir) != expected:
            raise RuntimeError("network shell differs from exact qualified CHIRRTL")
        firtool = Path.home() / ".cache/llvm-firtool/1.135.0/bin/firtool"
        identity = subprocess.check_output([firtool, "--version"], text=True)
        if "CIRCT firtool-1.135.0" not in identity:
            raise RuntimeError("pinned firtool required")
        subprocess.run([firtool, fir, "--split-verilog", "--lowering-options=disallowLocalVariables",
                        "--preserve-values=named", "-o", output], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    raw = output / "raw-memory-leaves"
    raw.mkdir()
    annotations = {}
    parallel_bindings = parallel_instruction_bindings({
        path.name: path.read_text() for path in output.glob("I1CoherentLineCache*.sv")
    }) if receipt.get("parallel_instruction_way_reads") else {}
    array = re.compile(r"(?m)^([ \t]*)reg\s+\[(\d+):0\]\s+Memory\s*\[0:(\d+)\];")
    for path in output.glob("*.sv"):
        text = path.read_text()
        match = array.search(text)
        if not match:
            continue
        width, depth = int(match[2]) + 1, int(match[3]) + 1
        style = memory_style(path.name, width, depth, parallel_bindings)
        if style:
            if len(array.findall(text)) != 1:
                raise RuntimeError("unexpected multiple RAM arrays: " + path.name)
            shutil.copyfile(path, raw / path.name)
            attribute = "rom_style" if path.stem.startswith("storage") else "ram_style"
            text = array.sub(lambda m: m[1] + f'(* {attribute} = "{style}" *)\n' + m[0], text)
            path.write_text(text)
            annotations[path.name] = {"width": width, "depth": depth, "style": style,
                "raw_sha256": sha(raw / path.name), "stamped_sha256": sha(path),
                "change": "actual Memory array attribute only; no logic or latency change"}
    if not any(v["style"] == "block" and v["depth"] == 512 and k.startswith("data")
               for k, v in annotations.items()):
        raise RuntimeError("cache payload512x64 bank binding missing")
    for name in parallel_bindings:
        leaf = annotations.get(name, {})
        if leaf.get("style") != "block" or leaf.get("width") != 64 or leaf.get("depth") != 256:
            raise RuntimeError("parallel instruction256x64 per-way BRAM binding missing: " + name)
    if not any(k.startswith("tagBanks") for k in annotations) or \
            not any(k.startswith("directoryBanks") for k in annotations):
        raise RuntimeError("cache/directory tag RAM leaf binding missing")
    rom = ROOT / "src/main/resources/inorder/bootrom.hex"
    shutil.copyfile(rom, output / "bootrom.hex")
    replacements = 0
    for path in output.glob("*.sv"):
        text = path.read_text()
        count = text.count('"src/main/resources/inorder/bootrom.hex"')
        if count:
            path.write_text(text.replace('"src/main/resources/inorder/bootrom.hex"', '"bootrom.hex"'))
            replacements += count
    if replacements != 1:
        raise RuntimeError("physical boot ROM initialization binding mismatch")
    for name in ("ValenceI1BscanDebugPort.sv", "ValenceI1DmiCdc.sv"):
        source = ROOT / "src/main/resources/inorder" / name
        emitted = (output / name).read_text().removeprefix("// Generated by CIRCT firtool-1.135.0\n")
        if emitted.rstrip("\n") != source.read_text().rstrip("\n"):
            raise RuntimeError("physical USER2 blackbox resource drift")
        shutil.copyfile(source, output / name)
    for name in ("synth_network.tcl", "network_ooc.xdc", "network_cdc.tcl",
                 "network_clock_balance.tcl", "bscan_timing_i1.tcl"):
        shutil.copyfile(HERE / name, output / name)
    shutil.copyfile(ROOT / "fpga/next/check_jtag_chain.tcl", output / "check_jtag_chain.tcl")
    for name in ("cdc_constraints.tcl", "native-gmac-cdc-constraints.tcl"):
        shutil.copyfile(ROOT / "fpga/zu15eg" / name, output / name)
    for name, digest in receipt["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("source drift during export")
    native_count = 6 if bandwidth else 7
    native_names = ["private-uncached-x2", "device-origins-x2", "atomic-home", "home-ordinary"]
    if not bandwidth:
        native_names.insert(2, "device-arbiter-output")
    manifest = {"status": "PASS_SHORT_TESTED_NETWORK_RTL_EXPORT_ONLY",
        "top": "I1NetworkFpgaShell", "part": "xczu15eg-ffvb1156-2-i", "target_hz": 300000000,
        "icache_bytes": 32768, "dcache_bytes": 32768, "coherent_ways": 2,
        "coherent_bandwidth": bandwidth,
        "coherent_whole_line": whole_line,
        "line_read_request_boundaries": 1 if whole_line else 0,
        "home_write_payload_owners": 1,
        "coherent_control_revision": receipt.get("coherent_control_revision"),
        "parallel_instruction_way_reads": bool(receipt.get("parallel_instruction_way_reads")),
        "parallel_instruction_ram_bindings": parallel_bindings,
        "prepared_ddr_payload": bool(receipt.get("prepared_ddr_payload")),
        "parallel_instruction_candidates": bool(receipt.get("parallel_instruction_candidates")),
        "disjoint_instruction_transitions": bool(receipt.get("disjoint_instruction_transitions")),
        "parallel_backend_control": bool(receipt.get("parallel_backend_control")),
        "registered_id_serial_class": bool(receipt.get("registered_id_serial_class")),
        "prepared_native_requests": bool(receipt.get("prepared_native_requests")),
        "local_cache_metadata": bool(receipt.get("local_cache_metadata")),
        "isolated_writer_launch": True,
        "bounded_dma_descriptor_checks": True,
        "native_timing_boundaries": native_names,
        "native_timing_boundary_count": native_count,
        "data_admission": "occupancy-only ordered physical owner" if bandwidth else "legacy hit-under-miss",
        "home_write_cohorts": bandwidth, "line_dispatch_flow": bandwidth,
        "fast_data_translation": bool(receipt.get("fast_data_translation")),
        "instruction_admission": "occupancy-only read-only; no extra fetch stage",
        "cache_control": "CPU plus shared probe/flush tag ports; existing hit owner forwards LRU/dirty metadata",
        "home_control": "per-Acquire/ordinary/maintenance directory addresses; serialized one-payload writer",
        "clock_buffers": "5 actual parallel raw/gated BUFGCEs; pre-global-buffer root contract",
        "line_engine_entries": 2,
        "hardware_nominal_cpu_hz": 300000000, "uart_domain_hz": 50000000,
        "receipt": str(args.receipt.resolve()), "receipt_sha256": sha(args.receipt),
        "cdc_receipt": str(args.cdc_receipt), "cdc_sha256": sha(args.cdc_receipt),
        "managed_clock_receipt": str(args.managed_clock_receipt),
        "managed_clock_sha256": sha(args.managed_clock_receipt),
        "flags": flags, "source_sha256": receipt["source_sha256"], "annotations": annotations,
        "firtool": {"version": identity.strip(), "sha256": sha(firtool)},
        "source_resources": {str(p.relative_to(ROOT)): sha(p) for p in (
            rom, ROOT / "src/main/resources/inorder/ValenceI1BscanDebugPort.sv",
            ROOT / "src/main/resources/inorder/ValenceI1DmiCdc.sv")},
        "exporter_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (
            Path(__file__), HERE / "synth_network.tcl", HERE / "network_ooc.xdc",
            HERE / "network_cdc.tcl", HERE / "network_clock_balance.tcl")},
        "physical_qualified": False, "board_qualified": False, "bit_generated": False,
        "scope": "300MHz coherent CPU + managed tri-speed network OOC; not board MIG/RGMII IO/clock IP signoff",
        "files_sha256": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}}
    if diagnostic:
        manifest["status"] = "DIAGNOSTIC_USER_STOPPED_TARGET_CPU_RTL_EXPORT_NOT_FULL_QUALIFICATION"
        manifest["diagnostic_evidence"] = diagnostic
        manifest["full_short_qualified"] = False
        manifest["scope"] += "; explicit user-stopped diagnostic, full short suite incomplete"
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": manifest["status"], "output": str(output)}), flush=True)


if __name__ == "__main__":
    main()
