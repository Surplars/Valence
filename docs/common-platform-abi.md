# Common platform ABI 1.0

`soc.platform.CommonPlatformAbi` is the CPU-independent configuration contract for
the current A1 board/software ABI. Its pure Scala specification is
`platform.CommonPlatformAbiSpec`. Definitions and a passing configuration test are
not evidence that either CPU is interchangeable or that a split-clock board works.
Existing A1 and I1 profile defaults are unchanged.

The first extraction shares the exact native memory request/reply wire layout
and replaces A1's inline APLIC pair with `CommonInterruptFabric`. The selected
CPU adapters, shared Home and final independent-clock assembly are still work
in progress; `CommonCpuTilePort` defines that boundary, not its completion.
The public instruction-fetch source namespace remains four bits, separately
from each three-bit coherent-client source namespace.

## First extraction checks

Run `IonSoC.test.testOnly platform.CommonPlatformAbiSpec
platform.CommonPlatformBoundarySpec` with the JVM property
`-Dchisel.project.root=/absolute/path/to/checkout`. Fourteen configuration,
wire-width and structural checks pass. These are not CPU execution tests.

`simulator/gsim/common/interrupt_fabric.py --help` describes the bounded GSIM
check. It requires explicit existing Java classes and pinned/qualified GSIM and
Clang paths; it does not install tools. Source, classpath, tools and outputs are
hashed in its receipt. The focused result is 45 MSI writes and 45 real replies,
M/S delegation, physical IRQ sampling, 60 stalled-offer cycles, response errors,
common reset cancellation and 16 consecutive accepted requests (II=1). An MSI
identity-corruption negative control fails as intended, with sanitizers enabled.

The common MSI instance explicitly locks arbitration selection while stalled.
It keeps all eight response-owner slots and adds no data pipeline stage. Sources
must retain valid/payload until acceptance except under common reset; APLIC's
output queues satisfy this contract. A runtime assertion rejects withdrawal.
Other `TwoMasterRegisterArbiter` callers retain the previous default selection
behavior. Decoupled alone did not promise irrevocable selection; this is an
explicit stronger contract for the new external/CDC boundary.

## Frozen software boundary

All ranges below are half-open. Addresses are physical bytes, little-endian.

| Resource | Base | Bytes | Owner/interface |
| --- | --- | --- | --- |
| ROM | `0x80000000` | 128 KiB | Board ROM, reset entry |
| RAM | `0x80200000` | 1 MiB on-chip; explicit 512 MiB/1 GiB/2 GiB DDR | Memory fabric |
| Timer | `0x02000000` | 64 KiB decode | RegisterPort; only listed timer registers valid |
| M-APLIC | `0x0c000000` | 16 KiB | Machine root, RegisterPort |
| S-APLIC | `0x0c004000` | 16 KiB | Delegated supervisor child, RegisterPort |
| UART | `0x10000000` | 8 | Byte registers, 16-byte FIFOs |
| Copy DMA | `0x10001000` | 40 | Natural 64-bit registers |
| Network DMA | `0x10002000` | 256 | Optional, 64-bit descriptor/control ABI |
| JTAG loader | `0x10003000` | 64 | Optional cooperative RAM loader |
| Ethernet | `0x10040000` | 256 KiB decode | Optional; native GMAC has 4 KiB per port |
| CMU | `0x10080000` | 4 KiB | Optional independent clock-management IP |
| M/S IMSIC | `0x24000000` / `0x28000000` | 4 KiB each | Internal MSI target only, **not CPU load/store windows** |

`mtimecmp=0x02004000`, `mtime=0x0200bff8`; each supports aligned 64-bit
access and low/high 32-bit aliases. No MSIP array is implied by the timer aperture.
APLIC is naturally aligned 32-bit; UART is 8-bit. RegisterPort data is right
justified by the CPU router, while native TL data retains its byte lane. Illegal
widths, masks and addresses retain precise error replies; atomics must not modify
MMIO. Native GMAC and the old AXI Ethernet backend are different register ABIs.

The interrupt interface preserves 31 one-based sources: UART 3, copy DMA 4,
GMAC 5, network DMA 6 and CMU 7. Source `n` is bit `n-1`. One hart targets
M/S IMSIC files 0/1, 127 identities, no guest files. APLIC emits ordinary
backpressured 32-bit MSI writes on RegisterPort and consumes their responses;
MSI admission is not response completion. IMSIC CSR access is qualified by the
CPU's privilege and commit authority. The timer feeds MTIP/cause 7 directly;
M/S external causes are 11/9. An I1 PLIC cannot silently stand in for this AIA ABI.

## ROM, memory and clocks

