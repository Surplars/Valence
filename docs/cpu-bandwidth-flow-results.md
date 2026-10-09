# CPU physical-ingress flow: source-matched executed-board result

Checkpoint: 2026-10-09. Baseline source `e8520ab23fb31cd03566787056d5e937e1aca7c3`
plus the opt-in queue-flow patch. The physical-ingress flag alone differs in this
comparison. Both virtual precheck and prechecked queue flow are off. No default
has changed and no routed FPGA timing, mapped area or physical-board gain is claimed.

## Measured result

The selected GSIM BoardSoc executes the same six frozen guest binaries on both
sides. Each guest warms its exact loop before four timed passes. Payload is useful
bytes; copy does not count its source read and destination write twice.

| Case | OFF kernel cycles | ON kernel cycles | OFF / ON kernel MiB/s at 100 MHz | OFF / ON complete cycles | OFF / ON complete MiB/s |
|---|---:|---:|---:|---:|---:|
| Read 4 KiB | 6,195 | 5,189 | 252.220 / 301.118 | 6,782 / 5,775 | 230.389 / 270.563 |
| Write 4 KiB | 9,801 | 9,801 | 159.423 / 159.423 | 12,526 / 12,527 | 124.741 / 124.731 |
| Copy 4 KiB | 15,636 | 14,353 | 99.9296 / 108.862 | 18,310 / 17,026 | 85.3359 / 91.7714 |
| Read 8 KiB | 12,339 | 10,313 | 253.262 / 303.016 | 12,926 / 10,899 | 241.761 / 286.724 |
| Write 8 KiB | 19,529 | 19,529 | 160.018 / 160.018 | 24,392 / 24,390 | 128.116 / 128.126 |
| Copy 8 KiB | 31,252 | 28,689 | 99.9936 / 108.927 | 36,063 / 33,501 | 86.6539 / 93.2808 |

Complete includes the actual drain and cache-flush tail. Timed read/write data
miss counters are zero. The four/eight KiB read kernel improves 19.39%/19.65%;
copy improves 8.94%/8.93%; the write kernel is unchanged. The source-matched OFF
cycles exactly reproduce all six earlier hot replay cases. This does not extend
the earlier model's source qualification to other workloads.

## What changed in the measured pipeline

Every architectural hot read has exactly six OFF and five ON start-to-result
cycles. The accepted start enters the registered request FIFO on the same edge;
FIFO-to-physical acceptance is three versus two cycles. Physical cache service,
registered return buffering and LSU result production each remain one cycle.

At 8 KiB, full-slot completion/replacement overlaps 4,084 OFF and 4,092 ON cycles.
The usual launch gaps change from alternating 1/5 to 1/4 cycles. Physical
outstanding peak remains one; both actual LSU owners are used. This is a real
upstream owner-residency improvement, not an increase in D-cache service rate.

Two owners at five cycles have a local all-hit read supply roof of 305.176 MiB/s,
versus 254.313 at six cycles. The observed 303.016 MiB/s is 99.29% of that new
configuration-local roof. The 64-bit one-transfer-per-cycle interface roof is
762.939 MiB/s; neither figure is a universal 100 MHz CPU limit. A different owner,
return or issue architecture can change the lower roof.

Write still has one live LSU/StoreBuffer owner, two-cycle start-to-result and
mostly four-cycle launches; the two-entry StoreBuffer never fills. It remains a
separate serial head/retire supply bottleneck. See `cpu-store-supply-next-plan.md`.

## Speculative traffic is included, not hidden

The faster read path admits four extra physical reads per timed read case, each
at exactly `sourceBase + HOT_BYTES`. The original untimed kernel already warms
that cache line; no new ELF, artificial cache injection or adjusted latency was
used. Each is an ordinary aligned cached RAM LD. The full allocation token is
canceled before physical issue, drains through its physical and LSU replies,
produces no accepted LSU completion, and never retires. Their returned data are
checked against the independent memory map. For 8 KiB this address aliases the
first destination word, so the expected value is its actual independently
initialized value, not an assumed zero.

