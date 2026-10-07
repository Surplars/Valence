#!/usr/bin/env python3
"""Native Windows xsim proof for RX admission-stop CDC only; never FPGA routing.

Export first with:
  mill -i IonSoC.test.runMain ip.GmacRxAdmissionStopCdcMain <fresh-rtl-dir>
Then run this script with <fresh-rtl-dir> <fresh-result-dir>.
--prepare-only stages a hashed portable input packet without running any tool.
The frame owner and CPU status tail are surrogates; no MAC, CPU or DMA runs.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rtl", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--vivado-bin", type=Path, default=Path(r"E:\Xilinx\2025.1\Vivado\bin"))
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    rtl = args.rtl.resolve()
    output_dir = args.output.resolve()
    if output_dir.exists():
        parser.error("use a fresh output directory")
    if not args.prepare_only and os.name != "nt":
        parser.error("runtime requires native Windows xvlog/xelab/xsim; use --prepare-only to stage inputs")
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    source_names = (
        "src/main/scala/ip/bus/CdcDataChannels.scala",
        "src/main/scala/ip/bus/ClockDomainCrossing.scala",
        "src/main/scala/ip/ethernet/EthernetClockCrossing.scala",
        "src/main/scala/ip/ethernet/EthernetPort.scala",
        "src/main/scala/ip/ethernet/EthernetRxAdmissionStop.scala",
        "src/test/scala/ip/GmacRxAdmissionStopCdc.scala",
        "build.mill",
    )
    sources = [root / name for name in source_names]
    rtl_files = sorted(rtl.glob("*.sv"))
    modules = set()
    for path in rtl_files:
        modules.update(re.findall(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)", path.read_text(), re.MULTILINE))
    required = {"GmacRxAdmissionStopCdcTop", "EthernetRxAdmissionStop", "EthernetFrameClockBridge",
                "CdcDataFifo", "CdcMailbox", "CdcResetRelease", "CdcLevel"}
    if not required.issubset(modules):
        parser.error("missing complete CDC-only export: " + ", ".join(sorted(required - modules)))
    if any(re.search(r"MachineCore|TileLinkGmac|EthernetPacketDma|GmiiFrame|axi_ethernet|soc_top", name)
           for name in modules):
        parser.error("export includes MAC/CPU/CSR/DMA/SoC modules outside this CDC-only test")
    inputs = [*rtl_files, here / "rx_admission_stop_cdc_tb.sv", here / "cdc_run.tcl", Path(__file__).resolve()]
    if len({path.name for path in inputs}) != len(inputs):
        parser.error("duplicate input basenames would overwrite staged inputs")
    missing = [str(path) for path in sources + inputs if not path.is_file()]
    if missing:
        parser.error("missing source/input files: " + ", ".join(missing))
    tools = [args.vivado_bin / (tool + ".bat") for tool in ("xvlog", "xelab", "xsim")]
    if not args.prepare_only and any(not tool.is_file() for tool in tools):
        parser.error("native Windows xvlog.bat/xelab.bat/xsim.bat not found in --vivado-bin")

    source_hashes = {str(path.relative_to(root)): digest(path) for path in sources}
    input_hashes = {path.name: digest(path) for path in inputs}
    protected = sorted((root / "src/main/scala/core").rglob("*.scala"))
    protected += sorted((root / "src/main/scala/ip/dma").rglob("*.scala"))
    protected_hashes = {str(path.relative_to(root)): digest(path) for path in protected}
    output_dir.mkdir(parents=True)
    for path in inputs:
        shutil.copy2(path, output_dir / path.name)
    for path in sources:
        archived = output_dir / "source" / path.relative_to(root)
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, archived)
    report = {
        "status": "PREPARED_NOT_RUN" if args.prepare_only else "RUNNING",
        "scope": "RX admission-stop mailbox and frame FIFO CDC only; frame/status owners are surrogates",
        "source_sha256": source_hashes,
        "input_sha256": input_hashes,
        "protected_cpu_dma_sha256": protected_hashes,
        "exported_modules": sorted(modules),
        "tool_bin": str(args.vivado_bin),
        "independent_clock_runtime_verified": False,
        "negative_checks": {},
        "coordinated_reset_only": True,
        "clock_pause_model_only": True,
        "mac_cpu_dma_simulated": False,
        "rgmii_verified": False,
        "physical_clock_gate_verified": False,
        "physical_cdc_constraints_verified": False,
        "board_verified": False,
        "synthesis_run": False,
        "route_run": False,
        "bit_generated": False,
        "commands": [],
    }
    failed = False

    def run(tool, command_args, log):
        command = [str(args.vivado_bin / (tool + ".bat")), *command_args]
        report["commands"].append(command)
        result = subprocess.run(command, cwd=output_dir, capture_output=True, text=True, timeout=90)
        text = result.stdout + result.stderr
        (output_dir / log).write_text(text)
        return result.returncode, text

    try:
        if not args.prepare_only:
            for tool, command_args, log in (
                ("xvlog", ["--sv", *[path.name for path in inputs if path.suffix == ".sv"]], "compile.log"),
                ("xelab", ["rx_admission_stop_cdc_tb", "--snapshot", "rx_admission_stop_cdc",
                           "--debug", "typical", "--timescale", "1ns/1ps"], "elaborate.log"),
            ):
                code, text = run(tool, command_args, log)
                if code:
                    raise RuntimeError(log + ": " + text[-2400:])
            code, text = run("xsim", ["rx_admission_stop_cdc", "-tclbatch", "cdc_run.tcl"], "positive.log")
            marker = "RX_ADMISSION_STOP_CDC_PASS clock_cases=4"
            if code or marker not in text or text.count("RX_STOP_CASE_PASS case=") != 4:
                raise RuntimeError("independent-clock positive failed: " + text[-3000:])
            report["positive_summary"] = [line for line in text.splitlines()
                                          if "RX_STOP_CASE_" in line or marker in line]
            for injection, rejection in (
                ("payload", "RX stop independent payload scoreboard mismatch"),
                ("drain", "RX stop independent drain scoreboard mismatch"),
            ):
                code, negative = run("xsim", ["rx_admission_stop_cdc", "-tclbatch", "cdc_run.tcl",
                                               "-testplusarg", "inject_" + injection],
                                     "negative-" + injection + ".log")
                if rejection not in negative or "RX_ADMISSION_STOP_CDC_PASS" in negative:
                    raise RuntimeError("independent negative control did not reject: " + injection +
                                       ": " + negative[-1800:])
                report["negative_checks"][injection] = "REJECTED_INDEPENDENT_MISMATCH"
            report.update(status="PASS_RX_ADMISSION_STOP_CDC_SHORT", independent_clock_runtime_verified=True)
    except BaseException as error:
        failed = True
        report.update(status="FAIL_RX_ADMISSION_STOP_CDC_SHORT", failure=str(error))
    finally:
        try:
            current_sources = {str(path.relative_to(root)): digest(path) for path in sources}
            current_inputs = {path.name: digest(path) for path in inputs}
            current_protected = {str(path.relative_to(root)): digest(path) for path in protected}
            archived_sources = {name: digest(output_dir / "source" / name) for name in source_hashes}
            staged_inputs = {name: digest(output_dir / name) for name in input_hashes}
            if (source_hashes != current_sources or input_hashes != current_inputs or
                    protected_hashes != current_protected or source_hashes != archived_sources or
                    input_hashes != staged_inputs):
                raise RuntimeError("source/RTL/testbench/protected CPU/DMA or staged input drift")
        except BaseException as error:
            failed = True
            report.update(status="FAIL_INPUT_DRIFT", failure=str(error))
        report["output_sha256"] = {path.name: digest(path) for path in sorted(output_dir.glob("*.log"))}
        (output_dir / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed:
        raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__":
    main()
