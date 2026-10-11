# Atomic PMP range publication candidate

Status: focused component Scala/GSIM qualification and official small-unit native
structure checks passed. No synthesis, STA, placement, routing, or board run. Base: `507c81beefede7ecb806dc5219d65df8591ba5df`. The stopped physical
report was estimated Physopt postPlace, WNS −1.558 ns, and was not routed. This
candidate makes no physical improvement or full-board qualification claim. Focused
results are bound in [the evidence record](experiments/registered-pmp-regions-evidence.json).

## Contract and source change

`OooParams.registeredPmpRegions` is default false and requires the architectural
machine CSR owner with 8 or 16 implemented PMP entries. All existing board presets
remain unchanged. `FpgaNextConfig.RegisteredPmpCandidate` and the exact
`--registered-pmp-regions` option select it explicitly. Native managed-board and
GSIM board constructors carry the same flag, including the actual constructor
comparison in `BoardSocGsim`.

The machine system unit remains the sole raw PMP CSR owner. Its existing native
instruction decoding, captured SystemRequest, legal-CSR/write checks, cfg
sanitization, own-entry lock and locked-next-TOR filters drive conditionally
selected write targets. With the flag off, these targets are the original raw
registers, and the original combinational decoder drives the exported bounds.
With the flag on, they are next-state wires; the same raw registers commit those
wires and one shared decoder computes the derived register inputs. Raw cfg/addr
and decoded low/end/active become visible together at that CSR edge.

Each implemented range has its own enable. A cfg write enables each writable
entry in its addressed eight-entry bank. An accepted address write enables its
own range, even if OFF, plus the next range only when that entry is TOR. A locked
next TOR entry suppresses the raw address write and both enables through the
existing guard. A changed predecessor can therefore change next-TOR low/active
on the same edge, including equality and reversed bounds. A cfg write cannot
change the predecessor address. No per-checker decoder is introduced.

Reset remains raw cfg/address zero, decoded low zero/end seven/inactive, including
unused entries. Retaining 65-bit bounds preserves the exact observable inactive
TOR top-zero underflow and extended access-end semantics. Permissions,
first-overlap priority, privilege/MPRV, CSR refetch/invalidate and VM drain are
unchanged. The separate raw-PMP context-change comparator is unchanged.

## Throughput, storage and timing obligations

- Request latency, accepted request duty, CSR command capacity (one), flush
  backpressure and existing minimum CSR completion latency are unchanged by
  design. No request pipeline stage or protocol port is added.
- Declared new derived state is 131 bits per implemented entry: 1,048 bits for
  eight entries or 2,096 for sixteen. The original raw CSR state is unchanged.
  The 16-entry upper bound is about 2.05% of the stopped report's 102,063 FF.
  Official firtool DCE retains all 1,048/2,096 derived bits in the native SV;
  constant propagation and register merging are not measured resource savings.
- No RAM, permission checker, raw-state shadow bank or extra request queue is
  added. The two independent access observers exist only in the narrow fixture.
- Per-entry enable load is at most 131 declared register bits; at most eight
  entries update for a cfg write and two for an address write. Native synthesis
  must report actual enable fanout and FF/LUT cost rather than relying on these
  source estimates.
- The new path is captured CSR operand/read value → RW/RS/RC → filtered cfg/addr
  next-state mux → shared NAPOT/TOR decoding → derived D. It must be analyzed in
  the combined implementation. Registering request-visible bounds does not prove
  this update path meets timing, nor remove downstream permission/SEAL/cache
  cones. There is no timing exception or pipeline workaround in this change.

## Focused verification

`PmpCsrPublicationGsim` instantiates the actual `MachineSystemUnit`, with its
production SystemRequest port, normal instruction decoder, raw CSR registers,
privilege logic, completion hold and VM/FENCE.I handshakes. It exposes all 16 raw
and decoded entries on every observed cycle and separately observes real data
and fetch checks. The driver never injects raw PMP state or decodes a replacement
CSR module.

The independent C++ model derives filtered raw state from CSR RW/RS/RC and
immediate instructions, decodes NAPOT by counting trailing ones, and checks
half-open byte intervals using 128-bit arithmetic. Every observation compares
raw cfg/addr, all 65 bound bits, active, data/fetch permission, effective privilege,
SATP, CSR completion data/token/exception and refetch/flush sequencing. GSIM's
pre-edge output convention is accounted for explicitly: each snapshot is the
post-edge state from the preceding step, including the first observation after
CSR publication, reset release and held completions/flushes.

