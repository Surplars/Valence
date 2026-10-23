# CommonMachinePlatform Linux build

This is a shared UP RV64GC-capable kernel and common rootfs with explicit I1 and A1 device-tree
boot profiles. Static BusyBox userland may use the LP64 soft-float subset; its
manifest records the actual ABI separately from hardware LP64D capability. It is not the old standalone FiveStageSoc and does not claim A1
board testing. Default CPU/fabric clocks are50MHz, mtime250MHz, DDR UI250MHz,
UART reference7.3728MHz/460800baud, and DDR2GiB starting at0x80200000. The driver
set is SoC identity, CSR-only AIA, fixed/leaf-gate CMU, memcpy DMAengine, GMAC
with packet DMA, and read-only clock/telemetry monitor. No automatic DVFS.

## Build stages

Use the prepared cloud toolchain environment and clean pinned source checkouts.
The current environment receipt is external to the repository and includes
compiler/package provenance. No downloads occur in these builders.

    source scripts/cloud/env.sh
    source /workspace/shared/valence-linux-build-cache/env.sh
    python3 fpga/firmware/debian_rootfs/build_image.py --platform common-boot50 \
      --stage kernel --out build/fpga/common-linux-boot50 --init-system busybox --jobs 8

The kernel stage works from tinyconfig without a historical baseline. It builds
the Image and six matching external modules once. The kernel-build.json records
release/vermagic, dependencies, exact module/source hashes, profile and config.
It rejects uninstalled in-tree modules. A bound historical cache is optional;
old profile metadata cannot silently become the new image profile.

Next the common_rootfs builder packages the exact six modules and BusyBox.
Use its CLI help for the rootfs invocation. Once rootfs-build-common.json exists:

    python3 fpga/firmware/debian_rootfs/build_image.py --platform common-boot50 \
      --stage image --out build/fpga/common-linux-boot50 \
      --rootfs-out build/fpga/common-linux-rootfs \
      --rootfs-record rootfs-build-common.json \
      --delivery-out build/fpga/common-linux-delivery --jobs 8

The image stage embeds the rootfs once, then builds two independent OpenSBI
wrappers with the same Linux Image and rootfs hashes. i1/ and a1/ contain their
own valence.vld, OpenSBI BIN/ELF, DTB/DTS, raw Image, config and manifest.
common-manifest.json binds both manifests. Pick the CPU matching the actual bit;
this does not switch the CPU inside the FPGA. BootROM -> OpenSBI -> Linux is the
normal chain; U-Boot is not required. Entry is0x80200000, DTB0x80300000,
Linux0x80400000. Preserve menu diagnostics/monitor reserved memory.

SBI console is the default. The independent legacy mode remains explicit via
--platform legacy and requires its own baseline. Common mode currently accepts only BusyBox/SBI; other init systems and UART-IRQ
remain explicit legacy flows until their complete module packaging is adapted.

Checks:

    python3 fpga/firmware/debian_rootfs/test_common_linux_profile.py
    python3 -m unittest discover -s fpga/firmware/linux_net -p test_build_image.py

Source/DT host checks are not Linux boot or peripheral board validation. Retain
prior bit identity and board evidence separately from these software manifests.

I1 enables the runtime clock monitor and dynamic CPU-rate CCF provider. A1 lacks
those hardware windows in the current platform, so its monitor node is disabled
and CMU has no dynamic parent reference. Both archives contain the same six
modules, with capability-conditional startup. No A1 dynamic-clock claim is made.
