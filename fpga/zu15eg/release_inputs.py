#!/usr/bin/env python3
"""Read-only adapter for the immutable fresh-BMG staging manifest.

This proves input identity, not implementation/CDC/release qualification. The
original hardware commit and the current qualification tools are distinct. Never
rewrite inputs.json to make an old release schema or receipt appear current.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

from verify_native_release_contract import require, sha

FRESH_STATUS = "STAGED_FRESH_BMG_EXACT_ROM_NOT_IMPLEMENTED"
HELPERS = "fpga/zu15eg/concurrency_validation/"
ROM = "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0"
INPUT_FOLDERS = ("rtl", "board", "scripts", "firmware", "mig",
                 "ip-build/board_ip.srcs", "ip-build/board_ip.gen")


def checked_file(root, name, digest):
    relative = Path(name)
    require(not relative.is_absolute() and ".." not in relative.parts and
            "\\" not in name and relative.as_posix() == name, "Unsafe input path: " + name)
    require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "Invalid digest: " + name)
    require(not any(root.joinpath(*relative.parts[:n]).is_symlink()
                    for n in range(1, len(relative.parts) + 1)), "Linked input: " + name)
    path = root / relative
    require(path.is_file() and sha(path) == digest, "Input identity mismatch: " + name)
    return path


def git_blob(repo, commit, name):
    return subprocess.check_output(["git", "-C", str(repo), "show", commit + ":" + name])


def load_release_inputs(root, repo, filename="inputs.json"):
    root, repo = Path(root).resolve(), Path(repo).resolve()
    inputs = json.loads((root / filename).read_text(encoding="utf-8-sig"))
    if inputs.get("status") != FRESH_STATUS:
        require("source_binding" not in inputs and "parameters_after_output" not in inputs,
                "Unrecognized fresh input schema/status")
        require("release_input_schema" not in inputs, "Adapter marker is not a stored input field")
        return inputs  # Legacy callers retain every existing legacy gate.

    binding = inputs["source_binding"]
    commit = binding["commit"]
    require(binding["status"] == "PASS" and re.fullmatch(r"[0-9a-f]{40}", commit),
            "Invalid source commit binding")
    source_bytes = git_blob(repo, commit, HELPERS + "integrated-source-sha256.json")
    require(hashlib.sha256(source_bytes).hexdigest() == binding["manifest_sha256"],
            "Bound source manifest changed")
    sources = json.loads(source_bytes)
    require(sources and len(sources) == binding["source_files"], "Incomplete source binding")
    expected_scala = {name for name in sources if name.startswith("src/main/scala/")}
    actual_scala = {p.relative_to(repo).as_posix() for p in (repo / "src/main/scala").rglob("*.scala")}
    tracked_scala = set(subprocess.check_output(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", commit, "src/main/scala"],
        text=True).splitlines())
    require(expected_scala and actual_scala == expected_scala ==
            {name for name in tracked_scala if name.endswith(".scala")}, "Production Scala inventory drift")
    for name, digest in sources.items():
        checked_file(repo, name, digest)
        require(hashlib.sha256(git_blob(repo, commit, name)).hexdigest() == digest,
                "Committed source drift: " + name)

    export = json.loads(git_blob(repo, commit, HELPERS + "EXPORT-RECEIPT.json"))
    require(export["status"] == "PASS_EXPORT_IDENTITY_FUNCTIONAL_SCOPE_ONLY", "Unqualified export identity")
    require(inputs["variant"] in ("integrated-off", "integrated-on"), "Only integrated source variants supported")
    variant = export["variants"][inputs["variant"]]
    params = inputs["parameters_after_output"]
    require(params == variant["parameters_after_output"] and
            inputs["cpu_precheck"] is variant["cpu_precheck"], "Export parameters changed or omitted")
    require(params[:15] == ["100000000", "staged-fetch-turnover", "460800", "rv64gc",
            "50000000", "50000000", "250000000", "2147483648", "512", "512", "4", "16", "2", "2", "1"],
            "Wrong explicit release CPU/UART/DDR/cache/clock profile")

    mapping = inputs["candidate_sha256"]
    require(mapping, "Empty candidate inventory")
    actual = set()
    for folder in INPUT_FOLDERS:
        require((root / folder).is_dir() and not (root / folder).is_symlink(), "Missing input folder: " + folder)
        for path in (root / folder).rglob("*"):
            require(not path.is_symlink(), "Linked candidate input: " + str(path))
            if path.is_file():
                actual.add(path.relative_to(root).as_posix())
    require(actual == set(mapping), "Incomplete or changed candidate inventory")
    for name, digest in mapping.items():
        checked_file(root, name, digest)
    require({name[4:]: digest for name, digest in mapping.items() if name.startswith("rtl/")} ==
            variant["rtl_sha256"], "RTL export inventory/hash mismatch")
    live_sources = dict(sources)
    for target, entry in export["source_map"].items():
        require(mapping.get(target) == entry["sha256"], "Staged board/script identity drift: " + target)
        require(hashlib.sha256(git_blob(repo, commit, entry["repo_path"])).hexdigest() == entry["sha256"],
                "Committed board/script identity drift: " + target)
        # A separate read-only reporting-tool revision may follow the hardware
        # commit. The actual staged scripts remain bound above; hardware and
        # constraints must also match the live checkout. No report is accepted
        # just because its generating tool changed.
        if target != "scripts/report_ram_concurrency.tcl":
            checked_file(repo, entry["repo_path"], entry["sha256"])
            live_sources[entry["repo_path"]] = entry["sha256"]

    expected = json.loads(git_blob(repo, commit, HELPERS + "expected-local-inputs.json"))
    fixed_folders = ("mig", *("ip-build/" + tree + "/sources_1/ip/" + name
                     for tree in ("board_ip.srcs", "board_ip.gen")
                     for name in ("clk_wiz_ddr", "axi_clock_converter_ddr")))
    fixed = {name: digest for name, digest in expected["sha256"].items()
             if any(name.startswith(folder + "/") for folder in fixed_folders)}
    require(fixed and inputs["fixed_ip_files_reused_by_exact_hash"] == len(fixed) and
            {name: digest for name, digest in mapping.items()
             if any(name.startswith(folder + "/") for folder in fixed_folders)} == fixed,
            "Fixed IP inventory/hash mismatch")
    for name in ("firmware/bootrom.bin", "firmware/bootrom.coe"):
        require(mapping.get(name) == expected["sha256"][name], "Wrong recovered ROM image: " + name)
    for key, value in (("historical_rom_binary_reproduced", True), ("historical_rom_dcp_reused", False),
                       ("cpu_checkpoint_reused", False)):
        require(inputs[key] is value, "Unsupported recovery provenance: " + key)
    auditor = "fpga/firmware/audit_bootrom.py"
    checked_file(repo, auditor, hashlib.sha256(git_blob(repo, commit, auditor)).hexdigest())
    spec = importlib.util.spec_from_file_location("release_bootrom_audit", repo / auditor)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rom = module.audit(root / "firmware/bootrom.bin", root / (ROM + ".mif"), root / (ROM + ".dcp"), "menu")
    for key in ("profile", "binaryBytes", "binarySha256", "mifWordsMatched", "romDcpSha256"):
        require(inputs["rom_word_audit"][key] == rom[key], "Fresh ROM proof drift: " + key)
    require(rom["binaryBytes"] == expected["rom_word_audit"]["binaryBytes"] and
            rom["mifWordsMatched"] == 32768, "Incomplete ROM word proof")

    config = checked_file(repo, "src/main/scala/core/ooo/BoardSocTop.scala",
                          sources["src/main/scala/core/ooo/BoardSocTop.scala"]).read_text()
    bases = re.findall(r'val ramBase = BigInt\("([0-9a-fA-F]+)", 16\)', config)
    require(len(bases) == 1 and int(bases[0], 16) == 0x80200000, "Unexpected source-bound RAM base")
    ram_base, ddr_bytes = int(bases[0], 16), int(params[7])
    profile = dict(isa="rv64gc", f_d_enabled=True, issue_width=2, cpu_hz=int(params[0]),
                   uart_baud=int(params[2]), ddr_bytes=ddr_bytes, ram_base=hex(ram_base),
                   end_exclusive=hex(ram_base + ddr_bytes), tx_clock_architecture="common_clk250_dedicated_oddr")
    for key, value in profile.items():
        require(key not in inputs or inputs[key] == value, "Conflicting release profile: " + key)
    return dict(inputs, **profile, checked_source_sha256=live_sources,
                release_input_schema="fresh-bmg-v1", hardware_source_commit=commit)
