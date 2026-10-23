# CommonMachinePlatform Linux coverage and acceptance

Scope: hardware source `84a498a`, shared A1/I1 CommonMachinePlatform only. The
older independent FiveStageSoc PLIC address map is **not** this platform.
A1/I1 share a UP RV64GC/FPU-enabled kernel and rootfs. The current small
BusyBox rootfs uses static RV64IMAC/LP64 executables; LP64D/FPU userland is
supported by the CPU/kernel profile but is not the shipped BusyBox ABI. CPU identity and optional clockmon status DTs differ;
TIME250 and external peripheral ABI do not. No test below claims board success.

## Offline audit

Run `python3 fpga/firmware/debian_rootfs/test_audit_common_linux.py` for fast
positive and deliberately broken-input controls. Audit the actual final DTs:

```
python3 fpga/firmware/debian_rootfs/audit_common_linux.py \
  --i1-dts I1.dts --a1-dts A1.dts --console sbi \
  --config linux.config --initramfs rootfs.cpio --kernel-release RELEASE \
  --image Image --firmware fw_payload.bin
```

Use the actual uncompressed newc initramfs and kernelrelease. `--console uart-irq`
selects exclusive native ttyS0 checks. The same audit accepts source DTS or DTB
converted by dtc to DTS. Optional arguments omitted mean those checks were **not
run**; `static_dt_contract_passed` does not imply packed modules were checked.
The audit checks all six actual modules, RISC-V ELF identity, matching vermagic,
archive paths, load mentions/order, kernel features and payload placement. It
is not proof that conditional startup paths execute, dependencies resolve, or
hardware drivers probe. Retain the builder's full depmod, source hashes,
compression/exact embedded initramfs and ELF segment binding checks as well.

## Exact memory and firmware contract

CPU RAM window is `[0x80200000, 0x100200000)`, exactly 2 GiB. It is **not**
`[0x80000000, 0x100000000)`. Hardware checks the full physical address before
subtracting `0x80200000` to obtain the DDR offset. The final offset is below
`0x80000000`, so MIG's 31-bit offset port does not truncate the CPU's final 2 MiB.
Evidence: `platform/CommonPlatformAbi.scala`, `CommonMachineFabric.scala`
(axiAddressBase/axiWindowBytes), and
`core/ooo/platform/bus/TileLinkAxi4BurstBridge.scala` (full-width check/subtraction).

OpenSBI entry is `0x80200000`, relocated DTB is `0x80300000` (64 KiB reservation),
and raw Linux Image entry is `0x80400000` (firmware offset 2 MiB). Reserve
`[0xfff78000,0xffff8000)` for menu diagnostics and
`[0xffff8000,0xffffc000)` for monitor. OpenSBI adds its resident reservation.
Raw Linux Image is not a direct replacement for the monitor's OpenSBI payload.

## Implemented inventory

| Device | MMIO / interrupt | Software coverage | Remaining board acceptance |
|---|---|---|---|
| UART | 10000000/8, APLIC3; UART50, virtual reference7372800 | built-in 8250; optional IRQ profile or SBI recovery console | RX/TX ownership, ttyS0 IRQ count, sustained no-loss input |
| Timer | mtime0200bff8, cmp02004000; MTIP7, TIME250 | OpenSBI ACLINT MTIMER and SBI Linux timer | wall time, sleep/timeouts, timer interrupt growth |
| AIA | root0c000000/4000, leaf0c004000/4000; SEIP9 | valence_aia, CSR-only selftests | both selftests, normal IRQ delivery, no storm |
| memcpy DMA | 10001000/28, APLIC4 | valence_dma, DMAengine and benchmark | correctness, coherent CPU visibility, IRQ4 and errors |
| Ethernet + packet DMA | MAC10040000/1000; DMA10002000/100; APLIC6 used, MAC5 available | valence_gmac, NAPI, managed-PHY handling | DHCP/static address, ping, bidirectional transfer, 10/100/1000 link where available, stop/start |
| CMU leaf clocks | 10080000/800; source7 intentionally not enabled | valence_cmu fixed/leaf CCF | rates/status, no unwanted IRQ or console gate |
| I1 dynamic CMU rate/performance (A1 absent) | 10080800/100 and10080900/200 | valence_clockmon read-only ABI2/telemetry | valid snapshots; rate reports match hardware; no automatic switching |
| Platform identity | root DT | valence_soc | identity should match selected CPU DT |
| DDR/MIG | RAM window above, DDR_UI250 | normal Linux memory, no block-storage driver | allocation/stress including CPU addresses above4GiB |
| JTAG loader | 10003000/40 | BootROM/maintenance-owned, no general Linux write driver | remains outside ordinary Linux ownership |

Six modules are packaged in the common rootfs; only five bind on current A1.
A1 cannot enable the dynamic/performance extension: CommonMachinePlatform
requires I1 runtimeDebugAdmission for the full rate/performance dependency chain.
Its clockmon DT node must be disabled (no probe/MMIO); sharing a kernel is not
evidence that optional hardware exists.

The modules implement these software components: valence_soc, valence_aia,
valence_cmu, valence_dma, valence_gmac, valence_clockmon. Rate and performance are
one module with two resources, not two fabricated modules.

No GPIO, usable I2C/SPI controller, SD/eMMC/NVMe, USB, RTC, watchdog or writable
reset controller is instantiated on this Common platform. The LED follows reset.
Do not add fake DT nodes/drivers merely because the physical board has connectors
or reusable source files exist. Rootfs is RAM-backed, not persistent local disk.
No standard CPU-writable IMSIC MSI aperture, PLIC or MSWI exists here. Reboot and
poweroff are not qualified; do not fabricate a syscon reset mapping.

## Short manual board acceptance, independently for I1 and A1

1. Cold boot the intended bit and matching CPU DT; record hashes, OpenSBI identity,
   ISA, memory map and Linux command line. Both profiles must use the same kernel
   and rootfs hashes. Confirm no illegal instruction or kernel fault.
2. Confirm six driver probes on I1, five on A1 (clockmon disabled), and AIA's two selftests. Capture dmesg and
   `/proc/interrupts`; verify sources actually increase under UART/DMA/network
   activity, with no idle interrupt storm. SBI console success alone is not a
   native UART IRQ pass.
3. Compare a timed sleep against a host clock and inspect uptime/timer activity.
   TIME must remain250MHz even when CPU/fabric nominal frequency differs.
4. Run separately prepared compatible FPU/context, memcpy DMA and bounded memory
   acceptance tests. The small rootfs does not currently package fpu-test,
   dma-bench, net-bench or iperf; do not claim these commands exist in the image.
   Confirm data comparisons and IRQ completion, not only benchmark exit text.
   Explicitly test allocator/data integrity in the final above4GiB2MiB window
   with a suitable bounded kernel-aware test; do not write arbitrary physical
   RAM or reserved firmware regions through devmem.
5. Exercise network address setup, ping and, after supplying a compatible test binary, bidirectional iperf/net-bench with a
   known host. Record IRQ/NAPI/queue counters, errors, packet loss and link speed.
   Test ifdown/ifup and cable link loss/recovery without unsafe DMA cancellation.
6. Read CMU status and, on I1 dynamic hardware only, clockmon rate/performance snapshots; verify valid flags,
   changing counters and no writes/automatic frequency changes. RAM diagnostic
   frequency roundtrips are not Linux cpufreq/runtime-DVFS qualification.
7. Mark each check pass/fail/not-run separately. Keep both CPU profiles unverified
   until their own board evidence exists; do not infer A1 success from I1 success.
