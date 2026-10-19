#!/usr/bin/env python3
"""Bounded functional bring-up. Default: plan only; execution needs --run PROFILE."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROFILES = HERE / "config/bringup-profiles.json"
FLOOR_BYTES = 4 * 1024**3


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def free_bytes(path):
    return shutil.disk_usage(path).free


class Guard:
    """One bounded child process group at a time; preserve logs on every failure."""

    def __init__(self, output=None):
        self.output = output
        self.records = []

    def run(self, label, command, *, cwd=ROOT, timeout=120, expected=0, env=None):
        command = list(map(str, command))
        where = self.output or ROOT
        require(free_bytes(where) >= FLOOR_BYTES, "4 GiB free disk floor reached before " + label)
        log_path = self.output / (label + ".log") if self.output else None
        start = time.monotonic()
        minimum = free_bytes(where)
        error = None
        code = None
        with (log_path.open("w+b") if log_path else tempfile.TemporaryFile()) as log:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while True:
                    minimum = min(minimum, free_bytes(where))
                    require(minimum >= FLOOR_BYTES, "4 GiB free disk floor reached during " + label)
                    if process.poll() is not None:
                        break
                    require(time.monotonic() - start <= timeout, "bounded timeout during " + label)
                    time.sleep(0.2)
            except BaseException as exc:
                error = str(exc)
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
            code = process.returncode
            log.seek(0)
            result = log.read().decode(errors="replace")
        record = {"label": label, "command": command, "cwd": str(cwd), "exit": code,
                  "seconds": round(time.monotonic() - start, 3), "minimum_free_bytes": minimum,
                  "timeout_seconds": timeout, "error": error}
        if log_path:
            record.update(log=log_path.name, log_sha256=sha(log_path))
            (self.output / (label + ".json")).write_text(json.dumps(record, indent=2) + "\n")
        self.records.append(record)
        require(error is None, error or "child failed")
        require(code == expected, f"{label}: expected exit {expected}, got {code}; " + result[-3000:])
        return result


def executable(value, label):
    require(bool(value), "explicit --" + label + " is required")
    found = shutil.which(str(value))
    require(found is not None, label + " executable not found: " + str(value))
    # Preserve the invoked symlink name (clang++/gcc driver behavior may depend on it).
    return Path(found).absolute()


def validate_qualification(receipt, source, binary, cxx, revision, changed, diff_sha, lock):
    require(receipt.get("upstream_revision") == revision == lock["revision"], "qualification revision mismatch")
    require(receipt.get("upstream_repository") == lock["repository"], "qualification repository mismatch")
    require(receipt.get("historical_gate_modified") is False, "qualification must preserve historical gates")
    require(receipt.get("binary_sha256") == sha(binary), "qualified GSIM binary hash mismatch")
    require(receipt.get("compiler_sha256") == sha(cxx), "qualified compiler hash mismatch")
    require(receipt.get("patch_sha256") == diff_sha, "qualified GSIM patch hash mismatch")
    patches = receipt.get("patched_sources", {})
    require(bool(patches) and set(patches) == set(changed), "qualified modified-source set mismatch")
    for relative, expected in patches.items():
        path = (source / relative).resolve()
        require(path.is_relative_to(source.resolve()), "qualification source path escapes checkout")
        require(sha(path) == expected, "qualified source hash mismatch: " + relative)
    require(bool(receipt.get("focused_executions")) and bool(receipt.get("upstream_runtime_harnesses")),
            "qualification lacks focused and upstream runtime evidence")
    require("address,undefined" in receipt.get("sanitizers", ""), "qualification lacks sanitizer evidence")


def classpath_manifest(path, main="inorder.FiveStageSocGsimMain"):
    content = path.read_text().strip()
    require(bool(content), "empty Java classpath")
    records = {}
    found_main = False
    for entry in content.split(os.pathsep):
        item = Path(entry)
        require(item.is_absolute(), "classpath entry must be absolute: " + entry)
        if not item.exists():
            require(item.name in ("resources", "compile-resources"), "classpath entry missing: " + entry)
            records[entry] = {"status": "absent optional resource directory; ignored by Java"}
            continue
        if item.is_dir():
            files = sorted(item.rglob("*.class"))
            records[entry] = {str(p.relative_to(item)): sha(p) for p in files}
            found_main |= (item / (main.replace(".", "/") + ".class")).is_file()
        else:
            records[entry] = sha(item)
    require(found_main, "classpath lacks compiled " + main)
    return content, {"file": str(path), "file_sha256": sha(path), "entries": records,
                     "main": main, "mode": "explicit existing classes; no implicit compilation"}


def verify_classpath_unchanged(saved):
    _, current = classpath_manifest(Path(saved["file"]), saved["main"])
    require(current == saved, "compiled classpath drift during execution")


def preflight(args, profile, guard):
    require(profile["status"] == "executable_fixture", "profile blocked: " + "; ".join(profile.get("blockers", [])))
    require(args.gsim_source is not None, "explicit --gsim-source is required")
    source = args.gsim_source.resolve()
    binary = executable(args.gsim_bin, "gsim-bin")
    cxx = executable(args.cxx, "cxx")
    gcc = executable(args.gcc, "gcc")
    objcopy = executable(args.objcopy, "objcopy")
    lock = json.loads((HERE / "config/toolchain.json").read_text())
    revision = guard.run("gsim-revision", ["git", "rev-parse", "HEAD"], cwd=source).strip()
    require(revision == lock["revision"], "GSIM upstream pin mismatch")
    # Check staged and unstaged tracked modifications against HEAD; never rewrite old gates.
    changed = guard.run("gsim-changed", ["git", "diff", "HEAD", "--name-only"], cwd=source).splitlines()
    diff = guard.run("gsim-patch", ["git", "diff", "HEAD", "--binary"], cwd=source)
    version = guard.run("cxx-version", [cxx, "--version"]).splitlines()[0]
    match = re.search(r"clang version (\d+)", version)
    require(match and int(match[1]) >= lock["minimum_clang_major"], "Clang 19 or newer required")
    qualification = None
    if args.gsim_qualification:
        qualification = json.loads(args.gsim_qualification.read_text())
        validate_qualification(qualification, source, binary, cxx, revision, changed,
                               hashlib.sha256(diff.encode()).hexdigest(), lock)
    else:
        require(not changed, "modified GSIM requires explicit --gsim-qualification; old clean-pin gate retained")
    gcc_version = guard.run("gcc-version", [gcc, "--version"]).splitlines()[0]
    require(guard.run("gcc-target", [gcc, "-dumpmachine"]).strip() == "riscv64-unknown-elf",
            "payload compiler must target riscv64-unknown-elf")
    objcopy_version = guard.run("objcopy-version", [objcopy, "--version"]).splitlines()[0]
    inputs = ("driver", "wrapper", "firmware_builder") if profile.get("flow") == "ooo_local_rom" else (
        "driver", "payload", "linker", "rom")
    for key in inputs:
        require((ROOT / profile[key]).is_file(), "profile input missing: " + profile[key])
    tools = {"gsim_source": str(source), "gsim_revision": revision, "gsim_binary": str(binary),
             "gsim_binary_sha256": sha(binary), "gsim_tracked_patch_sha256": hashlib.sha256(diff.encode()).hexdigest(),
             "compiler": str(cxx), "compiler_version": version, "compiler_sha256": sha(cxx),
             "gcc": str(gcc), "gcc_version": gcc_version, "gcc_sha256": sha(gcc),
             "objcopy": str(objcopy), "objcopy_version": objcopy_version, "objcopy_sha256": sha(objcopy),
             "gsim_mode": "explicit qualified patched tool" if qualification else "clean pinned source",
             "historical_pin_gates_modified": False}
    if profile.get("flow") == "ooo_local_rom":
        require(gcc.name == "riscv64-unknown-elf-gcc", "OoO firmware needs a riscv64-unknown-elf-gcc prefix")
        prefix = str(gcc)[:-3]
        require(Path(prefix + "objcopy").resolve() == objcopy.resolve(),
                "OoO firmware prefix must select the explicit objcopy")
        size = executable(prefix + "size", "size")
        size_version = guard.run("size-version", [size, "--version"]).splitlines()[0]
        tools.update(cross_prefix=prefix, size=str(size), size_sha256=sha(size), size_version=size_version,
                     python=sys.executable, python_sha256=sha(sys.executable))
    if qualification:
        tools["qualification_file"] = str(args.gsim_qualification.resolve())
        tools["qualification_sha256"] = sha(args.gsim_qualification)
        tools["qualification_scope"] = qualification.get("scope")
    if args.java_classpath_file:
        cp, manifest = classpath_manifest(args.java_classpath_file.resolve(), profile["main"])
        java = executable(args.java, "java")
        tools.update(java=str(java), java_sha256=sha(java), classpath=manifest)
        emitter = [str(java), "-Xmx2g", "-XX:ActiveProcessorCount=2", "-Dchisel.project.root=" + str(ROOT),
                   "-cp", cp, profile["main"]]
    else:
        mill = shlex.split(args.mill_command)
        require(bool(mill), "empty --mill-command")
        executable(mill[0], "mill-command")
        emitter = [*mill, profile.get("mill_module", "OrbitalI1") + ".test.runMain", profile["main"]]
        tools["mill_command"] = mill
    return tools, emitter


def source_manifest(profile=None):
    paths = [ROOT / "build.mill", ROOT / "AGENTS.md", Path(__file__), PROFILES,
             HERE / "config/toolchain.json"]
    paths += list((ROOT / "src/main/scala").rglob("*.scala"))
    paths += list((ROOT / "src/test/scala/inorder").glob("*.scala"))
    paths += list((HERE / "harness").glob("five_stage*.cpp"))
    paths += list((HERE / "harness").glob("five_stage*.h"))
    paths += list((ROOT / "fpga/inorder/bootrom").glob("*"))
    paths += [HERE / "inorder/soc_smoke.S", HERE / "inorder/soc_link.ld",
              ROOT / "src/main/resources/inorder/bootrom.hex"]
    if profile and profile.get("flow") == "ooo_local_rom":
        paths += [ROOT / profile["wrapper"], ROOT / profile["driver"]]
        paths += [p for p in (ROOT / "fpga/firmware").rglob("*")
                  if p.suffix in (".py", ".S", ".c", ".h", ".ld", ".json")]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths)) if p.is_file()}


def validate_positive(text):
    require("FIVE_STAGE_SOC_PASS " in text, "positive oracle completion marker missing")
    require("ddr_2g_uart_loopback_msip_mtip_plic_mmio_axi_fault=PASS" in text, "functional chain marker missing")
    counters = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", text)}
    require(counters.get("rom_retired", 0) > 0, "positive execution did not retire BootROM instructions")
    require(counters.get("retired", 0) > 0 and counters.get("axi_reads", 0) > 0 and
            counters.get("axi_writes", 0) > 0, "positive execution lacks CPU/DDR activity")
    require(counters.get("jtag") == 0 and counters.get("retry") == 0, "unexpected boot fixture")
    return counters


def run_i1(profile, output, tools, emitter, guard, receipt, save):
    firmware = output / "firmware"
    firmware.mkdir()
    gcc, objcopy = tools["gcc"], tools["objcopy"]
    flags = ["-march=rv64i_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany", "-mno-relax",
             "-nostdlib", "-nostartfiles", "-Wl,--no-relax"]
    # Direct requested compiler paths: no PATH wrapper and no writes into historical evidence.
    for name, assembly, linker in (("bootrom", ROOT / "fpga/inorder/bootrom/start.S",
                                    ROOT / "fpga/inorder/bootrom/link.ld"),
                                   ("soc", ROOT / profile["payload"], ROOT / profile["linker"])):
        guard.run(name + "-assemble", [gcc, *flags, "-T" + str(linker), assembly,
                                        "-o", firmware / (name + ".elf")])
        guard.run(name + "-objcopy", [objcopy, "-O", "binary", firmware / (name + ".elf"),
                                       firmware / (name + ".bin")])
    image = (firmware / "bootrom.bin").read_bytes()
    require(0 < len(image) <= 4096, "ROM image does not fit 4 KiB")
    padded = image + bytes(4096 - len(image))
    rom_text = "".join(f"{int.from_bytes(padded[n:n+8], 'little'):016x}\n" for n in range(0, 4096, 8))
    rebuilt_rom = firmware / "bootrom.hex"
    rebuilt_rom.write_text(rom_text)
    checked_rom = ROOT / profile["rom"]
    require(rom_text.splitlines() == checked_rom.read_text().splitlines(),
            "checked BootROM does not reproduce from checked assembly")
    require((firmware / "soc.bin").stat().st_size > 0, "empty SoC guest")
    receipt["bootrom"] = {"source_reproduced": True, "bytes": len(image), "hex_sha256": sha(checked_rom)}
    model = output / "model"
    model.mkdir()
    guard.run("elaborate", [*emitter, model, profile["xlen"], *profile["flags"]], timeout=600)
    fir = model / (profile["top"] + ".fir")
    require(fir.is_file() and "romInitialize" in fir.read_text(), "wrong ROM simulation fixture")
    guard.run("generate", [tools["gsim_binary"], "--threads=1", "--dir=" + str(model), fir], timeout=600)
    units = sorted(model.glob(profile["top"] + "[0-9]*.cpp"))
    require(bool(units), "GSIM emitted no model translation units")
    binary = model / "run"
    guard.run("compile", [tools["compiler"], "-std=c++20", "-O1", "-fsanitize=address,undefined",
                          "-fno-sanitize-recover=all", "-DDUT_XLEN=64", "-DI1_HAS_ROM=1",
                          "-I" + str(model), *units, ROOT / profile["driver"], "-o", binary], timeout=900)
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    argv = [binary, firmware / "soc.bin", checked_rom]
    positive = guard.run("positive", argv, env=env, timeout=180)
    counters = validate_positive(positive)
    negative = guard.run("negative", [*argv, "--inject"], env=env, timeout=180, expected=1)
    require("bare SoC guest fail path" in negative, "negative oracle did not reject DDR corruption")
    require("FIVE_STAGE_SOC_PASS" not in negative, "negative execution also reported success")
    require(not any(x in negative for x in ("AddressSanitizer", "runtime error:", "UndefinedBehaviorSanitizer")),
            "negative execution hit a sanitizer failure")
    return {"status": "PASS_FUNCTIONAL_I1_COMPACT_ROM", "checks": {"positive": positive.strip(),
            "negative": negative.strip(), "negative_control": "PASS_REJECTED_DDR_CORRUPTION"},
            "counters": counters}


def validate_ooo_contract(contract, rom):
    expected = {"cpu_hz": 40000000, "timebase_hz": 40000000, "uart_divisor": 1,
                "uart_reference_hz": 24000000, "uart_baud": 1500000, "uart_contract_checked": True,
                "boot_menu": False, "netboot": False, "jtag_download": False, "ddr_bytes": None,
                "boot_ui": "plain", "download_autostart": True, "manual_image_launch": False,
                "image_limit": 0xfc000,
                "external_return_policy": "reset_required_unknown_peripheral_ownership"}
    for key, value in expected.items():
        require(key in contract and contract[key] == value, "OoO firmware contract mismatch: " + key)
    require(contract.get("bootrom_sha256") == sha(rom), "OoO firmware ROM hash mismatch")


def validate_ooo_positive(text):
    markers = ("reset ROM banner / ROM instruction-byte oracle: PASS",
               "whole-image bad CRC / no unverified execution / manual launch removed: PASS",
               "chunk CRC retry / RAM image byte oracle / AUTOBOOT sample guest: PASS",
               "APP RETURN / download and manual-launch lock: PASS",
               "hardware reset / fresh AUTOBOOT / byte-half-word-doubleword loads / RAM signature: PASS",
               "IRQ delivery chain: NOT COVERED", "DDR / Linux / frequency / physical board: NOT COVERED",
               "GSIM functional board baseline: PASS ")
    for marker in markers:
        require(marker in text, "OoO completion marker missing: " + marker)
    require(not any(x in text for x in ("AddressSanitizer", "runtime error:", "UndefinedBehaviorSanitizer")),
            "OoO execution hit a sanitizer failure")
    counters = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", text)}
    for key in ("cycles", "romCommits", "ramCommits", "ramReads", "ramWrites", "checkedReadBytes", "uartBytes"):
        require(counters.get(key, 0) > 0, "OoO oracle coverage absent: " + key)
    require(counters["cycles"] <= 30000000, "OoO cycle bound exceeded")
    require(counters.get("uartDivisor") == 1 and counters.get("ramBytes") == 1048576,
            "OoO runtime fixture mismatch")
    return counters


def run_ooo(profile, output, tools, emitter, guard, receipt, save):
    receipt.update(irq_chain_status="NOT COVERED", independent_clock_platform_status="NOT COVERED")

    def stage(name):
        receipt["stage"] = name
        save()

    stage("FIRMWARE_BUILD")
    firmware = output / "firmware"
    require(not firmware.exists(), "fresh OoO firmware directory required")
    guard.run("firmware-build", [tools["python"], "-B", ROOT / profile["firmware_builder"],
                                "--out", firmware, "--prefix", tools["cross_prefix"],
                                "--cpu-hz", "40000000", "--uart-divisor", "1",
                                "--uart-reference-hz", "24000000", "--uart-baud", "1500000"], timeout=120)
    rom, sample = firmware / "bootrom.bin", firmware / "sample_app.bin"
    require(0 < rom.stat().st_size <= 131072, "OoO ROM image size mismatch")
    require(0 < sample.stat().st_size <= 0xfc000, "OoO sample image size mismatch")
    contract = json.loads((firmware / "bootrom-contract.json").read_text())
    validate_ooo_contract(contract, rom)
    receipt["firmware_contract"] = contract
    stage("FIRMWARE_CONTRACT_PASS_MODEL_ELABORATION")
    model = output / "model"
    model.mkdir()
    guard.run("elaborate", [*emitter, model], timeout=600)
    fir = model / (profile["top"] + ".fir")
    require(fir.is_file() and "io : {" in fir.read_text(), "OoO model FIR missing")
    stage("MODEL_ELABORATED_GSIM_GENERATION")
    guard.run("generate", [tools["gsim_binary"], "--threads=1", "--dir=" + str(model), fir], timeout=600)
    units = sorted(model.glob(profile["top"] + "[0-9]*.cpp"))
    require(bool(units), "GSIM emitted no OoO model translation units")
    stage("MODEL_GENERATED_HOST_COMPILATION")
    binary = model / "run"
    guard.run("compile", [tools["compiler"], "-std=c++20", "-O1", "-fsanitize=address,undefined",
                          "-fno-sanitize-recover=all", "-I" + str(model), *units,
                          ROOT / profile["driver"], "-o", binary], timeout=900)
    stage("MODEL_COMPILED_FUNCTIONAL_BOOT_EXECUTION")
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    positive = guard.run("functional-boot", [binary, rom, sample], env=env, timeout=600)
    counters = validate_ooo_positive(positive)
    stage("FUNCTIONAL_BOOT_PASS_IRQ_NOT_COVERED")
    return {"status": "PASS_FUNCTIONAL_OOO_LOCAL_ROM_IRQ_NOT_COVERED", "counters": counters,
            "checks": {"functional_boot": positive.strip(),
                       "negative_controls": "PASS_BAD_IMAGE_CRC_CHUNK_RETRY_MANUAL_LAUNCH_AND_RETURN_LOCK"}}


def run_profile(profile, *args):
    flow = profile.get("flow", "i1_compact_rom")
    require(flow in ("i1_compact_rom", "ooo_local_rom"), "unknown execution flow: " + flow)
    return (run_ooo if flow == "ooo_local_rom" else run_i1)(profile, *args)


def execute(args, profile):
    output = args.output.resolve()
    require(not output.exists(), "refusing to overwrite existing output: " + str(output))
    output.mkdir(parents=True)
    guard = Guard(output)
    frozen = source_manifest(profile)
    receipt = {"status": "RUNNING", "profile_name": args.run, "profile": profile,
               "source_sha256": frozen, "physical_qualified": False, "performance_qualified": False,
               "clock_scope": "single CPU/fabric clock; independent clocks and CDC not exercised",
               "free_disk_floor_bytes": FLOOR_BYTES, "commands": guard.records}

    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    save()
    try:
        tools, emitter = preflight(args, profile, guard)
        receipt["tools"] = tools
        receipt["git_head"] = guard.run("project-revision", ["git", "rev-parse", "HEAD"]).strip()
        receipt["git_status"] = guard.run("project-status", ["git", "status", "--short"])
        save()
        result = run_profile(profile, output, tools, emitter, guard, receipt, save)
        require(all(sha(ROOT / name) == digest for name, digest in frozen.items()), "source drift during execution")
        if "classpath" in tools:
            verify_classpath_unchanged(tools["classpath"])
            receipt["compiled_classpath_unchanged"] = True
        receipt.update(result)
    except BaseException as error:
        receipt.update(status="FAIL", error=str(error))
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*"))
                                       if p.is_file() and p.name != "receipt.json"}
        save()
        print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}))


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--run", metavar="PROFILE")
    mode.add_argument("--preflight", metavar="PROFILE")
    mode.add_argument("--plan", action="store_true")
    ap.add_argument("--output", type=Path, help="fresh evidence directory, mandatory for --run")
    ap.add_argument("--gsim-source", type=Path)
    ap.add_argument("--gsim-bin")
    ap.add_argument("--gsim-qualification", type=Path, help="explicit compatible patched-tool qualification receipt")
    ap.add_argument("--cxx")
    ap.add_argument("--gcc")
    ap.add_argument("--objcopy")
    ap.add_argument("--java-classpath-file", type=Path, help="reuse explicitly selected compiled classes")
    ap.add_argument("--java", default="java")
    ap.add_argument("--mill-command", default="mill -i -j2", help="argv parsed without a shell; used unless classpath supplied")
    return ap


def main(argv=None):
    ap = parser()
    args = ap.parse_args(argv)
    config = json.loads(PROFILES.read_text())
    selected = args.run or args.preflight
    if not selected:
        print(json.dumps({**config, "free_disk_floor_bytes": FLOOR_BYTES,
                          "current_free_bytes": free_bytes(ROOT), "executed": False}, indent=2))
        return 0
    if selected not in config["profiles"]:
        ap.error("unknown profile: " + selected)
    if args.run and args.output is None:
        ap.error("--run requires --output pointing to a fresh evidence directory")
    profile = config["profiles"][selected]
    try:
        if args.run:
            execute(args, profile)
        else:
            tools, _ = preflight(args, profile, Guard())
            print(json.dumps({"status": "PREFLIGHT_PASS_NOT_EXECUTED", "profile": selected,
                              "fixture": profile, "tools": tools}, indent=2))
    except (OSError, RuntimeError, ValueError) as error:
        print("bringup: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
