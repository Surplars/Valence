#!/usr/bin/env python3
"""Short I1 TL-C/300 MHz-cut qualification; no frequency claim from GSIM."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(Path(__file__).resolve().parent))
from soc_acceptance import sources, sha
from fp_payload import generate as generate_fp

CHECK_WALL_TIMEOUT_SECONDS = 300


def qualification_sources():
    result = sources()
    for name in ("simulator/gsim/harness/ethernet_packet_dma.cpp",
                 "simulator/gsim/harness/line_read_channel.cpp",
                 "simulator/gsim/harness/line_read_preflight.cpp",
                 "simulator/gsim/harness/five_stage_plic.cpp",
                 "simulator/gsim/harness/dma_pipeline_ddr.h"):
        result[name] = sha(ROOT / name)
    return result


def functional_fir(text):
    """Ignore ONLY the unsupported physical hints removed from RAMs; no logic/locators."""
    start = text.index(":%[") + 3
    annotations, length = json.JSONDecoder().raw_decode(text[start:])
    def removed(a):
        return (a.get("class") == "firrtl.AttributeAnnotation" and
                a.get("description") == 'ram_style = "distributed"' and
                re.fullmatch(r"~\|I1CoherentLine(?:Cache(?:_[0-9]+)?|Home)>(?:tagBanks|directoryBanks)_[0-9]+",
                             a.get("target", "")))
    keep = [a for a in annotations if not removed(a)]
    return text[:start] + json.dumps(keep, sort_keys=True) + text[start + length:]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--pair-only", action="store_true",
                    help="Only affected small TL-C/atomic/DMA models; no CPU rebuild or throughput claim")
    ap.add_argument("--cache-bytes", type=int, choices=(2048, 32768), default=32768,
                    help="Explicit target I/D capacity, independently retained as an elaboration parameter")
    ap.add_argument("--vectors-receipt", type=Path,
                    default=ROOT / "build/gsim/i1-fd-jtag-timing-20261015-r4/receipt.json")
    ap.add_argument("--reuse-models", type=Path,
                    help="Fresh FIR must match exactly except removed unsupported RAM physical annotations")
    ap.add_argument("--rebuild-changed-models", action="store_true",
                    help="With --reuse-models: rebuild genuinely changed FIR models, never reuse them")
    ap.add_argument("--reuse-failed-builds", action="store_true",
                    help="Compile cache ONLY: exact fresh FIR/artifact hashes, rerun ALL tests; explicit PASS performance reference required")
    ap.add_argument("--performance-reference", type=Path,
                    help="Frozen OLD hardware receipt, independent of exact-FIR compilation reuse")
    ap.add_argument("--control-cuts", action="store_true",
                    help="Explicit new coherent cache/device control cuts; defaults remain removable")
    ap.add_argument("--bandwidth-cuts", action="store_true",
                    help="New ordered D admission, owner turnover, Home write cohorts and compact DMA cuts")
    ap.add_argument("--fast-data", action="store_true",
                    help="Explicitly select the EXISTING registered full-page data authorization option")
    ap.add_argument("--whole-line", action="store_true",
                    help="Reuse the two real DDR slots for an aggregate whole-line reply; no duplicate reader")
    args = ap.parse_args()
    if args.rebuild_changed_models and not args.reuse_models:
        ap.error("--rebuild-changed-models requires a passing prior model receipt")
    if args.reuse_failed_builds and not (args.reuse_models and args.rebuild_changed_models
                                        and args.performance_reference):
        ap.error("failed build cache requires explicit reuse/rebuild and a separate PASS performance reference")
    if args.bandwidth_cuts and not args.control_cuts:
        ap.error("--bandwidth-cuts requires --control-cuts")
    if args.whole_line and not args.bandwidth_cuts:
        ap.error("--whole-line requires --bandwidth-cuts")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe fresh tag required")
    output = ROOT / "build/gsim" / ("i1-coherent-network-" + args.tag)
    if output.exists():
        ap.error("refusing to overwrite evidence")
    output.mkdir(parents=True)
    frozen = qualification_sources()
    receipt = {
        "status": "RUNNING", "checks": {}, "source_sha256": frozen,
        "physical_qualified": False, "board_qualified": False,
        "cpu_target_hz": 300000000, "cpu_target_ns": 10 / 3,
        "check_wall_timeout_seconds": CHECK_WALL_TIMEOUT_SECONDS,
        "clock_targets_hz": {"aon": 50000000, "uart": 50000000,
                             "mac_tx_reference": 125000000, "ddr_ui": 250000000},
        "scope": "independent TL-C pair + actual RV64 CPU Bare/Sv39 byte oracle; no Linux or Vivado",
        "coherence": "exclusive private I/D; 1/2-way selectable, combined capacity-sized Home; real B/C/E",
        "cache_bytes_each": args.cache_bytes,
        "directory_entries_cpu": 2 * args.cache_bytes // 64, "ddr_slots": 2, "max_write_slots": 1,
        "ooo_modified": False,
        "pair_only": args.pair_only,
        "coherent_control_cuts": args.control_cuts,
        "coherent_bandwidth": args.bandwidth_cuts, "fast_data_translation": args.fast_data,
        "coherent_control_revision": "registered-id-class-prepared-native-payload-local-metadata",
        "registered_id_serial_class": args.control_cuts and not args.pair_only,
        "prepared_native_requests": args.control_cuts,
        "local_cache_metadata": args.control_cuts,
        "parallel_backend_control": args.control_cuts and not args.pair_only,
        "parallel_instruction_way_reads": args.control_cuts and not args.pair_only,
        "prepared_ddr_payload": args.whole_line,
        "parallel_instruction_candidates": args.control_cuts and not args.pair_only,
        "disjoint_instruction_transitions": args.control_cuts and not args.pair_only,
        "coherent_whole_line": args.whole_line,
        "axi_service": "same seeded independent channels; R=floor+[0,12], B=floor-1+[0,10]; no board latency claim",
    }
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}

    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    save()
    try:
        gs = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gs, text=True):
            raise RuntimeError("GSIM pin/cleanliness mismatch")
        gsim = gs / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["tools"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version}
        prior = json.loads(args.reuse_models.read_text()) if args.reuse_models else None
        allowed_reuse_status = ("PASS_I1_TLC_CPU_SHORT_ONLY_PHYSICAL_PENDING",) + (
            ("FAIL",) if args.reuse_failed_builds else ())
        if prior and (prior["status"] not in allowed_reuse_status or
                      prior["tools"] != receipt["tools"]):
            raise RuntimeError("passing identical-tool model receipt required")
        if prior:
            receipt["reuse_models"] = {"path": str(args.reuse_models.resolve()), "sha256": sha(args.reuse_models),
                "prior_status": prior["status"],
                "scope": "EXACT_FRESH_FIR_AND_HASHED_COMPILE_ARTIFACTS_ONLY_ALL_TESTS_RERUN"}
        performance_path = args.performance_reference or args.reuse_models
        performance = json.loads(performance_path.read_text()) if performance_path else None
        if performance and (performance["status"] != "PASS_I1_TLC_CPU_SHORT_ONLY_PHYSICAL_PENDING" or
                            performance["tools"] != receipt["tools"] or
                            performance["cache_bytes_each"] != args.cache_bytes):
            raise RuntimeError("matched passing frozen hardware/performance receipt required")
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"],
                   log=output / "scala.log")

        def link_driver(out, top, driver, name="run", defines=(), width=64):
            common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-DDUT_XLEN=" + str(width), "-I" + str(out),
                        *defines, *sorted(out.glob(top + "[0-9]*.o")),
                        ROOT / "simulator/gsim/harness" / driver, "-o", out / name],
                       log=out / (name + "-link.log"), timeout=900)

        def model(name, entry, top, driver, flags=(), defines=(), width=64):
            print("BUILD", name, flush=True)
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder." + entry,
                        out, width, *flags], log=out / "elaborate.log")
            original = out / (top + ".fir")
            old_fir = args.reuse_models.parent / name / (top + ".fir") if prior else None
            if old_fir is not None and old_fir.exists():
                previous = args.reuse_models.parent / name
                if sha(old_fir) != prior["artifact_sha256"].get(name + "/" + old_fir.name):
                    raise RuntimeError("prior FIR artifact drift: " + name)
                identical = functional_fir(original.read_text()) == functional_fir(old_fir.read_text())
                if not identical and not args.rebuild_changed_models:
                    raise RuntimeError("exact functional FIR mismatch for model reuse: " + name)
            else:
                identical = False
            if identical:
                artifacts = [p for p in previous.iterdir() if p.suffix in (".h", ".cpp", ".o")]
                if not any(p.suffix == ".o" for p in artifacts):
                    raise RuntimeError("no retained model objects: " + name)
                for path in artifacts:
                    if sha(path) != prior["artifact_sha256"].get(name + "/" + path.name):
                        raise RuntimeError("model artifact drift: " + str(path))
                    shutil.copy2(path, out / path.name)
                receipt.setdefault("functional_fir_identity", {})[name] = {
                    "fresh_sha256": sha(original), "previous_sha256": sha(old_fir),
                    "gate": "EXACT_FIR_LOGIC_AND_LOCATORS_ONLY_UNSUPPORTED_RAM_HINTS_IGNORED"}
                link_driver(out, top, driver, defines=defines, width=width)
                return out
            if old_fir is not None and old_fir.exists():
                receipt.setdefault("rebuilt_changed_models", {})[name] = {
                    "fresh_sha256": sha(original), "previous_sha256": sha(old_fir),
                    "gate": "CHANGED_FIR_FRESH_GSIM_GENERATION_AND_COMPILE_NO_MODEL_REUSE"}
            elif prior:
                receipt.setdefault("new_models", []).append(name)
            parser = original
            if original.stat().st_size % 4096 == 0:
                parser = out / (top + ".gsim-input.fir")
                parser.write_bytes(original.read_bytes() + b"\n")
                receipt.setdefault("gsim_parser_padding", {})[name] = {
                    "reason": "pinned GSIM mmap EOF SIGBUS", "original_sha256": sha(original),
                    "parser_sha256": sha(parser), "padding": "one newline"}
            common.run([gsim, "--threads=1", "--dir=" + str(out), parser],
                       log=out / "generate.log", timeout=900)
            for source in sorted(out.glob(top + "[0-9]*.cpp")):
                common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                            "-fno-sanitize-recover=all", "-I" + str(out), "-c", source,
                            "-o", source.with_suffix(".o")], log=out / (source.stem + "-compile.log"), timeout=900)
            link_driver(out, top, driver, defines=defines, width=width)
            return out

        def check(name, out, argv=(), negative=None, binary="run"):
            common.run([out / binary, *argv], env=env, log=out / (name + ".log"),
                       timeout=CHECK_WALL_TIMEOUT_SECONDS)
            receipt["checks"][name] = (out / (name + ".log")).read_text().strip()
            print(receipt["checks"][name], flush=True)
            save()
            if negative:
                bad_args, expected = negative
                bad = subprocess.run([str(out / binary), *map(str, bad_args)], env=env,
                                     capture_output=True, text=True, timeout=CHECK_WALL_TIMEOUT_SECONDS)
                (out / (name + "-negative.log")).write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or expected not in bad.stdout + bad.stderr:
                    raise RuntimeError("independent negative control failed: " + name)
                receipt["checks"][name + "-negative"] = "PASS_REJECTED_BYTE_ORACLE_MUTATION"
                save()

        if not args.pair_only:
            name = "serial-class"
            out = model(name, "FiveStageSerialClassMain", "FiveStageSerialClassFixture",
                        "five_stage_serial_class.cpp")
            check(name, out, negative=(["--wrong-class"], "independent ISA serial class oracle"))
            for prepare in (False, True):
                name = "native-queue-" + ("prepared" if prepare else "default")
                out = model(name, "FiveStagePreparedQueueMain", "FiveStagePreparedQueueFixture",
                            "five_stage_prepared_queue.cpp", ["--prepare"] if prepare else [])
                check(name, out, negative=(["--wrong-data"], "independent registered queue payload oracle"))
                check(name + "-credit", out,
                      negative=(["--wrong-ready"], "independent registered queue credit oracle"))
            name = "backend-control"
            out = model(name, "FiveStageBackendControlMain", "FiveStageBackendControlFixture",
                        "five_stage_backend_control.cpp")
            check(name, out, negative=(["--wrong-capacity"], "independent backend capacity handshake oracle"))
            check(name + "-owner", out, negative=(["--wrong-owner"], "independent nearest producer payload oracle"))
            name = "plic-irq-presence"
            out = model(name, "FiveStagePlicMain", "FiveStagePlicHarness", "five_stage_plic.cpp")
            check(name, out, negative=(["--wrong-payload"], "PLIC reply payload/side-effect oracle"))
            check(name + "-irq", out, negative=(["--wrong-irq"], "PLIC priority/threshold IRQ oracle"))
            for capacity in (256, 32768):
                name = "coherent-if-pma-" + str(capacity)
                out = model(name, "I1InstructionCachePmaMain", "I1InstructionCachePmaFixture",
                            "five_stage_coherent_if_pma.cpp", ["--cache-bytes=" + str(capacity)],
                            ["-DI1_IF_CACHE_BYTES=" + str(capacity)])
                check(name, out, negative=(["--wrong-data"], "independent coherent IF byte oracle"))
                check(name + "-hint", out, negative=(["--wrong-hint"],
                      "trusted coherent IF cacheability contradicts physical/noAllocate policy"))
            if args.whole_line:
                for write_flow in (False, True):
                    for burst in (8, 16):
                        name = "line-read-shared-" + ("flow-" if write_flow else "") + "2-burst" + str(burst)
                        options = (["--burst16"] if burst == 16 else []) + (["--write-flow"] if write_flow else [])
                        out = model(name, "I1LineReadChannelMain", "LineReadChannelGsim",
                                    "line_read_channel.cpp", options,
                                    ["-DLINE_SHARED_SLOTS=2", "-DLINE_WRITE_CREDITS=1",
                                     "-DLINE_MAX_BURST_BEATS=" + str(burst)])
                        for suffix, mutation, expected in (
                                ("", "line-data", "whole-line independent byte/error oracle mismatch"),
                                ("-tags", "line-tag", "whole-line independent tag oracle mismatch"),
                                ("-rlast", "early-rlast", "AXI read ID or RLAST mismatch"),
                                ("-rid", "bad-rid", "AXI R response has no live read owner")):
                            check(name + suffix, out, negative=(["--mutate=" + mutation], expected))
            # Same existing public DMA packet/byte oracle, full ABI, stop,
            # errors, four credits, posted RX, overlap and >4GiB ownership.
            for cuts, disabled in ((False, False), (True, False), (True, True)):
                name = "peripheral-decode-" + ("cuts" if cuts else "direct") + ("-disabled" if disabled else "")
                options = (["--timing-cuts"] if cuts else []) + (["--disabled"] if disabled else [])
                out = model(name, "I1PeripheralDecodeMain", "I1PeripheralDecodeFixture",
                            "five_stage_peripheral_decode.cpp", options,
                            ["-DI1_DISABLED_PERIPHERALS=1"] if disabled else [])
                check(name, out, negative=(["--wrong-owner"], "independent peripheral owner/address oracle"))
                if not disabled:
                    check(name + "-payload", out, negative=(["--wrong-payload"], "peripheral request payload changed"))
            for large_ddr in (False, True):
                name = "packet-dma-bounded-" + ("2g" if large_ddr else "8k")
                options = ["--timing-cuts"] + (["--large-ddr"] if large_ddr else [])
                defines = ["-DDMA_RAM_BYTES=2147483648ULL"] if large_ddr else []
                out = model(name, "I1PacketDmaMain", "EthernetPacketDma",
                            "ethernet_packet_dma.cpp", options, defines)
                check(name, out, negative=(["--wrong-data"], "TX independent byte oracle mismatch"))
            for cuts in (False, True):
                name = "device-frontend-" + ("cuts" if cuts else "direct")
                out = model(name, "I1DeviceFrontEndMain", "I1CoherentDeviceFrontEnd",
                            "five_stage_device_frontend.cpp", ["--cuts"] if cuts else [])
                check(name, out, negative=(["--wrong-data"],
                      "independent device lane/error/order oracle mismatch"))
            if args.bandwidth_cuts:
                name = "device-frontend-compact"
                out = model(name, "I1DeviceFrontEndMain", "I1CoherentDeviceFrontEnd",
                            "five_stage_device_frontend.cpp", ["--cuts", "--compact"])
                check(name, out, negative=(["--wrong-data"],
                      "independent device lane/error/order oracle mismatch"))
            for width in (32, 64):
                name = "pmp-page-split-" + str(width)
                out = model(name, "I1PmpTimingMain", "I1PmpTimingFixture",
                            "five_stage_pmp_timing.cpp", width=width)
                check(name, out, negative=(["--wrong-permission"], "independent PMP full-interval/priority oracle"))
            dependency = json.loads((ROOT / "simulator/gsim/config/floating-point-dependencies.json").read_text())
            for name, digest in dependency["local_sources_sha256"].items():
                if sha(ROOT / "third_party/berkeley-hardfloat/src/main/scala" / name) != digest:
                    raise RuntimeError("pinned HardFloat source drift: " + name)
            reference = json.loads(args.vectors_receipt.read_text())
            vectors = args.vectors_receipt.parent / "vectors.txt"
            if reference["status"] != "PASS_I1_PARAMETERIZED_FD_JTAG_TIMING_CUTS_SHORT_ONLY" or \
                    sha(vectors) != reference["vectors_sha256"]:
                raise RuntimeError("independent SoftFloat vectors provenance mismatch")
            receipt["independent_fp_vectors"] = {"receipt": str(args.vectors_receipt.resolve()),
                "receipt_sha256": sha(args.vectors_receipt), "sha256": sha(vectors)}
            for profile in ("f", "fd"):
                name = "postmul-numerical-" + profile
                out = model(name, "I1FloatingPointMain", "I1FloatingPointGsim", "five_stage_fp_numerical.cpp",
                            ["--timing-cuts", *(["--d"] if profile == "fd" else [])],
                            ["-DI1_TIMING_CUTS=1"])
                check(name, out, [vectors, profile],
                      negative=([vectors, profile, "--inject-mismatch"], "FP full mismatch: SoftFloat value"))
                check(name + "-completion", out, [vectors, profile],
                      negative=([vectors, profile, "--inject-completion"],
                                "FP full mismatch: registered completion owner status"))
            for width in (32, 64):
                name = "mdu-local-completion-" + str(width)
                out = model(name, "FiveStageMulDivMain", "FiveStageMulDiv",
                            "five_stage_mul_div.cpp", ["--dsp-tiled"], width=width)
                check(name, out, negative=(["--wrong-data"], "independent MDU oracle mismatch"))
            for instruction in (False, True):
                name = "pmp-translation-" + ("instruction" if instruction else "data")
                out = model(name, "FiveStageTranslationMain", "FiveStageTranslationHarness",
                            "five_stage_translation.cpp",
                            ["--timing-cuts", "--atomic", *(["--instruction"] if instruction else [])],
                            ["-DI1_INSTRUCTION_TRANSLATION=1"] if instruction else [])
                check(name, out, negative=(["--wrong-page"], "independent Sv39/PMP/page-vs-access fault oracle"))
            for window, entries in (("aligned", 4), ("shifted", 4), ("board", 8)):
                name = "if-candidates-" + window
                defines = ["-DI1_INSTRUCTION_TRANSLATION=1", "-DI1_INSTRUCTION_PMA=1",
                           "-DI1_SPLIT_INSTRUCTION_CANDIDATES=1"]
                if window != "aligned":
                    defines += ["-DI1_PMA_" + window.upper() + "=1"]
                out = model(name, "FiveStageTranslationMain", "FiveStageTranslationHarness",
                            "five_stage_translation.cpp",
                            ["--instruction", "--timing-cuts", "--atomic", "--split-candidates",
                             "--window=" + window, "--tlb=" + str(entries)], defines)
                check(name, out, negative=(["--wrong-page"],
                      "independent Sv39/PMP/page-vs-access fault oracle"))
                check(name + "-pma", out, negative=(["--wrong-pma"],
                      "independent instruction PMA/noAllocate oracle"))
            if args.fast_data:
                name = "pmp-translation-data-fast"
                out = model(name, "FiveStageTranslationMain", "FiveStageTranslationHarness",
                            "five_stage_translation.cpp", ["--timing-cuts", "--atomic", "--fast-data-translation"])
                check(name, out, negative=(["--wrong-page"], "independent Sv39/PMP/page-vs-access fault oracle"))
        for cuts, ways, capacity in ((False, 1, 256), (True, 1, 256), (True, 2, 256),
                                     (True, 2, args.cache_bytes)):
            name = ("pair-cut" if cuts else "pair-direct") + "-ways" + str(ways) + "-bytes" + str(capacity)
            out = model(name, "I1CoherentPairGsimMain", "I1CoherentPairGsim",
                        "five_stage_coherence.cpp",
                        (["--cuts"] if cuts else []) + (["--two-way"] if ways == 2 else []) +
                            ["--cache-bytes=" + str(capacity)],
                        ["-DI1_PAIR_CACHE_BYTES=" + str(capacity)] +
                            (["-DI1_COHERENT_TWO_WAY"] if ways == 2 else []))
            check(name, out, negative=(["--wrong-data"], "independent dirty-owner byte oracle"))
            check(name + "-ordinary-stream", out, negative=(
                ["--wrong-stream"], "independent ordinary cohort byte/order oracle"))
        if args.bandwidth_cuts:
            for capacity, ordered in ((256, False), (256, True), (args.cache_bytes, True)):
                name = "pair-bandwidth-ways2-bytes" + str(capacity) + ("-ordered" if ordered else "")
                out = model(name, "I1CoherentPairGsimMain", "I1CoherentPairGsim", "five_stage_coherence.cpp",
                            ["--cuts", "--two-way", "--bandwidth", "--cache-bytes=" + str(capacity)] +
                                (["--ordered-admission"] if ordered else []),
                            ["-DI1_PAIR_CACHE_BYTES=" + str(capacity), "-DI1_COHERENT_TWO_WAY",
                             "-DI1_HOME_WRITE_PIPELINE"] + (["-DI1_ORDERED_ADMISSION"] if ordered else []))
                check(name, out, negative=(["--wrong-data"], "independent dirty-owner byte oracle"))
                check(name + "-ordinary-stream", out, negative=(
                    ["--wrong-stream"], "independent ordinary cohort byte/order oracle"))
        if args.pair_only:
            if qualification_sources() != frozen:
                raise RuntimeError("source drift during pair qualification")
            receipt["status"] = "PASS_I1_TLC_PAIR_DMA_ATOMIC_SHORT_ONLY"
            return
        here = ROOT / "simulator/gsim/inorder"
        image = output / "stream"
        common.run(["riscv64-unknown-elf-gcc", "-march=rv64i_zicsr_zifencei", "-mabi=lp64",
                    "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                    "-T" + str(here / "soc_link.ld"), here / "privilege_throughput.S",
                    "-o", image.with_suffix(".elf")], log=output / "stream-build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", image.with_suffix(".elf"),
                    image.with_suffix(".bin")], log=output / "stream-objcopy.log")
        large = output / "stream64k"
        common.run(["riscv64-unknown-elf-gcc", "-march=rv64i_zicsr_zifencei", "-mabi=lp64",
                    "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                    "-DI1_STREAM_WORDS=8192", "-DI1_STREAM_DST=0x80280000",
                    "-T" + str(here / "soc_link.ld"), here / "privilege_throughput.S",
                    "-o", large.with_suffix(".elf")], log=output / "stream64k-build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", large.with_suffix(".elf"),
                    large.with_suffix(".bin")], log=output / "stream64k-objcopy.log")
        payloads = {}
        corpus_source = output / "fd-corpus.S"
        receipt["cpu_fp_corpus"] = generate_fp(vectors, corpus_source, True)
        for name, source, linker, march, definitions in (
                ("privilege", here / "privilege_smoke.S", "privilege_link.ld", "rv64i_zicsr_zifencei", []),
                ("ca", here / "ca_smoke.S", "soc_link.ld", "rv64imac_zicsr_zifencei", []),
                ("fd-corpus", corpus_source, "fp_link.ld", "rv64imafdc_zicsr_zifencei", []),
                ("fd-context", here / "fp_context.S", "fp_link.ld", "rv64imafdc_zicsr_zifencei", ["-DHAVE_D=1"])):
            elf = output / (name + ".elf")
            common.run(["riscv64-unknown-elf-gcc", "-march=" + march, "-mabi=lp64",
                        "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                        *definitions, "-T" + str(here / linker), source, "-o", elf],
                       log=output / (name + "-build.log"))
            payloads[name] = elf.with_suffix(".bin")
            common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", elf, payloads[name]],
                       log=output / (name + "-objcopy.log"))
        flags = ["--pipeline=fpga8", "--timing-cuts", "--dsp-tiled",
                 "--icache=" + str(args.cache_bytes), "--dcache=" + str(args.cache_bytes),
                 "--predictor=128", "--early-memory-issue", "--overlap-write-lookup",
                 "--sv39", "--pmp=8", "--c", "--a", "--f", "--d", "--soc-no-bootrom",
                 "--soc-clock-hz=300000000"]
        if args.control_cuts:
            flags += ["--coherent-control-cuts"]
        if args.bandwidth_cuts:
            flags += ["--coherent-bandwidth"]
        if args.fast_data:
            flags += ["--fast-data-translation"]
        if args.whole_line:
            flags += ["--coherent-whole-line"]
        cm_source = Path("/home/openion/Valence/simulator/build/coremark-src")
        cm_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cm_source, text=True).strip()
        if cm_revision != "1f483d5b8316753a742cbf5590caf5bd0a4e4777" or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=cm_source, text=True):
            raise RuntimeError("standard CoreMark pin/cleanliness mismatch")
        cm = output / "coremark"
        cm.mkdir()
        cm_flags = ["-O3", "-march=rv64im_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany", "-mno-relax",
                    "-msmall-data-limit=0", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
                    "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                    "-DITERATIONS=1", "-DPERFORMANCE_RUN=1", "-DTOTAL_DATA_SIZE=2000", "-DI1_COREMARK_SOC"]
        cm_inputs = [cm_source / f for f in ("core_list_join.c", "core_main.c", "core_matrix.c",
                                            "core_state.c", "core_util.c")]
        common.run(["riscv64-unknown-elf-gcc", *cm_flags, "-I" + str(here / "coremark_port"),
                    "-I" + str(cm_source), "-T" + str(here / "coremark_soc.ld"),
                    here / "coremark_soc_start.S", *cm_inputs, here / "coremark_port/core_portme.c",
                    "-lgcc", "-o", cm / "coremark.elf"], log=cm / "build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", cm / "coremark.elf", cm / "coremark.bin"],
                   log=cm / "objcopy.log")
        symbols = subprocess.check_output(["riscv64-unknown-elf-nm", "-n", cm / "coremark.elf"], text=True)
        (cm / "symbols.txt").write_text(symbols)
        values = {row.split()[-1]: int(row.split()[0], 16) for row in symbols.splitlines() if len(row.split()) == 3}
        cm_argv = [cm / "coremark.bin", *[hex(values[k]) for k in (
            "coremark_validation_errors", "coremark_crcs", "coremark_phase", "coremark_validated",
            "coremark_duration_warnings")]]
        receipt["coremark_payload"] = {"source_commit": cm_revision, "flags": cm_flags,
            "sha256": sha(cm / "coremark.bin"), "data_size": 2000, "iterations": 1,
            "source_sha256": {p.name: sha(p) for p in cm_inputs},
            "scope": "O3 actual coherent RV64GC SoC, retired-store cycle ROI, NOT formal >=10s score"}
        common.run(["riscv64-unknown-elf-gcc", "-march=rv64im_zicsr_zifencei", "-mabi=lp64",
                    "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                    "-T" + str(here / "coremark_soc.ld"), here / "fetch_control_smoke.S",
                    "-o", cm / "fetch-control.elf"], log=cm / "fetch-control-build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary",
                    cm / "fetch-control.elf", cm / "fetch-control.bin"], log=cm / "fetch-control-objcopy.log")
        def coremark_check(name, out):
            link_driver(out, "FiveStageSoc", "five_stage_soc_coremark.cpp", name="coremark",
                        defines=["-DI1_COHERENT_READBACK"])
            key = name + "-coremark-o3"
            check(key, out, cm_argv, binary="coremark",
                  negative=([*cm_argv, "--inject"], "CoreMark independent register oracle mismatch"))
            line = receipt["checks"][key]
            if not line.startswith("I1_SOC_COREMARK_PASS "):
                raise RuntimeError("missing independent actual-CPU CoreMark PASS")
            result = json.loads(line.split(" ", 1)[1])
            result["roi_ipc"] = result["roi_instructions"] / result["roi_ticks"]
            receipt.setdefault("benchmarks", {})[name] = result
            check(name + "-fetch-control", out, [cm / "fetch-control.bin", "--smoke"], binary="coremark")
            save()
        def stream_latency_checks(name, out, slow=True):
            for mode in ("bare", "sv39"):
                for large_stream in (False, True):
                    argv = [large.with_suffix(".bin") if large_stream else image.with_suffix(".bin"),
                            "--" + mode + "-throughput"] + (["--large-stream"] if large_stream else [])
                    key = name + ("-64k-" if large_stream else "-") + mode
                    check(key, out, argv, negative=([*argv, "--wrong-stream"],
                          "independent streaming READ checksum") if not large_stream else None)
                    if slow and args.bandwidth_cuts and large_stream:
                        for delay in (40, 80):
                            check(key + "-latency" + str(delay), out, [*argv, "--memory-latency=" + str(delay)])
        for capacity in sorted(set((2048, args.cache_bytes))):
            name = "cpu-coherent" if capacity == args.cache_bytes else "cpu-coherent-2k"
            selected = [f for f in flags if not f.startswith(("--icache=", "--dcache="))] + [
                "--icache=" + str(capacity), "--dcache=" + str(capacity),
                "--coherent-caches", "--soc-fabric-cuts", "--coherent-ways=2"]
            out = model(name, "FiveStageSocGsimMain", "FiveStageSoc",
                        "five_stage_privilege_soc.cpp", selected,
                        ["-DI1_COHERENT_READBACK"])
            receipt.setdefault("cpu_flags", {})[name] = selected
            stream_latency_checks(name, out, slow=capacity == args.cache_bytes)
            check(name + "-precise-privilege", out, [payloads["privilege"]],
                  negative=([payloads["privilege"], "--wrong-result"],
                            "independent privileged SoC result ledger oracle"))
            link_driver(out, "FiveStageSoc", "five_stage_ca_soc.cpp", name="ca",
                        defines=["-DI1_COHERENT_READBACK"])
            check(name + "-ca", out, [payloads["ca"]], binary="ca",
                  negative=([payloads["ca"], "--wrong-result"],
                            "independent C/A completion/alias/boundary oracle"))
            check(name + "-ca-page-end", out, [payloads["ca"], "--compressed-boundary"], binary="ca")
            if capacity == args.cache_bytes:
                link_driver(out, "FiveStageSoc", "five_stage_fp_soc.cpp", name="fp",
                            defines=["-DI1_COHERENT_READBACK"])
                check(name + "-fd-corpus", out,
                      [payloads["fd-corpus"], receipt["cpu_fp_corpus"]["cases"]], binary="fp",
                      negative=([payloads["fd-corpus"], receipt["cpu_fp_corpus"]["cases"], "--wrong-result"],
                                "independent FP actual CPU result/flags/context ledger oracle"))
                check(name + "-fd-context", out, [payloads["fd-context"], 32, "--faults"], binary="fp")
                coremark_check(name, out)
        if args.whole_line:
            name = "cpu-whole-line-off"
            selected = [f for f in flags if f != "--coherent-whole-line"] + [
                "--coherent-caches", "--soc-fabric-cuts", "--coherent-ways=2"]
            out = model(name, "FiveStageSocGsimMain", "FiveStageSoc",
                        "five_stage_privilege_soc.cpp", selected, ["-DI1_COHERENT_READBACK"])
            receipt.setdefault("cpu_flags", {})[name] = selected
            stream_latency_checks(name, out)
            coremark_check(name, out)
        if args.bandwidth_cuts and args.fast_data:
            # Separate new structural handoffs from the pre-existing fast-data
            # permission option. Same capacities, binary, ABI and service law.
            name = "cpu-structural-only"
            selected = [f for f in flags if f != "--fast-data-translation"] + [
                "--coherent-caches", "--soc-fabric-cuts", "--coherent-ways=2"]
            out = model(name, "FiveStageSocGsimMain", "FiveStageSoc",
                        "five_stage_privilege_soc.cpp", selected, ["-DI1_COHERENT_READBACK"])
            receipt.setdefault("cpu_flags", {})[name] = selected
            stream_latency_checks(name, out)
            coremark_check(name, out)
        if performance:
            # Deliberately run the frozen PREVIOUS hardware, not a current-FIR
            # reuse claim. Same new payload/oracle/service as the candidate.
            baseline = output / "cpu-frozen-baseline"
            baseline.mkdir()
            previous = performance_path.parent / "cpu-coherent"
            for path in previous.iterdir():
                if path.suffix not in (".fir", ".h", ".cpp", ".o"):
                    continue
                if sha(path) != performance["artifact_sha256"].get("cpu-coherent/" + path.name):
                    raise RuntimeError("frozen performance model drift: " + path.name)
                shutil.copy2(path, baseline / path.name)
            receipt["frozen_performance_baseline"] = {
                "receipt": str(performance_path.resolve()), "sha256": sha(performance_path),
                "flags": performance["cpu_flags"]["cpu-coherent"],
                "scope": "old hardware is intentionally unchanged, NOT current-FIR qualification"}
            coremark_check("cpu-frozen-baseline", baseline)
            if args.bandwidth_cuts:
                link_driver(baseline, "FiveStageSoc", "five_stage_privilege_soc.cpp",
                            defines=["-DI1_COHERENT_READBACK"])
                stream_latency_checks("cpu-frozen-baseline", baseline)
            old, new = receipt["benchmarks"]["cpu-frozen-baseline"], receipt["benchmarks"]["cpu-coherent"]
            for field in ("roi_instructions", "retired", "trace_fnv64", "crcfinal"):
                if old[field] != new[field]:
                    raise RuntimeError("CoreMark matched architectural cohort drift: " + field)
            if args.bandwidth_cuts:
                for suffix in ("-bare", "-sv39", "-64k-bare", "-64k-sv39",
                               "-64k-bare-latency40", "-64k-sv39-latency40",
                               "-64k-bare-latency80", "-64k-sv39-latency80"):
                    old = json.loads(receipt["checks"]["cpu-frozen-baseline" + suffix].split(" ", 1)[1])
                    new = json.loads(receipt["checks"]["cpu-coherent" + suffix].split(" ", 1)[1])
                    if any(old[k] != new[k] for k in ("retired", "axi_reads", "axi_writes", "bytes")):
                        raise RuntimeError("stream architectural/traffic cohort drift: " + suffix)
                    receipt.setdefault("bandwidth_comparison", {})[suffix] = {
                        "old": old, "new": new, "throughput_ratios": {
                            k.removesuffix("_ticks"): old[k] / new[k]
                            for k in ("read_ticks", "write_ticks", "copy_ticks")}}
                if receipt["benchmarks"]["cpu-coherent"]["roi_ticks"] > \
                        receipt["benchmarks"]["cpu-frozen-baseline"]["roi_ticks"]:
                    raise RuntimeError("actual-CPU O3 CoreMark performance regression")
        # Full managed network shell elaboration is NOT multi-clock behavior or
        # board RGMII IO timing qualification. Those remain explicit separate gates.
        shell = output / "network-elaboration"
        common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.I1NetworkFpgaShellMain",
                    shell, 64, *[f for f in flags if f != "--soc-no-bootrom"],
                    "--coherent-caches", "--coherent-ways=2", "--soc-fabric-cuts", "--soc-network",
                    "--soc-jtag", "--soc-user-chain=2"], log=output / "network-elaborate.log")
        receipt["checks"]["network-shell"] = "PASS_CHIRRTL_ONLY_NOT_CDC_OR_PHYSICAL"
        if qualification_sources() != frozen:
            raise RuntimeError("source drift during qualification")
        receipt["status"] = "PASS_I1_TLC_CPU_SHORT_ONLY_PHYSICAL_PENDING"
    except Exception as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*")
                                      if p.is_file() and p.name != "receipt.json"}
        save()
        print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}), flush=True)


if __name__ == "__main__":
    main()