Read 4 KiB therefore performs 2,052 physical reads for 2,048 useful loads; read
8 KiB performs 4,100 for 4,096. The 32 extra bytes remain in raw request counts,
cycle time and miss checks, and are excluded from useful payload. The timed read
cache footprint includes one additional 64-byte guard line. Copy has no extra
reads in these cases. The old output field `read_physical_minus_architectural`
is source-buffer-only and remains zero; it must not be interpreted as total
speculative traffic. Use `timed_physical_reads - architectural_loads` (four for
these ON read cases), `speculative_guard_reads` and `speculative_guard_bytes`.

The old r2 observer rejected the first guard request as nonbuffer traffic. That
failed receipt and a diagnostic trace are preserved. The r3 revision bounds the
admission to this exact guard address and proves its complete token history;
it does not waive arbitrary out-of-buffer accesses. Four embedded negatives
remove cancellation/reply or forge completion/retirement. The independent
reviewer additionally exercised the extracted admission and lifetime checks;
those isolated host-oracle mutations are not claimed as live RTL mutations.

## Evidence and identities

- Six-case A/B: `build/gsim/cpu-bandwidth-flow-board-r3/receipt.json`, status
  `PASS_SOURCE_MATCHED_CPU_FLOW_BOARD`, SHA-256
  `c3ecce8af87ec1bd50347005690e42e4cd1ada1ac26bbe760ef541287e7a080b`.
- Executed models: `fpga-next-board-cpu-flow-off-r1` and `...-on-r1`, each with
  its own source inventory, generated model/object hashes and RV64GC smoke plus
  injected-failure receipt. r3 verifies their exact source inventories match.
- Final hot driver SHA-256:
  `d5844bc43cd39f6a8be1a081a5a4756fc12457bc94c814d131d4f546ec130054`.
- Production adapter SHA-256:
  `753ddcb25817f5873f253b196ee6bcaa6d96b81bff6b419fe0289db08635b1df`.
- Production OooParams SHA-256:
  `d94855fb7d2415e389445a5daa6443aa51ba2dfa3e0c0e47735fa0a49f3da376`.
- Every case checks architectural instruction/load/store counts, identical
  retirement PC trace, accepted address/data/mask, full-token route/ownership,
  signature and final backing bytes. Seven route/authorization/token corruption
  runs are rejected on each side, in addition to each guest's oracle mutations.
- Physical adapter proof: `physical-ingress-flow-r1` and the stronger same-model
  `physical-ingress-flow-order-upgrade` proof. Held-valid acceptance-time context
  proof: `physical-ingress-held-context-r1/receipt.json`, SHA-256
  `302ce1f989410cefe7f203e992140df79410744e73a7f76c50a403d0f92c9717`.
- Independent production and oracle reviews are preserved in
  `build/cpu-ingress-independent-review-20261009` and
  `build/cpu-ingress-oracle-review-20261009`.

All performance figures are measured model cycles converted using an assumed
100 MHz clock and the frozen host AXI timing model. The six-case result itself
is not NEMU qualification. Exact-model NEMU, representative cold/over-cache/chase/Sv39/protection/atomic
extensions, full selected RTL export and structural comparison are qualified
separately below. Routed timing, mapped area, physical-board measurements and
combined CPU+DMA-enabled integration remain unqualified. Neither native RTL
counts nor functional simulation establishes those physical results.

## Exact-model NEMU extension

`build/gsim/cpu-flow-board-nemu-r1/receipt.json` completed
`PASS_SOURCE_MATCHED_BOARD_HOT_NEMU`, SHA-256
`18f907a4507fe89612a207c685d19a092344af8d04e39158156563d5ed3af547`.
All twelve OFF/ON cases passed. The independent reference checked 123,444 guest
retired PCs individually and all 32 GPRs after 81,294 complete retirement edges,
including 42,150 dual-retire edges. GPR snapshots are after the entire edge, not
between its two lanes. Including the fixed ROM prefix, 2,602,560 GPR values were
checked. Each case also compared 4,194,368 final RAM bytes, including executable,
buffer, signature and intervening memory.

