#!/usr/bin/env python3
"""Stage the affected-short-tested CPU board, temporarily without MAC/PHY/DMA."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from export_network import memory_style, parallel_instruction_bindings, sha
from board_short_proof import (BANDWIDTH37, BANDWIDTH38, BANDWIDTH39, BANDWIDTH40, BANDWIDTH41, BANDWIDTH42, BANDWIDTH43, BANDWIDTH44,
    BANDWIDTH_PROFILES, validate_bandwidth37, validate_bandwidth38, validate_bandwidth39, validate_bandwidth40,
    validate_bandwidth41, validate_bandwidth42, validate_bandwidth43, validate_bandwidth44)


def validate_bootrom_proof(path, selected):
    from check_bootrom_boot import simulation_flags
    proof = json.loads(path.read_text())
    if (proof.get("status") != "PASS_I1_BOOTROM_UART_SHORT" or
            proof.get("board_flags") != selected or
            proof.get("simulation_flags") != simulation_flags(selected) or
            proof.get("rom_sha256") != sha(ROOT / "src/main/resources/inorder/bootrom.hex") or
            set(proof.get("checks", {})) != {"real_cpu_uart", "wrong-banner", "empty-rom"} or
            "I1_BOOTROM_UART_PASS" not in proof["checks"]["real_cpu_uart"] or
            any(proof["checks"][name] != "PASS_EXPECTED_REJECTION" for name in ("wrong-banner", "empty-rom"))):
        raise RuntimeError("exact BootROM UART positive/negative proof required before board synthesis")
    for name, digest in proof["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("BootROM proof source/oracle drift: " + name)
    for name, digest in proof["artifact_sha256"].items():
        if sha(path.parent / name) != digest:
            raise RuntimeError("BootROM proof artifact drift: " + name)
    return {"receipt": str(path.resolve()), "sha256": sha(path), "rom_sha256": proof["rom_sha256"],
            "scope": proof["scope"], "checks": proof["checks"], "actual_netlist_init_gate_required": True}


def without_mac(text):
    def cut(begin, end, replacement=""):
        nonlocal text
        if text.count(begin) != 1 or text.count(end) != 1:
            raise RuntimeError("exact old board wrapper boundary changed")
        a, b = text.index(begin), text.index(end)
        text = text[:a] + replacement + text[b:]
    text = text.replace("module soc_top_i1_network_ddr", "module soc_top_i1_cpu_ddr")
    cut("    input wire eth_rxc", "    output wire [16:0] c0_ddr4_adr",
        "    output wire eth_reset_gate,\n")
    cut('    (* DONT_TOUCH = "TRUE" *) BUFG tx_word_clock_buffer', "    // All board/UI")
    cut('    (* ASYNC_REG = "TRUE" *) reg [2:0] delay_reset_pipe;',
        "    wire [3:0] cpu_awid;", "    assign eth_reset_gate = 1'b1; // PHY held in reset; MAC omitted.\n")
    text = text.replace("    I1NetworkFpgaShell u_soc", "    I1PeripheralFpgaShell u_soc")
    text = text.replace("        .io_macTxClock(clk_tx_raw), .io_macRxClock(clk_rx),\n", "")
    cut("        .io_rgmii_rxRise", "        .io_ddrAxi_aw_bits_id")
    if any(x in text for x in ("u_rgmii", "u_soc/bank/gmac", ".io_rgmii", "EthernetPacketDma")):
        raise RuntimeError("MAC boundary survived no-MAC staging")
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--ip-reference", required=True, type=Path)
    ap.add_argument("--bootrom-receipt", required=True, type=Path,
        help="fresh actual CPU BootROM/UART proof; no bypass for a synthesized board")
    args = ap.parse_args()
    r = json.loads(args.receipt.read_text())
    if r["status"] not in ("PASS_I1_CPU_TIMING26_AFFECTED_SHORT_ONLY",
                            "PASS_I1_CPU_TIMING27_AFFECTED_SHORT_ONLY",
                            "PASS_I1_CPU_TIMING28_AFFECTED_SHORT_ONLY",
                            "PASS_I1_CPU_TIMING29_AFFECTED_SHORT_ONLY",
                            "PASS_I1_CPU_TIMING30_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING31_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING32_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY",
                       "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES):
        ap.error("fresh affected short PASS required; no stopped/failed receipt override")
    if r["status"] in ("PASS_I1_CPU_TIMING27_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING28_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING29_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING30_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING31_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING32_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY",
                       "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES) and (
            not r.get("performance_gates") or not all(r["performance_gates"].values())):
        ap.error("CoreMark recovery and stream performance gates must all pass")
    if r["status"] == "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY":
        from check_jtag_update import CHANGED, verify_external
        base_receipt = Path(r["base_receipt"])
        base = json.loads(base_receipt.read_text())
        base_board = Path(r["base_board"])
        if (sha(base_receipt) != r["base_receipt_sha256"] or
                sha(base_board / "board-manifest.json") != r["base_board_manifest_sha256"] or
                base["status"] != "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY" or
                len(base["checks"]) != 127 or len(base["performance_gates"]) != 18 or
                not all(base["performance_gates"].values()) or
                r["performance_gates"] != base["performance_gates"] or
                r["cpu_flags"] != base["cpu_flags"] or r["jtag_scan_bits"] != 65 or
                tuple(r["allowed_changed_base_sources"]) != CHANGED or
                len(r["checks"]) != 24):
            ap.error("exact JTAG-only affected proof / CPU base127/18 required")
        for name, digest in base["source_sha256"].items():
            if (sha(Path(r["base_source_snapshot"]) / name) != digest or
                    (name not in CHANGED and sha(ROOT / name) != digest)):
                ap.error("JTAG update changed unrelated CPU/source: " + name)
        for kind, status in (("chain", "PASS_I1_JTAG_SERIAL_CHAIN_XSIM"),
                             ("protocol", "PASS_I1_HALF_CYCLE_CDC_XSIM_ONLY")):
            receipt = Path(r[kind + "_receipt"])
            if sha(receipt) != r[kind + "_receipt_sha256"]:
                ap.error("changed xsim receipt: " + kind)
            proof = verify_external(receipt, status)
            if len(proof["cases"]) != (12 if kind == "chain" else 3):
                ap.error("missing serial TAP / protocol coverage")

    supplemental = {}
    supplemental_proof = None
    if r["status"] == "PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY":
        # The inherited harness allowlist predates this new boundary driver.
        # Its exact creation input was retained before launch and full-text
        # compared afterwards; require that explicit proof, do not mutate PASS.
        supplemental_file = args.receipt.parent / "supplemental-source-proof.json"
        supplemental_proof = json.loads(supplemental_file.read_text())
        path = "simulator/gsim/harness/line_read_preflight.cpp"
        if (supplemental_proof.get("status") != "PASS_NEW_DRIVER_EXACT_CREATION_INPUT" or
                supplemental_proof.get("path") != path or
                supplemental_proof.get("matches_exact_apply_patch_input_before_r4_launch") is not True or
                supplemental_proof.get("source_drift") != [] or
                sha(ROOT / path) != supplemental_proof.get("sha256")):
            ap.error("new independent preflight driver lacks its exact pre-launch source proof")
        supplemental[path] = supplemental_proof["sha256"]
    for name, digest in {**r["source_sha256"], **supplemental}.items():
        if sha(ROOT / name) != digest:
            ap.error("source/oracle drift: " + name)
    for name, digest in r["artifact_sha256"].items():
        if sha(args.receipt.parent / name) != digest:
            ap.error("short artifact drift: " + name)
    dependency_file = ROOT / "simulator/gsim/config/floating-point-dependencies.json"
    dependencies = json.loads(dependency_file.read_text())
    for name, digest in dependencies["local_sources_sha256"].items():
        if sha(ROOT / "third_party/berkeley-hardfloat/src/main/scala" / name) != digest:
            ap.error("pinned third-party HardFloat source drift: " + name)
    bandwidth_proof = None
    if r["status"] in BANDWIDTH_PROFILES:
        validate = {BANDWIDTH37: validate_bandwidth37, BANDWIDTH38: validate_bandwidth38,
                    BANDWIDTH39: validate_bandwidth39, BANDWIDTH40: validate_bandwidth40,
                    BANDWIDTH41: validate_bandwidth41, BANDWIDTH42: validate_bandwidth42,
                    BANDWIDTH43: validate_bandwidth43, BANDWIDTH44: validate_bandwidth44}[r["status"]]
        flags, bandwidth_proof = validate(r, args.receipt, ROOT)
    else:
        flags = r["cpu_flags"]["cpu-coherent"]
    for flag in ("--icache=32768", "--dcache=32768", "--soc-clock-hz=300000000",
                 "--coherent-caches", "--coherent-control-cuts", "--f", "--d", "--sv39"):
        if flag not in flags:
            ap.error("required target flag missing: " + flag)
    out = args.output.resolve()
    if out.parent != Path("/mnt/e/VM/Share/Valence-rtl") or not out.name.startswith("orbital-i1-cpu300-board-"):
        ap.error("explicit fresh isolated board directory required")
    selected = [x for x in flags if x != "--soc-no-bootrom"] + [
        "--soc-managed-uart", "--soc-jtag", "--soc-user-chain=2"]
    if r["status"] in ("PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES):
        selected += ["--soc-jtag-scan-bits=65"]
    bootrom_proof = validate_bootrom_proof(args.bootrom_receipt, selected)
    out.mkdir(exist_ok=False)
    rtl = out / "rtl"; rtl.mkdir()
    with (out / "export.log").open("w") as log:
        subprocess.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.I1PeripheralFpgaShellMain",
            str(rtl), "64", *selected], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        firtool = Path.home() / ".cache/llvm-firtool/1.135.0/bin/firtool"
        identity = subprocess.check_output([firtool, "--version"], text=True)
        if "CIRCT firtool-1.135.0" not in identity:
            raise RuntimeError("pinned firtool required")
        subprocess.run([firtool, rtl / "I1PeripheralFpgaShell.fir", "--split-verilog",
            "--lowering-options=disallowLocalVariables", "--preserve-values=named", "-o", rtl],
            stdout=log, stderr=subprocess.STDOUT, check=True)
    raw = rtl / "raw-memory-leaves"; raw.mkdir()
    bindings = parallel_instruction_bindings({
        p.name: p.read_text() for p in rtl.glob("I1CoherentLineCache*.sv")})
    array = re.compile(r"(?m)^([ \t]*)reg\s+\[(\d+):0\]\s+Memory\s*\[0:(\d+)\];")
    annotations = {}
    fanout_annotations = {}
    controller_annotations = {}
    misc_completion_annotations = {}
    rom_bindings = 0
    for p in rtl.glob("*.sv"):
        text = p.read_text()
        if r["status"] in (BANDWIDTH42, BANDWIDTH43, BANDWIDTH44) and p.name == "I1CoherentLineHome.sv":
            signal = "state" if r["status"] == BANDWIDTH42 else "stateStorage"
            text, count = re.subn(r"(?m)^([ \t]*)(reg\s+\[12:0\]\s+" + signal + r"\s*;)",
                r'\1(* EXTRACT_ENABLE = "no", FSM_ENCODING = "none" *)' + "\n" + r"\1\2", text)
            if count != 1:
                raise RuntimeError("explicit one-hot Home phase register missing")
            misc_completion_annotations[p.name] = {"signal":signal, "state_bits":13,
                "extract_enable":False, "fsm_encoding":"none"}
        if r["status"] in ("PASS_I1_CPU_TIMING29_AFFECTED_SHORT_ONLY",
                           "PASS_I1_CPU_TIMING30_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING31_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING32_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY",
                       "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES):
            if p.name == "I1FloatingPointExecute.sv":
                text, count = re.subn(
                    r"(?m)^([ \t]*)(wire[^\n;]*\bcapturePayloadEnable\b[^\n;]*;)",
                    r"\1(* MAX_FANOUT = 32 *)\n\1\2", text)
                if count != 1:
                    raise RuntimeError("named pure FPU capture enable binding missing")
                fanout_annotations[p.name] = {"signal": "capturePayloadEnable", "max_fanout": 32,
                    "count": count, "purpose": "local physical replicas; same logical owner and edge"}
            if p.name == "FiveStageMachineState.sv":
                text, count = re.subn(
                    r"(?m)^([ \t]*)(reg[^\n;]*\beffective(?:Lower|Upper)_\d+\s*;)",
                    r"\1(* MAX_FANOUT = 4 *)\n\1\2", text)
                if count != 16:
                    raise RuntimeError("PMP8 registered-bound fanout binding missing")
                fanout_annotations[p.name] = {"signals": "effectiveLower/Upper[0:8]", "max_fanout": 4,
                    "count": count, "purpose": "local comparator-bound replicas; no architectural state added"}
        if r["status"] in ("PASS_I1_CPU_TIMING30_AFFECTED_SHORT_ONLY", "PASS_I1_CPU_TIMING31_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING32_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY",
                       "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES):
            translation = re.fullmatch(r"FiveStageAddressTranslation(?:_\d+)?\.sv", p.name)
            cache = re.fullmatch(r"I1CoherentLineCache(?:_\d+)?\.sv", p.name)
            if translation or cache:
                width = 13 if translation else 12
                pattern = r"(?m)^([ \t]*)(reg\s+\[" + str(width - 1) + r":0\]\s+stateStorage\s*;)"
                text, count = re.subn(pattern,
                    r'\1(* EXTRACT_ENABLE = "no", FSM_ENCODING = "none" *)' + "\n" + r"\1\2", text)
                if count != 1:
                    raise RuntimeError("explicit onehot CPU controller binding missing: " + p.name)
                if translation:
                    text, faults = re.subn(r"(?m)^([ \t]*)(reg\s+localFaultZero\s*;)",
                        r"\1(* MAX_FANOUT = 16 *)" + "\n" + r"\1\2", text)
                    if faults != 1:
                        raise RuntimeError("registered local fault-payload marker missing")
                controller_annotations[p.name] = {"state_bits": width, "onehot": True,
                    "extract_enable": False, "fsm_encoding": "none",
                    "local_fault_marker_max_fanout": 16 if translation else None}
            if p.name in ("I1FloatingPointMiscS.sv", "I1FloatingPointMiscD.sv"):
                text, count = re.subn(r"(?m)^([ \t]*)(reg\s+finishedOwner\s*;)",
                    r"\1(* MAX_FANOUT = 32 *)" + "\n" + r"\1\2", text)
                if count != 1:
                    raise RuntimeError("registered FP completion predecode missing: " + p.name)
                misc_completion_annotations[p.name] = {"signal": "finishedOwner", "max_fanout": 32}
        match = array.search(text)
        if match:
            width, depth = int(match[2]) + 1, int(match[3]) + 1
            style = memory_style(p.name, width, depth, bindings)
            if r["status"] in (BANDWIDTH38, BANDWIDTH39, BANDWIDTH40, BANDWIDTH41, BANDWIDTH42, BANDWIDTH43, BANDWIDTH44) and p.stem.startswith("directoryBanks"):
                from check_directory_writer import inspect_leaf
                geometry = inspect_leaf(text)
                if (geometry["read_ports"] != 6 or
                        sha(p) != bandwidth_proof["directory_raw_leaf_sha256"]):
                    raise RuntimeError("actual board directory differs from short-tested LUTRAM leaf")
            if r["status"] in BANDWIDTH_PROFILES and p.stem.startswith("entries_32x"):
                if (width, depth) != (125, 32):
                    raise RuntimeError("banked125-bit/32-row BTB leaf geometry changed")
                style = "distributed"
            if p.stem.startswith("fetchClassBanks"):
                if not (r["status"] in ("PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY",
                        "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY",
                       "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES) and width == 64 and depth == 256):
                    raise RuntimeError("unexpected cached parcel metadata RAM geometry")
                style = "distributed"
            if style:
                if len(array.findall(text)) != 1:
                    raise RuntimeError("ambiguous RAM leaf")
                shutil.copy2(p, raw / p.name)
                attribute = "rom_style" if p.stem.startswith("storage") else "ram_style"
                text = array.sub(lambda m: m[1] + f'(* {attribute} = "{style}" *)\n' + m[0], text)
                annotations[p.name] = {"width": width, "depth": depth, "style": style,
                    "raw_sha256": sha(raw / p.name)}
        rom_bindings += text.count('"src/main/resources/inorder/bootrom.hex"')
        p.write_text(text.replace('"src/main/resources/inorder/bootrom.hex"', '"bootrom.hex"'))
    if rom_bindings != 1 or not bindings:
        raise RuntimeError("actual BootROM/per-way I-cache RAM binding missing")
    if r["status"] in ("PASS_I1_CPU_TIMING29_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING30_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING31_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING32_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY",
                       "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES) and len(fanout_annotations) != 2:
        raise RuntimeError("required explicit CPU300 local-fanout hints missing")
    if r["status"] in ("PASS_I1_CPU_TIMING30_AFFECTED_SHORT_ONLY", "PASS_I1_CPU_TIMING31_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING32_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY",
                       "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES) and (
            len(controller_annotations) != 4 or
            len(misc_completion_annotations) != (3 if r["status"] in (BANDWIDTH42, BANDWIDTH43, BANDWIDTH44) else 2)):
        raise RuntimeError("required onehot/FPU completion bindings missing")
    for name in bindings:
        a = annotations.get(name, {})
        if a.get("style") != "block" or a.get("width") != 64 or a.get("depth") != 256:
            raise RuntimeError("32KiB I-cache per-way BRAM binding missing")
    if r["status"] in ("PASS_I1_CPU_TIMING27_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING28_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING29_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING30_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING31_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING32_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY",
                       "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY",
                       "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES):
        modules = {item["module"] for items in bindings.values() for item in items}
        instances = sum(len(items) for items in bindings.values())
        if len(modules) != 2 or instances != 32:
            raise RuntimeError("both 32KiB caches require exact sixteen-bank per-way BRAM bindings")
    elif not any(x["style"] == "block" and x["depth"] == 512 and n.startswith("data")
                 for n, x in annotations.items()):
        raise RuntimeError("32KiB D-cache SRAM binding missing")
    if r["status"] in BANDWIDTH_PROFILES and not any(n.startswith("entries_32x") and
            a["style"] == "distributed" and a["width"] == 125 and a["depth"] == 32
            for n, a in annotations.items()):
        raise RuntimeError("same-capacity four-bank BTB distributed RAM binding missing")
    shutil.copy2(ROOT / "src/main/resources/inorder/bootrom.hex", rtl / "bootrom.hex")
    for name in ("ValenceI1BscanDebugPort.sv", "ValenceI1DmiCdc.sv"):
        source = ROOT / "src/main/resources/inorder" / name
        emitted = (rtl / name).read_text().removeprefix("// Generated by CIRCT firtool-1.135.0\n")
        if emitted.rstrip("\n") != source.read_text().rstrip("\n"):
            raise RuntimeError("USER2 resource binding changed")
        shutil.copy2(source, rtl / name)
    for p in rtl.glob("*.sv"):
        if p.stem.startswith(("TriSpeed", "Gmii", "EthernetPacketDma", "Rtl8211f")):
            raise RuntimeError("unwanted MAC/PHY/DMA in actual no-MAC elaboration: " + p.name)
    board = out / "board"; board.mkdir()
    (board / "soc_top_i1_cpu_ddr.sv").write_text(
        without_mac((HERE / "soc_top_i1_network_ddr.sv").read_text()))
    shutil.copy2(ROOT / "fpga/zu15eg/board_ddr.xdc", board / "board_ddr.xdc")
    shutil.copy2(args.ip_reference / "board/pl_ddr4_pins.xdc", board / "pl_ddr4_pins.xdc")
    (board / "phy_disabled.xdc").write_text(
        "set_property PACKAGE_PIN Y2 [get_ports eth_reset_gate]\n"
        "set_property IOSTANDARD LVCMOS18 [get_ports eth_reset_gate]\n"
        "set_property DRIVE 8 [get_ports eth_reset_gate]\n")
    scripts = out / "scripts"; scripts.mkdir()
    for name in ("build_board_cpu.tcl", "synth_board_cpu.tcl", "board_cpu_constraints.tcl", "prepare_board_mem.tcl",
                 "bscan_timing_i1.tcl", "audit_board_reset_cdc.tcl", "save_board_physopt.tcl",
                 "configure_board_mem.tcl", "audit_board_bootrom.tcl", "report_board_cpu_targets.tcl"):
        shutil.copy2(HERE / name, scripts / name)
    # Reuse only pure helper definitions, not the old MAC-specific invocation.
    old_constraints = (HERE / "board_constraints.tcl").read_text()
    helpers = old_constraints[old_constraints.index("proc i1_board_clock"):
        old_constraints.index("proc i1_real_board_constraints")]
    (scripts / "board_clock_helpers.tcl").write_text(helpers)
    for folder, name in (("fpga/zu15eg", "cdc_constraints.tcl"),
                         ("fpga/zu15eg", "native-gmac-cdc-constraints.tcl"),
                         ("fpga/next", "check_jtag_chain.tcl")):
        shutil.copy2(ROOT / folder / name, scripts / name)
    old_project = args.ip_reference / "project"
    project = out / "project"; project.mkdir()
    for suffix in ("cache", "gen", "srcs", "ip_user_files"):
        source = old_project / ("i1_board." + suffix)
        if source.exists():
            shutil.copytree(source, project / source.name)
    runs = project / "i1_board.runs"; runs.mkdir()
    for name in ("ddr4_0", "clk_wiz_i1", "axi_clock_converter_i1"):
        source = old_project / "i1_board.runs" / (name + "_synth_1")
        shutil.copytree(source, runs / source.name)
    tree = ET.parse(old_project / "i1_board.xpr")
    for parent in tree.getroot().iter():
        for child in list(parent):
            if child.tag == "File" and any(part in child.attrib.get("Path", "")
                    for part in ("$PPRDIR/../rtl/", "$PPRDIR/../board/")):
                parent.remove(child)
    tree.getroot().set("Path", str(project / "i1_board.xpr").replace("/mnt/e/", "E:/"))
    tree.write(project / "i1_board.xpr", encoding="UTF-8", xml_declaration=True)
    if r["status"] == "PASS_I1_CPU_TIMING33_AFFECTED_SHORT_ONLY" and (
            len(r.get("checks", {})) != 105 or len(r.get("performance_gates", {})) != 18 or
            "--cache-fetch-predecode" not in flags or
            not any(name.startswith("fetchClassBanks") and x["style"] == "distributed"
                for name, x in annotations.items())):
        ap.error("exact batch33 checks105/performance18 and real distributed parcel RAM required")
    if r["status"] in ("PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY",
                       "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY", *BANDWIDTH_PROFILES):
        required_inputs = ("simulator/gsim/harness/line_read_preflight.cpp",
            "simulator/gsim/harness/five_stage_increment.cpp",
            "simulator/gsim/harness/five_stage_jtag_timing.cpp",
            "src/main/scala/core/inorder/I1JtagRamLoader.scala")
        expected_checks = 37 if r["status"] == BANDWIDTH44 else 33 if r["status"] == BANDWIDTH43 else 27 if r["status"] == BANDWIDTH42 else 63 if r["status"] == BANDWIDTH41 else 49 if r["status"] == BANDWIDTH40 else 37 if r["status"] == BANDWIDTH39 else 29 if r["status"] in BANDWIDTH_PROFILES else (
            24 if r["status"] == "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY" else 127)
        if (len(r.get("checks", {})) != expected_checks or
                len(r.get("performance_gates", {})) != (13 if r["status"] in BANDWIDTH_PROFILES else 18) or
                "--cache-fetch-predecode" not in flags or "--indexed-data-proofs" not in flags or
                any(p not in r["source_sha256"] for p in required_inputs) or
                not (rtl / "I1JtagRamLoader.sv").is_file() or
                (rtl / "JtagRamLoader.sv").exists() or
                not any(name.startswith("fetchClassBanks") and x["style"] == "distributed"
                    for name, x in annotations.items())):
            ap.error("exact batch34 checks127/performance18, primary source closure, indexed D proofs, "
                "private JTAG and distributed parcel RAM required")
    if r["status"] == "PASS_I1_CPU_TIMING32_AFFECTED_SHORT_ONLY" and (
            len(r.get("checks", {})) != 89 or len(r.get("performance_gates", {})) != 18):
        ap.error("exact batch32 checks89/performance18 required")
    for name, digest in {**r["source_sha256"], **supplemental}.items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("source drift during board export")
    jtag_equivalence = None
    if r["status"] == "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY":
        previous = Path(r["base_board"]) / "rtl"
        before = {p.name: sha(p) for p in previous.glob("*.sv")}
        after = {p.name: sha(p) for p in rtl.glob("*.sv")}
        allowed = {"I1PeripheralFpgaShell.sv", "I1UartClockBank.sv",
                   "ValenceI1BscanDebugPort.sv"}
        changed = sorted(name for name in before if before[name] != after.get(name))
        if set(before) != set(after) or set(changed) != allowed:
            ap.error("JTAG-only CPU/SoC RTL identity failed: " + str(changed))
        def without_shell_source_locations(text):
            # Exact known CIRCT trailing source-location comments only; never
            # discard logic, attributes, arbitrary comments or CPU differences.
            return re.sub(r"\t// src/main/scala/core/inorder/I1PeripheralFpgaShell\.scala:[^\n]*",
                          "", text)
        for name in ("I1PeripheralFpgaShell.sv", "I1UartClockBank.sv"):
            old_text = without_shell_source_locations((previous / name).read_text())
            new_text = without_shell_source_locations((rtl / name).read_text())
            if name == "I1PeripheralFpgaShell.sv":
                new_text, count = re.subn(r"\.JTAG_CHAIN\(2\),\n    \.SCAN_BITS\(65\)",
                                         ".JTAG_CHAIN(2)", new_text)
                if count != 1:
                    ap.error("exact single USER2 scan-length parameter change required")
            if old_text != new_text:
                ap.error("unexpected shell/bank logic change beyond scan parameter: " + name)
        shell = (rtl / "I1PeripheralFpgaShell.sv").read_text()
        if not re.search(r"\.SCAN_BITS\s*\(\s*65\s*\)", shell):
            ap.error("real USER2 transport did not receive SCAN_BITS=65")
        jtag_equivalence = {"status": "PASS_EXACT_OTHER_SV_BYTES",
            "base_board": r["base_board"], "identical_sv_files": len(before) - len(changed),
            "changed_sv_files": changed, "scan_bits": 65,
            "uart_bank_logic_exact_after_only_source_location_comments": True,
            "shell_logic_exact_after_only_source_location_comments_and_scan_parameter": True,
            "cpu_performance_rerun": False, "inherited_cpu_checks": 127,
            "inherited_performance_gates": 18}
    manifest = {"status": "PASS_AFFECTED_SHORT_BOARD_STAGED_NOT_IMPLEMENTED", "mac": False,
        "part": "xczu15eg-ffvb1156-2-i",
        "top": "soc_top_i1_cpu_ddr", "cpu_hz": 300000000, "cache_bytes_each": 32768,
        "uart_hz": 50000000, "aon_hz": 50000000, "ddr_ui_hz": 250000000,
        "ddr_bytes": 2147483648, "axi_data_bits": 64, "uart_baud": 460800,
        "jtag_update_equivalence": jtag_equivalence, "bandwidth_short_proof": bandwidth_proof,
        "bootrom_short_proof": bootrom_proof, "synthesis_verilog_defines": ["ENABLE_INITIAL_MEM_"],
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_worktree_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "flags": selected, "source_sha256": {**r["source_sha256"], **supplemental},
        "supplemental_source_proof": supplemental_proof,
        "short_receipt": str(args.receipt.resolve()), "short_receipt_sha256": sha(args.receipt),
        "hardfloat_dependency_sha256": sha(dependency_file),
        "ip_reference": str(args.ip_reference), "reused_old_cpu": False,
        "memory_annotations": annotations, "parallel_instruction_ram_bindings": bindings,
        "physical_fanout_annotations": fanout_annotations,
        "controller_annotations": controller_annotations,
        "misc_completion_annotations": misc_completion_annotations,
        "cpu_extra_intraclock_hold_guard_ns": 0.080,
        "source_resources": {str(p.relative_to(ROOT)): sha(p) for p in HERE.glob("*")
            if p.is_file() and p.name in ("export_board_cpu.py", "board_short_proof.py", "check_directory_writer.py",
                "build_board_cpu.tcl", "synth_board_cpu.tcl", "audit_board_reset_cdc.tcl", "save_board_physopt.tcl",
                "prepare_board_mem.tcl", "configure_board_mem.tcl", "audit_board_bootrom.tcl", "check_bootrom_boot.py",
                "report_board_cpu_targets.tcl",
                "audit_batch39_short.py", "audit_batch40_short.py", "audit_batch41_short.py",
                "audit_board41_stage.py", "audit_batch42_short.py", "audit_board42_stage.py",
                "audit_batch43_short.py", "audit_board43_stage.py", "audit_batch44_short.py",
                "audit_board44_stage.py", "collect_board_candidate.py",
                "write_board_bit.tcl", "collect_bootrom_delivery.py",
                "board_cpu_constraints.tcl", "soc_top_i1_network_ddr.sv", "board_constraints.tcl")},
        "files_sha256": {str(p.relative_to(out)): sha(p) for folder in (rtl, board, scripts)
            for p in folder.rglob("*") if p.is_file()},
        "reused_ip_sha256": {str(p.relative_to(project)): sha(p) for p in project.rglob("*")
            if p.is_file() and p.suffix in (".xci", ".dcp")},
        "physical_qualified": False, "board_qualified": False, "bit_generated": False}
    (out / "board-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": manifest["status"], "output": str(out)}), flush=True)


if __name__ == "__main__":
    main()
