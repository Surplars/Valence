# Common I1/A1 BusyBox initramfs

This is a new cloud-only path. It does not modify or reuse a completed Debian
rootfs, does not require host root/mknod privileges, downloads nothing, and does
not operate a serial port, JTAG connection or board. It consumes the environment
owner's pinned musl 1.2.5 / BusyBox 1.37.0 archives and extracted source trees.

## Build and pack

From the repository, after the independent source/tool setup:

    source scripts/cloud/env.sh
    source /workspace/shared/valence-linux-build-cache/env.sh
    python3 fpga/firmware/common_rootfs/build_rootfs.py userland \
      --out build/fpga/common-linux-userland \
      --uapi-headers "$VALENCE_LINUX_UAPI_HEADERS" --jobs 4
    python3 fpga/firmware/common_rootfs/test_common_rootfs.py
    python3 fpga/firmware/common_rootfs/build_rootfs.py pack \
      --kernel-build build/fpga/common-linux-boot50 \
      --userland build/fpga/common-linux-userland \
      --out build/fpga/common-linux-rootfs

An interrupted private userland build can be resumed explicitly with `--resume`.
A completed manifest is never overwritten. A module update needs a new `pack`
output directory, not another userland compilation. The final image builder
consumes `--rootfs-record rootfs-build-common.json` from that output directory.
Do not change the kernel/module receipt between packing and image assembly.

BusyBox is static RV64IMAC, soft-float **LP64**, using musl. This is distinct from
the two CPUs' RV64GC/LP64D platform capability. ELF headers, absence of PT_INTERP,
ISA attributes, required applets, archive digests and final bytes are checked.
Upstream build warnings are recorded, not silently turned into a zero-warning
claim. Build logs are per invocation; host packaging does not prove target CPU
execution. `--uapi-headers` is an explicit private target header tree, not a host
system installation. Existing musl libc headers take precedence over overlapping
UAPI helper directories.

## Actual drivers and capabilities

The kernel-build receipt is authoritative for every actual filename, SHA256,
release, vermagic and dependency. The packer independently reads ELF `.modinfo`
and rejects omitted, extra, mismatched or cyclic modules and uninventoried
in-tree `CONFIG=m` components. The current reviewed platform policy is:

1. valence_soc: DT identity only, no nonexistent console-mode parameter.
2. valence_aia: IRQ selftest must be ready and nonfaulted before DMA consumers.
3. valence_clockmon: load only if its compatible is enabled in the **live DT**.
4. valence_cmu: after the live clock provider on an enabled I1 profile.
5. valence_dma and valence_gmac: blocked if IRQ or clock provider initialization
   failed. There is no polling fallback.

All six modules are included. Current A1 DT disables/omits clockmon, so A1 skips
it as `SKIP_UNSUPPORTED_DT` without accessing nonexistent rate/perf MMIO and uses
five active modules. The I1 dynamic profile enables it and uses all six. CPU name
strings are not used to infer capability. New hardware/module capabilities
require review of the explicit startup/probe policy, not guessing a module count.
The clock monitor is read-only; this rootfs does **not** expose a qualified Linux
runtime DVFS policy or perform frequency requests at boot. GPIO, SD and USB
hardware are not invented or claimed.

## Console, diagnostics and networking

The selected kernel must use the SBI console profile. `/init` inherits
`/dev/console`, mounts proc/sys/devtmpfs/devpts/run/tmp and starts one interactive
BusyBox shell via `setsid cttyhack`. It never starts a competing serial getty,
changes the UART divisor or takes UART ownership from OpenSBI. It preserves a
visible rescue shell after startup failures, records `FAILED_RESCUE_SHELL`, and
never prints the ready marker in that case. Successful module registration and
visible probe state are still not hardware qualification.

Use `valence-diagnose` to show modules, IRQs, rates/performance if present, DMA,
network state and kernel logs. No DHCP runs automatically. `valence-net up`
explicitly enables the actual eth0 interface; `valence-net dhcp` explicitly
requests a bounded DHCP lease. `--network-auto-enable` at pack time only brings
eth0 up after successful initialization; it does not request an address. There
is no SSH/telnet listener or automatic storage mount. All rootfs changes are
RAM-only. The local serial diagnostic shell is privileged and intended for a
trusted, physically controlled development setup, not a multiuser production OS.

BusyBox 1.37.0 `ip` is not the full iproute2 implementation: `ip -s link` is
unsupported. The helpers use `ip link show` and `/proc/net/dev` counters instead.
The original r2 delivery remains immutable; its two helper scripts can be fixed
in the running RAM rootfs without restarting Linux:

    sed -i 's/ip -s link/ip link show/g' /usr/sbin/valence-diagnose /usr/sbin/valence-net

Read `cat /proc/net/dev` separately on that temporary r2 patch. A later package
includes counters in both helpers. This repair does not change drivers, kernel,
BusyBox bytes, network settings or hardware. The regression can execute a real
host build of the pinned applet, including the old-command negative control:

    VALENCE_TEST_BUSYBOX=/absolute/path/to/host/busybox python3 fpga/firmware/common_rootfs/test_common_rootfs.py

## Acceptance boundary

The deterministic newc writer encodes root-owned console/null/tty device nodes
without creating host device nodes. The original cpio and deterministic gzip
copy are byte-bound in the record; rootfs contents, runtime scripts, real module
metadata and kernel receipt are also bound. Focused tests exercise I1/A1 startup,
IRQ/provider/hash failures, metadata and path rejection, and independently parse
the cpio device headers. An independent audit must read the actual final cpio.
Neither these checks nor ELF compilation is a Linux boot, whole-SoC timing,
network transfer or board test. Those qualifications remain explicitly false.
