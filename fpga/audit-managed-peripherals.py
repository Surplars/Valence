#!/usr/bin/env python3
"""Freeze/archive short functional, CDC and internal OOC evidence, never claim board signoff."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def slack(path):
    return float(re.search(r"Slack \((?:MET|VIOLATED)\)\s*:\s*([-\d.]+)ns", path.read_text())[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native", type=Path)
    parser.add_argument("gsim", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    gsim = load(args.gsim / "receipt.json")
    cdc = load(args.native / "functional-r5/receipt.json")
    assert gsim["status"] == "PASS_MANAGED_PERIPHERALS_SINGLE_CLOCK"
    assert cdc["status"] == "PASS_MANAGED_PERIPHERAL_CDC_SHORT"
    for name, hashed in gsim["source_sha256"].items():
        assert digest(root / name) == hashed, "functional source drift: " + name
    for name, hashed in gsim["rtl_sha256"].items():
        assert digest(args.gsim / name) == hashed, "exported RTL drift"
        assert digest(args.native / "rtl" / Path(name).name) == hashed, "CAD RTL differs from functional export"
    for name, hashed in cdc["input_sha256"].items():
        assert digest(Path(name)) == hashed, "CDC input drift"
    previous = load(root / "build/fpga/clock-management-20261004-r1/audit-final.json")
    changed_original = {"src/main/scala/" + name for name in (
        "core/ooo/BoardSocTop.scala", "core/ooo/MachinePlatform.scala", "ip/bus/ClockDomainCrossing.scala",
        "ip/clock/ClockManagementUnit.scala", "ip/uart/UartConsole.scala", "ip/ethernet/EthernetDmaFrameAdapter.scala",
        "ip/ethernet/EthernetPort.scala", "ip/ethernet/TileLinkGmacControl.scala")}
    protected = {name: hashed for name, hashed in previous["frozen_source_sha256"].items()
        if name.startswith("src/main/scala/") and name not in changed_original}
    for name, hashed in protected.items():
        assert digest(root / name) == hashed, "protected CPU/DMA/home changed: " + name
    reports = args.native / "review-r3"
    setup = slack(reports / "internal_setup.rpt")
    hold = slack(reports / "internal_hold.rpt")
    assert setup > 0 and hold > 0, "internal timing failed"
    skew = [float(v) for v in re.findall(r"Slack \(MET\)\s*:\s*([\d.]+)ns",
        (reports / "post_route_bus_skew.rpt").read_text())]
    assert len(skew) == 13 and min(skew) > 0, "skew constraints failed/incomplete"
    cdc_text = (reports / "post_route_cdc.rpt").read_text()
    critical = {name: int(count) for name, count in re.findall(r"^(CDC-\d+)\s+Critical\s+(\d+)", cdc_text, re.M)}
    assert critical == {"CDC-1": 1, "CDC-11": 4}, "unreviewed CDC critical set changed"
    for endpoint in ("gmac/txConfig/mailbox/captured_reg[3]/D", "gmac/agent_1/request/stages_reg[0]/D",
        "gmac/ingress/q_sync/stages_reg[0]/D", "uart/agent/request/stages_reg[0]/D",
        "uart/ingress/q_sync/stages_reg[0]/D"):
        assert any("Critical" in row and endpoint in row for row in cdc_text.splitlines()), "CDC endpoint changed"
    assert "checking unconstrained_internal_endpoints (0)" in (reports / "post_route_timing.rpt").read_text()
    frozen = args.output / "frozen-source"
    frozen.mkdir(parents=True, exist_ok=False)
    names = set(gsim["source_sha256"])
    names.update(("src/test/scala/ip/ManagedPeripheralCdc.scala", "src/test/scala/ooo/ManagedBoardSocMain.scala"))
    names.update(("docs/managed-peripherals.md", "docs/soc-registers.md", "docs/soc-datasheet.md",
        "docs/performance-status.md", "docs/README.md", "fpga/zu15eg/clock-domain-plan.md",
        "fpga/zu15eg/ethernet-integration.md", "simulator/gsim/README.md"))
    names.update(str(p.relative_to(root)) for p in (root / "fpga").rglob("*managed*" ) if p.is_file())
    frozen_hashes = {}
    for name in sorted(names):
        path = root / name
        target = frozen / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        frozen_hashes[name] = digest(path)
        assert digest(target) == frozen_hashes[name]
    archive = args.output / "native-results"
    archive.mkdir(exist_ok=False)
    archived = {}
    for path in sorted(args.native.rglob("*")):
        if not path.is_file() or "xsim.dir" in path.parts or path.suffix not in {
            ".sv", ".v", ".tcl", ".py", ".json", ".log", ".rpt", ".dcp"}: continue
        name = str(path.relative_to(args.native))
        target = archive / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        archived[name] = digest(path)
        assert digest(target) == archived[name], "archive hash mismatch"
    report = {
        "status": "PASS_FUNCTIONAL_AND_INTERNAL_OOC_NOT_BOARD_SIGNOFF",
        "gsim_receipt": str(args.gsim / "receipt.json"), "gsim_summary": gsim["integration"]["summary"],
        "gsim_reset_sampled_only": True, "single_clock_only": True,
        "cdc_status": cdc["status"], "cdc_summary": cdc["summary"],
        "cdc_waveform_bytes": [390, 1332], "independent_negatives": 4,
        "clocks_hz": {"cpu": 100000000, "aon": 50000000, "uart": 50000000, "tx": 125000000, "rx": 125000000},
        "internal_setup_ns": setup, "internal_hold_ns": hold,
        "skew_groups": len(skew), "minimum_skew_slack_ns": min(skew),
        "resources": {"LUT": 3964, "FF": 4503, "RAMB18": 2, "BUFGCE": 3, "DSP": 0},
        "cdc_critical_unwaived": critical, "cdc_warnings_unwaived": {"CDC-6": 4, "CDC-15": 650},
        "cdc_manual_review": {
            "CDC-1": "TX enable: 52-bit atomic mailbox pruned to one held/captured bit; request/ACK settling contract, NOT a direct unsynchronized level",
            "CDC-11": "AON quiesce fans to raw-ingress and its SAME-primary gated-domain ACK synchronizers; deliberate retained ACK vs always-running wake distinction; independent-edge CDC surrogate exercised; keep visible for board review"},
        "zero_io_budget_all_hold_ns": -0.555, "board_verified": False, "phy_or_rgmii_verified": False,
        "cpu_ipc_or_fmax_measured": False, "dynamic_frequency": False, "bit_generated": False,
        "synthesis_runs": 1, "place_route_runs": 1, "route_checkpoint_report_review_runs": 1,
        "failure_history": "r1 scalar-clock-export; r2 harness macro; r3 GSIM derived reset alias; CDC r1 stale STOP, r2/r3 shared static task, r4 xelab dynamic event hang stopped; CAD initial selector failure; no oracle relaxed",
        "authorized_original_main_changes": sorted(changed_original),
        "protected_original_main_sha256": protected, "frozen_source_sha256": frozen_hashes,
        "native_archive_sha256": archived,
    }
    (args.output / "audit-final.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], "archive_files=" + str(len(archived)))


if __name__ == "__main__": main()