The full firmware remains `fpga/firmware`: UART/CRC download, optional 80x24 TUI,
diagnostics, JTAG and native-GMAC netboot. The independent I1 ROM at `0x10000`
is a historical bring-up profile, not this firmware ABI. Monitor RAM is 16 KiB at
`min(RAM end - 16 KiB, 0xffff8000)`; TUI requires DDR and additionally reserves
512 KiB below the monitor. CRC table modes occupy 64/1024/2048/4096 bytes.
The RAM verification protocol retains dirty flush plus two 64 KiB clean-read
sweeps; FENCE.I alone does not promise invalidation of every clean D-cache line.

Netboot retains both DMA and MAC endpoints. MAC RX_STOP closes producer
admission and drains admitted frames/CDC/prefetch/data/status while a scratch RX
consumer remains live. Only then stop/drain DMA DDR writes and reclaim posted
completions before buffer reuse. Both RX_STOP offsets are `0x90`; DMA capability
is bit 0 at `0x98`, native GMAC capability bit 8. An accepted STOP write or an
empty FIFO is not the drained condition. Existing software ownership and CRC
validation before launch are required; external-image return still requires reset
when peripheral ownership is unknown.

`CommonClockConfig(clockFrequencyHz, fabricClockHz, timebaseHz)` distinguishes
CPU nominal frequency from the fixed timer domain. ABI 1 has one mtime tick per
fabric cycle, so `timebaseHz == fabricClockHz`; no CPU:fabric ratio is assumed.
Its firmware defines, ROM reporting text and DT properties derive from one object:
CPU `clock-frequency` differs from `timebase-frequency` when clocks differ.
The old synchronous A1 board has all three equal. Current `build.py --cpu-hz`
and C `CPU_HZ` really scale `rdtime` budgets and throughput reporting; until those
consumers migrate, the compatibility value is **timebaseHz**, never the new CPU
rate. Do not evade the existing firmware 6–200 MHz limit to describe a faster CPU.
UART baud-generator reference is separate from both CPU and timer frequencies.
The metadata helpers are not yet wired into the firmware builder or DT generation.

## Maintenance and transport completion

The existing A1 FENCE.I chain is preserved:

1. The ROB-head barrier stops new fetches and waits for older CPU memory and
   frontend/translation/fetch-cache quiescence (`IntegerBackend`, `MachinePlatform`).
2. Private-cache flush drains its MSHR, bypass, prefetch and writeback obligations.
   Only after cache-local completion does Home close new admissions and drain its
   accepted acquire, release, probe, native-access and DMA-line owners.
3. `MachineSystemUnit` waits for cache completion **and** Home drain. The matching
   system redirect token then invalidates frontend and instruction line cache
   before fetch resumes. Neither an enqueue nor local cache completion is enough.

For a split-domain adapter, `CommonMaintenanceCompletion` describes additional
mandatory evidence for the same maintenance request/epoch: retired native/MMIO
responses, completed ordered reservation clear, all source obligations, E-acked
Grant sinks, whole-line transport, and both CDC endpoints including held output
and response stages. It is a pure checklist, not an implemented acknowledgement
generator. A wrong-epoch pulse or an unsynchronized collection of empty flags is
not evidence. B/C/D/E and lineGrant must continue to drain while admission stops.
Instruction invalidation follows memory acknowledgement; only its matching
completion permits fetch resumption.

The 64-byte line uses eight 64-bit beats. Standard TL A/B/C/D/E preserves every
source/sink, opcode/param, mask, size, denial/corruption and multibeat owner. The
optional private `LineGrant` carries all 512 data bits plus source, sink, cap,
denied and corrupt; it replaces GrantData beats, never E GrantAck or ownership.
Native return-owner identity remains distinct from TL source/sink identity and
must survive CDC unchanged. `CommonTransportShape` rejects mismatched direct
transport widths/capabilities; a remapping adapter needs a separate lossless proof.
Preserve independent channel credits; no shared one-request token may serialize
unrelated traffic. Accepted writes complete at their terminal response owner,
including downstream AXI B where applicable, not at request-FIFO dequeue.

## Remaining integration/qualification

This initial ABI change adds definitions, independent literal/configuration tests
and firmware drift checks only. Shared interface/fabric modules do not by themselves
qualify both CPU adapters, MSI/time/maintenance CDC, actual ROM/DT clock generation,
complete firmware boot or matched throughput/latency. Those remain integration
and qualification work. Both clocks
must keep running; common cold reset covers all transaction owners including
external DDR. No hot-reset, gating, measured Fmax, routed timing or board claim
is made. No build, simulator, Vivado or full regression was run by this change's
author; the integration owner runs the combined compile and focused checks.
