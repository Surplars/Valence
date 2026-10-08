#!/usr/bin/env python3
"""Export the current uncommitted cumulative source and local short-test receipts.

Temporary Git indexes prove exact replay without staging the user's real index,
committing, pushing, or replacing any of the original dot evidence.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zlib

from stage_incremental import STAGED_FOLDERS, check, check_hashes, check_tree, validate_cpu_proof

ROOT = Path(__file__).resolve().parents[2]
BASE = "6c8977f684830137fae088d4679f9d84e5ce4a11"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args, env=None):
    return subprocess.check_output(["git", *map(str, args)], cwd=ROOT, env=env)


def validate_proofs(proofs, root):
    """PASS text alone must never requalify a receipt's changed sources."""
    statuses = {"cpu": "PASS_SELECTED_BOARD_FUNCTIONAL", "prefetch": "PASS",
                "prf": "PASS_PRF_RAM_ONLY", "monitor": "passed", "network": "passed"}
    check(set(proofs) == set(statuses), "Missing local prerequisite")
    documents = {role: json.loads(path.read_text()) for role, path in proofs.items()}
    for role, document in documents.items():
        check(document.get("status") == statuses[role], "Unpassed local prerequisite: " + role)
        if role == "cpu":
            validate_cpu_proof(document, root)
        else:
            check_hashes(root, document.get("source_sha256"), role + " frozen source drift")
    cpu = documents["cpu"]
    for role in ("prefetch", "prf", "monitor"):
        check(cpu["inputs"].get(str(proofs[role])) == sha(proofs[role]),
              "CPU did not test this prerequisite: " + role)
    rom = proofs["monitor"].parent / "firmware/bootrom.bin"
    check(rom.is_file() and documents["monitor"].get("rom_sha256") == sha(rom)
          and cpu["inputs"].get(str(rom)) == sha(rom), "Monitor/CPU ROM identity mismatch")
    return documents


