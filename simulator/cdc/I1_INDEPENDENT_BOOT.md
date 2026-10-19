# I1 independent CPU/fabric short boot

This entry runs the actual I1 CPU, private coherent caches, original I1 Home,
ROM, peripherals and AXI manager with separately driven CPU and fabric edges.
The existing single-clock `FiveStageSoc`, with the **same selected parameters**,
is the control. It is a bounded functional acceptance, not a board release.

## Explicit profiles; no reduced default

The emitter requires all four arguments:

```
inorder.I1IndependentClockSocMain NEW_RTL_DIR single|independent test-only|full-cpu ROM_HEX
```

- `test-only`: RV64IMA, fpga8, 2 KiB I/D caches, two ways, 64-byte lines.
  This small regression fixture is not production geometry.
- `full-cpu`: 32 KiB I/D, two ways, C/A/F/D, S/U/Sv39, PMP8, predictor128,
  DSP-tiled multiply, and the checked-in batch44 CPU optimization selection.
  The explicit flag list and source-selection chain are in the emitter. This
  reconstructs the public selection, not a hash match to a frozen bitstream.
  The short guest exercises an RV64IMA subset, not all enabled ISA features.

Both preserve two DDR read slots, one write owner, full A/B/C/D/E, separate
LineGrant, both uncached ports, whole-line transfer and read/writeback overlap.
The independent assembly uses the recovered `HeldResponseCdcDataFifo` at depth
16 on every data lane. No one-request mailbox replaces the coherent transport.
The compatible II=2 FIFO remains available only as a separate component control.

The emitter writes `emission-profile.json` from the actual constructed parameters
and ROM hash. The runner rejects mismatched mode, profile, geometry, timebase or
ROM, and requires matching single/independent profiles. Fresh directories are
mandatory; source, model, guest and tool hashes are retained in receipts.

## Executable steps

Use already installed tools; these commands do not install anything. Substitute
absolute paths and fresh output directories. Compile once after source edits.

```sh
make compile
make i1-independent-boot-guest I1_CDC_GUEST=/evidence/guest \
  I1_CDC_CROSS_PREFIX=/tools/riscv64-unknown-elf-
make i1-independent-boot-rtl I1_CDC_RTL=/evidence/single \
  I1_CDC_MODE=single I1_CDC_PROFILE=full-cpu \
  I1_CDC_ROM="$PWD/src/main/resources/inorder/bootrom.hex"
make i1-independent-boot-rtl I1_CDC_RTL=/evidence/independent \
  I1_CDC_MODE=independent I1_CDC_PROFILE=full-cpu \
  I1_CDC_ROM="$PWD/src/main/resources/inorder/bootrom.hex"
make i1-independent-boot-test I1_CDC_OUT=/evidence/result \
  I1_CDC_GUEST=/evidence/guest I1_CDC_SINGLE_RTL=/evidence/single \
  I1_CDC_INDEPENDENT_RTL=/evidence/independent I1_CDC_PROFILE=full-cpu \
  I1_CDC_TEST_ARGS='--iverilog /tools/iverilog --vvp /tools/vvp'
```

The candidate command above selects the full CPU geometry. For the reduced
regression control only, explicitly select `test-only` in both exports and the
run. Never reuse small RTL under a full-CPU label. Native compilation happens
once per mode; all independent clock ratios reuse one binary. A continuous
4 GiB free-disk floor, wall-clock limit and CPU-edge limit bound the test.

Pinned GSIM advances registers on its global `step()` without independently
qualifying CPU/fabric edges. Therefore this specific test uses the approved
native Icarus independent-edge exception, with standard firtool lowering and no
DUT rewrite. Existing GSIM single-clock baseline receipts remain separate.
No Verilator, Vivado, Linux or broad regression is invoked.

## Acceptance order

1. Common cold reset, clock-lock hold, actual ROM retirement and UART banner,
   DDR-ready gating, then instruction retirement from the real RAM image.
2. RAM dependent stores/loads, byte lanes and the final word of the 2 GiB
   aperture; an independent bounded AXI model preserves owners and held offers.
