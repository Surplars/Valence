# Common I1/A1 Debian candidate

This is a new cloud-built candidate, not a replacement of the previously delivered
read-only BusyBox r2. No Linux board boot or performance result is implied by a
successful build, QEMU userspace check, or native host test.

## Components and policy

- One pinned Linux kernel and one real Debian 13 (`trixie`, `riscv64`) RAM root.
  The root includes configured Debian packages and `dpkg`/`apt`, not a BusyBox
  impersonation of Debian. Package versions/hashes/signature provenance live in
  the base receipt. Dinit is pinned by `dinit/lock.json` and actually cross-built.
- Dinit runs as PID 1, with Debian shell/utilities and an SBI serial root console.
  There is no SSH service, persistent disk, systemd, udev, or dbus daemon.
  Package changes disappear after reboot; `apt` needs an operational link,
  gateway/DNS and adequate RAM. Network defaults remain explicitly editable
  `192.168.137.30/24`, gateway/DNS `192.168.137.1`.
- DDR is 2 GiB starting at `0x80200000`; reference timebase remains 250 MHz.
  Reset CPU/fabric clocks are 50 MHz. Shared reset-contract fields are not a
  claim that every later runtime CPU rate remains 50 MHz.
- The normal build option defaults to read-only boot50. The new explicit
  `--i1-boot-cpu-hz 125000000` option adds the reviewed control policy to the I1 DT.
  Earliest platform module loading lets the clockmon driver perform one bounded
  CPU-only 50→125 request, before CMU/AIA/DMA/GMAC initialization. Exact hardware
  tuple is D10/M40/O8; fabric is not changed. Unknown/faulted state is not called
  a successful fallback. The driver owns all rate writes, not shell/devmem.
- Loading a module in Linux cannot speed up the preceding ROM netboot transfer,
  OpenSBI startup or kernel/initramfs decompression. Those are separate paths.
- The old A1 platform still has no runtime rate/performance windows: its DT
  disables clockmon and has no dynamic parent. It shares all six module files,
  but does not load clockmon. A future A1 hardware variant needs its own proven
  capability profile; CPU name alone is not evidence.

## Reproducible stages

1. Prepare a signed, configured base with a metadata-preserving newc archive and
   `rootfs-build.json` (`stage=bootstrapped`). Never replace UID/GID/devices with
   host ownership or assume that unpacking `.deb` files configures them.
2. Build Dinit tools using `build_dinit_rootfs.py --stage tools`. Use the official
   pinned clean source and the documented cross-toolchain environment.
3. Run `build_image.py --stage kernel --platform common-boot50 --init-system dinit`
   in a fresh candidate directory. `--reuse-kernel` and its exact `--baseline`
   reuse existing objects; no delivered r2 cache is changed. This selects LZ4
   and rebuilds the six module files with W=1.
4. Within the approved fakeroot metadata context run `build_dinit_rootfs.py
   --stage rootfs --common-base --seed BASE --tools-build DINIT_TOOLS
   --kernel-build NEW_KERNEL --performance-tools PERF_TOOLS --out NEW_ROOTFS`
   with the validated explicit rootless QEMU runner. The builder checks installed
   package states, `dpkg --audit`, target `dinitcheck`, module dry-run dependencies,
   character console metadata and the LZ4 round trip.
5. Run `build_image.py --stage image --platform common-boot50 --out NEW_KERNEL
   --rootfs-out NEW_ROOTFS --delivery-out NEW_DELIVERY --i1-boot-cpu-hz 125000000`.
   One Image/rootfs is wrapped into explicit I1/A1 DT and OpenSBI/netboot packages.
   For a rescue candidate omit the rate option and use fresh output/cache binding.

The publisher's performance bundle is accepted only after every SHA, destination,
mode, package dependency and static RV64 LP64D ELF is checked. All files are
prevalidated before installation, and existing paths cannot be overwritten.
Benchmarks are manually invoked, never run at boot. Reported bandwidth is not a
claim about the MIG/DDR physical upper limit.

