# Optional split-low ROB tag advance

Private experimental profile:
`full-r1-m3-checked-flow-store-row-elastic-proof-guarded-natural-pmp-split-tag`.
Its control is the qualified guarded-natural profile; only `splitLowTagAdvance`
is enabled. Public defaults, the qualified e48bf96 branch and its delivered RTL
remain unchanged. The existing guarded-natural memory contract is reused, not
replaced. Legacy board factories reject this flag instead of silently ignoring it.

## Contract

`SplitLowTagAdvance` is a pure combinational helper: zero registered latency,
initiation interval one, one base/count pair and one full-width-plus-carry result.
It adds no storage, credit, stage, capacity, ready/valid or backpressure. For known
widths B > C > 0, it adds the C-bit count to the low C bits, independently computes
the high-field increment, then chooses the increment only on low-field carry.
All C-bit count values are supported; the output is exactly B+1 bits. Invalid or
unknown widths are rejected. Production selection is deliberately restricted to
64-bit tags and two rename lanes (two-bit accepted count).

Only `RenameRob.advancedTag` is selected by the default-false flag. The disabled
branch retains the original `nextTag +& allocatedCount`. Lane tags remain
`base + lane`, with their original full-width overflow blockers; they are not
prefix-popcount indices. Prefix admission, invalid holes, capacity, dispatch,
recovery, reset, and every register remain unchanged. In particular, the existing
conditional `exhausted := advancedTag(p.tagBits)` assignment is unchanged, not
replaced with sticky OR. Exhaustion prevents subsequent admission through the
existing gate, rather than through modified counter arithmetic.

## Focused qualification (2026-10-25)

* Shared source-bound Scala compile passed; eight focused suites passed 23 tests,
  including exact one-flag profile/configuration equality, unchanged shared memory
  policy, default-off behavior and helper width rejection/output widths.
* Actual emitted Chisel helper passed full-domain SAT against an independent
  65-bit repeated bit-ripple increment oracle: every 64-bit base, count 0..3,
  original addition and lane tags, plus arbitrary predecessor exhausted/reset/
  recovery in a conditional-state projection. MAX+0..3 is included without
  assumptions. Carry-selection and exhaustion-hold mutants both failed as
  expected. This projection is not an arbitrary-state proof of the whole Ledger.
* Actual two-wide ROB16/PRF48/tag64 Ledger control/split pair passed the unchanged
  independent deque oracle under the qualified deterministic corrected GSIM epoch
  (`128c4853a6584cd1181cff863fc727a824fe132ad3c60f3ba323d46ea3b135fa`),
  with ASan/UBSan. All three positive logs match byte-for-byte. Per model the main
  run includes 18,000 random cycles, 14,300 allocations, 8,572 commits and 1,191
  recoveries; additional head-trap tests include 3,000 random cycles. Directed
  tests cover reset with live owners, holes, backpressure, out-of-order completion,
  ordered retirement, recovery and every stale generation bit. All 26 observation
  negative controls were rejected across the pair. Live nextTag starts at zero:
  bounded runtime does not traverse 2^64 exhaustion and no state-injection
  backdoor or narrowed counter was added.
* Independent emitted-FIR comparison accepts only the helper arithmetic expansion;
  every other module/body line is identical after removing source locators. All
  four lowered child SV modules and all 295 register declarations are unchanged.

Evidence:

| Check | Receipt / log | SHA256 |
|---|---|---|
| Compile | `build/split-low-tag-advance-20261025-r1/scala/compile-receipt.json` | `21fb8625bb35e3e4e355ac83332168cfc9ebb4f0d0bbf6113422384863bff9aa` |
| Focused Scala | `build/split-low-tag-advance-20261025-r1/focused-specs.log` | See retained log |
| Actual helper SAT | `build/tag-advance-actual-helper-20261025-r2/receipt.json` | `f31808b987f717be5a5512bc74fc9a11b6f241aaa5a65f1f2935aaa46a2f693b` |
| Actual Ledger GSIM | `build/gsim/split-low-tag-advance-ledger-20261025-r1/receipt.json` | `2edd1ab9bfc0d9f8a55984d4bb2b4f6fa7ed1587c096040e70ec485945db1939` |
| Actual Ledger maps | `build/split-low-tag-ledger-mapping-20261025-r1/receipt.json` | `5427fbf62676efa0e1f629e9bc82ac8ca298ce27babf8d82388d42be29b6e2ea` |

