# Opt-in shared fetch PMP comparisons

`OooParams.sharedFetchPmpRelations` defaults to `false`. It requires an existing
word-span, parallel packet PMP configuration with PMP enabled. This change does
not select a new board profile or promote an implementation candidate.

## Contract

`NearbyWordRelations` shares unsigned comparisons of neighboring wrapped word
addresses. For a bound and a packet base, it compares the high word once, compares
equality with that high word and its successor, and resolves each offset with a
small low-field comparison. Explicit high-word wrap handles the all-ones address.

The packet checker keeps the full 64-bit byte address. Its 62-bit word comparison
and separate 65th-bit access-end handling preserve an individually wrapped start
address and a non-wrapped four-byte access interval. Region decoding, first
overlap priority, partial-coverage denial, execute permission, lock bits, and
privilege policy are unchanged. No address bits are discarded.

The combinational checker accepts a new base and permission state every cycle.
It adds no register, memory, queue, backpressure, or pipeline cycle. It checks
`2 * width - 1` possible halfword instruction starts over `width + 1` words.
The selected two-issue geometry remains two-wide; a four-wide fixture is a
scaling check, not evidence of a working wider CPU.

## Bounded verification

From a checkout with the existing pinned GSIM and Mill toolchain available:

```sh
mill -i IonSoC.test.testOnly ooo.SharedFetchPmpSpec
VALENCE_GSIM_SOURCE=/path/to/existing/pinned/gsim-src \
  python3 -B simulator/gsim/shared_fetch_pmp.py --tag shared-pmp-review --build-run
```

The runner never fetches or installs a simulator. Without `--build-run`, it
reports preflight only. Use a fresh tag to preserve previous evidence.

- The independent mathematical model checks reduced widths exhaustively and
  full-width examples deterministically. This alone is not an RTL proof.
- Four raw RTL fixtures check both ordering directions at word widths 8 and 62,
  with maximum offsets 2 and 4. Width 8 checks every base/bound pair; width 62
  checks directed high-address, carry, wrap, and deterministic random cases.
- Baseline/shared packet pairs at widths 2 and 4 use the independent 128-bit
  byte-interval PMP oracle. Every packet instruction-start lane is checked on
  every input vector, covering TOR/NA4/NAPOT, OFF predecessors, first overlapping
  entry, partial coverage, execute denial, locked/unlocked M mode, U/S mode,
  no-match policy, physical-width limits, and XLEN-wrapped packet starts.
- Every fixture rejects an injected expected-result mismatch. Separate private
  Scala-class overlays compile actual reversed-priority and missing-high-wrap
  source mutants; the ordinary independent oracles must reject both.
- The receipt hashes sources, generated models, normal/negative logs, simulator
  binary, and source-mutant evidence, and rejects source drift during the run.

`SharedFetchPmpSpec` checks the default-off option, invalid configuration guards,
state-free elaboration at widths 1/2/4, supported entry counts 0/8/16, and rejection
of an unbounded shared window. Behavioral RTL coverage is specifically the
16-entry, balanced-comparison, two/four-wide packet domain.

## Structural evidence and limits

### Recorded bounded result, 2026-10-08

`build/gsim/shared-pmp-review-fixed-20261008/receipt.json` reports
`PASS_SHARED_PMP_MODULE_ONLY`. All three Scala checks passed. The four raw RTL
fixtures checked 196,611 / 327,685 / 1,156,299 / 1,927,165 word-relation pairs
(both ordering directions per pair). The separate mathematical-model counter
was 16,469,296 pairs, not an RTL count.

Each baseline/shared packet variant checked 261,768 instruction starts at width
2 or 610,792 at width 4. All eight expected-mismatch controls exited 1. Both
compiled source mutants exited 1 for the intended reason: reversed priority was
caught by the all-lane byte-interval oracle, and missing high-word wrap was
caught by the raw ordering oracle. All models used ASan/UBSan, pinned GSIM
`93b8cd23edd3228807c4f2a08c19c3936a463cb2`, and Clang 19.1.7.

The first receipt (`shared-pmp-review-20261008`) remains a failed run: its eight
normal/negative fixtures passed, but an over-strict runner check rejected Mill's
legitimately absent optional resource directories before source mutation. Only
the runner was corrected. A fresh complete bounded run then passed; no DUT or
oracle fix was needed.

### Elaborated counts

`shared_fetch_pmp_structure.py` examines only the elaborated `PacketFetchPmp`
module from each matched fixture. It verifies all 16 lower bounds, upper bounds,
activity bits, and configurations remain inputs, and no state appears.

At width 2, the logical ordered comparisons change from 96 62-bit comparisons
to 32 60-bit high comparisons plus 96 used two-bit low comparisons. At width 4,
they change from 160 62-bit comparisons to 32 59-bit high comparisons plus 160
used three-bit low comparisons. Equality, carry, mux, and Boolean logic remain;
these changes are not a claim that total gate count decreases proportionally.

The report also counts pre-optimization CHIRRTL primitives. These include both
returned low-comparison directions even when a caller uses only one. Textual
input references are wires, not physical register-file read ports. PMP state
capacity and external ports do not change.

Measured pre-optimization counts, baseline to shared:

- Width 2: `lt` 768 to 256, `leq` 0 to 192, `eq` 1779 to 1619,
  `mux` 590 to 982, and `add` 22 to 33. Each lower/upper-bound input has 16
  distinct entries; textual references change from 96 to 64 per bound vector.
- Width 4: `lt` 1280 to 256, `leq` 0 to 320, `eq` 4519 to 3975,
  `mux` 2252 to 2900, and `add` 46 to 59. Each lower/upper-bound input has 16
  distinct entries; textual references change from 192 to 128 per bound vector.

The potential path tradeoff is fewer replicated high-word ordering cones with
greater fanout and added low/carry/wrap selection after those comparisons. The
existing instruction-index muxes and first-overlap priority tree remain. An
implementation may benefit or regress after optimization and routing; only a
matched combined-candidate timing/resource run can decide that.

No full-core integration, NEMU workload, mapped LUT/FF/BRAM, physical fanout,
power, routed timing, Fmax, or board result is established by these module tests.
The option must remain unpromoted until the combined candidate passes its
independent integration and implementation gates.
