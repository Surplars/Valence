# Generic A1 CPU capacity specification

This is one bounded CPU-private capacity axis for the configurable common SoC.
It does not create a new issue width, ISA subset, or measured performance tier.

## Contract

`CommonA1CpuSpec(lsuOwners = 2 | 4)` is an optional argument to
`CommonMachinePlatform`. Omitting it preserves the previous public or explicitly
selected experimental configuration. Explicit specifications are supported only
for the generic A1 production static-clock profile; I1, other clock profiles,
experimental A1 selections and runtime admission combinations are rejected.
An incompatible specification is never silently ignored or overridden.

Both explicit choices retain two-wide rename/completion/commit, the derived
two-wide issue budget, ROB16, PRF48, store-buffer depth2, RV64GC, PMP/VM/FP
capabilities, caches and shared-fabric policy. The one existing configuration
change is `lsuEntries`, which derives the LSU reservation and response-owner
capacities. More reservation slots do not imply more request or completion ports.

The same resolver supplies the tile, export identity and effective CPU metadata.
The shared fabric still uses its existing platform configuration: CPU-private
capacity selection does not rewrite shared DDR, cache, peripheral or clock
parameters. The independently selected JTAG RAM-download option is retained.

## Export

Add `--a1-lsu-owners=2` or `--a1-lsu-owners=4` to an otherwise valid
`platform.CommonMachinePlatformMain` command. For example:

```sh
mill -i IonSoC.test.runMain platform.CommonMachinePlatformMain OUTPUT a1 \
  --compile-receipt=BOUND_COMPILE_RECEIPT.json --programmable \
  --a1-lsu-owners=4 --jtag-download=off --emit-chirrtl-only
```

The explicit specification requires the existing complete successful compile
receipt, bound to actual sources and compiled classes. An exit-only receipt is
not sufficient. The output identity records the requested specification and
resolved core parameters; the emission manifest adds `a1Resources` for ROB,
physical registers, LSU owners and store-buffer entries. The qualification field
explicitly distinguishes configuration export from CPU behavioral qualification.

## Validation scope

This source was reconstructed on 2026-10-29 after an unpublished local worktree
was lost. The following are fresh results for the reconstruction, not adoption
of the lost batch's reported passes:

- Ten Scala tests passed: five CPU-spec tests, four existing selection tests and
  one memory-capacity test. Seven Python parser tests passed, covering direct and
  wrapped queues at both capacities plus six malformed cases.
- Fresh default platform SV is byte-identical to the source/tool-bound historical
  JTAG-on baseline (SHA256 `9a07752e8ae264569b8db34c7125db35ba1e5984205a0dcfb4f41b9d708aee26`).
  Default CPU identity also matches the independently bound historical public
  CLI-off CPU identity; these are separate artifacts with separate provenance.
- Fresh whole-platform FIR proves the following actual dimensions:

  | Dimension | Default / 2 owners | Explicit 4 owners |
  |---|---:|---:|
  | LSU reservations | 2 | 4 |
  | Registered request FIFO | 2 | 4 |
  | Response-owner FIFO | 2 | 4 |
  | Store-buffer physical owner credits | 3 | 5 |
  | Store-buffer write entries | 2 | 2 |

- The real public exporter ran with `--a1-lsu-owners=4 --jtag-download=off`,
  programmable ROM and a fully bound compile receipt. Its emitted FIR has the
  four-owner geometry and no JTAG loader. Its manifest reports ROB16/PRF48/LSU4/
  store-buffer2 and issue width2; CPU identity matches the structural four-owner
  configuration. Hardware-clock/ROM settings differ from the structural emitter,
  so their complete platform FIRs are not claimed identical.
- Two fresh small LSU GSIM models passed under ASAN/UBSAN. Each passed independent
  full-token ownership, capacity, held-request/completion, cancelled stale-error
  response, reuse, precise-fault, store-drain and serialized-load checks. Each
  deliberately corrupted oracle exited1 with the exact expected mismatch;
  neither negative case is counted as a successful DUT workload.

The first validation attempt exposed an invalid runtime-boundary **test fixture**
(9/10 Scala tests passed); the corrected legal capability ladder passed all10.
The first Python attempt exposed a truncated synthetic request **test fixture**;
using the actual full native request payload passed all7 without weakening the
parser. Both failed attempts are preserved. Neither correction changed production
hardware. Scala results are from r2; Python/structural/component results are from
r3, whose Python-only change leaves all compiled Scala inputs/classes unchanged.
The terminal evidence is `build/cpu-spec-rebuild-20261029-r3/TERMINAL_RESULTS.json`
(local evidence, separately archived); final documentation is a post-validation
source delta, not part of the compiled hardware input set.

Wrapper cancellation is test stimulus, not execution of backend branch recovery.
A serialized load using a non-RAM address is not an MMIO-routing or side-effect
test. No full CPU execution, throughput, resource-map, Fmax or board result is
claimed by this configuration stage. Such conclusions require a separately
matched CPU workload and implementation measurement.