The first helper formal attempt is retained in
`build/tag-advance-actual-helper-20261025-r1`: Yosys stopped before proof on
single-file firtool verification-layer include packaging. R2 uses split RTL and
passed on the identical compiled Scala; no RTL workaround or source recompile.

## Actual Ledger resource / connectivity prescreen

Bare untapped RenameRob was emitted from the same exact profile pair, then mapped
with pinned Yosys xcup in two separately matched policies: standard default and
no-SAT-sharing (generic share omitted, `memory -nomap -nosat`). Both policies give
the same component results; no whole-CPU map was run for this experiment.

| Component resource | Control | Split |
|---|---:|---:|
| LUT | 16,772 | 16,760 |
| FF | 5,956 | 5,956 |
| CARRY4 | 73 | 73 |
| MUXF | 2,211 | 1,837 |
| RAM32M16 | 14 | 14 |

Conservative unweighted bit-aware primitive graph depths, cutting sequential
state and keeping D/CE/R separate:

| Actual input/state root → endpoint | Control | Split |
|---|---:|---:|
| Allocation-valid → exhausted D | 22 | 7 |
| Allocation-valid → high-tag D | 21 | unreachable |
| Allocation-valid → high-tag CE | 2 | 7 |
| Early tag state → tag state | 40 | 26 |
| All state/input → any state endpoint | 40 | 35 |

The CE depth increase is an explicit tradeoff, not hidden by the shorter D cone.
These roots are actual top-level allocation valids, not an artificial late-count
port. Unreachable means no connection from that root within this graph, not an
absent register or unused enable. These are connectivity bounds, not sensitizable
paths, physical delay, STA, Fmax or whole-CPU timing. Global mapping can restructure
other cones; the small component LUT/MUXF delta must not be extrapolated to CPU
resource savings.

## Matched integrated CPU check

`build/gsim/split-low-tag-advance-cpu-20261025-r1/receipt.json`
(SHA256 `d71935a0d5a19aa006a433b3dfd2b2f6cde1fa5b59e844330658b2dfb8678645`)
passed with exactly one newly generated candidate DUT and a replay of the qualified
corrected-epoch guarded baseline: eight guest executions total. Fresh disabled
FIR matched the qualified e48 baseline after removing source locators; effective
configuration differs only in the new flag. All module ports, memory and cache
geometry are identical; only the RenameRob body changes.

| Guest metric | Guarded control | Split |
|---|---:|---:|
| VM stream cycles | 681 | 681 |
| VM dependency cycles | 1,018 | 1,018 |
| Hot-load ROI cycles | 531 | 531 |
| Cold-load ROI cycles | 360 | 360 |

Full guest logs, metrics and owner observations match exactly. A candidate
physical-address observation mutant was rejected. Source, corrected tool epoch,
compile, component/formal/structural/resource evidence and reused baseline
artifact bindings were rechecked unchanged. These focused workloads show no
cycle/throughput regression and **no performance uplift**; simulation host build
or run time is not hardware speed. This is not a full ISA/system regression,
physical timing test, or board qualification.

A separate zero-DUT/zero-guest-rebuild Bare ROM check replayed the guarded
baseline and linked only a candidate host against the existing candidate model,
using the original host, ELF and oracles. Full logs and six ROI records match:
7,192 cycles, 8,570 retired instructions, 1,221 loads, 39 stores, 1,260 replies and
640 validation bytes. Proof-query offers/accepts are both zero; this is not
proof-hit evidence, network/DMA throughput or a board result. All bindings remain
unchanged and the CPU receipt above is immutable. An initial runner preflight
receipt-schema parsing failure was retained; it occurred before any build or
runtime and was not a DUT failure. Bare receipt:
`build/gsim/split-tag-bare-rom-20261025-r1/receipt.json`, SHA256
`ed8c0d9e4f237d7726bf1f81580adda56780e2d0dc1b06d5adbca05ebdecc61d`.

## Remaining boundary

The earlier build-only prototype in
`build/tag-advance-prototype-20261025-r1/REPORT.md` remains separate historical
projection evidence. The matched CPU check above is distinct from the helper/Ledger checks and
limited to its focused guest scenarios and separate Bare ROM check. No default promotion, new full CPU synthesis,
routed timing, board result or hardware frequency improvement is claimed.