3. MSIP, MTIP and PLIC UART-loopback interrupts, plus precise MMIO/R/B faults.
4. Successful LR/SC and invalidation after a trap or ordinary cached store;
   final dirty data is read through the coherent device port, not assumed to
   have reached backing memory already.
5. Two genuine CPU/fabric ratios and phases with a fixed 50 MHz fabric,
   monotonic/progressing atomic time snapshots, and a lost-response negative
   control that must hit the bounded-completion oracle.

Only a successful fresh `receipt.json` establishes these checks. A configuration
or elaboration pass is not a boot pass. Boot cycle/AXI counts are reported; they
are not a CPU benchmark or evidence of an achievable frequency.

## Recorded full-CPU functional acceptance (2026-10-19)

`full-cpu` passed the same-parameter single-clock control (50/50 MHz) and
independent CPU/fabric clocks (100/50 MHz, phase 3 ns; 33.3/50 MHz, phase 7 ns).
Each case checked 33 real UART bytes, all seven intended traps, successful and
cleared LR/SC, 139 coherent readbacks, and two simultaneously outstanding DDR
reads. Both independent cases exercised every A/B/C/D/E channel, both uncached
ports, separate I/D LineGrant and ordered reservation clears. The lost-first-DDR
response negative was rejected at the CPU-edge bound, without a wall timeout.

Receipt status: `PASS_NATIVE_I1_INDEPENDENT_SHORT_BOOT_FULL_CPU`.
Receipt SHA-256: `eea1109e0b6525d729c336fa89b5a6fa2504476fb2a0b7cd075e2b9b079ccc53`.
All source, RTL, profile and binary hashes were verified after the run. Production
assertions and the checked ROM initialization were active in native simulation.
Boot counts include UART polling and are not an IPC/bandwidth benchmark; this
short guest observed no simultaneous AXI read/write overlap. Full ISA, sustained
bandwidth, active DMA/network and physical/board qualification remain unproved.

## Lifecycle and remaining release gates

Both clocks remain running. Only common cold reset is supported, including the
external DDR transaction epoch and every cache/Home/CPU owner. Local transport
empty does not mean transactions drained. No unilateral reset, retention or
clock gating is implemented.

The timer and UART use the fixed fabric clock, not the variable CPU clock. IRQs
cross as persistent levels; time crosses as an atomic mailbox sample. LR/SC
clear events are ordered with D-uncached requests; a clear waits for replies of
older accepted requests before reaching AtomicMemory. D and LineGrant remain
separate because the I1 Home may produce ReleaseAck and LineGrant together.

The complete board profile is still blocked by JTAG download/cache-maintenance
event CDC, managed UART/CMU integration and board clock/reset/Gray-bus constraints.
The assembly rejects unsupported maintenance owners rather than dropping their
pulses. MIG/DDR UI bridging, physical CDC/timing and board validation are separate
release gates. No old 300 MHz bitstream qualification transfers to this source.

The A1 interrupt/boot/MMIO ABI has not been unified with this I1 platform. A1's
existing single-clock boot fixture remains independently named. Replacing the
CPU on one common full board platform is a later integration milestone, not a
claim made by this short-boot entry. Network and Linux are later milestones too.

## Candidate physical clock target, still unqualified

The first full-board timing target is CPU 300 MHz, fabric 250 MHz, DDR UI
250 MHz, and managed UART/AON 50 MHz. Fabric and UI may share a clock only if
the board implementation actually supplies the same clock/phase/reset contract;
matching frequency numbers alone do not remove a CDC boundary. CPU/fabric
remains asynchronous. These are STA targets, not closed or board-ready clocks.

A 64-bit lane accepting one beat per 250 MHz fabric edge has a theoretical
2.0 GB/s directional payload rate. Effective throughput also depends on source
rate, clock-credit round trips, packet/line overhead, Home scheduling, cache
owners and real DDR service. Choosing a lower fabric target is an explicit
measured fallback, not a silent release default. The 50 MHz functional test
timebase is not that fallback and does not predict attainable frequency.

Before a bitstream is considered usable, require routed setup/hold and relevant
RX paths, complete reset/clock/Gray-bus CDC review, qualified RAM mapping, and
real board boot acceptance. Positive placed slack alone is insufficient. The
historical batch44 CPU300 result does not qualify the newly separated fabric.
