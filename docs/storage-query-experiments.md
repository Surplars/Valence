# Default-off ROB completion-storage and recovery-query experiments

These are separately qualified experiments, not new production profiles. The
normal two-wide A1 configuration and `IntegerBackend` remain unchanged. The only
production API addition is `RenameRob.experimentalCompletionDataStorage`, default
`false`. Test-only overlays select storage and, independently, queried recovery.
See [reproduction instructions](../simulator/gsim/experiments/storage_query/README.md).

## Contract and scope

Storage retains ROB capacity, two completion writers, two consecutive commit
readers, combinational read latency, allocation-zero observable values, complete
64-bit token checks, existing completion acceptance/duplicate priority and recovery
semantics. It reuses `DualWriterRobCompletionData`; it does not change admission,
credits or pipeline stages. It rejects combination with either historical banking
option and requires two writers/readers and a power-of-two ROB of at least four.
CPU evidence covers only ROB16/PRF48/LSU4 and ROB32/PRF64/LSU4.

The query overlay subclasses the original `ParallelRecoveryAdmission`. Two queried
ages use the existing external/local keep boundaries and winner arbitration,
instead of selecting the late 32-entry survival vector for each completion.
Original admission outputs and full-tag arbitration remain in the helper contract;
ordinary CPU elaboration may prune unused outputs. This is not
an `OooParams` option: the overlay must be compiled into an isolated output and
placed before production classes. Do not silently overwrite normal class files.

Both variants retain the generic A1 RV64GC configuration, F/D, atomics, compressed
instructions, translation/PMP and two-wide execution. The historical
`bankedRobCompletionData` parameter remains false: constructor opt-in, not that
old profile, activates this storage experiment. `splitLowTagAdvance`,
`retirementIntent` and `retirementSlotIdentity` remain false. No tag-advance or
hierarchy-preservation candidate is included.

## Recorded cloud qualification (2026-10-30)

These results precede publication and are not a claim that every historical
experiment was rerun by this commit. GSIM r4, Clang 19.1.7, Java 21, FIRTool 1.135
and Yosys 0.52 were used. No Verilator was used.

* Original register versus storage: four CPU models (16/48 and 32/64 paired),
  16 positive and eight precise negative checks. Smoke, fixed one-iteration
  CoreMark-like guest, branch recovery and fixed memory congestion agreed byte
  for byte within each capacity. Guest retired 384330 instructions; ROI retired
  360525. ROI cycles: 470604 at 16/48 and 449274 at 32/64, unchanged by storage.
  This is not an official CoreMark score.
* Storage32 versus query32: only one new CPU model, immutable storage model
  reused. Six positive and four precise negative checks. Branch, independent
  480-body ALU supply and memory congestion ROI cycles were 345, 1134 and 101,
  respectively, identical between variants. The congestion service withheld
  grants for 32 cycles. This finite supply test does not establish peak sustained
  internal dispatch. No additional query CoreMark run was performed.
* Generated admission RTL equivalence: 16/32, unconstrained full encodings,
  including both recovery requests, winner ties, wrap, inactive recovery, raw
  invalid outputs, and full tags. Queried survival equals the old indexed
  output. A strict-boundary mutation produced the expected counterexample.
  This is a component combinational proof, not full sequential CPU equivalence.

## Matched actual CPU-inner-ledger structural map

Same 32/64 context and synthesis settings; not full-CPU Vivado resource results.
Logic LUT excludes LUTRAM. RAM32M16 counts are separate, not silently added to
Vivado total LUT. MUXF increases are retained rather than omitted.

| Metric | Register reference | Storage | Storage + query |
|---|---:|---:|---:|
| LUT1..6 | 29514 | 21181 | 21492 |
| FF | 11416 | 5304 | 5304 |
| RAM32M16 | 14 | 64 | 64 |
| MUXF7 | 4793 | 5570 | 5780 |
| MUXF8 | 2084 | 2439 | 2574 |
| MUXF9 | 491 | 599 | 630 |
| Maximum cell depth | 39 | 38 | 38 |
| Recovery to RAM write enable | n/a | 27 | 25 |
| Commit lane data/next-PC depth | — | 27 / 26 | 23 / 23 |

Storage/query CARRY4 count is 114. Query costs 311 additional logic LUT (+1.47%)
and more MUXF in exchange for shorter selected control cones; the global maximum
is unchanged. This is a tradeoff, not an unconditional improvement.

The graph cuts sequential feedback at state outputs and treats RAM reads as
address-to-data arcs, excluding write/clock arcs. LUT/MUX/CARRY4/RAM-read cells
count as one, buffers zero. These are structural depths, not sensitized paths or
STA. Whole-module mapping can redistribute logic; source/module names and context
matter, so module attribution is approximate and cross-batch numbers are not
interchangeable. No routed timing, board clock, frequency or default-profile
promotion follows from these data. Matched local Vivado comparison is separate
work, not a result delivered by this commit.

## Publication checks

The new `ooo.ExperimentalCompletionStorageSpec` passed all three active Scala
configuration/elaboration tests after `mill -i IonSoC.test.compile`. It checks
omitted-argument default-off behavior, actual 16/48 and 32/64 storage geometry,
unchanged parameters and precise incompatible-option/geometry rejection. It does
not simulate hardware. The public overlay preparation tests exercise exact-source
creation and refusal on drift/context mismatch/unsafe output destinations.

The final public runner was executed for both 32/64 roles: isolated compilation,
actual JVM class-origin checks and ordinary tile export all passed. Each role's
166 SV files and three parameter JSONs matched its previously qualified export
byte for byte. The only cross-role SV differences were `RenameRob` and
`ParallelRecoveryAdmission`. This establishes reproduction of those inputs;
no new CPU simulation or physical implementation is implied.
