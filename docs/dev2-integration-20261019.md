# Orbital-I1 integration and shared-platform boundary

## Fixed inputs and scope

This integration combines public `main` `84ba5c0a1fa2d09b7792392edc27b154f97244a0`
and public `dev2` `9f83113924a488f26ce555514794fcca72c0b871`, with merge base
`1e90af966c15d871d2544469174acba78473113b`. It imports the independent Orbital-I1
CPU, board tools and tests without replacing Orbital-A1 or its newer platform fixes.
Generated RTL, simulator binaries, build caches, bitstreams and DCPs are not source inputs.

The long-term goal is one peripheral implementation and board platform, with only the
CPU tile selected. This merge preserves the two existing configurations; it does not yet
make their complete SoC tops interchangeable.

## Shared-module decisions

| Area | Integration decision | Qualification boundary |
| --- | --- | --- |
| Build/source layout | Retain `OrbitalI1`; update its five explicit CPU-independent source paths for main's OoO directory reorganization. | Both `IonSoC` and the isolated `OrbitalI1` must compile. No dependency on the OoO pipeline or legacy core is added. |
| DMA | One `EthernetPacketDma` retains main's launch-captured TX word count and dev2's default-off `boundedDescriptorChecks`. | Test ordinary/posted TX and bounded/default descriptor checks, invalid high addresses, masks, errors, STOP and backpressure. No-MAC batch44 does not instantiate this DMA. |
| MAC/clock bank | One implementation retains main's `rawClockHandoff`/instance witness and dev2's `balancedRawClock(s)` with independent default-off controls. | Default, handoff-only and balanced-only configurations remain available. Both-on is rejected at construction pending a dedicated combined MAC lifecycle/CDC test. |
| UART/clock leaves | Retain dev2's explicit parallel continuous/gated BUFG leaves and independent gate-control clock as optional parameters. | Do not silently change existing default clocks or treat a digital clock model as vendor/physical qualification. |
| TL line/AXI | Retain the timing-oriented line-engine options and main's newer AXI bridges. Existing added bridge options remain default off. | Do not alter credits, accepted-write completion, source/sink lifetime or coherent backpressure to make types match. |
| I1 cache/Home/JTAG | Keep I1's timing-specific implementations and 65-bit USER2 profile. | These are CPU/memory-profile contracts; do not replace them with generic older/newer files solely by version date. |
| Already common leaves | Keep one TileLink protocol, RegisterPort, timer, UART console, clock-management unit, debug-loader protocol/reference and other byte-identical shared IPs. I1's active timing loader remains private as noted above. | Composition and platform ABI still need explicit unification. |

The handoff sampler belongs to the same continuous TX clock leaf as its source payload
and reset. The combined topology is deliberately unavailable in this merge, so neither
existing branch silently opts into an unqualified half-cycle/clock-tree combination.

## What is preserved from the 300 MHz I1 profile

The I1 CPU, cache/Home timing logic, register-file/RAM mapping, board clock constraints,
no-MAC peripheral shell and private timing JTAG remain the dev2 implementations. The
public batch44 description selects CPU300/UI250/AON50/UART50, I/D caches of 32 KiB,
two DDR slots, 65-bit USER2 and no MAC. It reports post-route WNS 0.000 ns, hold
+0.007 ns and pulse-width +0.081 ns. Nine existing reset CDC Critical endpoints remain;
structural reset-release checks are not complete CDC sign-off.

Those measurements belong to the frozen batch44 source/configuration and its original
reports, not automatically to this integrated tree. The original routed DCP/report bundle
is external to Git and was not rerun or independently requalified for this merge. No new
300 MHz, bitstream, board-stability, Linux or full CDC claim is made. Even when a changed
source is outside the no-MAC elaborated cone, the old all-source receipt hash closure is
not a receipt for a new merged checkout. See [the batch44 record](../fpga/inorder/README.md).

## Optimizations to retain and candidates for common utilities

| Optimization | Keep now | Possible common extraction |
| --- | --- | --- |
| Preload only unowned queue/metadata storage; commit ownership on handshake | I1's prepared two-slot/FIFO implementations and capacities | Default-off shared queue behavior only after independent full/empty/wrap/stall/reset and no-credit-borrowing checks. |
| Separate stored/flow payload alternatives from late valid selection | I1 flow queue and coherent response paths | A common queue leaf only for the same `pipe=false`, `flow=true`, power-of-two-depth contract. |
| Registered fetch-word alignment and prepared trap targets | I1 CPU control/parcel ownership | Reuse the structural idea on A1 after precise exception, redirect, compressed cross-word and in-flight-owner proof; do not copy the single-owner FSM. |
| Banked synchronous RAM and one-write-port directory | I1 RAM latency, collision bypass, bank geometry and physical attributes | Share RAM leaves/audits where ports and hazards match; A1's multiported PRF and cache ownership remain CPU-specific. |
| Bounded window/arithmetic factoring | Optional descriptor/window/timing paths | Extract width/overflow-tested helpers; address-only inclusion is not a permission or full-access-range proof. |
| Balanced continuous/gated clocks | Explicit I1 clock profile | One parameterized board clock bank, with actual CDC and setup/hold checks for the final selected configuration. |
| ROM initialization and physical content audit | I1's exact ROM image and mapping/write-disable checks | Share tooling once ROM address, port, reset and firmware ABI are agreed. |

