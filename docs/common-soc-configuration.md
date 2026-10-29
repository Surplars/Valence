# Common SoC configuration: one explicit input, resolved output

`CommonMachinePlatformMain` accepts a small JSON file in place of its `i1|a1`
argument. The existing CLI remains valid. No new hardware protocol, ISA subset,
clock point or performance qualification is introduced.

```sh
mill -i IonSoC.test.runMain platform.CommonMachinePlatformMain \
  build/my-soc --soc-config=config/common-soc/a1-lsu4-jtag-off.json \
  --compile-receipt=/absolute/path/to/bound-compile-receipt.json \
  --programmable --emit-chirrtl-only
```

Use a fresh output directory. A successful **source/classpath-bound** compile
receipt remains mandatory for explicit CPU specifications, including every file
preset. `--programmable` is the native verification ROM choice; production ROM
export instead selects `--vivado-memories`. Neither choice means board signoff.

## File schema 1 and supported selection matrix

```json
{
  "schema": 1,
  "cpu": {"kind": "a1", "clockProfile": "production", "lsuOwners": 4},
  "peripherals": {"jtagDownload": false}
}
```

All fields are required. Unknown fields, wrong types, duplicate keys and unsupported
values are errors. File selection cannot be mixed with `--clock-profile`,
`--experimental-a1-profile`, `--a1-lsu-owners`, `--jtag-download` or a positional
CPU selector. There is no override order, auto-sizing, inheritance or plugin layer.

| Checked-in file | LSU reservations | JTAG RAM download |
|---|---:|---|
| `a1-lsu2-jtag-on.json` | 2 | present |
| `a1-lsu2-jtag-off.json` | 2 | absent |
| `a1-lsu4-jtag-on.json` | 4 | present |
| `a1-lsu4-jtag-off.json` | 4 | absent |

These are explicit **generic production-static A1** combinations. All retain
RV64GC, two-wide issue, ROB 16, PRF 48, store buffer 2, coherent 32 KiB/two-way
I/D caches and the existing shared fabric. LSU reservations are not additional
issue or return ports. Names describe settings, not measured performance tiers.

JTAG means the RAM-download/DMI endpoint, not architectural halt/resume debug.
Disabling it preserves the fixed ABI/MMIO hole and all other peripherals; it does
not renumber IRQs or move devices. Schema 1 retains Ethernet, ordinary DMA, UART and clock management; schema 2
adds the optional composition axes described below. Existing I1, clock and experimental selections remain on the legacy
CLI, with their original constraints; file schema 1 does not expand them.

## File schema 2: backend-window capacities

Schema 2 retains the same outer/peripheral fields and requires two additional CPU
integers: `robEntries` and `physicalRegs`. For example:

```json
{
  "schema": 2,
  "cpu": {"kind": "a1", "clockProfile": "production", "lsuOwners": 4,
          "robEntries": 32, "physicalRegs": 64},
  "peripherals": {"jtagDownload": true}
}
```

The legal domain is ROB 16/32/64 × PRF 48/64 × LSU 2/4. Validation uses the existing
`BackendCapacityConfig`; PRF shortage is allocation backpressure, not a requirement
that PRF exceed ROB + 32. All configurations retain two-wide operation and unchanged
ISA, cache/fabric/coherence and store-buffer policy. The issue queue and per-ROB
metadata grow with ROB, so this is a **backend-window**, not ROB-storage-only, axis.
Specialized experimental/runtime topology restrictions are not relaxed.

The existing four schema-1 files remain unchanged. Two schema-2 examples are
`a1-rob16-prf64-lsu4-jtag-on.json` and `a1-rob32-prf64-lsu4-jtag-on.json`.
Schema 2 with explicit 16/48 and schema 1 with implicit 16/48 have identical CPU
identity. Baseline override fields retain their original `None` representation and
`requestedCpuSpec` retains its old one-field shape. The source JSON and its hash
preserve input provenance separately. Nondefault capacity identities include both
ROB and PRF. This normalization does not equate an omitted legacy CPU spec with an
explicit spec.