## Resource bounds and evidence

The common rootfs payload is capped at 512 MiB. The image stage separately checks
runtime Image + unpacked file bytes + 64 MiB reserve against 2 GiB, and preserves
BootROM diagnostic reservations. This is a packaging bound, not a measured
worst-case allocator/network stress result. The final receipt records actual
sizes; keep significant free RAM when installing packages or running tests.

Focused tests cover DT positive/negative policies, real dtc round trips,
production platform-shell module ordering using isolated mocks, tool receipt
validation, and legacy Dinit service grammar. Native supervisor tests need a
Unix control socket; if the execution sandbox forbids one, record them as
blocked, not passed. QEMU checks userspace ABI/package execution only, never the
Valence memory model, DDR, clock stop/resume, interrupts, or actual Linux boot.

## Separate boot-pair / performance compiler candidate

The sealed CPU-only r2 above remains unchanged. A new, explicitly selected
candidate may additionally use `--i1-boot-fabric-hz 125000000`, and only together
with CPU125, I1, SBI, and the reviewed boot-pair driver. Its DT must contain both
`openion,fabric-boot-hz = <125000000>` and `openion,i1-boot-pair-125`.
CPU transitions first, then the fabric, before DMA/GMAC consumers start.
The driver exposes a separate read-only `fabric_boot_control` result, not a
runtime fabric-write interface. Dinit independently checks both domain results.
Unknown/missing/unconfirmed state blocks dependent devices; an explicitly
confirmed safe50 state is distinguished from successful125. There is no blind
software recovery write or automatic retry. If the CPU transition failed and
hardware confirms CPU50, a not-attempted fabric transaction is accepted only
when its own reported state confirms fabric50.

The kernel stage accepts `--kernel-optimization size|performance` (default size).
Performance selects Linux's `CONFIG_CC_OPTIMIZE_FOR_PERFORMANCE=y`, normally
`-O2`; size selects `CONFIG_CC_OPTIMIZE_FOR_SIZE=y`, `-Os`. The prepared receipt
records both the choice and the exact final config SHA. No unrelated feature is
changed by this option. Later driver fixes use module-only refresh rather than
rebuilding every kernel object. A same-frequency/same-rootfs A/B comparison is
needed to attribute effects to compiler policy; CPU/fabric frequency changes
must not be conflated with `-O2` benefits. Larger code can worsen I-cache pressure,
so this is an explicit performance candidate, not a guaranteed speedup.

## Experimental A1 runtime observer candidate

`--experimental-a1-runtime --a1-runtime-hardware-contract CONTRACT.json` is an
image-stage-only selection producing a separate `a1-runtime/` package. It never
replaces the existing static `a1/` or I1 packages. A hardware-owner contract must
bind the exact experimental CommonA1DynamicMain source and emitter receipt,
CPU telemetry descriptor v2 and fabric descriptor v1, model-only scope, no
physical/board qualification, and cold CPU/fabric50 with TIME250.

The DT combines root `openion,valence-a1-runtime-v2`, existing CPU
`openion,orbital-a1`, and monitor
`openion,valence-a1-runtime-clock-monitor-v2`. The driver must verify all three
before mapping the runtime windows, then validate hardware descriptors. CPU
telemetry ABI2 sums two independently Gray-sampled retirement lanes; it is not
the I1 single-lane IPC ABI. All write-control and boot-frequency policy properties
are prohibited. No I1 125 MHz qualification transfers to A1.

The DT/contract checks reject software profile mixups; they cannot prove which
bitstream a user actually programmed. Do not load this package on an old A1 bit,
which lacks these MMIO windows. Only the separately identified experimental
runtime hardware may use it, initially as read-only boot50. A model emitter
receipt is not a placed/routed bit or evidence of successful Linux board boot.