Home/directory is a coherence and memory subsystem, not an LLC data cache or a generic
peripheral. I1's two coherent I/D clients and private whole-line `LineGrant` capability do
not automatically match A1's D-cache/Home plus separate instruction-fetch arrangement.
Likewise, I1's bounded outstanding owners/PTW priority are not throughput or fairness
proofs for a wider, nonblocking OoO CPU.

## Remaining common-platform work

1. Define one versioned address/boot/interrupt manifest before switching CPUs under a
   shared board top. I1 has PLIC at `0x0c000000`; A1 uses APLIC/IMSIC. I1 BootROM is
   `0x10000`/4 KiB; main board ROM is `0x80000000`/128 KiB. I1 boot status at
   `0x10002000` conflicts with main's packet-DMA window; I1 currently places DMA at
   `0x10005000`. These differences must never be silently resolved by CPU selection.
2. Define a CPU-tile adapter with explicit coherent/uncached ports, source/sink and
   credit ownership, error/denied/corrupt propagation, interrupt/time sidebands,
   optional IMSIC CSR handshake, reservation maintenance and reset/drain semantics.
   A common interrupt ABI may require real CPU support, not only an address decoder.
3. Extract the common peripheral bank first, with identical MMIO widths/errors,
   ROM/loader ABI, interrupt sources, timer timebase, clocks and firmware/device-tree
   contracts. Keep named compatibility profiles until both CPU compositions pass the
   same independent peripheral checks.
4. Converge the shared memory/fabric separately while retaining private L1s. Establish
   coherent-client topology, DMA dirty-line visibility, AMO/LR-SC behavior, flush and
   accepted-write completion without reducing both CPUs to a single-outstanding path.
5. Consolidate genuinely equivalent timing leaves in coherent batches. Run affected
   short functional tests before any separately authorized physical qualification of
   the final combined board. Only the measured source/configuration/device/constraints
   may carry a frequency claim.

Reset is also an ABI: I1 can release ROM boot after lock and latch later readiness loss;
main currently includes DDR readiness in core/memory hold. A unified reset/fault policy
must retain every offered or accepted owner across CPU, Home, DMA, AXI CDC and MIG.
No unilateral hot reset may discard an outstanding transaction.

## Integration verification

Completed bounded checks:

- `mill -i -j2 IonSoC.compile`: 278 production Scala sources compiled.
- `mill -i -j2 IonSoC.test.compile`: 582 test sources compiled; the DMA test entry
  was then incrementally recompiled after its final option edit.
- `mill -i -j2 OrbitalI1.test.testOnly inorder.FiveStageConfigSpec`: isolated I1
  production/test compile and all 17 configuration tests passed.
- `mill -i -j2 IonSoC.test.testOnly ip.SharedPeripheralProfileSpec ip.SelfGmacParamsSpec ip.EthernetPacketDmaSpec`:
  9 elaboration/configuration checks passed, including both legal clock options,
  unchanged restrictions and rejection of their unqualified combination.
- `python3 -m unittest discover -s fpga/inorder -p 'test_*.py'`: 52 tests passed.
- Five small `EthernetPacketDmaGsimMain` configurations passed the unchanged
  independent C++ byte/descriptor/backpressure/STOP oracle and a negative oracle:
  bounded off/on × posted-TX slots 0/4 at 8 KiB RAM, plus bounded on with 2 GiB RAM.
  Each ran 158 packet cases; bounded/default public oracle metrics matched for both
  posted-TX settings. The emitted FIR was checked to select the requested bounded
  path and retain main's captured TX-count register.
- Existing raw-handoff native component gate: 35 lifecycle cases, four behavior
  negatives and two structural negatives passed. Default-off and the immutable
  pre-handoff fixture emitted 44 byte-identical RTL files. This uses the existing
  digital BUFGCE model and does not validate vendor primitives or physical CDC.

The DMA tests used the previously recovered/qualified GSIM tool based on pinned
upstream `93b8cd23edd3228807c4f2a08c19c3936a463cb2` with its recorded compatibility
patches and sanitizers. They are new focused results, not a replay of dev2's original
WSL toolchain or its batch44 receipt. An initial DMA attempt used a stale compiled
emitter and did not actually select bounded mode; it was marked invalid, retained,
and superseded by the structurally checked run after stable recompilation.

All `src/main/scala/core/inorder` files remain byte-identical to dev2. No main source
file was deleted. The five whitespace warnings on imported files are already present
in dev2; their frozen source bytes were preserved. No full regression, long Linux
simulation, Vivado run or new physical implementation was performed.
