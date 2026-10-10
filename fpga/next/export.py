#!/usr/bin/env python3
"""Freeze source identity and export one FPGA-next profile; never run Vivado.

The reference source hashes bind what was actually emitted, not the historical
baseline commit label. Staging a local implementation is a separate operation.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
_media_spec = importlib.util.spec_from_file_location("valence_media_integration", HERE / "media_integration.py")
media_integration = importlib.util.module_from_spec(_media_spec)
_media_spec.loader.exec_module(media_integration)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    files = [p for folder in ("src/main/scala", "third_party/berkeley-hardfloat/src/main/scala")
             for p in (ROOT / folder).rglob("*.scala")]
    files += [ROOT / name for name in ("build.mill", ".mill-version",
        "src/test/scala/ooo/FpgaNextMain.scala", "fpga/next/baseline.json", "fpga/next/export.py",
        "fpga/next/soc_top_fpga_next_ddr.sv", "fpga/zu15eg/soc_top_gmac_ddr.sv", "fpga/next/check_jtag_chain.tcl",
        "fpga/next/media_integration.py", "fpga/next/performance.py", *media_integration.INPUTS)]
    # Blackbox SV/resources are functional source, never omit them from a binding.
    for folder in ("src/main/resources", "fpga/next/rtl"):
        if (ROOT / folder).exists():
            files += [p for p in (ROOT / folder).rglob("*") if p.is_file()]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(files))}


def bscan_board_wrapper(text):
    ports = "    input wire jtag_tck, jtag_tms, jtag_tdi, jtag_trst_n, jtag_debug_por_n,\n    output wire jtag_tdo, jtag_tdo_oe,\n"
    reset = "    wire board_reset = ~sys_rst_n | ~button_n;"
    if text.count(ports) != 1 or text.count(reset) != 1:
        raise RuntimeError("board wrapper debug/reset binding changed; re-review required")
    text = text.replace(ports, "")
    text = text.replace(reset, reset + "\n    // Existing hard FPGA TAP supplies BSCAN; no extra package JTAG pins.\n"
        "    wire jtag_tck = 1'b0, jtag_tms = 1'b1, jtag_tdi = 1'b0, jtag_trst_n = 1'b1;\n"
        "    wire jtag_debug_por_n = ~board_reset;\n    wire jtag_tdo, jtag_tdo_oe;")
    return text.replace("// JTAG reservation pins deliberately have no package assignments here.",
        "// BSCAN candidate: existing FPGA JTAG connector; cold board reset supplies debug POR.")


def bscan_legacy_board_wrapper(text):
    instance = "    BoardSocTop u_soc ("
    reset = "    wire board_reset = ~sys_rst_n | ~button_n;"
    if text.count(instance) != 1 or text.count(reset) != 1:
        raise RuntimeError("legacy board wrapper debug/reset binding changed; re-review required")
    return text.replace(instance,
        "    // Boot-only USER-chain downloader; physical JTAG belongs to BSCANE2.\n"
        "    FpgaNextSocTop u_soc (\n"
        "        .jtag_tck(1'b0), .jtag_tms(1'b1), .jtag_tdi(1'b0), .jtag_trstN(1'b1),\n"
        "        .jtag_debugPorN(~board_reset), .jtag_tdo(), .jtag_tdoOe(),")

def check_wrapper_ports(wrapper, top):
    declaration = re.search(r"\bmodule\s+FpgaNextSocTop\s*\((.*?)\);", top, re.S)
    instance = re.search(r"\bFpgaNextSocTop\s+u_soc\s*\((.*?)\);", wrapper, re.S)
    if not declaration or not instance:
        raise RuntimeError("missing exact top declaration/board instance")
    # CIRCT emits ordinary ANSI ports; obtain the final identifier of each
    # comma-separated declaration (including grouped same-direction ports).
    ports = {re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", part)[-1]
             for part in declaration.group(1).split(",") if part.strip()}
    connected = re.findall(r"\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(", instance.group(1))
    missing = set(connected) - ports
    if missing or len(connected) != len(set(connected)):
        raise RuntimeError("board wrapper/top named-port mismatch: " + str(sorted(missing)))
    if ports - set(connected):
        raise RuntimeError("board wrapper leaves top ports unbound: " + str(sorted(ports - set(connected))))
    return len(connected)


def main(argv=None, expected_profile_sha256=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    debug = ap.add_mutually_exclusive_group()
    debug.add_argument("--experimental-jtag-stub", action="store_true",
                    help="emit unqualified TAP/DTM with fail-only endpoint; never enables CPU halt/resume")
    debug.add_argument("--experimental-jtag-ram", action="store_true",
                       help="boot-owned RAM download through standalone soft TAP; no hart debug")
    debug.add_argument("--experimental-jtag-bscan", type=int, choices=(1, 2, 3, 4),
                       help="boot-owned RAM download through explicitly allocated FPGA USER chain")
    ap.add_argument("--experimental-trispeed-ethernet", action="store_true",
                    help="emit logic-qualified tri-speed media; native clocks/pads/CDC remain unqualified")
    choice = ap.add_mutually_exclusive_group()
    choice.add_argument("--reference", action="store_true", help="emit register-topology control with common correctness fixes")
    choice.add_argument("--storage-candidate", action="store_true", help="emit the earlier storage-only candidate for ablation")
    ap.add_argument("--emit", action="store_true", help="actually elaborate; default only validates the locked profile")
    ap.add_argument("--virtual-ram-load-precheck", action="store_true")
    ap.add_argument("--prechecked-data-flow", action="store_true")
    ap.add_argument("--lsu-entries", type=int, choices=(2, 4), default=2)
    ap.add_argument("--data-translation-entries", type=int, choices=(4, 8, 16, 32), default=8,
                    help="D-TLB capacity only; I-TLB remains 8 and PTE cache remains 4")
    ap.add_argument("--physical-load-ingress-flow", action="store_true")
    ap.add_argument("--translated-response-empty-flow", action="store_true",
                    help="default-off local response flow retaining registered request and permission boundaries")
    ap.add_argument("--prepared-store-lookahead", action="store_true",
                    help="default-off reconstructed prepared physical RAM store prefill")
    ap.add_argument("--load-order-older-retire", action="store_true")
    ap.add_argument("--fetch-previous-packet", action="store_true",
                    help="retain the previous registered fetch packet; explicit default-off experiment")
    ap.add_argument("--independent-fetch-payload-capture", action="store_true")
    ap.add_argument("--owner-local-issue-ready", action="store_true")
    ap.add_argument("--shared-fetch-pmp-relations", action="store_true")
    ap.add_argument("--share-protected-head-payload", action="store_true")
    ap.add_argument("--banked-instruction-data", action="store_true")
    ap.add_argument("--prefetch-break-on-store", action="store_true")
    ap.add_argument("--store-next-line-prefetch", action="store_true")
    ap.add_argument("--store-prefetch-mru-insertion", action="store_true")
    ap.add_argument("--posted-store-merge", action="store_true",
                    help="default-off physical committed-store merge candidate")
    ap.add_argument("--dma-line-transfers", action="store_true", help="experimental coherent 64-byte memory-copy DMA")
    ap.add_argument("--dma-line-entries", type=int, choices=(1, 2, 4), default=1)
    ap.add_argument("--dma-line-yield-cycles", type=int, choices=(0, 4, 8, 16, 32, 64), default=0)
    ap.add_argument("--prefetch-candidate-cycles", type=int, choices=(1, 3, 16), default=1)
    a = ap.parse_args(argv)
    if a.posted_store_merge and a.prechecked_data_flow:
        ap.error("--posted-store-merge excludes --prechecked-data-flow until separately qualified")
    if a.store_prefetch_mru_insertion and not a.store_next_line_prefetch:
        ap.error("--store-prefetch-mru-insertion requires --store-next-line-prefetch")
    if a.dma_line_entries != 1 and not a.dma_line_transfers:
        ap.error("multiple DMA line owners require --dma-line-transfers")
    if a.dma_line_yield_cycles and not a.dma_line_transfers:
        ap.error("line yield requires --dma-line-transfers")
    if a.prechecked_data_flow and not a.virtual_ram_load_precheck:
        ap.error("prechecked data flow requires --virtual-ram-load-precheck")
    profile = json.loads((HERE / "baseline.json").read_text())
    selected = not (a.reference or a.storage_candidate)
    features = {
        "independent_fetch_payload_capture": selected or a.independent_fetch_payload_capture,
        "owner_local_issue_ready": selected or a.owner_local_issue_ready,
        "shared_fetch_pmp_relations": selected or a.shared_fetch_pmp_relations,
        "share_protected_head_payload": selected or a.share_protected_head_payload,
        "banked_instruction_data": selected or a.banked_instruction_data}
    if a.reference and features["share_protected_head_payload"]:
        ap.error("protected head sharing requires the banked issue payload in a candidate profile")
    complete = not a.reference and all(features.values())
    profile["profile"].update(features)
    profile["profile"]["name"] = "fpga-next-selected-v2" if complete else (
        "fpga-next-reference-topology-v1" if a.reference else "fpga-next-storage-v1")
    if not complete:
        for key, suffix in (("independent_fetch_payload_capture", "fetch-capture"),
            ("owner_local_issue_ready", "owner-ready"), ("shared_fetch_pmp_relations", "shared-pmp"),
            ("share_protected_head_payload", "shared-head"), ("banked_instruction_data", "banked-idata")):
            if features[key]:
                profile["profile"]["name"] += "-" + suffix
    profile["profile"]["prefetch_candidate_cycles"] = a.prefetch_candidate_cycles
    if a.prefetch_candidate_cycles != 1:
        profile["profile"]["name"] += "-prefetch-retry" + str(a.prefetch_candidate_cycles)
    profile["profile"]["prefetch_break_on_store"] = a.prefetch_break_on_store
    if a.prefetch_break_on_store:
        profile["profile"]["name"] += "-store-break"
    profile["profile"]["virtual_ram_load_precheck"] = a.virtual_ram_load_precheck
    if a.virtual_ram_load_precheck:
        profile["profile"]["name"] += "-virtual-precheck"
    profile["profile"]["data_translation_entries"] = a.data_translation_entries
    profile["profile"]["instruction_translation_entries"] = 8
    profile["profile"]["pte_cache_entries"] = 4
    if a.data_translation_entries != 8:
        profile["profile"]["name"] += "-dtlb" + str(a.data_translation_entries)
    profile["profile"]["prechecked_data_flow"] = a.prechecked_data_flow
    profile["profile"]["physical_load_ingress_flow"] = a.physical_load_ingress_flow
    profile["profile"]["translated_response_empty_flow"] = a.translated_response_empty_flow
    if a.prechecked_data_flow:
        profile["profile"]["name"] += "-prechecked-flow"
    if a.physical_load_ingress_flow:
        profile["profile"]["name"] += "-physical-ingress-flow"
    if a.translated_response_empty_flow:
        profile["profile"]["name"] += "-translated-response-empty-flow"
    profile["profile"]["load_order_older_retire"] = a.load_order_older_retire
    profile["profile"]["lsu_entries"] = a.lsu_entries
    if a.lsu_entries != 2:
        profile["profile"]["name"] += "-lsu" + str(a.lsu_entries)
    if a.load_order_older_retire:
        profile["profile"]["name"] += "-older-load-retire"
    profile["profile"]["fetch_previous_packet"] = a.fetch_previous_packet
    if a.fetch_previous_packet:
        profile["profile"]["name"] += "-fetch-previous-packet"
    profile["profile"]["prepared_store_lookahead"] = a.prepared_store_lookahead
    if a.prepared_store_lookahead:
        profile["profile"]["name"] += "-prepared-store-lookahead"
    profile["profile"]["store_next_line_prefetch"] = a.store_next_line_prefetch
    if a.store_next_line_prefetch:
        profile["profile"]["name"] += "-checked-store-prefetch"
    profile["profile"]["store_prefetch_mru_insertion"] = a.store_prefetch_mru_insertion
    if a.store_prefetch_mru_insertion:
        profile["profile"]["name"] += "-store-prefetch-mru"
    profile["profile"]["posted_store_merge"] = a.posted_store_merge
    if a.posted_store_merge:
        profile["profile"]["name"] += "-posted-store-merge"
    profile["profile"]["experimental_trispeed_ethernet"] = a.experimental_trispeed_ethernet
    profile["profile"]["tri_speed_tx_frame_slots"] = 2 if a.experimental_trispeed_ethernet else 1
    if a.experimental_trispeed_ethernet:
        profile["profile"]["name"] += "-experimental-trispeed"
    profile["profile"]["dma_line_transfers"] = a.dma_line_transfers
    profile["profile"]["dma_line_entries"] = a.dma_line_entries
    profile["profile"]["dma_line_yield_cycles"] = a.dma_line_yield_cycles
    if a.dma_line_transfers:
        profile["profile"]["name"] += "-dma-lines"
    if a.dma_line_entries > 1:
        profile["profile"]["name"] += "-owners" + str(a.dma_line_entries)
    if a.dma_line_yield_cycles:
        profile["profile"]["name"] += "-yield" + str(a.dma_line_yield_cycles)
    profile["profile"]["banked_issue_payload"] = not a.reference
    profile["profile"]["banked_fetch_hints"] = not a.reference
    profile["profile"]["fp_state_ram"] = not a.reference
    profile["profile"]["fp_shared_rounders"] = not a.reference
    profile["profile"]["banked_cache_tags"] = not a.reference
    profile["profile"]["fp_shared_product"] = not a.reference
    profile["profile"]["jtag_pins_reserved"] = not bool(a.experimental_jtag_bscan)
    profile["profile"]["jtag_transport_experimental"] = bool(a.experimental_jtag_stub or a.experimental_jtag_ram or a.experimental_jtag_bscan)
    profile["profile"]["jtag_ram_download"] = bool(a.experimental_jtag_ram or a.experimental_jtag_bscan)
    profile["profile"]["jtag_backend"] = "bscan-user-v1" if a.experimental_jtag_bscan else "standalone-dtm"
    profile["profile"]["bscan_chain"] = a.experimental_jtag_bscan
    profile["profile"]["debug_module_implemented"] = False
    if expected_profile_sha256 is not None:
        digest = hashlib.sha256(json.dumps(profile["profile"], sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        if digest != expected_profile_sha256:
            ap.error("performance preset full profile changed; requalification required")
    before = sources()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError("unresolved source revision")
    output = a.output.resolve()
    if output.exists():
        raise RuntimeError("refusing existing export output: " + str(output))
    rtl = output / "rtl"
    command = ["mill", "-i", "IonSoC.test.runMain", "ooo.FpgaNextMain", str(rtl)]
    command.append("--reference" if a.reference else "--candidate" if a.storage_candidate else "--selected")
    command.append("--data-translation-entries=" + str(a.data_translation_entries))
    if a.share_protected_head_payload:
        command.append("--share-protected-head-payload")
    if a.banked_instruction_data:
        command.append("--banked-instruction-data")
    if a.owner_local_issue_ready:
        command.append("--owner-local-issue-ready")
    if a.shared_fetch_pmp_relations:
        command.append("--shared-fetch-pmp-relations")
    if a.experimental_trispeed_ethernet:
        command.append("--experimental-trispeed-ethernet")
    if a.independent_fetch_payload_capture:
        command.append("--independent-fetch-payload-capture")
    if a.experimental_jtag_stub:
        command.append("--experimental-jtag-stub")
    if a.experimental_jtag_ram:
        command.append("--experimental-jtag-ram")
    if a.experimental_jtag_bscan:
        command.append("--experimental-jtag-bscan=" + str(a.experimental_jtag_bscan))
    if a.dma_line_transfers:
        command.append("--dma-line-transfers")
    if a.dma_line_entries > 1:
        command.append("--dma-line-entries=" + str(a.dma_line_entries))
    if a.dma_line_yield_cycles:
        command.append("--dma-line-yield-cycles=" + str(a.dma_line_yield_cycles))
    if a.prefetch_break_on_store:
        command.append("--prefetch-break-on-store")
    if a.prefetch_candidate_cycles != 1:
        command.append("--prefetch-candidate-cycles=" + str(a.prefetch_candidate_cycles))
    if a.virtual_ram_load_precheck:
        command.append("--virtual-ram-load-precheck")
    if a.prechecked_data_flow:
        command.append("--prechecked-data-flow")
    if a.lsu_entries != 2:
        command.append("--lsu-entries=" + str(a.lsu_entries))
    if a.physical_load_ingress_flow:
        command.append("--physical-load-ingress-flow")
    if a.translated_response_empty_flow:
        command.append("--translated-response-empty-flow")
    if a.load_order_older_retire:
        command.append("--load-order-older-retire")
    if a.fetch_previous_packet:
        command.append("--fetch-previous-packet")
    if a.prepared_store_lookahead:
        command.append("--prepared-store-lookahead")
    if a.store_next_line_prefetch:
        command.append("--store-next-line-prefetch")
    if a.store_prefetch_mru_insertion:
        command.append("--store-prefetch-mru-insertion")
    if a.posted_store_merge:
        command.append("--posted-store-merge")
    if not a.emit:
        print(json.dumps({"status": "PREFLIGHT_ONLY", "profile": profile["profile"]["name"],
            "git_head": head, "source_files": len(before), "output": str(output),
            "virtual_ram_load_precheck": a.virtual_ram_load_precheck,
            "data_translation_entries": a.data_translation_entries,
            "instruction_translation_entries": 8, "pte_cache_entries": 4,
            "fetch_previous_packet": a.fetch_previous_packet,
            "prepared_store_lookahead": a.prepared_store_lookahead,
            "translated_response_empty_flow": a.translated_response_empty_flow,
            "posted_store_merge": a.posted_store_merge,
            "physical_qualification": False, "configuration": profile["profile"],
            "command": command}, indent=2))
        return
    output.mkdir(parents=True)
    receipt = {"schema": "valence-fpga-next-export-v1", "status": "RUNNING",
        "baseline_source_commit": profile["source_commit"], "git_head": head,
        "source_sha256": before, "profile": profile["profile"],
        "virtual_ram_load_precheck": a.virtual_ram_load_precheck,
        "command": command, "synthesis": False, "physical_qualification": False}
    try:
        started = time.monotonic()
        with (output / "elaborate.log").open("w") as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
        receipt["seconds"] = time.monotonic() - started
        receipt["exit"] = result.returncode
        if result.returncode:
            raise RuntimeError("RTL export failed; see " + str(output / "elaborate.log"))
        if before != sources():
            raise RuntimeError("source changed during export")
        inventory = {p.relative_to(output).as_posix(): sha(p) for p in sorted(rtl.rglob("*")) if p.is_file()}
        if not inventory or not any(name.endswith(".sv") for name in inventory):
            raise RuntimeError("no SystemVerilog export")
        # firtool's list can omit HasBlackBoxResource source. Add only the
        # explicitly audited debug resource; never glob verification layers.
        listed = []
        filelist = rtl / "filelist.f"
        if filelist.exists():
            listed = [line.strip() for line in filelist.read_text().splitlines()
                      if line.strip() and not line.strip().startswith("#")]
        if not listed:
            listed = ["FpgaNextSocTop.sv"]
        resources = (["ValenceJtagDebugPort.sv"] if
            a.experimental_jtag_stub or a.experimental_jtag_ram or a.experimental_jtag_bscan else [])
        if a.experimental_jtag_bscan:
            resources.append("ValenceBscanDebugPort.sv")
        for name in resources:
            resource = rtl / name
            if not resource.is_file():
                raise RuntimeError("enabled debug resource missing from export: " + name)
            if resource.name not in listed:
                listed.append(resource.name)
        if a.experimental_jtag_bscan or a.experimental_trispeed_ethernet:
            # Match the existing selected GMII board by default; tri-speed remains
            # an independent explicit option. Never deliver mismatched top ports.
            if a.experimental_trispeed_ethernet:
                source = HERE / "soc_top_fpga_next_ddr.sv"
                wrapper = source.read_text()
                if a.experimental_jtag_bscan:
                    wrapper = bscan_board_wrapper(wrapper)
                media = "experimental-trispeed"
            else:
                source = ROOT / "fpga/zu15eg/soc_top_gmac_ddr.sv"
                wrapper = bscan_legacy_board_wrapper(source.read_text())
                media = "existing-gmii-baseline"
            connected_ports = check_wrapper_ports(wrapper, (rtl / "FpgaNextSocTop.sv").read_text())
            (output / "board").mkdir()
            path = output / "board" / source.name
            path.write_text(wrapper)
            receipt["board_wrapper"] = {"path": str(path.relative_to(output)), "sha256": sha(path),
                "source": str(source.relative_to(ROOT)), "source_sha256": sha(source), "media": media,
                "requires": "matching board/IP composition; debug allocation and CDC/RDC signoff",
                "debug_por_source": "existing sys_rst_n/button_n whole-board reset" if a.experimental_jtag_bscan
                    else "reserved external debug POR; no package mapping assigned",
                "additional_jtag_package_pins": 0 if a.experimental_jtag_bscan else 7,
                "named_ports_checked": connected_ports, "qualified": False}
            if a.experimental_trispeed_ethernet:
                receipt["tri_speed_native_integration"] = media_integration.stage(ROOT, output)
        if a.experimental_jtag_bscan:
            guard = output / "board/check_jtag_chain.tcl"
            guard.write_text((HERE / "check_jtag_chain.tcl").read_text())
            required = output / "board/require_jtag_chain.tcl"
            required.write_text("# Mandatory read-only post-synthesis gate; exact cell required.\n"
                "source [file join [file dirname [info script]] check_jtag_chain.tcl]\n"
                "if {![info exists VALENCE_JTAG_OWN_CELL]} {error {Set exact VALENCE_JTAG_OWN_CELL from the open synthesized design}}\n"
                "valence_assert_jtag_chain " + str(a.experimental_jtag_bscan) + " $VALENCE_JTAG_OWN_CELL\n")
            receipt["required_post_synthesis_gate"] = {"path": str(required.relative_to(output)),
                "sha256": sha(required), "guard_sha256": sha(guard), "status": "NOT_RUN_NO_VIVADO",
                "must_pass_before_implementation_or_bitstream": True}
        if before != sources():
            raise RuntimeError("source changed during board integration staging")
        for name in listed:
            item = Path(name)
            if item.is_absolute() or ".." in item.parts or not (rtl / item).is_file():
                raise RuntimeError("unsafe/missing synthesis filelist item: " + name)
        (output / "synthesis-files.f").write_text("".join("rtl/" + name + "\n" for name in listed))
        receipt["synthesis_filelist_sha256"] = sha(output / "synthesis-files.f")
        receipt["rtl_sha256"] = inventory
        receipt["status"] = "PASS_RTL_EXPORT_ONLY"
        receipt["limitations"] = ["No FPGA synthesis, routed timing, CDC or board qualification",
            "External DDR, clock, UART/GMAC domain and PHY wrappers still require matched board integration",
            "No bitstream generated"]
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = str(error)
        raise
    finally:
        if (output / "elaborate.log").exists():
            receipt["log_sha256"] = sha(output / "elaborate.log")
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("PASS_RTL_EXPORT_ONLY " + str(output / "receipt.json"))


if __name__ == "__main__":
    main()