def validate_physical_state(state, candidate, proofs):
    check(state.get("status") == "STAGED_SELECTED_DDR2G_RV64GC100_NOT_ROUTED",
          "Candidate ROM/IP staging is not finalized")
    check(state.get("proof_sha256") == sha(proofs["cpu"])
          and state.get("network_proof_sha256") == sha(proofs["network"]),
          "Candidate uses different functional proofs")
    check_tree(candidate, state["candidate_sha256"],
               (*STAGED_FOLDERS, "ip-build/board_ip.srcs", "ip-build/board_ip.gen"),
               "Candidate input inventory/content drift")
    rom = proofs["monitor"].parent / "firmware/bootrom.bin"
    check(sha(candidate / "firmware/bootrom.bin") == sha(rom), "Candidate uses different tested ROM")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    out = a.output.resolve()
    if out.exists():
        raise RuntimeError("Preserve previous handoff; select a fresh output")
    if git("rev-parse", "HEAD").decode().strip() != BASE:
        raise RuntimeError("Unexpected base HEAD")
    proof_dirs = {"cpu": "incremental-handoff-20261008-r1",
        "prefetch": "data-prefetch-handoff-20261008-r2", "prf": "prf-handoff-20261008-r1",
        "monitor": "monitor-handoff-20261008-r1", "network": "network-tx-handoff-20261008-r1"}
    proofs = {role: ROOT / "build/gsim" / name / "receipt.json" for role, name in proof_dirs.items()}
    validate_proofs(proofs, ROOT)
    proof_hashes = {role: sha(path) for role, path in proofs.items()}
    index = Path(git("rev-parse", "--git-path", "index").decode().strip())
    if not index.is_absolute():
        index = ROOT / index
    index_before = sha(index)
    out.mkdir(parents=True)
    temporary_root = ROOT / "build/handoff-20261008"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="export-index-", dir=temporary_root) as folder:
        environment = {**os.environ, "GIT_INDEX_FILE": str(Path(folder) / "selected.index")}
        git("read-tree", BASE, env=environment)
        git("add", "-A", "--", ".", env=environment)
        tree = git("write-tree", env=environment).decode().strip()
        patch = out / "all-current-changes-from-6c8977f.patch"
        patch.write_bytes(git("diff", "--cached", "--binary", "--full-index", BASE, env=environment))
        changed = git("diff", "--cached", "--name-only", "-z", BASE, env=environment).split(b"\0")
        check_env = {**os.environ, "GIT_INDEX_FILE": str(Path(folder) / "replay.index")}
        git("read-tree", BASE, env=check_env)
        git("apply", "--check", "--cached", patch, env=check_env)
        git("apply", "--cached", patch, env=check_env)
        replay = git("write-tree", env=check_env).decode().strip()
        if replay != tree:
            raise RuntimeError("Cumulative patch replay tree mismatch")
    if sha(index) != index_before:
        raise RuntimeError("Real index unexpectedly changed")
    sources = {p.decode(): sha(ROOT / p.decode()) for p in changed if p and (ROOT / p.decode()).is_file()}
    for name, digest in sources.items():
        dest = out / "changed-files" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, dest)
        if sha(dest) != digest:
            raise RuntimeError("Copied source mismatch: " + name)
    (out / "CHANGED-FILES.json").write_text(json.dumps(sources, indent=2) + "\n")
    receipts = out / "evidence"
    receipts.mkdir()
    unit_results = []
    for label, args in (("linux-software", ["-m", "unittest", "discover", "-s", "fpga/firmware/linux_net", "-p", "test_*.py"]),
                        ("rom-audit", ["-m", "unittest", "fpga/firmware/test_audit_bootrom.py"])):
        p = subprocess.run(["python3", *args], cwd=ROOT, capture_output=True, text=True,
                           timeout=60, env={**os.environ, "PYTHONPATH": "fpga/firmware"})
        log = receipts / (label + ".log")
        log.write_text(p.stdout + p.stderr)
        if p.returncode:
            raise RuntimeError(log.read_text())
        unit_results.append({"role": label, "log": str(log), "log_sha256": sha(log), "exit": 0})
    for role, path in proofs.items():
        shutil.copy2(path, receipts / (role + "-receipt.json"))
        logs = receipts / role
        logs.mkdir()
        # Small logs only; large GSIM/FIR/object checkpoints remain in WSL.
        for p in path.parent.rglob("*.log"):
            if p.stat().st_size < 256 * 1024:
                target = logs / p.relative_to(path.parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
        for p in path.parent.glob("receipt-before-*.json"):
            shutil.copy2(p, logs / p.name)
    rom = proofs["monitor"].parent / "firmware/bootrom.bin"
    candidate = "/mnt/e/VM/Share/Valence-rtl/native-rv64gc-incremental-20261008-r1"
    old = "/mnt/e/VM/Share/Valence-rtl/native-rv64gc-round2-20261007-r1"
    stage = ["python3", "fpga/zu15eg/stage_incremental.py", "--proof", str(proofs["cpu"]),
        "--network-proof", str(proofs["network"]), "--baseline", old,
        "--rtl", "build/fpga/incremental-20261008-r1/rtl", "--output", candidate, "--finalize-rom"]
    physical = Path(candidate) / "inputs.json"
    physical_state = json.loads(physical.read_text()) if physical.is_file() else None
    if physical_state is not None:
        validate_physical_state(physical_state, Path(candidate), proofs)
        shutil.copy2(physical, receipts / "candidate-inputs.json")
        shutil.copy2(Path(candidate) / "rom-ip.log", receipts / "rom-ip.log")
    state = {"status": "PASS_LOCAL_SHORT_ACCEPTANCE_NEXT_STA", "not_a_release": True,
        "updated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repo": str(ROOT), "branch": git("branch", "--show-current").decode().strip(), "base_commit": BASE,
        "source_uncommitted": True, "main_preserved": git("rev-parse", "main").decode().strip() == BASE,
        "commit_created": False, "pushed": False, "real_git_index_unchanged": True,
        "patch": patch.name, "patch_sha256": sha(patch), "changed_file_count": len(sources),
        "selected_git_tree": tree, "replayed_git_tree": replay, "replay_verified": True,
        "source_sha256": sources,
        "host_unit_results": unit_results,
        "proofs": {role: {"path": str(path), "sha256": proof_hashes[role],
            "status": json.loads(path.read_text())["status"]} for role, path in proofs.items()},
        "configuration": {"isa": "rv64gc", "issue_width": 2, "lsu_entries": 2, "cpu_hz": 100000000,
            "uart_baud": 460800, "ddr_bytes": 2147483648, "icache_bytes": 32768, "dcache_bytes": 32768,
            "read_mshrs": 2, "response_entries": 2, "ddr_slots": 4, "write_slots": 2, "writebacks": 2,
            "lvt_prf": True, "banked_rob": True, "shared_store_reads": True, "compact_tags": True,
            "identity_data_flow": True, "next_line_prefetch": True, "unordered_ddr_responses": True,
            "overlap_writeback_refill": True, "network_frame_bytes": 2048,
            "network_mac_rx_slots": 4, "network_rx_slots": 4, "network_tx_slots": 4, "network_memory_credits": 4,
            "defaults_changed": False},
        "rom": {"path": str(rom), "sha256": sha(rom), "bytes": rom.stat().st_size,
            "crc32": hex(zlib.crc32(rom.read_bytes())), "menu": True, "allocated_bytes": 131072,
            "netboot": True, "tftp_blksize": 1024, "tftp_windowsize": 4, "application_return_requires_reset": True},
        "windows_candidate": candidate.replace("/mnt/e/", "E:/"),
        "candidate_inputs": candidate + "/inputs.json",
        "candidate_input_status": physical_state["status"] if physical_state else "ROM_IP_NOT_FINALIZED",
        "rom_mif_audit": physical_state["rom_word_audit"] if physical_state else None,
        "remaining": ["One current complete-SoC synth/place/route and resource/RAM inference review",
            "Actual CPU100/AON50/UART50/MAC125/DDR250 STA, RGMII, CDC/reset/Gray/payload/DRC/ROM INIT review",
            "Kernel compilation of posted RX/TX drivers, rebuild image and DT consistency",
            "Board netboot/large-packet/netbench liveness and Linux FPU scheduling",
            "Matched byte-identical full-CPU performance baseline before claiming improvement"],
        "stage_finalize_command": stage,
        "stage_finalize_completed": bool(physical_state),
        "next_sta_tcl": candidate + "/scripts/build_native_board.tcl",
        "next_sta_tclargs": [candidate, candidate + "/mig/ZU15EG.srcs/sources_1/ip/ddr4_0/ddr4_0.xci",
            "rv64gc", "-", old + "/implementation/routed.dcp"],
        "scope_notes": ["Current WSL is already integrated: do NOT apply either cumulative patch again",
            "For a fresh clean exact base use ONLY the new all-current patch; never stack old component patches",
            "Keep two-issue/default flags unchanged; never bypass proof gates or relabel old timing as new",
            "No running full-SoC synthesis, no new bit, no board qualification",
            "Large reusable model/object artifacts remain in WSL; archive paths are not executables",
            "Do not apply the standalone XOR-owner experiment to the CPU"]}
    # Recheck frozen receipts and copied source identities after host tests.
    validate_proofs(proofs, ROOT)
    check(proof_hashes == {role: sha(path) for role, path in proofs.items()}, "Proof changed during export")
    for name, digest in sources.items():
        check(sha(ROOT / name) == digest, "Source changed during export: " + name)
    (out / "CURRENT-STATE.json").write_text(json.dumps(state, indent=2) + "\n")
    hashes = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    (out / "SHA256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(json.dumps({"status": state["status"], "files": len(sources), "tree_replay": True,
                      "output": str(out), "patch_sha256": state["patch_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
