#!/usr/bin/env python3
"""Strictly stage the two-leaf network-liveness ECO; never mutate the donor."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume-incomplete", action="store_true")
    args = parser.parse_args()
    repo, old, out = args.repo, args.baseline, args.output
    if out.exists():
        assert args.resume_incomplete and not (out / "inputs.json").exists(), "Preserve existing candidate"
        assert not any(out.rglob("*.dcp")), "Do not restage an implemented candidate"
    old_manifest = load(old / "inputs.json")
    changed_sources = {"src/main/scala/core/ooo/CoherentLineCache.scala",
                       "src/main/scala/ip/dma/EthernetPacketDma.scala"}
    source_changes = {name for name, digest in old_manifest["checked_source_sha256"].items()
                      if sha(repo / name) != digest}
    assert source_changes == changed_sources, sorted(source_changes)
    # Hash all old frozen input files before reusing the checkpoint's identity.
    for name, digest in old_manifest["candidate_sha256"].items():
        assert sha(old / name) == digest, "Donor input drift: " + name
    rtl = repo / "build/fpga/netboot-20261006-r4/export/rtl"
    fresh = {p.name: sha(p) for p in rtl.glob("*.sv")}
    previous = {p.name: sha(p) for p in (old / "rtl").glob("*.sv")}
    assert set(fresh) == set(previous) and len(fresh) == 236
    changes = {name for name in fresh if fresh[name] != previous[name]}
    assert changes == {"CoherentLineCache.sv", "EthernetPacketDma.sv"}, sorted(changes)
    checks = {
        "native_short": repo / "build/gsim/rv64gc-native-netboot-20261006-r4/receipt.json",
        "network_liveness": repo / "build/gsim/network-boot-checks-20261006-r4/receipt.json",
        "network_liveness_base": repo / "build/gsim/network-boot-checks-20261006-r3/receipt.json",
        "netboot": repo / "build/fpga/bootrom-netboot-checks-20261006-r1/receipt.json",
    }
    for role, path in checks.items():
        proof = load(path)
        if role == "native_short":
            assert proof["status"] == "PASS_RV64GC_NATIVE_AFFECTED_SHORT"
        else:
            assert proof["status"] in {"passed", "PASS_NETWORK_BOOT_AFFECTED_SHORT"}, proof["status"]
        for name, digest in proof.get("source_sha256", {}).items():
            assert sha(repo / name) == digest, role + " source drift: " + name
    fw = checks["netboot"].parent
    assert sha(fw / "netboot/bootrom.bin") == load(checks["netboot"])["netboot_rom_sha256"]
    donor = old / "implementation-report-recovery-r1/routed.dcp"
    assert donor.is_file()
    out.mkdir(parents=True, exist_ok=args.resume_incomplete)
    shutil.copytree(rtl, out / "rtl", dirs_exist_ok=args.resume_incomplete)
    for name in ("board", "scripts"):
        shutil.copytree(old / name, out / name, dirs_exist_ok=args.resume_incomplete)
    for name in ("build_netboot_rom.tcl", "synth_netboot_leaf.tcl",
                 "replace_network_candidate.tcl"):
        source = repo / "fpga/zu15eg" / name
        if source.exists():
            shutil.copy2(source, out / "scripts" / name)
    shutil.copytree(fw / "netboot", out / "firmware", dirs_exist_ok=args.resume_incomplete)
    release = out / "firmware-net-rv64gc-r4"
    release.mkdir(exist_ok=args.resume_incomplete)
    for name in ("valence.vld", "netboot_host.py"):
        shutil.copy2(fw / name, release / name)
    for name in ("uart_load.py", "linux_net/net_bench_peer.py"):
        shutil.copy2(repo / "fpga/firmware" / name, release / Path(name).name)
    linux = repo / "build/fpga/linux-net-rv64gc-20261006-r3/opensbi_linux_rv64gc_cpu100_u460800_gmac_fpu.bin"
    shutil.copy2(linux, release / linux.name)
    manifest = dict(old_manifest)
    manifest.update(status="STAGED_RV64GC_SOURCE_NOT_TIMING_QUALIFIED",
                    cpu_checkpoint_reused=True, bit_generated=False,
                    short_receipt_sha256=sha(checks["native_short"]),
                    checked_source_sha256={name: sha(repo / name)
                                           for name in old_manifest["checked_source_sha256"]},
                    candidate_sha256={str(p.relative_to(out)): sha(p)
                                      for p in out.rglob("*") if p.is_file()},
                    baseline_candidate=str(old), donor_checkpoint=str(donor),
                    donor_checkpoint_sha256=sha(donor),
                    donor_inputs_sha256=sha(old / "inputs.json"),
                    changed_rtl=sorted(changes), changed_sources=sorted(changed_sources),
                    fresh_export_sha256=fresh, netboot_enabled=True,
                    netboot_ip="192.168.137.30", netboot_server="192.168.137.1",
                    netboot_filename="valence.vld",
                    new_evidence={role: dict(path=str(path), sha256=sha(path))
                                  for role, path in checks.items()},
                    limits=["Incremental routed donor reuse, NOT fresh complete-SoC synthesis.",
                            "Cache and DMA RTL replaced; every other exported RTL shard is identical.",
                            "Linux IRQ/NAPI software reused; physical TCP lock fix NOT board-verified.",
                            "Network BootROM portable tests are not board PHY/DDR proof."])
    (out / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(status=manifest["status"], candidate=str(out),
                         changed_rtl=sorted(changes), donor_sha256=sha(donor))))


if __name__ == "__main__":
    main()