All twelve CPU tuples passed pure configuration and actual Common SoC CHIRRTL
geometry checks in the bounded batch below. Focused rename/ROB behavior passed
only LSU4 with (ROB,PRF) = (16,48), (16,64), (32,64). ROB64 remains elaboration-only,
not behavior-qualified. Component tests do not establish full-CPU execution,
execution-unit timing, ISA coverage, IPC or PPA.

## Single selection and separate identities

`CommonSocConfig` groups the existing typed CPU profile, optional CPU specification,
peripherals and optional experiment. It delegates CPU legality and resolution to
`CommonA1CpuSpec.resolve`; it is not a second parameter implementation. The top's
existing constructor is retained for compatibility and adapts to the descriptor.
JSON parsing lives beside the exporter, not in production hardware sources.

The exporter emits:

- `microarchitecture-identity.json`: unchanged CPU identity semantics. An omitted
  legacy CPU specification stays omitted; explicit LSU 2 has an explicit identity
  even though its hardware equals the default. JTAG is not a CPU identity axis.
- `resolved-soc-config.json`: requested selection, input path/hash when applicable,
  effective resources/cache/clock/fabric/MMIO/JTAG values and CPU identity digest.
  Values come from the actual resolved configuration, not preset sizing tables.
- `emission-profile.json`: existing export provenance plus hashes including the
  resolved report. Source and compiled-classpath stability checks remain in force.

Resolved settings, structural elaboration, component behavior, full CPU behavior
and physical results are different evidence levels. This configuration report does
not assert IPC, bandwidth, Fmax, area, timing closure or board correctness.

## Next parameter axes (not exposed by schema 1)

1. **Broader backend qualification:** schema 2 exposes the existing legal capacity
   domain, not a full CPU or physical qualification. ROB64 behavioral qualification
   and matched CPU-level measurements remain separate work.
2. **Cache geometry/concurrency:** `CommonA1CpuTile` currently requires 512 lines,
   two ways and two read-MSHR/response/writeback entries. Merely changing an outer
   JSON field would be misleading. Cache/home/sink-credit constraints and coherence
   tests must close together before exposing a real cache axis.
3. **Other peripherals:** JTAG and ordinary DMA have end-to-end optional presence;
   the network subsystem is the next bounded composition batch below.
   Further options require actual conditional instances/ports, unchanged ABI holes,
   interrupt/software descriptions and focused routing tests, not just feature bits.
4. **Width:** remains two-wide in this flow. Wider issue/retire is not unlocked by
   this work or by unrelated component parameter ranges.

This sequence targets configurable CPU **and** peripheral composition for different
SoCs, while keeping each advertised configuration reproducible and readable.

## Fresh validation (2026-10-29)

The current source passed 15 focused Scala tests (6 SoC selection/parser, 5 CPU
specification, 4 peripheral configuration). This includes all four checked-in
files versus legacy selection/CPU identity, omitted defaults and existing
experiments, unsupported fields/types/values, nested/escaped duplicate keys and
file/CLI conflicts. Four **actual public exporter** runs produced CHIRRTL using
those files and a fully source/classpath-bound receipt. The emitted hardware
contains the expected LSU/request/response-owner capacities (2/4), physical
store-owner credits (3/5), unchanged two store entries, and conditional JTAG
loader/DMI ports; unrelated fabric/DMA/interrupt modules remain present.
Resolved values, exact parsed input-byte hashes and CPU identities were checked.
The on/off JTAG pair has the same CPU identity at each LSU capacity, as intended.

Four additional actual CLI invocations rejected file/selector conflict, duplicate
JSON keys, unsupported LSU capacity and an exit-only compile receipt, all before
creating an output directory. These are successful rejection tests, not DUT runs.

A matched default structural export (`hardwareClocks=false`, no programmable ROM)
was lowered once and is byte-identical to the previously bound default SV
(SHA256 `9a07752e8ae264569b8db34c7125db35ba1e5984205a0dcfb4f41b9d708aee26`).
Default CPU identity also matches its independently bound prior artifact
(SHA256 `82c3ddc8ead92c46e3a5606af880958ae88ffdf9d0386d26b14466309d0149c1`).
The public file exports use hardware clocks and programmable ROM; they are **not**
claimed whole-platform byte-identical to that differently configured default.

