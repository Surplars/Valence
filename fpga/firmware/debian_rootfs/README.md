# Debian13 riscv64 VL100 builder

Authoritative interface/commands: [VL100 BSP](../../../docs/vl100-debian-bsp.md).
Keep source, Debian packages, rootfs, kernel objects and evidence in WSL.
Only deploy BIN/valence.vld/host scripts/manifest to Windows.

The bootstrap checks official signatures. QEMU-user only sets up foreign packages,
not hardware verification. No systemd, generic SMP kernel, disk, SSH, automatic
benchmark or board programming. Serial root login and driver/network init are automatic.

Stages using independent output directories (bootstrap/pack require WSL root):

    python3 fpga/firmware/debian_rootfs/build_rootfs.py --stage bootstrap --out build/fpga/<rootfs>
    python3 fpga/firmware/debian_rootfs/build_image.py --stage kernel --out build/fpga/<kernel> --memory-bytes 0x80000000
    python3 fpga/firmware/debian_rootfs/build_rootfs.py --stage pack --out build/fpga/<rootfs> --kernel-build build/fpga/<kernel>
    python3 fpga/firmware/debian_rootfs/build_image.py --stage image --out build/fpga/<kernel> --rootfs-out build/fpga/<rootfs>

Already packed drafts: --update-packed --generation <new-name>, then image
--rootfs-record rootfs-build-<new-name>.json. Completed archives/receipts are not overwritten.
Separate new release directories use --delivery-out. --resume-kernel only retries
an incomplete stage, retaining failures. CCF/DMAengine/SoC hidden Kconfig dependencies
are selected in a generated overlay, not patched upstream source.

Five W=1 module builds/vermagic/depmod/DT/exact-initramfs checks are not board qualification.
This 2 GiB image requires matching full-address RTL, Home stalled-read fix and ROM data.