ROM/reference initialization follows independently specified bootstrap semantics;
no mismatched architectural state is copied from the DUT or resynchronized.
Six PC/GPR/memory corruption runs fail with their required independent mismatch
anchors. All twelve original hot result lines are unchanged. This strengthens
the physical integer benchmark proof; it is not an exhaustive ISA, privilege,
FP or Linux qualification. The exact existing NEMU binary/configuration/source
provenance and the passive generated-model observation fields are recorded in
that extension, without rebuilding NEMU or either hardware model.

## Source-only fresh replay

The current runner no longer requires the historical recovery archive. With the
repository's pinned toolchain already available, it builds six portable guests
from tracked assembly/linker sources, then fresh source-matched OFF/ON models:

```sh
# Replace these placeholders with already verified existing tool locations.
export VALENCE_CLOUD_ENV=/path/to/verified/cloud-env
export VALENCE_GSIM_SOURCE=/path/to/verified/gsim-src
export CHISEL_FIRTOOL_PATH=/path/to/verified/firtool-1.135.0
source scripts/cloud/env.sh
python3 -B -m unittest discover -s simulator/gsim -p test_cpu_hot_fresh.py -v
python3 -B simulator/gsim/cpu_bandwidth_flow_board.py --tag fresh-local
```

To build/verify only the portable guest bundle, with no model or simulation:

```sh
python3 -B simulator/gsim/build_cpu_hot_bandwidth.py --out build/gsim/hot-guests-local
python3 -B simulator/gsim/build_cpu_hot_bandwidth.py --verify build/gsim/hot-guests-local/manifest.json
```

Explicit `--guest-manifest` supports relocation of a source-matched guest bundle.
Explicit `--model-tag` may reuse only complete models whose exact current source,
selected geometry/options, pinned toolchain and every artifact hash match. The
default never searches for an approximately matching model. Historical
`--hot-receipt` remains an archive-dependent compatibility input.

The fresh two-stage guest build uses a stable `guest.o` FILE symbol. Two builds
in distinct directories produced identical object, ELF, binary and symbol-header
hashes and identical full manifests. All six binary/header hashes match the
historical r3 guests; ELF hashes differ because the old one-step GCC build used
random temporary FILE symbols. This is a new reproducible ELF identity, not a
claim that the historical ELFs were identical. Thirty-five source-only argument,
relocation and drift-rejection tests pass. The future observer labels source-only
and total physical-read excess separately; the frozen r3 counters stay unchanged.

## Representative and current-access protection gates

The exact same two model objects passed ten representative positives, ten explicit
negative controls and four inline backing-corruption checks. Receipt
`build/gsim/cpu-flow-representative-r1/receipt.json`, SHA-256
`523918aa2b724a898733e4f92eee8bc5605f84e12c285a2bcfa065f2804c942e`.

| Representative ROI | OFF cycles | ON cycles | Throughput change |
|---|---:|---:|---:|
| 64 KiB, three-pass scalar read | 279,718 | 268,971 | +4.00% |
| 64 KiB, three-pass write kernel | 344,151 | 344,151 | unchanged |
| Write flush tail | 17,754 | 17,754 | unchanged |
| 64 KiB, three-pass copy kernel | 641,791 | 627,214 | +2.32% |
| Copy flush tail | 9,217 | 9,215 | two cycles shorter |
| Physical dependent chase, 3,072 hops | 231,188 | 227,973 | +1.41% |
| Independent lines, 64 KiB / three passes | 114,346 | 112,706 | +1.46% |
| Sv39 warm independent | 4,422 | 4,422 | unchanged |
| Sv39 cold pages | 512 | 512 | unchanged |
| Sv39 dependent chase | 2,311 | 2,311 | unchanged |

The 64 KiB stream exceeds the 32 KiB cache. Its read miss count is 3,073 on both
sides, and dependent physical chase has 3,072 misses; the hot-cache gain must not
be extrapolated to those workloads. Prefetch retention stays at the selected
one-attempt policy on both sides. Kernel and actual flush tails are separate.
The physical steady driver checks independent backing and chain values and
per-ROI retirement counts, but does not produce an architectural retired-PC hash.

