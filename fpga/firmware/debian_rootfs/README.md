# Debian13 riscv64 VL100 builder

Authoritative interface/commands: [VL100 BSP](../../../docs/vl100-debian-bsp.md).
Keep source, Debian packages, rootfs, kernel objects and evidence in WSL.
Only deploy BIN/valence.vld/host scripts/manifest to Windows.

The bootstrap checks official signatures. QEMU-user only sets up foreign packages,
not hardware verification. New kernel builds default to the Dinit/LZ4 profile;
`--init-system systemd` and `--init-system busybox` preserve explicit alternatives.
Neither profile runs a generic SMP kernel, disk, SSH, automatic benchmark or board programming.
Serial root login and driver/network init are automatic.

Dinit RAM-root workflow (current 2 GiB repaired netboot bit; no new RTL/bit required):

    git clone --depth 1 --branch v0.19.4 https://github.com/davmac314/dinit.git build/fpga/dinit-source-0.19.4
    python3 fpga/firmware/debian_rootfs/build_dinit_rootfs.py --stage tools --out build/fpga/<new-tools> --source build/fpga/dinit-source-0.19.4
    python3 fpga/firmware/debian_rootfs/build_image.py --stage kernel --out build/fpga/<new-kernel> --baseline build/fpga/<qualified-firmware> --init-system dinit --initramfs-compression lz4
    sudo python3 fpga/firmware/debian_rootfs/build_dinit_rootfs.py --stage rootfs --out build/fpga/<new-rootfs> --seed build/fpga/<verified-pre-systemd-rootfs> --seed-record <rootfs-build-record.json> --tools-build build/fpga/<new-tools> --kernel-build build/fpga/<new-kernel>
    python3 fpga/firmware/debian_rootfs/build_image.py --stage image --out build/fpga/<new-kernel> --rootfs-out build/fpga/<new-rootfs> --delivery-out build/fpga/<new-delivery>
    python3 fpga/firmware/debian_rootfs/audit_dinit_delivery.py --delivery build/fpga/<new-delivery> --rootfs-out build/fpga/<new-rootfs>

Dinit is built from a fixed, clean upstream revision in `dinit/lock.json`, not an
unsigned package mirror or a Debian systemd conversion. The original signed minbase
is restored privately; no packages are removed from an existing systemd rootfs.
The six explicit descriptors only keep Dinit and one agetty/login/bash chain resident;
driver/network/ready scripts exit after startup. No udevd, D-Bus, journald or additional
getty daemons run. Debian bash/apt/network tools and all five drivers remain available.
Library packages may contain vendor systemd unit metadata; Dinit never reads it.

The network requires successful platform/IRQ setup; serial login does not. Driver
and network output is available via `dinitctl catlog platform` / `dinitctl catlog network`.
Logs have 32 KiB per-service buffers and /run is capped at 16 MiB. Use
`dinitctl stop network` / `dinitctl start network` to control eth0, and `dinitctl list`
for status. Dinit's shutdown helpers are separately named `dinit-reboot` etc.; board
shutdown/reboot has not been qualified. /init mounts API filesystems then execs Dinit.
agetty owns hvc0 without a nested setsid wrapper. The legacy inittab is not shipped.

The diagnostic kernel retains initcall_debug/loglevel=8 and timestamps. LZ4 reduces
decompression work, not physical DDR traffic; only board measurements establish speed.
The kernel cache can be seeded with `--reuse-kernel <matching-completed-cache>` into a
fresh output, never edited in place. LZ4 support/magic/exact unpacked cpio are checked.
Run `test_dinit_rootfs.py` for eight short checks, including isolated native supervision
with platform failure. Native/QEMU tool checks are not Valence CPU runtime verification.

Systemd fallback workflow:

    python3 fpga/firmware/debian_rootfs/build_image.py --stage kernel --out build/fpga/<kernel> --baseline build/fpga/<qualified-firmware> --init-system systemd
    sudo python3 fpga/firmware/debian_rootfs/build_systemd_rootfs.py --stage setup --out build/fpga/<new-rootfs> --seed build/fpga/<verified-rootfs> --seed-record <rootfs-build-record.json>
    sudo python3 fpga/firmware/debian_rootfs/build_systemd_rootfs.py --stage pack --out build/fpga/<new-rootfs> --kernel-build build/fpga/<kernel>
    python3 fpga/firmware/debian_rootfs/build_image.py --stage image --out build/fpga/<kernel> --rootfs-out build/fpga/<new-rootfs> --delivery-out build/fpga/<new-delivery>

The final root stays in RAM; `/init` execs Debian systemd as PID 1, not BusyBox init.
No `/etc/initrd-release` is shipped. Standard agetty on hvc0 provides serial-only root
autologin. `valence-platform.service` orders IRQ adapter, CMU, DMA and GMAC loading;
standard ifupdown networking.service owns /etc/network/interfaces. Journald is volatile
and limited to 16 MiB. No disk or remote service is required.

`boot-diagnose` collects initcall unpack time, systemd critical chain, failed services
and monotonic logs. The first diagnostic firmware deliberately uses loglevel=8 and a
1 MiB log buffer so populate_rootfs start/end are visible. This adds UART logging cost.
The source kernel and RTL remain unchanged. `mem-bench 32 3` measures aligned CPU-visible
streaming bandwidth and `dma-bench 8388608 4` measures the independent DMA path. Neither
is MIG peak bandwidth; COPY logical R+W is not a count of physical AXI bytes. Benchmarks
are manual only. Static checks/QEMU package setup are not a board runtime claim.

Legacy BusyBox stages using independent output directories (bootstrap/pack require WSL root):

    python3 fpga/firmware/debian_rootfs/build_rootfs.py --stage bootstrap --out build/fpga/<rootfs>
    python3 fpga/firmware/debian_rootfs/build_image.py --stage kernel --out build/fpga/<kernel> --memory-bytes 0x80000000 --init-system busybox
    python3 fpga/firmware/debian_rootfs/build_rootfs.py --stage pack --out build/fpga/<rootfs> --kernel-build build/fpga/<kernel>
    python3 fpga/firmware/debian_rootfs/build_image.py --stage image --out build/fpga/<kernel> --rootfs-out build/fpga/<rootfs>

Already packed drafts: --update-packed --generation <new-name>, then image
--rootfs-record rootfs-build-<new-name>.json. Completed archives/receipts are not overwritten.
Separate new release directories use --delivery-out. --resume-kernel only retries
an incomplete stage, retaining failures. CCF/DMAengine/SoC hidden Kconfig dependencies
are selected in a generated overlay, not patched upstream source.
For a systemd setup that installed packages but failed final static checks, use
`build_systemd_rootfs.py --stage finalize --out <same-incomplete-rootfs>`.
This rechecks the target packages and units without restoring/downloading again;
it refuses already packed rootfs outputs. Unit verification uses the target Debian
systemd-analyze via QEMU-user, not an older host systemd parser. Dry-run modprobe
explicitly selects the compiled RISC-V release, never the host WSL kernel.

Five W=1 module builds/vermagic/depmod/DT/exact-initramfs checks are not board qualification.
This 2 GiB image requires matching full-address RTL, Home stalled-read fix and ROM data.
