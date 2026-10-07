#!/usr/bin/env python3
"""Stage one private RV64GC board; reuse IP, never the integer CPU checkpoint.

Run on Windows after explicit ManagedBoardSocMain RV64GC export and firmware
build. Hash gates reuse only unchanged component proofs, not an old CPU pass.
No Vivado project is opened or modified; no bitstream is generated.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from rv64gc_return_control_gate import gate_return_control_batch, gate_unchanged_writer


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def gate_map(repo, mapping):
    for name, expected in mapping.items():
        assert sha(repo / name) == expected, "Source changed since proof: " + name


def gate_boundary(directory, expected):
    proof = load(directory / "receipt.json")
    assert proof["status"] == expected
    for name, digest in proof["input_sha256"].items():
        assert sha(Path(name)) == digest, "Boundary input drift: " + name
    for name, digest in proof["output_sha256"].items():
        assert sha(directory / name) == digest, "Boundary artifact drift: " + name
    return sha(directory / "receipt.json")


QUARTER_TX_NEGATIVES = {
    "corrupt_data": ("PHY_RISING_SYMBOL",), "corrupt_control": ("PHY_FALLING_SYMBOL",),
    "bad_phase": ("TXC_RISE_NOT_2NS", "TXC_FALL_NOT_6NS", "PHY_SETUP_EYE"),
    "duplicate_breach": ("QUARTER_DDR_UNUSED_EDGE_CHANGED", "PHY_SETUP_EYE"),
    "capture_breach": ("PHY_RISING_SYMBOL", "PHY_FALLING_SYMBOL", "PHY_SETUP_EYE"),
    "phase_stop": ("TXC_PERIOD", "TXC_RISE_NOT_2NS", "TXC_FALL_NOT_6NS", "PHY_SETUP_EYE"),
}


def gate_quarter_tx(repo, directory):
    """Require selected production modules, never a private pad-probe PASS."""
    digest = gate_boundary(directory, "PASS_NATIVE_TX_QUARTER_BOARD_SHORT")
    proof = load(directory / "receipt.json")
    assert proof["actual_board_tx"] and not proof["hardware_phy_init_enabled"] and not proof["bit_generated"]
    assert (proof["clock_architecture"], proof["mac_hz"], proof["pad_hz"], proof["physical_tx_phase_ns"]) == (
        "common_clk250_dedicated_oddr", 125000000, 250000000, 2.0)
    assert not proof["phy_tx_delay_enabled"] and proof["phy_rx_delay_enabled"]
    assert set(proof["negative_checks"]) == set(QUARTER_TX_NEGATIVES)
    assert all(value == "PASS" for value in proof["negative_checks"].values())
    required = {"native_gmac_divided_clock.sv", "native_rgmii.sv", "native_tx_reset_boundary.sv",
                "native_tx_word_reset_boundary.sv", "native_tx_quarter_board_tb.sv",
                "soc_top_gmac_ddr.sv", "run_native_tx_quarter_board.py"}
    sources = {Path(name).name: (Path(name), value) for name, value in proof["input_sha256"].items()}
    assert len(sources) == len(proof["input_sha256"]) and set(sources) == required | {"glbl.v"}
    for name in required:
        assert sources[name][1] == sha(repo / "fpga/zu15eg" / name), "Not the current production TX source: " + name
    assert sha(directory / "executed_runner.py") == sources["run_native_tx_quarter_board.py"][1]
    assert sha(directory / "sealed_soc_top_gmac_ddr.sv.txt") == sources["soc_top_gmac_ddr.sv"][1]
    positive = (directory / "positive.log").read_text()
    assert "PASS_NATIVE_TX_QUARTER_BOARD_SHORT bytes=3072 encodings=4 reset_epochs=3 cold_relocks=2" in positive
    assert "Fatal:" not in positive
    for name, diagnostics in QUARTER_TX_NEGATIVES.items():
        text = (directory / (name + ".log")).read_text()
        assert "Fatal:" in text and any(value in text for value in diagnostics), "Wrong negative oracle: " + name
        assert "PASS_NATIVE_TX_QUARTER_BOARD_SHORT" not in text
    return digest


REVALIDATED_TL = ("src/main/scala/ip/tilelink/TwoMasterTileLinkArbiter.scala",
                  "src/main/scala/ip/tilelink/TwoBankTileLinkRouter.scala")
LINE_WRITER_SOURCE = "src/main/scala/ip/tilelink/TileLinkLineWriteEngine.scala"


def gate_path_batch(repo, path, short_path, components_only=False, updated_sources=None):
    """Replace two TL proofs; never mistake reused isolated proof for a new CPU pass."""
    proof = load(path)
    assert proof["status"] == "PASS_RV64GC_PATH_BATCH_AFFECTED_SHORT"
    assert (proof["isa"], proof["issue_width"], proof["cpu_hz"], proof["uart_baud"]) == (
        "rv64gc", 2, 100000000, 460800)
    updated_sources = updated_sources or {}
    assert not updated_sources or components_only, "Fresh writer proof only replaces isolated old dependencies"
    assert set(updated_sources) <= {LINE_WRITER_SOURCE}, "No arbitrary dependency exclusions"
    gate_map(repo, updated_sources)
    if components_only:
        # This mode is allowed only alongside the fresh structural/CPU gate.
        # Its old CPU/fetch/FPU checks are NOT used: only unchanged TL/IP/bus,
        # wrappers, independent drivers and their build dependencies are reused.
        dependencies = {name: digest for name, digest in proof["source_sha256"].items()
                        if name.startswith(("src/main/scala/ip/", "src/main/scala/bus/",
                                            "src/test/scala/ip/")) or name in (
                            "build.mill", "simulator/gsim/run.py",
                            "simulator/gsim/harness/tilelink_crossbar.cpp",
                            "simulator/gsim/harness/tilelink_burst.cpp",
                            "simulator/gsim/harness/tilelink_router.cpp")}
        assert all(name in dependencies for name in REVALIDATED_TL), "Incomplete TL dependency proof"
        for name in updated_sources:
            assert name in dependencies, "Changed dependency absent from old component proof"
            del dependencies[name]
        gate_map(repo, dependencies)
        models = {name: model for name, model in proof.get("reused_models", {}).items()
                  if name.startswith("crossbar-") or name == "router-errors"}
    else:
        assert proof["native_receipt_sha256"] == sha(short_path), "Batch/CPU proof mismatch"
        gate_map(repo, proof["source_sha256"])
        models = proof.get("reused_models", {})
    for model in models.values():
        gate_map(repo, model)
    checks = {
        "crossbar-legacy": "GSIM TileLink crossbar: PASS",
        "crossbar-raw": "GSIM TileLink crossbar: PASS",
        "crossbar-legacy-burst": "GSIM TileLink burst fabric: PASS PutFullData=2x8 Get=2x8 deniedGet=8",
        "crossbar-raw-burst": "GSIM TileLink burst fabric: PASS PutFullData=2x8 Get=2x8 deniedGet=8",
        "router-errors": "GSIM TileLink router: PASS",
        "timing-smoke": "GSIM control/memory timing + NEMU: PASS",
        "pipeline-recovery": "GSIM pipeline recovery + NEMU: PASS",
    }
    for name, prefix in checks.items():
        assert proof["checks"][name].startswith(prefix), "Missing affected check: " + name
    for name in ("crossbar-legacy", "crossbar-raw"):
        text = (path.parent / (name + "-negative.log")).read_text()
        assert "TileLink crossbar D source, data or owner mismatch" in text
    assert "TileLink router response data, source or route mismatch" in (
        path.parent / "router-errors-negative.log").read_text()
    assert "TileLink bank response has no matching source" in (
        path.parent / "router-errors/wrong-owner.log").read_text()
    return {**{name: proof["source_sha256"][name] for name in REVALIDATED_TL}, **updated_sources}


def gate_window_batch(repo, path, short_path):
    """Actual changed window/FP/store/writer and native CPU proof; no old CPU substitution."""
    proof = load(path)
    assert proof["status"] == "PASS_SOC_WINDOW_BATCH_AFFECTED_SHORT"
    assert (proof["isa"], proof["issue_width"], proof["cpu_hz"], proof["uart_baud"]) == (
        "rv64gc", 2, 100000000, 460800)
    assert proof["native_receipt_sha256"] == sha(short_path), "Window batch/CPU proof mismatch"
    assert LINE_WRITER_SOURCE in proof["source_sha256"], "Changed writer absent from proof"
    gate_map(repo, proof["source_sha256"])
    checks = {
        "fetch-window-3": ("GSIM registered fetch window: PASS", "fetch window independent oracle mismatch"),
        "fetch-window-5": ("GSIM registered fetch window: PASS", "fetch window independent oracle mismatch"),
        "fp-state": ("FP_STATE_PASS", "FP oracle mismatch"),
        "fp-numerical-fd": ("FP_FULL_PASS profile=fd", "FP full mismatch"),
        "fp-numerical-f": ("FP_FULL_PASS profile=f", "FP full mismatch"),
        "fp-numerical-small": ("FP_FULL_PASS profile=small", "FP full mismatch"),
        "line-writer": ("GSIM TileLink line write: PASS", "line write oracle mismatch"),
    }
    for name, (prefix, diagnostic) in checks.items():
        assert proof["checks"][name].startswith(prefix), "Missing changed boundary: " + name
        assert proof["checks"][name + "-negative"] == diagnostic
        assert diagnostic in (path.parent / name / "negative.log").read_text()
    assert "II1 adjacentFinalAck" in proof["checks"]["line-writer"], "Writer throughput/adjacent ownership not checked"
    assert proof["checks"]["line-read-write"].startswith("GSIM TileLink line read/write RAM: PASS")
    for name in (*checks, "line-read-write"):
        mapping = proof["model_sha256"][name]
        assert mapping, "Missing actual isolated model artifacts: " + name
        relative = {}
        for source, digest in mapping.items():
            prefix = "/home/openion/Valence/"
            assert source.startswith(prefix), "Unexpected isolated model path"
            relative[source[len(prefix):]] = digest
        gate_map(repo, relative)
    for name, prefix in (("timing-smoke", "GSIM control/memory timing + NEMU: PASS"),
                         ("pipeline-recovery", "GSIM pipeline recovery + NEMU: PASS")):
        assert proof["checks"][name].startswith(prefix), "Missing actual CPU check: " + name
    assert "GSIM short two-issue throughput + NEMU: PASS programs=13" in proof["checks"]["integer-core"]
    assert len(proof["integer_measurements"]) == 13
    assert "NEMU register mismatch" in (path.parent / "integer-core/negative.log").read_text()
    return sha(path)


def gate_refactor(repo, path, short_path):
    """Fresh bounded checks for all changed production boundaries and real RV64GC CPU."""
    proof = load(path)
    assert proof["status"] == "PASS_SOC_PIPELINE_REFACTOR_AFFECTED_SHORT"
    assert (proof["isa"], proof["issue_width"], proof["cpu_hz"], proof["uart_baud"]) == (
        "rv64gc", 2, 100000000, 460800)
    assert proof["native_receipt_sha256"] == sha(short_path), "Refactor/CPU proof mismatch"
    gate_map(repo, proof["source_sha256"])
    checks = {
        "cursor-neighbor": ("CURSOR_NEIGHBOR_PASS vectors=10445", "cursor neighbor independent oracle mismatch"),
        "natural-pmp": ("GSIM PMP checker: PASS", "PMP oracle mismatch"),
        "fp-memory": ("FP_MEMORY_PIPELINE_PASS", "FP memory boundary oracle mismatch"),
        "translation-context": ("TRANSLATION_CONTEXT_PASS", "VM context independent oracle mismatch"),
        "fetch-2-32": ("GSIM registered fetch packet: PASS width=2", "fetch packet oracle mismatch"),
        "fetch-4-8": ("GSIM registered fetch packet: PASS width=4", "fetch packet oracle mismatch"),
    }
    for name, (prefix, diagnostic) in checks.items():
        assert proof["checks"][name].startswith(prefix), "Missing structural check: " + name
        assert proof["checks"][name + "-negative"] == diagnostic
        assert diagnostic in (path.parent / name / "negative.log").read_text()
    for name, prefix in (("timing-smoke", "GSIM control/memory timing + NEMU: PASS"),
                         ("pipeline-recovery", "GSIM pipeline recovery + NEMU: PASS")):
        assert proof["checks"][name].startswith(prefix), "Missing CPU check: " + name
    assert "GSIM short two-issue throughput + NEMU: PASS programs=13" in proof["checks"]["integer-core"]
    assert len(proof["integer_measurements"]) == 13, "Incomplete short IPC evidence"
    assert "NEMU register mismatch" in (path.parent / "integer-core/negative.log").read_text()
    return sha(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--export", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--mig-project", type=Path, required=True)
    ap.add_argument("--short", type=Path, required=True)
    ap.add_argument("--path-batch", type=Path,
                    help="fresh affected TL/burst/CPU proof, required when those peripheral dependencies change")
    ap.add_argument("--refactor", type=Path,
                    help="fresh structural/CPU proof; permits only unchanged TL component reuse from --path-batch")
    ap.add_argument("--window-batch", type=Path,
                    help="fresh window/FP/store/writer/CPU proof; changed writer cannot reuse old IP proof")
    ap.add_argument("--return-control", type=Path,
                    help="current return/control/PMP/FP batch and actual native CPU proof")
    ap.add_argument("--contract-update", type=Path,
                    help="strict two-pure-Spec supplement plus 236 byte-identical exported RTL files")
    ap.add_argument("--writer-component", type=Path,
                    help="unchanged isolated writer only; never imports the old CPU proof")
    ap.add_argument("--tx-proof", type=Path, required=True)
    ap.add_argument("--rx-proof", type=Path, required=True)
    ap.add_argument("--clock-proof", type=Path, required=True)
    ap.add_argument("--repair-cdc-packing", action="store_true", help="preserve initial evidence; add missing helper and resume own synthesis")
    a = ap.parse_args()
    if a.repair_cdc_packing:
        old_path = a.candidate / "inputs.json"
        old = load(old_path)
        gate_map(a.repo, old["checked_source_sha256"])
        for name, expected in old["candidate_sha256"].items():
            assert sha(a.candidate / name) == expected, "Initial staged input drift: " + name
        fresh = a.candidate / "inputs-resume-r2.json"
        assert not fresh.exists(), "Preserve previous repair evidence"
        for name in ("cdc_constraints.tcl", "build_native_board.tcl"):
            source = a.repo / "fpga/zu15eg" / name
            shutil.copy2(source, a.candidate / "scripts" / name)
            old["candidate_sha256"]["scripts/" + name] = sha(source)
        old["previous_inputs_sha256"] = sha(old_path)
        checkpoint = a.candidate / "implementation/post_synth_unconstrained.dcp"
        old["own_completed_synthesis_checkpoint"] = str(checkpoint)
        old["own_completed_synthesis_sha256"] = sha(checkpoint)
        old["candidate_post_synth_checkpoint_reused"] = True
        old["repair"] = "Missing CDC helper packed; continue completed RV64GC synthesis. No hardware/RTL changes."
        fresh.write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
        print("REPAIRED_CDC_PACKING_REUSE_OWN_RV64GC_SYNTHESIS", old["own_completed_synthesis_sha256"])
        return
    assert not a.candidate.exists(), "Preserve existing candidate; use a fresh root"
    short = load(a.short)
    assert short["status"] == "PASS_RV64GC_NATIVE_AFFECTED_SHORT"
    assert (short["isa"], short["issue_width"], short["cpu_hz"], short["uart_baud"],
            short["timing_profile"]) == ("rv64gc", 2, 100000000, 460800, "staged-fetch-feedback")
    gate_map(a.repo, short["source_sha256"])
    gate_map(a.repo, short["cpu_artifact_sha256"])
    refactor_sha = gate_refactor(a.repo, a.refactor, a.short) if a.refactor else None
    assert sum(bool(p) for p in (a.refactor, a.window_batch, a.return_control)) <= 1, "Choose one current structural proof"
    window_sha = gate_window_batch(a.repo, a.window_batch, a.short) if a.window_batch else None
    assert bool(a.return_control) == bool(a.contract_update) == bool(a.writer_component), "Return/control requires both strict supplement and isolated writer proof"
    return_sha = gate_return_control_batch(a.repo, a.return_control, a.short,
                                          a.contract_update, a.export) if a.return_control else None
    writer_sources = gate_unchanged_writer(a.repo, a.writer_component) if a.writer_component else {}
    structural = bool(a.refactor or a.window_batch or a.return_control)
    assert not structural or a.path_batch, "Explicit unchanged TL component proof required"
    assert sha(Path(short["board_receipt"].replace("/home/openion/Valence", str(a.repo)))) == short["board_receipt_sha256"]
    top = (a.repo / "fpga/zu15eg/soc_top_gmac_ddr.sv").read_text()
    quarter_tx = "parameter TX_QUARTER_DDR = 1" in top
    tx = gate_quarter_tx(a.repo, a.tx_proof) if quarter_tx else gate_boundary(a.tx_proof, "PASS_NATIVE_TX90_SHORT")
    rx = gate_boundary(a.rx_proof, "PASS_NATIVE_RX_DESKEW_SHORT")
    if a.path_batch:
        assert load(a.rx_proof / "receipt.json").get("actual_board_rx"), "Use the exact current board RX proof"
    helper = a.repo / ("fpga/zu15eg/native_quarter_clock_constraints.tcl" if quarter_tx else "fpga/zu15eg/native_divided_clock_constraints.tcl")
    assert sha(helper) == sha(a.clock_proof / "tested_clock_constraints.tcl")
    log = a.clock_proof.with_suffix(".log").read_text(encoding="utf-8")
    marker = "PASS_NATIVE_QUARTER_CLOCK_REFERENCE_RETENTION" if quarter_tx else "PASS_NATIVE_CLOCK_REFERENCE_RETENTION"
    assert marker + " TEST_SENTINELS_ONLY" in log
    assert "Constraints 18-1055" not in log, "Clock references were discarded"

    # The CPU/board profile is newly checked. Prior managed-peripheral checks
    # are reusable ONLY for their unchanged peripheral source dependencies.
    managed_path = a.repo / "build/gsim/managed-peripherals-20261004-r4/receipt.json"
    managed = load(managed_path)
    assert managed["status"] == "PASS_MANAGED_PERIPHERALS_SINGLE_CLOCK"
    # CDC helpers live in ip/bus (not an ip/cdc directory). Include the
    # entire IP/bus dependency surface, including TL, AXI and packet types.
    prefixes = ("src/main/scala/ip/", "src/main/scala/bus/")
    updated = ({LINE_WRITER_SOURCE: load(a.window_batch)["source_sha256"][LINE_WRITER_SOURCE]}
               if a.window_batch else writer_sources)
    revalidated = gate_path_batch(a.repo, a.path_batch, a.short,
                                 components_only=structural, updated_sources=updated) if a.path_batch else {}
    reused = {k: v for k, v in managed["source_sha256"].items()
              if k.startswith(prefixes) and not k.endswith("/MdioClause22.scala")}
    for name in revalidated:
        assert name in reused, "Replaced TL dependency was absent from original proof"
        del reused[name]
    assert len(reused) >= 40, "Incomplete peripheral dependency proof"
    gate_map(a.repo, reused)
    mdio_path = a.repo / "build/gsim/native-timing-20261004-r3/receipt.json"
    mdio = load(mdio_path)
    assert mdio["status"] == "PASS_NATIVE_TIMING_SHORT"
    assert mdio["checks"]["mdio"].startswith("MDIO_CLAUSE22_PASS transactions=96")
    mdio_names = ("src/main/scala/ip/ethernet/MdioClause22.scala",
                  "simulator/gsim/harness/mdio_clause22.cpp")
    gate_map(a.repo, {k: mdio["source_sha256"][k] for k in mdio_names})

    board_source = a.repo / "fpga/zu15eg"
    pins_path = a.repo / "build/fpga/native-timing-20261004-r1/inputs.json"
    pins = load(pins_path)
    xdc = (board_source / "native_gmac_pins.xdc").read_text(encoding="utf-8")
    assert len(pins["pin_evidence"]) == 15
    for pin in pins["pin_evidence"]:
        assert ("set_property PACKAGE_PIN %s [get_ports {%s}]" % (pin["ball"], pin["port"])) in xdc
    assert sha(a.export / "firmware/bootrom.coe") == sha(a.baseline / "firmware/bootrom.coe"), "BMG initialization changed; regenerate ROM IP"
    system = (a.export / "rtl/MachineSystemUnit.sv").read_text()
    assert "64'h800000000014112D" in system
    assert "FloatingPointSystem floatingPoint (" in system
    assert "FloatingPointExecute execute (" in (a.export / "rtl/FloatingPointSystem.sv").read_text()
    top = (board_source / "soc_top_gmac_ddr.sv").read_text()
    assert "parameter FPGA_TX_CLOCK_SHIFT = 1" in top and "parameter HARDWARE_PHY_INIT = 0" in top
    assert ".ISOLATE_TX_PAD_CLOCK(FPGA_TX_CLOCK_SHIFT)" in top

    a.candidate.mkdir(parents=True)
    shutil.copytree(a.export / "rtl", a.candidate / "rtl")
    shutil.copytree(a.export / "firmware", a.candidate / "firmware")
    (a.candidate / "board").mkdir()
    for name in ("soc_top_gmac_ddr.sv", "native_rgmii.sv", "native_gmac_clocks.sv",
                 "native_gmac_divided_clock.sv", "native_gmac_pll_pair.sv", "native_tx_common_delay.sv",
                 "native_tx_reset_boundary.sv", "native_phy_board_control.sv", "native_phy_tx_init.sv",
                 "native_tx_word_reset_boundary.sv",
                 "board_ddr.xdc", "pl_ddr4_pins.xdc", "native_gmac_pins.xdc"):
        shutil.copy2(board_source / name, a.candidate / "board" / name)
    (a.candidate / "scripts").mkdir()
    for name in ("build_native_board.tcl", "native_board_constraints.tcl",
                 "native-gmac-cdc-constraints.tcl", "cdc_constraints.tcl", "native_divided_clock_constraints.tcl",
                 "native_quarter_clock_constraints.tcl"):
        shutil.copy2(board_source / name, a.candidate / "scripts" / name)
    for tree in ("board_ip.srcs", "board_ip.gen"):
        shutil.copytree(a.baseline / "ip-build" / tree, a.candidate / "ip-build" / tree)
    # Preserve relative XCI gen_directory layout in a PRIVATE MIG copy.
    # Even if Vivado regenerates something it cannot write into the GUI tree.
    for tree in ("ZU15EG.srcs", "ZU15EG.gen"):
        shutil.copytree(a.mig_project / tree / "sources_1/ip/ddr4_0",
                        a.candidate / "mig" / tree / "sources_1/ip/ddr4_0")
    gate_map(a.repo, short["source_sha256"])
    gate_map(a.repo, revalidated)
    if a.return_control:
        gate_return_control_batch(a.repo, a.return_control, a.short, a.contract_update, a.export)
        gate_unchanged_writer(a.repo, a.writer_component)
    if quarter_tx: assert gate_quarter_tx(a.repo, a.tx_proof) == tx, "TX drift during staging"
    assert gate_boundary(a.rx_proof, "PASS_NATIVE_RX_DESKEW_SHORT") == rx, "RX drift during staging"
    assert sha(helper) == sha(a.clock_proof / "tested_clock_constraints.tcl"), "Clock helper drift during staging"
    files = {str(p.relative_to(a.candidate)): sha(p)
             for p in sorted(a.candidate.rglob("*")) if p.is_file()}
    manifest = dict(status="STAGED_RV64GC_SOURCE_NOT_TIMING_QUALIFIED", isa="rv64gc",
                    f_d_enabled=True, issue_width=2, cpu_hz=100000000, aon_uart_hz=50000000,
                    uart_baud=460800, timing_profile="staged-fetch-feedback",
                    export_command=(" ".join(load(a.export / "receipt.json")["producer_argv"]) if a.return_control else
                                    "mill -i IonSoC.test.runMain ooo.SocPipelineBoardMain OUTPUT" if structural else
                                    "mill -i IonSoC.test.runMain ooo.ManagedBoardSocMain OUTPUT 100000000 staged-fetch-feedback 460800 rv64gc 50000000 50000000 250000000"),
                    cpu_checkpoint_reused=False, bit_generated=False,
                    short_receipt_sha256=sha(a.short), checked_source_sha256=short["source_sha256"],
                    managed_component_receipt_sha256=sha(managed_path), reused_peripheral_sha256=reused,
                    affected_path_batch_receipt_sha256=sha(a.path_batch) if a.path_batch else None,
                    structural_refactor_receipt_sha256=refactor_sha,
                    structural_window_batch_receipt_sha256=window_sha,
                    structural_return_control_receipt_sha256=return_sha,
                    pure_scala_contract_update_receipt_sha256=sha(a.contract_update) if a.contract_update else None,
                    strict_export_manifest_sha256=sha(a.export / "receipt.json") if a.return_control else None,
                    writer_component_receipt_sha256=sha(a.writer_component) if a.writer_component else None,
                    writer_component_scope="unchanged_isolated_writer_only_no_old_cpu" if a.writer_component else None,
                    bare_integer_metrics_scope="sealed_original_logs_not_reused_executable" if a.return_control else None,
                    path_batch_scope="unchanged_isolated_tilelink_only" if structural else "fresh_affected_cpu_and_tilelink",
                    revalidated_tilelink_source_sha256=revalidated,
                    mdio_component_receipt_sha256=sha(mdio_path), tx_receipt_sha256=tx, rx_receipt_sha256=rx,
                    tx_clock_architecture="common_clk250_dedicated_oddr" if quarter_tx else "common_ref500_div4_phases",
                    clock_reference_helper_sha256=sha(helper), clock_reference_log_sha256=sha(a.clock_proof.with_suffix(".log")),
                    pin_workbook_sha256=pins["pin_workbook_sha256"], pin_evidence=pins["pin_evidence"],
                    candidate_sha256=files,
                    limits=["New CPU and current-profile single-clock board short checks, not Linux/ISA certification.",
                            "Unchanged managed peripheral sources are hash-gated; changed TL dependencies use fresh independent burst/owner/CPU checks, not whole-board CDC simulation.",
                            "PHY delay readback and physical board operation remain unverified.",
                            "Full synthesis/place/route, timing coverage, CDC/DRC and resource review still pending."])
    (a.candidate / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest["status"], "files=", len(files), "unchanged_peripheral_sources=", len(reused))
    print("MIG:", a.candidate / "mig/ZU15EG.srcs/sources_1/ip/ddr4_0/ddr4_0.xci")


if __name__ == "__main__":
    main()
