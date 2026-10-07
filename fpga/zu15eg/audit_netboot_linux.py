#!/usr/bin/env python3
"""Revalidate and normalize the actual r3 IRQ/NAPI Linux payload for r4 release."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    repo = a.repo.resolve()
    sys.path.insert(0, str(repo / "fpga/firmware/linux_net"))
    import build_image as b
    from stage_firmware import cpio_files
    source = repo / "build/fpga/linux-net-rv64gc-20261006-r3"
    manifest = json.loads((source / "manifest.json").read_text())
    assert (manifest["isa"], manifest["issue_width"], manifest["cpu_hz"], manifest["uart_baud"]) == ("rv64gc", 2, 100000000, 460800)
    for mapping in (manifest["sources"], manifest["userland"]["sources"]):
        for name, digest in mapping.items():
            assert sha(repo / name) == digest, "Linux source drift: " + name
    b.validate_config((source / "linux.config").read_text())
    b.validate_dts((source / "valence-gc-gmac.dts").read_text())
    b.validate_dtb(source / "linux/scripts/dtc/dtc", source / "valence-gc-gmac.dtb")
    sources = {name: source / name for name in manifest["files"]}
    for name in ("valence_gmac.ko", "valence_aia.ko"):
        sources[name] = source / "module" / name
    for name in ("fpu-test", "coremark", "net-bench"):
        sources[name] = source / "apps" / name
    for name, path in sources.items():
        assert sha(path) == manifest["files"][name]["sha256"]
        assert path.stat().st_size == manifest["files"][name]["bytes"]
    image = source / "linux/arch/riscv/boot/Image"
    runtime_size = b.image_header(image)
    binary = sources[b.OUTPUT_NAME]
    padding = b.validate_payload(binary.read_bytes(), image.read_bytes())
    b.validate_embedded_dtb(binary.read_bytes(), sources["valence-gc-gmac.dtb"].read_bytes())
    compressed = (source / "linux/usr/initramfs_inc_data").read_bytes()
    offset = image.read_bytes().find(compressed)
    assert offset >= 0 and compressed[:2] == b"\x1f\x8b"
    uncompressed = gzip.decompress(compressed)
    packaged = cpio_files(uncompressed)
    expected = {
        "bin/busybox": source / "userland/busybox/busybox",
        **{"bin/" + name: sources[name] for name in ("coremark", "fpu-test", "net-bench")},
        **{"lib/modules/" + name: sources[name] for name in ("valence_gmac.ko", "valence_aia.ko")},
        **{target: b.HERE / name for target, name in (
            ("bin/net-status", "net-status"), ("bin/boot-time", "boot-time"),
            ("etc/network/interfaces", "interfaces"), ("init", "init"),
            ("bin/net-test", "net-test"), ("usr/share/udhcpc/default.script", "udhcpc.script"))},
    }
    for name, path in expected.items():
        assert packaged[name] == path.read_bytes(), "Actual initramfs drift: " + name
    for name in ("ip", "ping", "arping", "ifup", "ifdown", "udhcpc", "nc", "wget", "insmod"):
        assert any(path.endswith("/" + name) and data in (b"/bin/busybox", b"/bin/busybox\0")
                   for path, data in packaged.items()), "Missing BusyBox network applet"
    assert not a.out.exists(), "Preserve prior audit"
    a.out.mkdir(parents=True)
    normalized = a.out / "linux-inputs"
    normalized.mkdir()
    sources["Image"] = image
    for name, path in sources.items():
        shutil.copy2(path, normalized / name)
    manifest["files"] = {name: dict(bytes=path.stat().st_size, sha256=sha(path))
                         for name, path in sources.items()}
    manifest["normalized_source_manifest_sha256"] = sha(source / "manifest.json")
    save(normalized / "manifest.json", manifest)
    common = dict(source_directory=str(normalized.relative_to(repo)),
                  manifest_sha256=sha(normalized / "manifest.json"), physical_board_verified=False,
                  linux_fp_context_runtime_verified=False, bit_generated=False)
    save(a.out / "linux-input-audit.json", dict(common,
        status="PASS_NATIVE_LINUX_PAYLOAD_IDENTITY_NOT_RUNTIME",
        isa="rv64gc", issue_width=2, cpu_hz=100000000, uart_baud=460800,
        candidate_inputs_sha256=sha(a.candidate / "inputs.json"),
        payload_sha256=sha(binary), payload_bytes=binary.stat().st_size,
        kernel_entry="0x80400000", kernel_runtime_bytes=runtime_size, payload_padding=padding,
        dtb_sha256=sha(sources["valence-gc-gmac.dtb"]),
        timestamp_logging=True, data_plane="IRQ + NAPI; no periodic packet polling",
        original_firmware_manifest_sha256=sha(source / "manifest.json")))
    save(a.out / "kernel-rootfs-input-audit.json", dict(common,
        status="PASS_ACTUAL_KERNEL_INITRAMFS_CONTENTS_NOT_RUNTIME",
        kernel_image_sha256=sha(image), gzip_crc_verified=True,
        initramfs_offset_in_Image=hex(offset), cpio_entries=len(packaged),
        actual_payload_sha256={name: hashlib.sha256(packaged[name]).hexdigest() for name in expected},
        busybox_network_applets_verified=True,
        limits=["Actual packaged firmware contents verified, NOT physical networking or TCP liveness."]))
    print("PASS_NETBOOT_CURRENT_IRQ_NAPI_LINUX_ACTUAL_IMAGE_AND_INITRAMFS")


if __name__ == "__main__":
    main()