Sv39 runs have identical signatures, global retired-PC trace and lane-exact ROI
traces, a verified precise page-fault tuple and one UART LSR read. Their outstanding
cancellation counter is zero; this receipt is not evidence of cancellation after
an accepted outstanding memory operation. That ownership behavior is covered by
the separate directed backend/adapter and hot full-token proofs. Execute-denied
PMP is checked with the real grant/revoke/grant fetch guest. The fresh RV64GC
smoke covers its actual AMO/LR/SC, privilege and context cases; generic printed
labels from the shared fetch harness are not treated as additional FP coverage.

A separate new actual-CPU fixture closes denied **data** PMP, including MPRV.
`build/gsim/cpu-flow-data-pmp-r1/receipt.json`, SHA-256
`087a383103fe77482cd356c7977ffa802223b74ee7fa5f8f0ff6a57905b019cc`, passed
OFF/ON with six trap/data/count corruption negatives. An unlocked high-priority
8-byte NAPOT region denies an S-mode load and an M-mode MPRV=S load, each with
exact cause 5, original PC and tval. Neither faulting load retires or emits a
forbidden physical request. Two explicitly allowed M-mode reads and a neighboring
S-mode read succeed. The controlled S-mode ECALL is the third required trap.
Both runs retire the identical 108-instruction trace and fully drain the checked
signature/backing values (1,992/1,989 total cycles). This is an independent
assembly/host-oracle fixture, not a NEMU privilege-compliance claim.

## Fresh replay and native structural freeze

The fresh-source guest path executed all twelve paired cases and all route
negatives using explicitly verified model reuse. Its receipt is
`build/gsim/cpu-bandwidth-flow-board-fresh-r1/receipt.json`, SHA-256
`d47b8c921064acabab71b7d752785cc9c5901deb4ec7df21ab71a29e1b43ef31`.
All prior cycles, retirement traces and useful-byte results match r3 exactly.
The source-only mode defaults to building new models; that default construction
uses the already separately exercised `fpga_next_board.py` builder. This fresh
receipt truthfully records model origin as explicit reuse, not a new model build.

After those consumers finished, only the FPGA export CLI allow-list/options were
extended in `FpgaNextMain.scala` and `fpga/next/export.py`; production Scala and
the actual GSIM emitters were unchanged. Old model receipts are not rewritten to
claim that this unused export-entrypoint change was present earlier.

All four full selected production RTL exports passed: physical OFF/ON, and
prechecked OFF/ON with virtual precheck held enabled. The final four focused
Scala configuration tests and negative prechecked-without-precheck CLI gate pass.
`build/cpu-flow-native-r1/comparison.json`, SHA-256
`423fba9e1ea52e0f9f9ba7aeb30e9a89fc565ca92065a6405c7a24c681aa684d`, binds
the exports and selected storage censuses.

| Isolated flag | SV modules per side | Changed module | Adapter scalar registers / bits, both sides | Adapter scalar wires OFF → ON |
|---|---:|---|---:|---:|
| Physical ingress | 262 | DataTranslationAdapter | 14 / 184 | 65 / 501 bits → 69 / 505 bits |
| Prechecked flow | 264 | DataTranslationAdapter | 21 / 1,277 | 71 / 1,591 bits → 95 / 1,875 bits |

Only `DataTranslationAdapter.sv` changes within each pair. Ten fixed RAM/storage
groups remain byte-for-byte identical, and neither bypass adds literal register
state. The virtual precheck unit itself is a different baseline and has a cost;
it must not be conflated with the isolated queue-bypass delta. Wire declarations
are only a compact source-structure proxy. These are not mapped LUT/FF/BRAM
counts, synthesis area estimates, timing depths or a routed 100 MHz result.
The new forward mux/authorization cone still requires implementation timing
validation before selecting a board default. Combined CPU+DMA-enabled integration
is a separate later qualification and is not established by these CPU-only flags.
