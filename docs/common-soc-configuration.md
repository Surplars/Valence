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
not renumber IRQs or move devices. UART, Ethernet, DMA and clock management remain
mandatory. Existing I1, clock and experimental selections remain on the legacy
CLI, with their original constraints; file schema 1 does not expand them.

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

1. **ROB/PRF capacities:** `BackendCapacityConfig` already admits experimental ROB
   16/32/64 and PRF 48/64 while retaining two-wide rename/commit/completion.
   Admission there is not qualification of every Common SoC combination. Issue
   entry capacity is tied to ROB. A next batch must bind actual generated sizes,
   wraparound/full/stall/recovery behavior, identity and matched measurement before
   adding a bounded generic CPU specification; specialized topology guards stay.
2. **Cache geometry/concurrency:** `CommonA1CpuTile` currently requires 512 lines,
   two ways and two read-MSHR/response/writeback entries. Merely changing an outer
   JSON field would be misleading. Cache/home/sink-credit constraints and coherence
   tests must close together before exposing a real cache axis.
3. **Other peripherals:** only JTAG has end-to-end optional presence today.
   Other options require actual conditional instances/ports, unchanged ABI holes,
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