The first compile failed in the new JSON visitor's Scala existential return-type
implementation. A dependency API inspection also identified its key callback as
`String`; the two-line exporter-only correction passed the fresh compile/tests.
The original failure and exact correction are preserved, not mislabeled as a
hardware or test-fixture failure. Terminal evidence is
`build/soc-config-20261029-r2/TERMINAL_RESULTS.json` (local, separately archived).
Final documentation is a post-validation delta, not a change to compiled inputs.
No full CPU execution, GSIM behavioral requalification, IPC/bandwidth benchmark,
resource mapping, Fmax or board run was performed by this batch.


## Backend-capacity validation (2026-10-29)

The next coherent batch passed one fresh compile, **20 Scala tests** (7 CPU spec,
9 SoC config, 4 peripheral config) and 7 memory-geometry host tests. All four v1
example files are byte-identical to the preceding public commit. The omitted CPU
spec and explicit LSU2/LSU4 CPU identities retain their old digests and serialized
bytes; schema-2 default capacities equal schema 1. This batch had no unexpected
compile, elaboration or behavioral failure.

All **12** ROB16/32/64 × PRF48/64 × LSU2/4 combinations were actually emitted as
Common SoC CHIRRTL with JTAG on. The census verifies ROB entries/head/tail/count,
64-bit tags, PRF free/ready/data/owner storage, issue queue, pending and memory-live
rows, LSU slots/request/owner FIFOs and the unchanged two-entry store buffer.
Three mutated-IQ/metadata geometry negatives demonstrate parser sensitivity.
One actual public schema-2 CLI export (ROB32/PRF64/LSU4/JTAG off) additionally passed
input-hash, resolved-report and CPU-identity checks. Default SV and identity retain
the exact hashes recorded above; only this default SoC was lowered to SV.

| LSU4 tuple (ROB/PRF) | Rename/ROB component | Directed index wraps | Cross-wrap recovery cycles |
|---|---|---:|---:|
| 16/48 | PASS | 15 | 4 |
| 16/64 | PASS | 15 | 4 |
| 32/64 | PASS | 15 | 8 |

The ledger fixture uses exact resolved Common CPU parameters, not a hand-written
similar profile. Each also passed three fixed seeds / 18,000 randomized cycles
against an independent transaction deque/register-ownership oracle. Directed
checks exercise full-window rollback across index wrap and stale completion after
index reuse. Three retirement-payload observer corruptions failed as expected.
64-bit token width is structurally checked; this does not claim sensitivity to
every high tag bit or wraparound of the entire 64-bit tag space. Completion inputs
are synthetic: no execution unit, accepted LSU request during backend recovery,
Common transport-owner wrap, or integrated CPU execution is qualified by this test.

The actual owner-banked PRF implementation separately passed depth48 and depth64
word-oracle checks, including register63 at depth64, x0, bank ownership changes,
write collisions and reset. Four data/priority observer negatives were rejected.
A fifth, separate depth48 invalid-address test triggered the actual DUT assertion;
it is not counted as an observer corruption. ASAN/UBSAN reported no unexpected
failure. The existing small PRF fixture's synchronous-reset-only GSIM adaptation
preserves original and adjusted FIR and produced identical SV with matching
firtool options. This is not a general or asynchronous-reset equivalence claim.

Evidence: `build/backend-capacity-20261029-r1/TERMINAL_RESULTS.json`, source/delta,
command receipts, original/adjusted FIR and independent-oracle logs are archived
separately. There are 48 successful bounded command receipts, including the exact
expected nonzero negative-test exits. No full-CPU behavior, ISA compliance,
IPC/bandwidth, PPA, synthesis, routed timing or board qualification is claimed.
Post-validation README/documentation changes are recorded separately from the
compiled source epoch. The existing CPU identity qualification remains conservative.

## Optional ordinary memory-copy DMA

Schema 2 accepts optional `peripherals.memoryCopyDma: true|false`; omission keeps
it enabled. Schema 1 retains its exact original fields. Existing configuration
files and all 12 CPU capacity identities are unchanged. The new
`a1-rob16-prf48-lsu2-dma-off-jtag-on.json` is a hardware-composition example, not a
boot-qualified firmware preset. No additional legacy CLI selector is introduced.