Directed scenarios cover OFF/NA4/NAPOT/TOR, first-overlap and partial coverage,
TOR top zero/equal/reversed boundaries, changed OFF predecessors, all 54 NAPOT
carry positions and saturation, the 56/64-bit boundaries, all access sizes and
permission kinds, cfg sanitation, same-bank mixed locks, next-TOR locks across
cfg banks, CSR source-zero versus operand-zero, read-only/illegal/nonexistent
CSRs, suppressed reads, M/S/U and MPRV, SATP and FENCE.I/SFENCE.VMA, reset after
locks and reset during a held permission-update flush. A bounded deterministic
CSR stream periodically resets so locks cannot make all writes inert.

The runner uses existing `simulator/gsim/run.py` helpers, with a
backward-compatible optional GSIM-argument parameter. Both normal and mutant
models use official `--cpp-max-size-KB=1024` splitting, `--threads=1`, and serial
Clang execution. The driver reuses the existing trivially-copyable full-host-zero
initialization contract before two real reset edges; this compensates for the
pinned GSIM constructor's byte-count issue without changing DUT logic. It drops
start VALID after acceptance before poisoning the inactive request payload. It compares
matched 8/16-entry live versus registered runs and a zero-entry control, checks
actual emitted derived-register counts, runs an oracle-negative control, and
compiles two private source mutants (stale raw-address decode; omitted next-TOR
predecessor enable) that must fail the range-publication oracle. It does not edit
passed source/classes. Each receipt binds source and toolchain hashes, preserves
logs, and explicitly reports unmeasured physical results.

The focused gate used these commands after source review and CPU-slot handoff:

```
mill -i IonSoC.test.testOnly ooo.RegisteredPmpRegionsSpec ooo.FpgaNextConfigSpec
GSIM_CXX=clang++-19 python3 -B simulator/gsim/registered_pmp_regions.py --tag registered-pmp-r1 --build-run
```

The corresponding native structure/resource and timing assessment belongs to
the single combined batch. No local run or public preset activation is implied.

## Executed checks and remaining integration

- `python3 -B -m unittest fpga/next/test_registered_pmp_regions.py fpga/next/test_performance.py`:
  11 host tests passed. The omitted-option preset configurations and native CLI
  commands remain identical. Duplicate, value-bearing and abbreviated new flag
  forms are rejected.
- `python3 -B simulator/gsim/registered_pmp_regions.py --tag registered-pmp-r1`:
  preflight only, five models and two source mutants scheduled.
- Two host-only `common.test` argv tests passed: the default generation command
  is unchanged; the optional official split flag changes only generation argv.
- `git diff --check`: passed.
- Scala gate: 21 tests passed, including the actual machine unit's 8/16-entry
  ON/OFF emitted register counts and legal/default configuration checks.
- Five actual-CSR GSIM models passed under ASan/UBSan. The 8-entry live and
  registered models each executed 18,795 cycles / 632 CSR/system commands,
  checking 300,304 entry snapshots and 37,538 accesses. The 16-entry pair each
  executed 20,441 cycles / 638 commands, checking 326,640 snapshots and 40,830
  accesses. Matched ON/OFF logs, including held-flush/completion counts, were
  identical. A zero-entry control also passed.
- All five oracle-negative controls returned the expected mismatch. Real
  private-overlay source mutants were rejected: stale raw-address decode at
  entry 0/cycle 376; omitted TOR-predecessor enable at entry 1/cycle 966.
- Official firtool 1.135.0 exported all four existing 8/16-entry live/registered
  FIR files. DCE native SV scalar state was 1,928 → 2,976 bits for eight entries
  and 2,424 → 4,520 for sixteen. Added declarations were 24/48, with no array
  state delta, no raw PMP state delta (496/992 bits), and identical ON/OFF port
  signatures in every module. All derived widths remain 65/65/1 in that SV.

The native CSR update cone explicitly retains a 54-bit NAPOT increment, 65-bit
TOR subtract and NA4 add, next-cfg/address muxes, and a 54-bit predecessor
comparison for nonzero entries. Each native local enable condition controls
three derived registers totaling 131 bits. Shared CSR qualifiers still occur in
all 8/16 entry conditions. A syntax dependency census finds 51–52 (8 entries) or
59–60 (16 entries) ternary operators across each unique data-cone definition
closure, including the preexisting full CSR read selection. These counts are
not serial gate depth, mapped cells, electrical fanout, or timing results.

The component's base snapshot predates the six-file matching-board envelope.
That integration is now complete in the [combined candidate](fpga-next/timing-cdc-combined-v1.md):
the actual CPU allowlist carries the flag, BoardSocGsim keeps MatchingManagedBoard,
and its named PMP argument is checked against the actual full core configuration.
All four pure constructor reports and the actual emitted matching CPU profile
passed complete comparisons. Bare and Sv39 reproduced the qualified adoption-ON
results and complete AXI traces. Those combined results have their own source and
receipt identity; they do not turn this component check into physical timing proof.
