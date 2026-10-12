#!/usr/bin/env python3
"""One source-frozen FPGA-next board model for short RV64GC and DDR checks.

Does not run Linux, native GMAC/PHY, Vivado, or a full GSIM regression. All model
objects are reusable only inside this exact source/profile checkpoint. Baseline
and candidate outputs must use distinct tags.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import run as common
from mshr_occupancy import validate
from memory_capacity_geometry import verify_memory_geometry
from backend_capacity_geometry import verify_backend_capacity
from posted_cpu.verify_model import verify_posted_model
from build_virtual_load_core import build as build_virtual_guest
from virtual_load_board import parse as parse_virtual_metrics


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def marker(elf, name):
    dis = subprocess.check_output(["riscv64-unknown-elf-objdump", "-d", elf], text=True)
    section = dis.split("<" + name + ">:", 1)[1].split("\n\n", 1)[0]
    pcs = re.findall(r"^\s*([0-9a-f]+):.*\brdtime\b", section, re.M)
    if len(pcs) != 1:
        raise RuntimeError("missing/ambiguous timing marker: " + name)
    return int(pcs[0], 16)


def source_inventory():
    files = sorted((common.ROOT / "src").rglob("*.scala"))
    files += sorted((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").rglob("*.scala"))
    files += sorted((common.HERE / "harness").glob("*.h"))
    files += [common.HERE / "harness" / n for n in ("board_boot.cpp", "board_memory_steady.cpp", "rv64gc_board.cpp", "virtual_load_board.cpp")]
    files += [common.ROOT / n for n in ("build.mill", ".mill-version", "fpga/next/baseline.json",
        "fpga/firmware/sample_app.ld", "fpga/firmware/board_memory.h", "fpga/firmware/sample_start.S",
        "fpga/firmware/ddr_bench.c",
        "fpga/firmware/rv64gc_smoke.S", "simulator/gsim/payloads/board_memory_steady.c",
        "simulator/gsim/payloads/board_memory_independent.c", "simulator/gsim/payloads/board_memory_mixed_stores.c",
        "simulator/gsim/payloads/virtual_load_core.S",
        "simulator/gsim/payloads/virtual_load_core.ld", "simulator/gsim/build_virtual_load_core.py",
        "simulator/gsim/virtual_load_board.py", "simulator/gsim/run.py", "simulator/gsim/mshr_occupancy.py", "simulator/gsim/memory_capacity_geometry.py", "simulator/gsim/backend_capacity_geometry.py", "simulator/gsim/fpga_next_board.py", "simulator/gsim/posted_cpu/verify_model.py")]
    return {str(p.relative_to(common.ROOT)): sha(p) for p in sorted(set(files))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--preflight-only", action="store_true", help="print exact profile; do not create outputs or build")
    ap.add_argument("--variant", choices=("reference", "candidate", "selected"), default="reference")
    ap.add_argument("--lsu-entries", type=int, choices=(2, 4), default=2)
    ap.add_argument("--rob-entries", type=int, choices=(16, 32, 64), action="append",
                    help="explicit ROB capacity experiment; omitted preserves the selected profile")
    ap.add_argument("--physical-regs", type=int, choices=(48, 64), action="append",
                    help="explicit integer PRF capacity experiment; omitted preserves the selected profile")
    ap.add_argument("--data-translation-entries", type=int, choices=(4, 8, 16, 32), default=8,
                    help="D-TLB capacity only; I-TLB remains 8 and PTE cache remains 4")
    ap.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    ap.add_argument("--virtual-ram-load-precheck", action="store_true")
    ap.add_argument("--prechecked-data-flow", action="store_true")
    ap.add_argument("--physical-load-ingress-flow", action="store_true")
    ap.add_argument("--ddr-write-collection-flow", action="count", default=0,
                    help="default-off registered DDR write collection / AXI W overlap")
    ap.add_argument("--line-transfer-dispatch-flow", action="count", default=0,
                    help="default-off bounded home/line-engine dispatch bypass")
    ap.add_argument("--line-read-channel", action="count", default=0,
                    help="default-off independent home read ingress and whole-line return")
    ap.add_argument("--translated-response-empty-flow", action="store_true",
                    help="default-off local empty response flow; retains registered request and permission boundaries")
    ap.add_argument("--prepared-store-lookahead", action="store_true",
                    help="default-off reconstructed prepared physical RAM store prefill")
    ap.add_argument("--posted-preparation-priority", action="store_true",
                    help="default-off age-ordered prepared stores during an all-load posted window")
    ap.add_argument("--reconstruct-issue-token-index", action="count", default=0,
                    help="default-off reconstruction of issue-token ROB indices from their owning rows")
    ap.add_argument("--shared-memory-address-state", action="count", default=0,
                    help="default-off shared address metadata for memory preparation and load launch")
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
    ap.add_argument("--split-prefetch-tracking", action="count", default=0,
                    help="default-off separate read/store resident prefetch tokens with cross-protection")
    ap.add_argument("--durable-read-prefetch-candidate", action="count", default=0,
                    help="default-off finite READ resource/ordinary resident STORE wait")
    ap.add_argument("--read-prefetch-behind-store", action="count", default=0,
                    help="default-off READ capture behind exactly one STORE PF; requires durable retention")
    ap.add_argument("--read-prefetch-store-hold", action="count", default=0,
                    help="default-off finite read-candidate retention across accepted ordinary store hits")
    ap.add_argument("--read-prefetch-demand-adoption", action="count", default=0,
                    help="default-off demand attachment to an issued read prefetch; requires independent split tracking")
    ap.add_argument("--read-prefetch-dirty-retry", action="count", default=0,
                    help="default-off read prefetch dirty-victim retry; requires split prefetch tracking")
    ap.add_argument("--store-prefetch-mru-insertion", action="store_true")
    ap.add_argument("--store-prefetch-lru-victim", action="store_true",
                    help="default-off store-origin invalid-first/LRU victim experiment")
    ap.add_argument("--distinct-way-release", action="store_true",
                    help="default-off issued-store-PF/read other-way dirty release experiment")
    ap.add_argument("--frozen-store-proof-transport", action="store_true",
                    help="default-off full frozen actual-store payload, independent of frontier scheduling")
    ap.add_argument("--pending-virtual-store-proof", action="store_true",
                    help="default-off R16/PRF48 pending-store proof and bounded early-load credits")
    ap.add_argument("--bound-head-store-overlap", action="store_true",
                    help="default-off bound head store into an idle LSU beside saved disjoint younger loads")
    ap.add_argument("--aligned-fetch-permission-stage", action="count", default=0,
                    help="default-off aligned fetch permission token experiment")
    ap.add_argument("--shared-lane1-owner-match", action="count", default=0,
                    help="default-off lane-1 reuse of the pure registered ROB tag equality")
    ap.add_argument("--registered-canonical-store-event", action="count", default=0,
                    help="default-off canonical certificate event and matching backend lifecycle stage")
    ap.add_argument("--registered-pending-store-query", action="count", default=0,
                    help="default-off registered shared proof query; requires pending-store proofs")
    ap.add_argument("--pending-ready-store-bypass", action="count", default=0,
                    help="default-off bypass of proved data-ready non-head stores; requires bound head overlap")
    ap.add_argument("--pending-virtual-store-proof-slots", type=int, choices=(1, 2), default=1)
    ap.add_argument("--pending-store-early-load-credits", type=int, choices=(1, 2), default=1,
                    help="bounded total of reserved plus active early-load responsibilities; default 1")
    ap.add_argument("--memory-proof-frontier", action="store_true",
                    help="default-off unqualified bounded proof frontier; reviewed ROB64/PRF64/LSU4 only")
    ap.add_argument("--canonical-virtual-store-overlap", action="store_true",
                    help="default-off checked virtual-store to disjoint prechecked-load overlap")
    ap.add_argument("--posted-prefetch-head-offer", action="store_true",
                    help="default-off staged posted head offer while only PF remains busy")
    ap.add_argument("--posted-prefetch-coexistence", action="store_true",
                    help="default-off prefetch in empty posted-work windows")
    ap.add_argument("--posted-store-merge", action="store_true",
                    help="default-off physical committed-store merge candidate")
    ap.add_argument("--dma-line-transfers", action="store_true")
    ap.add_argument("--dma-line-entries", type=int, choices=(1, 2, 4, 8), default=1)
    ap.add_argument("--ddr-outstanding", type=int, choices=(4, 8), action="append")
    ap.add_argument("--ddr-write-credits", type=int, choices=(1, 2, 4), action="append")
    ap.add_argument("--dtlb-write-read-reuse", action="count", default=0,
                    help="default-off successful-write DTLB permission reuse and same-page upgrade")
    ap.add_argument("--translation-hit-flow", action="count", default=0,
                    help="default-off demand TLB hit to registered checked boundary")
    ap.add_argument("--independent-demand-admission", action="count", default=0,
                    help="default-off authorized LSU handoff and full-way cache demand admission")
    ap.add_argument("--dma-line-yield-cycles", type=int, choices=(0, 4, 8, 16, 32, 64), default=0)
    ap.add_argument("--prefetch-candidate-cycles", type=int, choices=(1, 3, 16), default=1,
                    help="bounded prefetch retention experiment; default keeps the inherited one-attempt policy")
    ap.add_argument("--mixed-store-stream", action="store_true",
                    help="also run identical 64KiB read streams with one scratch store every16/64 lines")
    ap.add_argument("--smoke-only", action="store_true", help="omit steady-memory run, but build the same full model")
    raw_args = sys.argv[1:]
    args = ap.parse_args(raw_args)
    if sum(option.split("=", 1)[0] == "--pending-store-early-load-credits" for option in raw_args) > 1:
        ap.error("duplicate --pending-store-early-load-credits capacity")
    if args.pending_store_early_load_credits != 1 and not args.pending_virtual_store_proof:
        ap.error("--pending-store-early-load-credits=2 requires --pending-virtual-store-proof")
    for name in ("durable_read_prefetch_candidate", "read_prefetch_behind_store"):
        if getattr(args, name) > 1:
            ap.error("duplicate --" + name.replace("_", "-") + " flag")
        setattr(args, name, bool(getattr(args, name)))
    if args.read_prefetch_behind_store and not args.durable_read_prefetch_candidate:
        ap.error("--read-prefetch-behind-store requires --durable-read-prefetch-candidate")
    if args.durable_read_prefetch_candidate and not (args.prefetch_candidate_cycles == 16 and
            args.split_prefetch_tracking and args.read_prefetch_dirty_retry and
            args.read_prefetch_demand_adoption and args.read_prefetch_store_hold):
        ap.error("--durable-read-prefetch-candidate requires lifetime 16 and split tracking, dirty retry, adoption and store hold")
    if args.read_prefetch_store_hold > 1:
        ap.error("duplicate --read-prefetch-store-hold flag")
    args.read_prefetch_store_hold = bool(args.read_prefetch_store_hold)
    if args.read_prefetch_store_hold and args.prefetch_candidate_cycles <= 1:
        ap.error("--read-prefetch-store-hold requires --prefetch-candidate-cycles greater than 1")
    if args.read_prefetch_demand_adoption > 1:
        ap.error("duplicate --read-prefetch-demand-adoption flag")
    args.read_prefetch_demand_adoption = bool(args.read_prefetch_demand_adoption)
    if args.read_prefetch_demand_adoption and not (args.split_prefetch_tracking and args.independent_demand_admission):
        ap.error("--read-prefetch-demand-adoption requires --split-prefetch-tracking and --independent-demand-admission")
    if args.read_prefetch_dirty_retry > 1:
        ap.error("duplicate --read-prefetch-dirty-retry flag")
    args.read_prefetch_dirty_retry = bool(args.read_prefetch_dirty_retry)
    if args.read_prefetch_dirty_retry and not args.split_prefetch_tracking:
        ap.error("--read-prefetch-dirty-retry requires --split-prefetch-tracking")
    if args.split_prefetch_tracking > 1:
        ap.error("duplicate --split-prefetch-tracking flag")
    args.split_prefetch_tracking = bool(args.split_prefetch_tracking)
    if args.split_prefetch_tracking and not args.store_next_line_prefetch:
        ap.error("--split-prefetch-tracking requires --store-next-line-prefetch")
    if args.ddr_write_collection_flow > 1:
        ap.error("duplicate --ddr-write-collection-flow flag")
    args.ddr_write_collection_flow = bool(args.ddr_write_collection_flow)
    if args.line_transfer_dispatch_flow > 1:
        ap.error("duplicate --line-transfer-dispatch-flow flag")
    args.line_transfer_dispatch_flow = bool(args.line_transfer_dispatch_flow)
    if args.line_read_channel > 1:
        ap.error("duplicate --line-read-channel flag")
    args.line_read_channel = bool(args.line_read_channel)
    for key, default in (("ddr_outstanding", 4), ("ddr_write_credits", 2)):
        values = getattr(args, key)
        if values and len(values) > 1:
            ap.error("duplicate --" + key.replace("_", "-"))
        setattr(args, key, values[0] if values else default)
    if args.dtlb_write_read_reuse > 1:
        ap.error("duplicate --dtlb-write-read-reuse")
    args.dtlb_write_read_reuse = bool(args.dtlb_write_read_reuse)
    if args.translation_hit_flow > 1:
        ap.error("duplicate --translation-hit-flow")
    args.translation_hit_flow = bool(args.translation_hit_flow)
    if args.independent_demand_admission > 1:
        ap.error("duplicate --independent-demand-admission")
    args.independent_demand_admission = bool(args.independent_demand_admission)
    if args.independent_demand_admission and not (args.virtual_ram_load_precheck and args.canonical_virtual_store_overlap):
        ap.error("independent admission requires virtual RAM precheck and canonical virtual store overlap")
    if args.reconstruct_issue_token_index > 1:
        ap.error("duplicate --reconstruct-issue-token-index flag")
    args.reconstruct_issue_token_index = bool(args.reconstruct_issue_token_index)
    if args.shared_memory_address_state > 1:
        ap.error("duplicate --shared-memory-address-state flag")
    args.shared_memory_address_state = bool(args.shared_memory_address_state)
    for field in ("rob_entries", "physical_regs"):
        values = getattr(args, field)
        if values is not None and len(values) != 1:
            ap.error("choose exactly one --" + field.replace("_", "-") + " value")
        setattr(args, field, values[0] if values else None)
    if args.frozen_store_proof_transport and not (args.virtual_ram_load_precheck and args.canonical_virtual_store_overlap):
        ap.error("--frozen-store-proof-transport requires virtual precheck and canonical overlap")
    for field in ("aligned_fetch_permission_stage", "registered_canonical_store_event", "shared_lane1_owner_match"):
        if getattr(args, field) > 1:
            ap.error("duplicate --" + field.replace("_", "-") + " flag")
        setattr(args, field, bool(getattr(args, field)))
    if args.registered_canonical_store_event and not args.canonical_virtual_store_overlap:
        ap.error("--registered-canonical-store-event requires --canonical-virtual-store-overlap")
    if args.registered_pending_store_query > 1:
        ap.error("duplicate --registered-pending-store-query flag")
    args.registered_pending_store_query = bool(args.registered_pending_store_query)
    if args.registered_pending_store_query and not args.pending_virtual_store_proof:
        ap.error("--registered-pending-store-query requires --pending-virtual-store-proof")
    if args.pending_ready_store_bypass > 1:
        ap.error("duplicate --pending-ready-store-bypass flag")
    args.pending_ready_store_bypass = bool(args.pending_ready_store_bypass)
    if args.pending_ready_store_bypass and not args.bound_head_store_overlap:
        ap.error("--pending-ready-store-bypass requires --bound-head-store-overlap")
    if args.bound_head_store_overlap and not args.pending_virtual_store_proof:
        ap.error("--bound-head-store-overlap requires --pending-virtual-store-proof")
    if args.pending_virtual_store_proof and not (not args.memory_proof_frontier and
            args.frozen_store_proof_transport and args.rob_entries in (None, 16) and args.physical_regs in (None, 48) and
            args.lsu_entries == 4 and args.data_translation_entries == 16 and
            args.canonical_virtual_store_overlap and args.virtual_ram_load_precheck and
            args.load_order_older_retire and not args.prechecked_data_flow):
        ap.error("--pending-virtual-store-proof requires independent frozen transport, ROB16/PRF48/LSU4/DTLB16, virtual precheck, canonical overlap and older-load retirement")
    if args.memory_proof_frontier and not (args.rob_entries == 64 and args.physical_regs == 64 and
            args.lsu_entries == 4 and args.data_translation_entries == 16 and
            args.canonical_virtual_store_overlap and args.virtual_ram_load_precheck and
            args.load_order_older_retire and not args.prechecked_data_flow):
        ap.error("--memory-proof-frontier requires reviewed ROB64/PRF64/LSU4, DTLB16, virtual precheck, canonical overlap and older-load retirement")
    if args.canonical_virtual_store_overlap and not args.virtual_ram_load_precheck:
        ap.error("--canonical-virtual-store-overlap requires --virtual-ram-load-precheck")
    if args.posted_preparation_priority and not (args.prepared_store_lookahead and args.posted_store_merge):
        ap.error("--posted-preparation-priority requires --prepared-store-lookahead and --posted-store-merge")
    if args.posted_prefetch_head_offer and not (args.posted_store_merge and args.posted_prefetch_coexistence):
        ap.error("--posted-prefetch-head-offer requires --posted-store-merge and --posted-prefetch-coexistence")
    if args.posted_prefetch_coexistence and not args.posted_store_merge:
        ap.error("--posted-prefetch-coexistence requires --posted-store-merge")
    if args.posted_store_merge and args.prechecked_data_flow:
        ap.error("--posted-store-merge excludes --prechecked-data-flow until separately qualified")
    if args.prechecked_data_flow and not args.virtual_ram_load_precheck:
        ap.error("prechecked data flow requires --virtual-ram-load-precheck")
    if args.store_prefetch_mru_insertion and not args.store_next_line_prefetch:
        ap.error("--store-prefetch-mru-insertion requires --store-next-line-prefetch")
    if args.store_prefetch_lru_victim and not args.store_next_line_prefetch:
        ap.error("--store-prefetch-lru-victim requires --store-next-line-prefetch")
    if args.distinct_way_release and not args.store_next_line_prefetch:
        ap.error("--distinct-way-release requires --store-next-line-prefetch")
    if args.dma_line_entries != 1 and not args.dma_line_transfers:
        ap.error("multiple DMA line owners require --dma-line-transfers")
    if args.dma_line_yield_cycles and not args.dma_line_transfers:
        ap.error("line yield requires --dma-line-transfers")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("unsafe tag")
    if args.smoke_only and args.mixed_store_stream:
        ap.error("mixed store streams require the full board suite")
    out = common.BUILD / ("fpga-next-board-" + args.tag)
    if out.exists() and not args.resume:
        ap.error("output exists; use a fresh tag or --resume for identical sources")
    parameters = ["--" + args.variant, "--data-translation-entries=" + str(args.data_translation_entries)]
    if args.dma_line_transfers:
        parameters.append("--dma-line-transfers")
    if args.dma_line_entries > 1:
        parameters.append("--dma-line-entries=" + str(args.dma_line_entries))
    if args.dma_line_yield_cycles:
        parameters.append("--dma-line-yield-cycles=" + str(args.dma_line_yield_cycles))
    if args.prefetch_break_on_store:
        parameters.append("--prefetch-break-on-store")
    if args.prefetch_candidate_cycles != 1:
        parameters.append("--prefetch-candidate-cycles=" + str(args.prefetch_candidate_cycles))
    if args.virtual_ram_load_precheck:
        parameters.append("--virtual-ram-load-precheck")
    if args.lsu_entries != 2:
        parameters.append("--lsu-entries=" + str(args.lsu_entries))
    if args.rob_entries is not None:
        parameters.append("--rob-entries=" + str(args.rob_entries))
    if args.physical_regs is not None:
        parameters.append("--physical-regs=" + str(args.physical_regs))
    if args.physical_load_ingress_flow:
        parameters.append("--physical-load-ingress-flow")
    if args.ddr_write_collection_flow:
        parameters.append("--ddr-write-collection-flow")
    if args.line_transfer_dispatch_flow:
        parameters.append("--line-transfer-dispatch-flow")
    if args.line_read_channel:
        parameters.append("--line-read-channel")
    if args.ddr_outstanding != 4:
        parameters.append("--ddr-outstanding=" + str(args.ddr_outstanding))
    if args.ddr_write_credits != 2:
        parameters.append("--ddr-write-credits=" + str(args.ddr_write_credits))
    if args.dtlb_write_read_reuse:
        parameters.append("--dtlb-write-read-reuse")
    if args.translation_hit_flow:
        parameters.append("--translation-hit-flow")
    if args.independent_demand_admission:
        parameters.append("--independent-demand-admission")
    if args.split_prefetch_tracking:
        parameters.append("--split-prefetch-tracking")
    if args.read_prefetch_dirty_retry:
        parameters.append("--read-prefetch-dirty-retry")
    if args.read_prefetch_demand_adoption:
        parameters.append("--read-prefetch-demand-adoption")
    if args.read_prefetch_store_hold:
        parameters.append("--read-prefetch-store-hold")
    if args.durable_read_prefetch_candidate:
        parameters.append("--durable-read-prefetch-candidate")
    if args.read_prefetch_behind_store:
        parameters.append("--read-prefetch-behind-store")
    if args.translated_response_empty_flow:
        parameters.append("--translated-response-empty-flow")
    if args.load_order_older_retire:
        parameters.append("--load-order-older-retire")
    if args.fetch_previous_packet:
        parameters.append("--fetch-previous-packet")
    if args.prepared_store_lookahead:
        parameters.append("--prepared-store-lookahead")
    if args.posted_preparation_priority:
        parameters.append("--posted-preparation-priority")
    if args.reconstruct_issue_token_index:
        parameters.append("--reconstruct-issue-token-index")
    if args.shared_memory_address_state:
        parameters.append("--shared-memory-address-state")
    if args.store_next_line_prefetch:
        parameters.append("--store-next-line-prefetch")
    if args.store_prefetch_mru_insertion:
        parameters.append("--store-prefetch-mru-insertion")
    if args.store_prefetch_lru_victim:
        parameters.append("--store-prefetch-lru-victim")
    if args.distinct_way_release:
        parameters.append("--distinct-way-release")
    if args.posted_store_merge:
        parameters.append("--posted-store-merge")
    if args.posted_prefetch_coexistence:
        parameters.append("--posted-prefetch-coexistence")
    if args.posted_prefetch_head_offer:
        parameters.append("--posted-prefetch-head-offer")
    if args.prechecked_data_flow:
        parameters.append("--prechecked-data-flow")
    if args.independent_fetch_payload_capture:
        parameters.append("--independent-fetch-payload-capture")
    if args.owner_local_issue_ready:
        parameters.append("--owner-local-issue-ready")
    if args.shared_fetch_pmp_relations:
        parameters.append("--shared-fetch-pmp-relations")
    if args.share_protected_head_payload:
        parameters.append("--share-protected-head-payload")
    if args.banked_instruction_data:
        parameters.append("--banked-instruction-data")
    if args.canonical_virtual_store_overlap:
        parameters.append("--canonical-virtual-store-overlap")
    if args.memory_proof_frontier:
        parameters.append("--memory-proof-frontier")
    if args.frozen_store_proof_transport:
        parameters.append("--frozen-store-proof-transport")
    if args.pending_virtual_store_proof:
        parameters.append("--pending-virtual-store-proof")
    if args.registered_pending_store_query:
        parameters.append("--registered-pending-store-query")
    if args.aligned_fetch_permission_stage:
        parameters.append("--aligned-fetch-permission-stage")
    if args.registered_canonical_store_event:
        parameters.append("--registered-canonical-store-event")
    if args.shared_lane1_owner_match:
        parameters.append("--shared-lane1-owner-match")
    if args.bound_head_store_overlap:
        parameters.append("--bound-head-store-overlap")
    if args.pending_ready_store_bypass:
        parameters.append("--pending-ready-store-bypass")
    if args.pending_virtual_store_proof_slots != 1:
        parameters.append(f"--pending-virtual-store-proof-slots={args.pending_virtual_store_proof_slots}")
    if args.pending_store_early_load_credits != 1 or any(
            option.split("=", 1)[0] == "--pending-store-early-load-credits" for option in raw_args):
        parameters.append(f"--pending-store-early-load-credits={args.pending_store_early_load_credits}")
    plan = {"rob_entries_override": args.rob_entries, "physical_regs_override": args.physical_regs,
            "canonical_virtual_store_overlap": args.canonical_virtual_store_overlap,
            "memory_proof_frontier": args.memory_proof_frontier,
            "frozen_store_proof_transport": args.frozen_store_proof_transport,
            "pending_virtual_store_proof": args.pending_virtual_store_proof,
            "registered_pending_store_query": args.registered_pending_store_query,
            "aligned_fetch_permission_stage": args.aligned_fetch_permission_stage,
            "registered_canonical_store_event": args.registered_canonical_store_event,
            "shared_lane1_owner_match": args.shared_lane1_owner_match,
            "bound_head_store_overlap": args.bound_head_store_overlap,
            "pending_ready_store_bypass": args.pending_ready_store_bypass,
            "pending_virtual_store_proof_slots": args.pending_virtual_store_proof_slots,
            "pending_store_early_load_credits": args.pending_store_early_load_credits,
            "posted_store_merge": args.posted_store_merge,
            "posted_prefetch_coexistence": args.posted_prefetch_coexistence,
            "posted_prefetch_head_offer": args.posted_prefetch_head_offer,
            "data_translation_entries": args.data_translation_entries,
            "instruction_translation_entries": 8, "pte_cache_entries": 4, "parameters": parameters, "fetch_previous_packet": args.fetch_previous_packet,
            "prepared_store_lookahead": args.prepared_store_lookahead,
            "posted_preparation_priority": args.posted_preparation_priority,
            "reconstruct_issue_token_index": args.reconstruct_issue_token_index,
            "shared_memory_address_state": args.shared_memory_address_state,
            "translated_response_empty_flow": args.translated_response_empty_flow,
            "store_next_line_prefetch": args.store_next_line_prefetch,
            "store_prefetch_mru_insertion": args.store_prefetch_mru_insertion,
            "store_prefetch_lru_victim": args.store_prefetch_lru_victim,
            "distinct_way_release": args.distinct_way_release,
            "ddr_write_collection_flow": args.ddr_write_collection_flow,
            "line_transfer_dispatch_flow": args.line_transfer_dispatch_flow,
            "line_read_channel": args.line_read_channel,
            "ddr_outstanding": args.ddr_outstanding, "ddr_write_credits": args.ddr_write_credits,
            "data_tlb_write_read_reuse": args.dtlb_write_read_reuse,
            "translation_hit_flow": args.translation_hit_flow,
            "independent_demand_admission": args.independent_demand_admission,
            "split_prefetch_tracking": args.split_prefetch_tracking,
            "read_prefetch_dirty_retry": args.read_prefetch_dirty_retry,
            "read_prefetch_demand_adoption": args.read_prefetch_demand_adoption,
            "read_prefetch_store_hold": args.read_prefetch_store_hold,
            "durable_read_prefetch_candidate": args.durable_read_prefetch_candidate,
            "read_prefetch_behind_store": args.read_prefetch_behind_store,
            "smoke_only": args.smoke_only, "passive_probes": True,
            "guest_suite": ["rv64gc"] if args.smoke_only else ["rv64gc", "steady", "independent-lines", "virtual-context"] +
                (["mixed-store16", "mixed-store64"] if args.mixed_store_stream else [])}
    if args.preflight_only:
        print(json.dumps({"status": "PREFLIGHT_ONLY", "plan": plan, "output": str(out)}, indent=2))
        return
    out.mkdir(parents=True, exist_ok=True)
    model, fw = out / "model", out / "firmware"
    model.mkdir(exist_ok=True)
    fw.mkdir(exist_ok=True)
    frozen = source_inventory()
    receipt_path = out / "receipt.json"
    state = json.loads(receipt_path.read_text()) if receipt_path.exists() else {
        "schema": "valence-fpga-next-board-evidence-v1", "status": "RUNNING", "inputs": frozen,
        "plan": plan, "steps": {}, "artifacts": {}, "tests": {}, "commands": [],
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True).strip()}
    if frozen != state["inputs"] or plan != state["plan"]:
        raise RuntimeError("source/profile drift: preserve the old evidence and use a fresh tag")

    save_lock = threading.Lock()

    def save():
        with save_lock:
            receipt_path.write_text(json.dumps(state, indent=2) + "\n")

    def guard():
        if source_inventory() != frozen:
            raise RuntimeError("sources changed during frozen board check")
        for relative, expected in state["artifacts"].items():
            if sha(out / relative) != expected:
                raise RuntimeError("checkpoint artifact changed: " + relative)

    def command(name, cmd, timeout=900, expected=0, anchor=None):
        index, log = 0, out / (name + ".log")
        while log.exists():
            index += 1
            log = out / (name + ".retry" + str(index) + ".log")
        print("+ " + " ".join(map(str, cmd)), flush=True)
        began = time.monotonic()
        try:
            with log.open("w") as stream:
                result = subprocess.run(list(map(str, cmd)), cwd=common.ROOT, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=timeout, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            record = {"command": list(map(str, cmd)), "log": log.relative_to(out).as_posix(),
                "log_sha256": sha(log), "actual_exit": result.returncode, "expected_exit": expected,
                "seconds": time.monotonic() - began}
            if result.returncode != expected or (anchor and anchor not in log.read_text()):
                record["status"] = "FAIL"
                state["commands"].append(record)
                save()
                raise RuntimeError(str(log) + "\n" + log.read_text()[-5000:])
            record["status"] = "PASS"
            return record
        except subprocess.TimeoutExpired:
            state["commands"].append({"command": list(map(str, cmd)), "log": log.relative_to(out).as_posix(),
                "log_sha256": sha(log), "status": "TIMEOUT", "seconds": time.monotonic() - began})
            save()
            raise

    def step(name, cmd, products=(), **kwargs):
        guard()
        if name not in state["steps"]:
            record = command(name, cmd, **kwargs)
            state["commands"].append(record)
            state["steps"][name] = record
            for product in products:
                state["artifacts"][product.relative_to(out).as_posix()] = sha(product)
            save()
        return state["steps"][name]

    state["status"] = "RUNNING"
    state.pop("error", None)
    save()
    try:
        gsim, cxx = common.setup(False)
        state["toolchain"] = json.loads((common.BUILD / "toolchain-used.json").read_text())
        f = common.ROOT / "fpga/firmware"
        elf, image = fw / "rv64gc.elf", fw / "rv64gc.bin"
        step("gc-build", ["riscv64-unknown-elf-gcc", "-march=rv64gc", "-mabi=lp64d", "-mcmodel=medany",
            "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-Wl,--build-id=none",
            "-Wl,--defsym=BOARD_RAM_BYTES=2147483648", "-Wl,--defsym=BOARD_MONITOR_BASE=4294934528",
            "-T", f / "sample_app.ld", f / "rv64gc_smoke.S", "-o", elf], [elf])
        step("gc-bin", ["riscv64-unknown-elf-objcopy", "-O", "binary", elf, image], [image])
        steady = fw / "steady.elf"
        if not args.smoke_only:
            step("steady-build", ["riscv64-unknown-elf-gcc", "-O2", "-march=rv64im_zicsr_zifencei", "-mabi=lp64",
                "-mcmodel=medany", "-mno-relax", "-msmall-data-limit=0", "-ffreestanding", "-fno-builtin",
                "-fno-stack-protector", "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-Wl,--gc-sections",
                "-ffunction-sections", "-fdata-sections", "-DCPU_HZ=100000000ULL", "-DUART_BAUD=460800",
                "-Wl,--defsym=BOARD_RAM_BYTES=2147483648", "-Wl,--defsym=BOARD_MONITOR_BASE=4294934528",
                "-T", f / "sample_app.ld", f / "sample_start.S", common.HERE / "payloads/board_memory_steady.c",
                "-lgcc", "-o", steady], [steady])
            step("steady-bin", ["riscv64-unknown-elf-objcopy", "-O", "binary", steady, fw / "steady.bin"], [fw / "steady.bin"])
        independent = fw / "independent.elf"
        virtual_guest = None
        if not args.smoke_only:
            step("independent-build", ["riscv64-unknown-elf-gcc", "-O2", "-march=rv64im_zicsr_zifencei", "-mabi=lp64",
                "-mcmodel=medany", "-mno-relax", "-msmall-data-limit=0", "-ffreestanding", "-fno-builtin",
                "-fno-stack-protector", "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-Wl,--gc-sections",
                "-ffunction-sections", "-fdata-sections", "-DCPU_HZ=100000000ULL", "-DUART_BAUD=460800",
                "-Wl,--defsym=BOARD_RAM_BYTES=2147483648", "-Wl,--defsym=BOARD_MONITOR_BASE=4294934528",
                "-T", f / "sample_app.ld", f / "sample_start.S", common.HERE / "payloads/board_memory_independent.c",
                "-lgcc", "-o", independent], [independent])
            step("independent-bin", ["riscv64-unknown-elf-objcopy", "-O", "binary", independent, fw / "independent.bin"],
                [fw / "independent.bin"])
            guard()
            if "virtual-guest" not in state["steps"]:
                virtual_guest = build_virtual_guest(fw / "virtual")
                state["virtual_guest"] = virtual_guest
                state["steps"]["virtual-guest"] = {"status": "BUILT_NOT_EXECUTED"}
                for file in ("guest.elf", "guest.bin", "guest.json", "guest.dis", "guest.nm"):
                    product = fw / "virtual" / file
                    state["artifacts"][product.relative_to(out).as_posix()] = sha(product)
                values = {name.upper(): value for name, value in virtual_guest["symbols"].items()}
                values["ENTRY"] = values.pop("_START")
                values["IMAGE_END"] = virtual_guest["symbols"]["_start"] + Path(virtual_guest["binary"]).stat().st_size
                header = fw / "virtual_load_guest_symbols.h"
                header.write_text("#pragma once\n" + "".join(
                    f"#define VIRTUAL_GUEST_{name} 0x{value:x}ULL\n" for name, value in values.items()))
                state["artifacts"][header.relative_to(out).as_posix()] = sha(header)
                save()
            virtual_guest = state["virtual_guest"]
        mixed = {}
        if args.mixed_store_stream:
            for period in (16, 64):
                name = "mixed" + str(period)
                elf = fw / (name + ".elf")
                binary = fw / (name + ".bin")
                step(name + "-build", ["riscv64-unknown-elf-gcc", "-O2", "-march=rv64im_zicsr_zifencei", "-mabi=lp64",
                    "-mcmodel=medany", "-mno-relax", "-msmall-data-limit=0", "-ffreestanding", "-fno-builtin",
                    "-fno-stack-protector", "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-Wl,--gc-sections",
                    "-ffunction-sections", "-fdata-sections", "-DCPU_HZ=100000000ULL", "-DUART_BAUD=460800",
                    "-DMIXED_STORE_LINE_PERIOD=" + str(period),
                    "-Wl,--defsym=DDR_TEST_PROGRAM_LIMIT=0x80400000",
                    "-Wl,--defsym=BOARD_RAM_BYTES=2147483648", "-Wl,--defsym=BOARD_MONITOR_BASE=4294934528",
                    "-T", f / "sample_app.ld", f / "sample_start.S", common.HERE / "payloads/board_memory_mixed_stores.c",
                    "-lgcc", "-o", elf], [elf])
                step(name + "-bin", ["riscv64-unknown-elf-objcopy", "-O", "binary", elf, binary], [binary])
                mixed[period] = (elf, binary)
        step("elaborate", ["mill", "-i", "IonSoC.test.runMain", "ooo.FpgaNextBoardGsimMain", model, *parameters],
             [model / "BoardSocGsim.fir"])
        fir = (model / "BoardSocGsim.fir").read_text()
        state["backend_capacity_census"] = verify_backend_capacity(
            fir, args.rob_entries or 16, args.physical_regs or 48)
        state["posted_model_census"] = verify_posted_model(fir, args.posted_store_merge, rob_entries=args.rob_entries or 16)
        save()
        step("generate", [gsim, "--threads=1", "--dir=" + str(model), model / "BoardSocGsim.fir"], timeout=900)
        for token in ("module FloatingPointSystem", "module OwnerBankedPhysicalRegisterFile", "module BankedRobPayload",
                      "module MixedCoherentLineHome", "module NonBlockingCoherentLineCache"):
            if token not in fir:
                raise RuntimeError("selected profile component missing: " + token)
        state["memory_geometry"] = verify_memory_geometry(fir, args.lsu_entries)
        validate(common.ROOT, model / "BoardSocGsim.h", 2, "board$platform$privateCache$")
        units = sorted(model.glob("BoardSocGsim[0-9]*.cpp"))
        if not units:
            raise RuntimeError("empty generated board model")
        for path in [model / "BoardSocGsim.h", *units]:
            state["artifacts"].setdefault(path.relative_to(out).as_posix(), sha(path))
        save()
        flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        pending = [p for p in units if "compile-" + p.stem not in state["steps"]]
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            tasks = {p: pool.submit(command, "compile-" + p.stem,
                [cxx, *flags, "-I" + str(model), "-c", p, "-o", p.with_suffix(".o")]) for p in pending}
            for path, future in tasks.items():
                result = future.result()
                state["steps"]["compile-" + path.stem] = result
                state["commands"].append(result)
                state["artifacts"][path.with_suffix(".o").relative_to(out).as_posix()] = sha(path.with_suffix(".o"))
                save()
        objects = [p.with_suffix(".o") for p in units]
        defines = ["-DBACKEND_OWNER_COUNT=" + str(args.lsu_entries), "-DUART_DIVISOR=1", "-DBOARD_CPU_HZ=100000000", "-DBOARD_UART_BAUD=460800", "-DUART_EXTRA_STOP_BITS=0",
            "-DDDR_MODEL=1", "-DBOARD_DDR_BYTES=2147483648ULL", "-DDDR_MULTI_ID_MODEL=1", "-DDDR_BENCHMARK_MODEL=1",
            "-DDDR_READ_CREDITS=8", "-DDDR_READ_LATENCY=32", "-DDDR_READ_BEAT_GAP=1", "-DBOARD_CYCLE_LIMIT=12000000ULL"]
        cases = [("gc", "rv64gc_board.cpp", [], image, "RV64GC_BOARD_PASS")]
        if not args.smoke_only:
            cases.append(("steady", "board_memory_steady.cpp", ["-DMODEL_MSHRS=2",
                "-DSTEADY_START_PC=" + str(marker(steady, "steady_start")) + "ULL",
                "-DSTEADY_STOP_PC=" + str(marker(steady, "steady_stop")) + "ULL"], fw / "steady.bin", "BOARD_MEMORY_STEADY_PASS"))
            cases.append(("independent", "board_memory_steady.cpp", ["-DMODEL_MSHRS=2", "-DINDEPENDENT_LINE_KERNEL=1",
                "-DSTEADY_START_PC=" + str(marker(independent, "steady_start")) + "ULL",
                "-DSTEADY_STOP_PC=" + str(marker(independent, "steady_stop")) + "ULL"], fw / "independent.bin", "BOARD_MEMORY_STEADY_PASS"))
            cases.append(("virtual", "virtual_load_board.cpp", ["-I" + str(fw)],
                Path(virtual_guest["binary"]), "VIRTUAL_BOARD_PASS"))
        for period, (elf, binary) in mixed.items():
            cases.append(("mixed" + str(period), "board_memory_steady.cpp", ["-DMODEL_MSHRS=2",
                "-DMIXED_READ_STORE_KERNEL=1", "-DMIXED_STORE_LINE_PERIOD=" + str(period),
                "-DSTEADY_START_PC=" + str(marker(elf, "steady_start")) + "ULL",
                "-DSTEADY_STOP_PC=" + str(marker(elf, "steady_stop")) + "ULL"], binary, "BOARD_MEMORY_STEADY_PASS"))
        for name, harness, extra, payload, anchor in cases:
            case_defines = [d for d in defines if name != "virtual" or d != "-DDDR_BENCHMARK_MODEL=1"]
            step(name + "-link", [cxx, *flags, *case_defines, *extra, "-I" + str(model), common.HERE / "harness" / harness,
                *objects, "-ldl", "-o", out / name], [out / name])
            result = step("test-" + name, [out / name, payload], anchor=anchor)
            state["tests"][name] = result
            print((out / result["log"]).read_text()[-4500:], flush=True)
            if name == "gc":
                state["tests"]["gc-negative"] = step("test-gc-negative", [out / name, payload, "--inject-mismatch"],
                    expected=1, anchor="firmware independent anchor/context failure")
            if name == "virtual":
                state["virtual_metrics"] = parse_virtual_metrics((out / result["log"]).read_text())
                for mutation, rejection in (("signature", "independent full-core signature mismatch"),
                    ("trap", "independent full-core trap provenance mismatch"),
                    ("marker", "ROI boundary order/uniqueness mismatch")):
                    state["tests"]["virtual-negative-" + mutation] = step("test-virtual-negative-" + mutation,
                        [out / name, payload, "--inject-" + mutation], expected=1, anchor=rejection)
            save()
        guard()
        state["status"] = "PASS_FPGA_NEXT_BOARD_SMOKE" if args.smoke_only else "PASS_FPGA_NEXT_BOARD_SUITE"
        state["limits"] = ["No native GMAC/PHY in this CPU wrapper", "No physical PPA/CDC/board result",
            "No Linux scheduler or exhaustive ISA compliance result", "Steady DDR is a controlled host-memory model, not physical bandwidth"]
    except BaseException as error:
        state["status"] = "FAIL"
        state["error"] = str(error)
        raise
    finally:
        save()
    print(state["status"] + " " + str(receipt_path), flush=True)


if __name__ == "__main__":
    main()