Disabling ordinary DMA removes its hardware, its `0x10001000..0x10001027` window
and its internal IRQ4 contribution, without renumbering anything. The window
becomes an error hole. External interrupt inputs are not masked. Network DMA
(IRQ6), GMAC, JTAG, timer, CMU and the coherent Home remain independent. Remaining
network/JTAG requests still pass through the ordinary data adapter, Atomic and
Home; they do not bypass coherence or reach DDR directly. An absent line-DMA
producer removes its optional Atomic/Home line ports as well. The resolved line
capacity becomes 1 (the existing disabled-port constructor contract), even if the
requested FPGA profile uses line transfers with depth 4; the profile itself is
not rewritten.

**Current firmware boundary:** the existing Linux device tree and benchmark
reference ordinary DMA, and monitor diagnostics access its CSRs. They are not
supported with DMA disabled. The public exporter therefore rejects DMA-off with
`--vivado-memories` under the current fixed-COE firmware contract. This is not a
fundamental restriction on DMA-off FPGA hardware. `--programmable` exports load
no firmware and remain available for a compatible custom image. The emission and
resolved reports record DMA presence and this compatibility limitation. No Linux
boot, full-CPU performance, area or timing qualification is implied.

### Focused DMA composition evidence (2026-10-29)

The bounded batch passed 24 pure Scala checks and 3 structural tests. These cover
all 12 CPU capacity identities independently of DMA/JTAG choice; four actual
Fabric DMA×JTAG structures; requested line-DMA depth 4 with its producer present
or absent, including zero producers; strict JSON and current firmware-export
compatibility checks. All six prior v1/v2 configuration files retain exact bytes.
The complete omitted-default A1 SV remains byte-identical (`9a07752e…`), as does
its CPU identity file (`82c3ddc8…`). An actual public programmable DMA-off export
was checked against its resolved report and source-bound compilation receipt.

Two static Fabric GSIM models passed independent transaction/data checks with
ASAN/UBSAN. DMA ON completed in 1,416 cycles: existing copies, dirty-owner probes,
backpressure and two drain epochs, plus actual IRQ4 delivery. DMA OFF completed
in 695 cycles: all former CSR slots and byte endpoints return held error replies
with correct owners; no duplicate reply or unsolicited IRQ4; legitimate external
source 4 still works; JTAG SBA writes/reads RAM; network RX writes RAM and network
TX reads a dirty private owner through Home. Two held AXI B responses (one per
remaining producer) prevent drain until consumed. These directed write addresses
start uncached/nonresident; the oracle does not require resident dirty Home data
to be written immediately to DDR. ON and OFF cycle totals use different tests
and are **not a performance comparison**.

Each model also rejected an injected fixed-data observer mismatch with exit 1
and no PASS marker. This checks data-oracle sensitivity, not comprehensive
mutation coverage of routing, interrupts or owner tracking. Both positive runs
ended with accepted DDR requests fully accounted for. No reset rewrite was used.

The first test compilation failed with four references to the former nonoptional
`dma.io` in the existing always-DMA probe helper. That real API adaptation failure
is preserved; the helper now explicitly enables DMA and accesses its known-present
module. The bounded retry and all subsequent checks passed. No production fallback
or weakened assertion was introduced.

Evidence: `build/memory-copy-dma-20261029-r2/TERMINAL_RESULTS.json`, with the original
r1 failure and both durable source checkpoints retained separately. This does not
qualify full-CPU execution, runtime clock crossing, Linux boot, FPGA deployment,
IPC/bandwidth, area, frequency or timing.


## Static network-subsystem selection

Schema 2 optionally accepts `peripherals.network` as a Boolean, defaulting to
`true`. Schema 1 keeps its exact original field set. The choice jointly controls
the GMAC/PHY-management logic and Ethernet packet DMA; it is not a packet-DMA-only
switch. `a1-rob16-prf48-lsu2-network-off.json` is a concrete programmable-ROM preset.
Network, JTAG download and ordinary memory-copy DMA are independent static choices.

With network disabled, the actual MAC, packet DMA and their external register,
stream, PHY and raw-clock ports are absent. UART, timebase, CMU, CPU configuration,
DDR interface and Home coherence remain. The network-DMA aperture at
`0x10002000..0x100020ff` and Ethernet aperture at `0x10040000..0x1007ffff` become
unmapped holes; devices and interrupt numbers are not shifted. Internal Ethernet
IRQ 5 and packet-DMA IRQ 6 contributions disappear, but independent external
sources at those numbers remain valid.

