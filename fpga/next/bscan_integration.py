"""Stage source-bound BSCAN candidate timing inputs; never invokes Vivado."""
import hashlib
import json
from pathlib import Path

INPUTS = ("fpga/next/bscan_integration.py", "fpga/next/bscan_timing.tcl",
          "fpga/next/bscan-timing-profile.json", "fpga/next/audit_bscan_netlist.tcl",
          "fpga/next/check_jtag_chain.tcl")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(root, output, chain):
    root, output = Path(root), Path(output)
    # Other USER chains can still export RTL, but this reviewed board profile
    # does not silently become a clock/CDC claim for them.
    if chain != 2:
        return {"status": "UNSUPPORTED_CHAIN_REQUIRES_REVIEW", "chain": chain,
                "physical_qualification": False}
    board = output / "board"
    board.mkdir(parents=True, exist_ok=True)
    files = {}
    for source in INPUTS[1:]:
        src = root / source
        dst = board / src.name
        dst.write_bytes(src.read_bytes())
        files[str(dst.relative_to(output))] = {"sha256": sha(dst), "source": source, "source_sha256": sha(src)}
    profile = json.loads((root / "fpga/next/bscan-timing-profile.json").read_text())
    contract = {
        "schema": "valence-bscan-export-contract-v1",
        "status": "STAGED_NOT_APPLIED_NOT_PHYSICAL_SIGNOFF",
        "profile": profile,
        "files": files,
        "rtl_source_sha256": sha(root / "src/main/resources/debug/ValenceBscanDebugPort.sv"),
        "apply_after_synthesis": "source board/bscan_timing.tcl; valence_apply_bscan_timing $exact_primitive $exact_engine $fabric_clock zu15eg-user2-tck50-positive-v1",
        "reapply_after_opt_design": "valence_reapply_bscan_cdc $exact_primitive $exact_engine $fabric_clock",
        "collect_source_bound_reports": "source board/audit_bscan_netlist.tcl; valence_collect_bscan_netlist $exact_primitive $exact_engine $fabric_clock $fresh_report_directory",
        "hierarchy_rule": "Discover exact sibling enabled.user_scan/enabled.transport or enabled/user_scan/enabled/transport in this netlist; no wildcard or copied old path.",
        "record_at_each_stage": ["source/export receipt and Tcl hashes", "part and exact USER2 hierarchy", "applied clocks and uncertainty", "expanded exception coverage", "bank/reset/qualifier audit result", "checkpoint and report hashes", "route status"],
        "physical_qualification": False,
    }
    path = board / "bscan-timing-contract.json"
    path.write_text(json.dumps(contract, indent=2) + "\n")
    return {"path": str(path.relative_to(output)), "sha256": sha(path),
            "status": contract["status"], "physical_qualification": False}
