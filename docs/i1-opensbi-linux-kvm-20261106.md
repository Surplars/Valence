# I1 PS-DDR OpenSBI / Linux / KVM handoff — 2026-11-06

The frozen R8 reset-fixed bit booted upstream OpenSBI v1.9, the user's Linux
7.4.0-rc1 tree, and a small diagnostic initramfs. Two real KVM VS guest MMIO
probes passed: one automatically at init, one from the UART `kvm` command.
UART transcripts were supplied by the user; XSDB publication and OpenSBI probe
logs were captured directly by the agent. This is basic KVM execution acceptance,
not full guest Linux, virtual interrupts, FPU/V context, or H compliance acceptance.

Windows delivery under `E:/VM/Share/Valence-rtl/Valence-InOrder/`:
- `board-soc-cpu300-20261106-r8/opensbi-20261106-r1/`
- `board-soc-cpu300-20261106-r8/linux-kvm-20261106-r1/`

Each package preserves the same reset-fixed R8 bit and PS DDR initialization.
Run `xsdb run_firmware.tcl <package-directory>` for Linux. Add `probe` only for
the OpenSBI S-mode probe package. A cold system/RPU reset and PL configuration
are performed. UART is PL UART, 460800 8N1. RPU phase 7 means published/released;
it never claims that Linux or KVM passed. Their acceptance comes from the UART.
The init commands are `info`, `kvm`, `help`; this is not a shell.

Sources and rebuild entry points:
- `software/opensbi/build.py`, `valence-ps-ddr.dts`, `defconfig`, `source-lock.json`.
- `software/linux/build.py --source /home/openion/linux --output build/<fresh-name>
  --firmware build/i1-opensbi-20261106-r1/firmware/board/platform/generic/firmware/fw_jump.bin`.
- `software/opensbi/embed_image.py <flat-bin> --output build/<fresh-image-name>`.
- `software/ps-rpu/build.py --load-only`, using the existing board-derived BSP at
  `build/ps-rpu-handoff-20261106-r1/rpu-bsp` and SDK
  `/mnt/e/Xilinx/2025.2/data/embeddedsw`.
- Exact successful commands and SHA256 are in build receipts and package
  `board-acceptance.json`. Build paths stay under the WSL Valence-InOrder clone.
- Linux commit `f66469d9905b39d2c260a15d7d6db450f4db67c1`; clean upstream source,
  out-of-tree build, KVM/FPU/V built in, UP, no spinwait hart-index boot assumption.
- OpenSBI v1.9 commit `cbf9f6734dd85a982c63e3cb5db7ffe09da839ca`; no source patch.
  The clone is ignored under `third_party/opensbi`. Build needs a dtc; this run
  used `build/i1-opensbi-20261106-r1/linux/scripts/dtc/dtc` from the user's kernel.

Current R8 ABI (must match the existing bit, not a future CPU candidate):

| Item | Current value |
| --- | --- |
| CPU/VPU/system clocks | 300/300/300 MHz |
| RV DDR | 0x80000000..0x8fffffff, 256 MiB |
| Corresponding PS DDR | 0x40000000..0x4fffffff |
| OpenSBI / kernel | 0x80000000 / 0x80200000 |
| Relocated DTB / mailbox | 0x8fe00000 / 0x8fff0000 |
| DT reserved handoff area | top 2 MiB |
| Hart ID | 0xbeef, inherited integration-test value |
| Interrupts | PLIC M/S contexts; UART source 3; MTIMER/MSWI |
| Timebase / UART reference | 300000000 / 7372800 Hz |
| UART | 0x10000000, byte MMIO, 460800 8N1 |
| MMU / guest MMU | Sv39 / Sv39x4, Svade |
| PMP / ASID / VMID | 0 implemented PMP entries, ASIDLEN=VMIDLEN=0 |

OpenSBI detected privilege v1.12 and `rv64imafdcvh`. `misa` is
0x80000000003411ad. This is not RVA23. Missing features include scalar B,
cache-block operations, scalar/vector supplemental ISA and supervisor features
such as Sstc/Svpbmt/Svinval/Svnapot. Consult the official
[RVA23 v1.0 requirements](https://docs.riscv.org/reference/rva23/v1.0/rva23-profiles.html).
The next hardware task must standardize the sole hart to 0: the privileged spec
requires at least one hart with ID 0. Never change just the DT while running R8.

The CPU300 setup WNS remains -0.323 ns. Board smoke success is not timing signoff.
The bounded quiet OpenSBI GSIM diagnostic reached its 2,000,000-cycle budget
before S-mode completion, with 735,585 retired instructions, and is not a PASS.
Its source/log are retained; user-authorized real-board testing supplied the
completed OpenSBI and Linux/KVM evidence. No long Linux GSIM was run.

OS handoff: Debian 13 riscv64 is recommended and officially supported upstream.
The current image contains only the diagnostic initramfs, not a Debian rootfs.
Existing Valence adaptations live in `fpga/firmware/linux_net/` and
`fpga/firmware/debian_rootfs/`: external AIA/CMU/DMA/GMAC drivers, Kconfig overlay,
DT/rootfs tooling. Current PLIC and UART work with upstream drivers. Old AIA,
PL DDR and GMAC device trees do not match this PS-DDR bit. In particular, the old
CMU driver's allowed gate mask is 0x68; this board has SYSTEM/CPU/VPU and mask
0x6, so that driver must not be loaded unchanged. PS Ethernet service is not yet
implemented; there is no PL MAC in this bit.

The user moved all further OS work to another task. CPU follow-up will change
hart ID and DDR mapping; coordinate those changes using a new hardware manifest
and matching DT rather than overwriting these known bootable packages.