CMU resource indices remain AON, CPU, TIME, UART, DDR_UI, GMAC_TX and GMAC_RX.
The last two entries advertise `present=false` and `canGate=false`, producing
present mask `0x1f` and gateable mask `0x08`. They are absent endpoints, not
fake-drained or instantly acknowledged managed clocks. Network-dependent runtime
admission/control/rate combinations remain rejected. The default enabled CMU
retains masks `0x7f` and `0x68`.

The exporter reports the actual network presence and CMU masks separately from
CPU identity. Network removal does not identify a different CPU microarchitecture.
The existing fixed-COE firmware calls netboot/GMAC discovery and quieting routines
(`fpga/firmware/bootrom.c` and `netboot_board.c`) and the existing Linux description
assumes network devices. Therefore this exporter rejects network-off with
`--vivado-memories`; programmable exports require compatible custom firmware and
software descriptions. This is the current image contract, not a hardware ban on
network-free FPGA systems. No new firmware boot compatibility is asserted.

### Focused network composition evidence (2026-10-29)

The bounded batch passed 28 pure Scala checks and 5 structural tests, including
all eight network × JTAG × ordinary-DMA compositions. Complete platform exports
confirm actual MAC/packet-DMA removal, retained UART/CMU/coherent Home and unchanged
CPU identity. The default SV remains byte-identical (`9a07752e…`), as does its CPU
identity file (`82c3ddc8…`); all seven earlier JSON presets retain exact bytes.

Two network-off Fabric models passed ASAN/UBSAN transaction checks. With ordinary
DMA and JTAG present, dirty-owner probes, late probes, drain and JTAG SBA held-B
and readback paths passed (2,932 cycles). With both absent, ordinary RAM/MMIO and
zero-producer drain passed (1,588 cycles). Each checks 42 former network addresses
with reads, writes and held error responses: all packet-DMA CSR words plus byte
endpoints, and sparse GMAC interior/boundary samples—not every GMAC byte address.
Owner preservation, no alias to DDR/endpoints, and external IRQ 5/6 delivery are
checked. Each also rejects an observer-only hole-response error-bit mutation with
exit 1 and the exact expected diagnostic. Different workloads mean these cycle
counts are **not a bandwidth or performance comparison**.

The actual network-off managed bank additionally passed four independent UART
receive/wake sequences, one serial transmit, four absent-resource STOP rejections
and 66 MMIO transactions (11,415 cycles), with ASAN/UBSAN. Its observer-only first
UART receive-byte mutation is rejected with the exact expected diagnostic.

These results use two explicit generator epochs. The Fabric models used the
previously pinned GSIM with the initialization byte-span fix. The bank preserves
its original AsyncReset FIR and original host/oracle, but uses the separately
qualified reset-graph repair described in `simulator/gsim/tool_fixes/RESET_GRAPH.md`.
The original bank generation was blocked before native compilation by missing
reset aliases and unqualified reset scheduling. An initial two-site tool repair
failed the unchanged held-reset oracle; the old tool also failed the unchanged
synchronous-release oracle. These failures were retained, not hidden with a FIR
reset-type rewrite. The final tool passed five named microfixtures, one observer
negative and two generator rejection controls before the bank was regenerated
and its actual reset/step interface independently reviewed.

The repair is bounded by those fixtures and GSIM step semantics. Arbitrary chained
synchronous reset-group networks, real-time setter edges, physical CDC and general
RTL compiler equivalence remain unqualified. Fabric wide line-grant payloads are
not independently inspected by these hosts. This batch does not measure full-CPU
IPC, bandwidth, PPA, Linux boot, FPGA timing or runtime independent-clock behavior.

Evidence is split between `build/network-option-20261029-r1/PARTIAL_RESULTS.json`
(the immutable original source and Fabric epoch) and
`build/network-option-reset-recovery-20261029-r1/EXECUTION_RESULT.json`
(the unchanged bank under the qualified repaired tool). Public documentation and
tool reproduction files are a separately reviewed post-validation addition.
