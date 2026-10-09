#!/usr/bin/env python3
"""Prepare native JTAG tests; --run uses only an explicitly installed Vivado.

Default is source-bound PREPARED_NOT_RUN. No installer, hardware manager, board
access, synthesis or bit generation. Protocol models and vendor UNISIM are
separate suites; neither establishes physical CDC or a board scan-chain layout.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DTM = "src/main/resources/debug/ValenceJtagDebugPort.sv"
BSCAN = "src/main/resources/debug/ValenceBscanDebugPort.sv"
LOADER_SOURCES = ("build.mill", ".mill-version",
                  "src/main/scala/ip/debug/JtagRamLoader.scala",
                  "src/main/scala/ip/debug/JtagDebugReservation.scala",
                  "src/main/scala/ip/bus/RegisterPort.scala",
                  "src/test/scala/debug/JtagRamNativeMain.scala")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def case(name, top, marker, sources, parameters=None, reject=None):
    return dict(name=name, top=top, marker=marker, sources=sources,
                parameters=parameters or {}, reject=reject)


def cases(suite, model=None):
    if suite == "protocol":
        result = [case(top, top + "_tb", marker,
                       [DTM, "simulator/jtag/" + top + "_tb.sv"])
                  for top, marker in (("jtag_debug", "PASS JTAG arcs=32"),
                                      ("dmi_cdc", "PASS CDC requests=101"),
                                      ("dtm_completion", "PASS DTM completion"))]
        result += [case("parameters_" + str(n), "jtag_parameters_tb", "PASS parameters ABITS=" + str(n),
                        [DTM, "simulator/jtag/jtag_parameters_tb.sv"], {"ABITS": n}) for n in (1, 7, 32)]
        result.append(case("bscan_pin_model", "bscan_user_tb", "PASS BSCAN_USER", [
            DTM, BSCAN, "simulator/jtag/bscan_user_tb.sv"]))
        return result
    if suite == "unisim-profile":
        return [case("vendor_profile", "bscan_unisim_profile_tb", "BSCAN_UNISIM_PROFILE_ONLY", [
            "simulator/jtag/bscan_unisim_profile_tb.sv"])]
    if suite == "unisim":
        if model is None or not 1 <= model["ir_length"] <= 32:
            raise ValueError("UNISIM requires explicit model IR length and USER1/USER2 opcodes from the installed model")
        width = model["ir_length"]
        if any(not 0 <= model[k] < 1 << width for k in ("user1", "user2")) or model["user1"] == model["user2"]:
            raise ValueError("invalid model USER opcode pair")
        sources = [DTM, BSCAN, "simulator/jtag/bscan_unisim_tb.sv"]
        params = dict(MODEL_IR_LENGTH=width, MODEL_USER1=model["user1"], MODEL_USER2=model["user2"])
        result = [case("vendor_phase_" + str(i), "bscan_unisim_tb", "BSCAN_UNISIM_PASS", sources,
                       dict(params, SYS_HALF=half, TCK_LOW=low, TCK_HIGH=high, START_PHASE=phase))
                  for i, (half, low, high, phase) in enumerate(((7, 19, 23, 3), (13, 11, 17, 5), (5, 29, 31, 7)))]
        result.append(case("vendor_bad_oracle", "bscan_unisim_tb", "BSCAN_UNISIM_PASS", sources,
                           dict(params, BAD_EXPECTED=1), "UNISIM_READBACK_ORACLE"))
        return result
    if suite == "loader-drain":
        sources = [DTM, "@loader/JtagRamLoader.sv", "simulator/jtag/loader_cdc_drain_tb.sv"]
        result = [case("drain_phase_" + str(i), "loader_cdc_drain_tb", "LOADER_CDC_DRAIN_PASS", sources,
                       dict(SYS_HALF=half, TCK_HALF=tck)) for i, (half, tck) in enumerate(((7, 11), (11, 7), (5, 17)))]
        result.append(case("bad_owner_reset", "loader_cdc_drain_tb", "LOADER_CDC_DRAIN_PASS", sources,
                           dict(BAD_RESET_OWNER=1), "DRAIN_OWNER_ORACLE"))
        return result
    raise ValueError("unknown suite")


def command_plan(row, files, vendor):
    compile_cmd = ["xvlog", "-sv", "-work", "xil_defaultlib", *files]
    elaborate = ["xelab", "-debug", "all", "-mt", "off", "xil_defaultlib." + row["top"]]
    if vendor:
        elaborate += ["xil_defaultlib.glbl", "-L", "unisims_ver"]
    for key, value in sorted(row["parameters"].items()):
        elaborate += ["-generic_top", key + "=" + str(value)]
    elaborate += ["-s", "valence_test"]
    return [compile_cmd, elaborate, ["xsim", "valence_test", "-runall", "-onerror", "quit"]]


def classify_run(row, returncode, log):
    # xsim versions need not return nonzero for every HDL $fatal: require the
    # intended oracle diagnostic, reject unexpected failures and false PASS.
    diagnostics = re.findall(r"^\s*(?:Fatal:|FATAL:|ERROR:)[^\n]*", log, re.MULTILINE)
    fatal = bool(diagnostics)
    if row["reject"]:
        # The anchor must occur in the fatal diagnostic itself, not a printed
        # command/source line. Unexpected additional diagnostics remain failures.
        if (not diagnostics or any(row["reject"] not in line for line in diagnostics) or
                row["marker"] in log):
            raise RuntimeError("negative case did not reach its intended oracle: " + row["name"])
        return "EXPECTED_ORACLE_REJECTION"
    if returncode or fatal or row["marker"] not in log:
        raise RuntimeError("missing clean explicit PASS: " + row["name"])
    return "PASS"


def validate_loader(directory):
    receipt = json.loads((directory / "native-loader.json").read_text())
    if (receipt.get("schema") != "valence-native-loader-v1" or receipt.get("timeout_cycles") != 64 or
            receipt.get("ram_base") != "0x80200000" or receipt.get("ram_end") != "0x80201000"):
        raise ValueError("exact 64-cycle standalone native loader fixture required")
    for path in LOADER_SOURCES:
        if receipt.get("source_sha256", {}).get(path) != sha(ROOT / path):
            raise ValueError("loader source binding mismatch: " + path)
    if receipt.get("rtl_sha256") != sha(directory / "JtagRamLoader.sv"):
        raise ValueError("loader RTL receipt mismatch")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("protocol", "unisim-profile", "unisim", "loader-drain"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="execute only in the separately authorized simulator task")
    parser.add_argument("--vivado-root", type=Path, help="existing installation; no PATH/tool download fallback")
    parser.add_argument("--model-ir-length", type=int)
    parser.add_argument("--model-user1", type=lambda s: int(s, 0))
    parser.add_argument("--model-user2", type=lambda s: int(s, 0))
    parser.add_argument("--loader-rtl", type=Path)
    args = parser.parse_args(argv)
    model = None
    if args.suite == "unisim":
        if None in (args.model_ir_length, args.model_user1, args.model_user2):
            parser.error("explicit installed-model IR/USER profile required; physical BSDL values are not defaults")
        model = dict(ir_length=args.model_ir_length, user1=args.model_user1, user2=args.model_user2)
    rows = cases(args.suite, model)
    output = args.output.resolve()
    if output.exists():
        parser.error("use a fresh output directory")
    vendor = args.suite.startswith("unisim")
    install = args.vivado_root.resolve() if args.vivado_root else None
    tools = {name: (install / "bin" / (name + (".bat" if os.name == "nt" else ""))) if install else None
             for name in ("xvlog", "xelab", "xsim")}
    if args.run and any(path is None or not path.is_file() for path in tools.values()):
        parser.error("--run requires xvlog/xelab/xsim in the explicit existing --vivado-root")
    loader = args.loader_rtl.resolve() if args.loader_rtl else None
    if args.suite == "loader-drain" and loader is None:
        parser.error("--loader-rtl with source-bound native-loader.json required")
    loader_receipt = validate_loader(loader) if loader else None
    vendor_files = {}
    if vendor and install:
        for name in ("glbl.v", "unisims/JTAG_SIME2.v", "unisims/BSCANE2.v"):
            path = install / "data/verilog/src" / name
            if not path.is_file():
                parser.error("missing installed model source for provenance: " + str(path))
            vendor_files[name] = path
    if vendor and args.run and not vendor_files:
        parser.error("installed vendor model provenance required")
    inputs = {p: (loader / p[len("@loader/"):]) if p.startswith("@loader/") else ROOT / p
              for row in rows for p in row["sources"]}
    inputs["simulator/jtag/run_xsim.py"] = Path(__file__).resolve()
    if any(not p.is_file() for p in inputs.values()):
        parser.error("missing source input")
    before = {p: sha(q) for p, q in inputs.items()}
    output.mkdir(parents=True)
    staged = {}
    for key, path in inputs.items():
        dest = output / "inputs" / key.replace("@loader/", "loader/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        staged[key] = dest
    report = dict(schema="valence-xsim-native-v1", status="PREPARED_NOT_RUN", suite=args.suite,
        input_sha256=before, installed_model_sha256={k: sha(v) for k, v in vendor_files.items()},
        model_profile=model, loader_receipt=loader_receipt, cases=[],
        runtime_attempted=False, runtime_executed=False, vendor_primitive_executed=False, physical_cdc_signoff=False,
        board_scan_chain_verified=False, board_verified=False, full_debug_module=False,
        installed_models_are_not_board_bsdl=True,
        protocol_scope="pin-event model only; no BSCANE2" if args.suite == "protocol" else args.suite)
    try:
        if args.run:
            # Record the actual executables, not merely a user-entered version.
            report["tool_versions"] = {}
            for name, tool in tools.items():
                result = subprocess.run([str(tool), "-version"], cwd=output, text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        timeout=60, shell=False)
                (output / (name + "-version.log")).write_text(result.stdout)
                if result.returncode:
                    raise RuntimeError(name + " version probe failed")
                report["tool_versions"][name] = result.stdout.strip()
        for row in rows:
            directory = output / row["name"]
            directory.mkdir()
            files = [str(output / "inputs" / p.replace("@loader/", "loader/")) for p in row["sources"]]
            if vendor:
                files.append(str(vendor_files.get("glbl.v", Path("<VIVADO>/data/verilog/src/glbl.v"))))
            commands = command_plan(row, files, vendor)
            result_row = dict(row, commands=commands, status="PREPARED_NOT_RUN")
            report["cases"].append(result_row)
            if not args.run:
                continue
            for index, command in enumerate(commands):
                actual = [str(tools[command[0]]), *command[1:]]
                if index == 2:
                    report["runtime_attempted"] = True
                result = subprocess.run(actual, cwd=directory, text=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, timeout=180, shell=False)
                log = result.stdout
                (directory / (command[0] + "-console.log")).write_text(log)
                if index < 2 and result.returncode:
                    raise RuntimeError(row["name"] + " " + command[0] + " failed")
                if index == 2:
                    result_row["status"] = classify_run(row, result.returncode, log)
        if args.run:
            report.update(status="PASS_SIMULATION_ONLY", runtime_executed=True,
                          vendor_primitive_executed=args.suite == "unisim")
            if args.suite == "unisim-profile":
                report["status"] = "PROFILE_PRINTED_NOT_PROTOCOL_QUALIFIED"
    except BaseException as error:
        report.update(status="FAILED", error=str(error))
        raise
    finally:
        if before != {p: sha(q) for p, q in inputs.items()}:
            report.update(status="FAILED", error="source changed during preparation/execution")
        if before != {p: sha(q) for p, q in staged.items()}:
            report.update(status="FAILED", error="staged simulation input changed during run")
        if report["installed_model_sha256"] != {k: sha(v) for k, v in vendor_files.items()}:
            report.update(status="FAILED", error="installed model source changed during run")
        report["log_sha256"] = {p.relative_to(output).as_posix(): sha(p)
                                for p in output.rglob("*.log") if p.is_file()}
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] == "FAILED":
        raise RuntimeError(report["error"])
    print(json.dumps({k: report[k] for k in ("status", "suite", "runtime_executed", "vendor_primitive_executed")}, indent=2))


if __name__ == "__main__":
    main()
