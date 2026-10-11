# Separate read/store resident prefetch tracking

This is a default-OFF cache experiment from `f722c0915784849599d7a75f71c7fd0ada724eb0`.
`--split-prefetch-tracking` requires checked store next-line prefetch. It changes no
recommended performance preset and does not select a longer candidate lifetime.

## Contract

The ordinary cache retains one globally pending candidate, at most one actual
prefetch MSHR, and its existing release owners. ON separates the shared resident
prefetch token into one read-origin token and one store-origin token. Each origin
may predict again when its own token is absent, consumed, or no longer resident.
A successful prefetch refill assigns its token using the transaction's captured
`storePrefetchOwner`; observation metadata and recycled MSHR origin bits never
control this assignment. A demand consumes only a matching full physical line
address. Two live resident tokens cannot represent the same full PA or cache slot.

The token capacity increases from one to two. The literal additional declaration
is one valid bit, 64 PA bits, and `log2Ceil(lines)` index bits: **74 bits at 512
lines**. This is a source-level estimate, not measured physical cost; constant
address bits can disappear during lowering. No cache payload, MSHR, WB, response
credit, bus port, or tag memory read port is added. The added token does require
another dynamically indexed read of the existing valid bitmap (a selection mux
over 512 valid bits in the stated profile). Opposite-token selection adds index
and full-PA comparisons in the candidate victim path. These are real combinational
costs; no zero-port/zero-logic-cost claim is made. Native/physical reports must
separately identify state, unchanged array geometry, and this selection/comparison
logic rather than report only the token bit estimate.

Victim selection first uses the original configured policy, then excludes the
other origin's unconsumed token using both actual index/way and full PA. The
candidate-set tag read already provides that PA. Store prediction remains invalid
first, then configured clean-first/LRU among eligible ways, and retains the full
existing dirty-release responsibility. Read prediction remains invalid/clean
only. A one-way cache with its sole way protected, or a read candidate whose only
unprotected victim is dirty, cancels without allocating. Resident tokens contribute
no busy/drain ownership; ordinary demands and coherence probes may evict them.
There is no permanent way pinning.

Banked tags retain the existing invalid-before-retag rule. Every replacement
invalidates a victim before installing a new tag. Each token observes that invalid
cycle, so checking resident validity needs no extra asynchronous tag read. ON
assertions reject retagging a still-valid tracked slot to a different full PA.

Per-edge token priority is old-token consumption/invalidation, then successful
refill of the captured origin, then flush. Thus an old token cannot erase a fresh
refill, and flush clears both tokens even alongside refill. Error refills install
neither data nor a token. Demand/probe/flush/error cancellation, PMP/page/next-line
authorization, posted coexistence, and C/D/E/late ReleaseAck lifetimes retain their
existing paths. OFF elaborates the original shared-token policy.

## Explicit activation

The measured executing-CPU candidate is selected with both independent switches:

```sh
mill -i IonSoC.test.runMain ooo.CpuSv39BandwidthGsimMain \
  build/gsim/split-prefetch-on16 admission \
  --split-prefetch-tracking --prefetch-candidate-cycles=16
```

This command emits the model; it does not run the CPU or synthesize an FPGA. For
the same-source lifetime-16 control, omit `--split-prefetch-tracking` while keeping
`--prefetch-candidate-cycles=16`. For the split-only counterexample, explicitly use
`--split-prefetch-tracking --prefetch-candidate-cycles=1`. Generic omission keeps
split OFF and candidate lifetime 1; existing named profiles retain their previous
choices. No recommended preset is changed. General board/export entry points
require `--store-next-line-prefetch` with `--split-prefetch-tracking`.

The recorded native ON16 export used the following exact option sequence, with
only the Python, checkout, and output paths made portable here. The full original
argv and its receipt hash are in the evidence index. Run it from the checkout root
with the pinned tools to emit this R16/PRF48/LSU2/D8 admission profile:

```sh
python3 -B fpga/next/export.py --output build/native/split-prefetch-on16 \
  --virtual-ram-load-precheck --physical-load-ingress-flow \
  --canonical-virtual-store-overlap --fetch-previous-packet \
  --prepared-store-lookahead --posted-store-merge \
  --posted-prefetch-coexistence --posted-prefetch-head-offer \
  --store-next-line-prefetch --store-prefetch-mru-insertion \
  --dtlb-write-read-reuse --translation-hit-flow \
  --ddr-write-collection-flow --line-transfer-dispatch-flow \
  --line-read-channel --independent-demand-admission \
  --prefetch-candidate-cycles 16 --split-prefetch-tracking --emit
```

Successful emission alone does not qualify mapped resources, STA, or board
execution. The existing performance preset does not enable this experiment.

The actual CPU profile is two-issue **ROB16/PRF48/LSU2/D-TLB8**, with 512-line,
two-way, 64-byte-line (32 KiB) data cache, two cache MSHRs, two writebacks, two response
entries, and DDR outstanding/write credits 4/2. It is not a ROB64/frontier fixture.
The guest processes 64 KiB twice under fixed DDR R32/B32 latency and the original
READY/backpressure service law. Original host, guest, architectural work, physical
request counts, and data/trap checks are retained. The 100 MHz throughput figures
are a simulation normalization, not an achieved-clock claim.

## Executing CPU COPY results

| Exact comparison | Sv39 ROI cycles | Sv39 clean tail | Bare ROI cycles | Bare clean tail |
| --- | ---: | ---: | ---: | ---: |
| Frozen f722, shared token, lifetime 1 | 331412 | 8149 | 284800 | 8062 |
| New source, split token, lifetime 1 | 331412 | 8030 | 284800 | 8112 |
| New source, shared token, lifetime 16 | 325901 | 8245 | 341534 | 8114 |
| New source, split token, lifetime 16 | 273627 | 8190 | 283459 | 8158 |

Each row passed the original oracle. The split-only lifetime-1 experiment provides
**zero ROI benefit** in both cases. Extending lifetime alone worsens Bare COPY
from 284800 to 341534 cycles; that regression is part of the result. Split plus
lifetime 16 improves payload throughput by 21.118% in Sv39 and 0.473% in Bare
against frozen f722/lifetime 1. Against the same-source shared-token/lifetime-16
control, splitting reduces Sv39 from 325901 to 273627 cycles and Bare from 341534
to 283459. These are narrowly qualified workload results, not a global optimum.
ROI excludes cleanup, whose independent measured tail is shown above. COPY drain
is 3 cycles in every row. The original host defines `clean_tail = done - end`
and `drain = drain - end`, so cleanup already includes drain. Inclusive payload
throughput uses `bytes * repetitions * 100 MHz / (ROI + clean_tail) / 2^20`;
adding drain again would double count it.

| COPY payload MiB/s including clean tail, at 100 MHz | Sv39 | Bare |
| --- | ---: | ---: |
| Frozen f722 OFF1 | 36.8122 | 42.6822 |
| New source ON1 | 36.8251 | 42.6749 |
| New source OFF16 | 37.4088 | 35.7502 |
| New source ON16 | 44.3550 | 42.8644 |

The passive origin observer reproduces every original output field. ON16 has
1344/32 useful read-origin prefetches in Sv39/Bare while retaining 2014 useful
store-origin prefetches in each. Relative to f722, original AXI AR/AW/R/W totals
are unchanged: Sv39 4160/2048/32832/16384 and Bare 4096/2048/32768/16384. Sv39
two-cache-owner cycles rise from 0 to 40706 and AXI read peak from 1 to 2. This
supports improved overlap; it does not imply extra MSHRs or DDR credits.

## Executing CPU READ and WRITE boundaries

These are additional original-host runs of the combined split/lifetime-16
candidate against frozen f722/lifetime 1. They do not isolate splitting at a
shared lifetime. Each cell reports its own receipt values; the first two numeric
columns are `ROI / clean_tail / drain` in cycles.

| Guest operation | f722 OFF1 | New ON16 | ROI payload gain | Inclusive MiB/s, OFF1 to ON16 |
| --- | ---: | ---: | ---: | ---: |
| Sv39 READ | 173975 / 746 / 3 | 108232 / 746 / 3 | 60.7427% | 71.5426 to 114.7020 |
| Bare READ | 157722 / 660 / 3 | 101826 / 659 / 3 | 54.8936% | 78.9231 to 121.9691 |
| Sv39 WRITE | 147186 / 15732 / 3 | 146895 / 15736 / 3 | 0.1981% | 76.7257 to 76.8611 |
| Bare WRITE | 77042 / 15700 / 55 | 77042 / 15700 / 55 | 0% | 134.7825 to 134.7825 |

All eight positive runs pass the original data, architectural-work/hash, response,
trap, and drain checks; all three read-data, final-WRITE-memory, and trap-expectation
poisons fail nonzero at their intended check. READ reduces AXI AR by 503 and R
beats by 4024 in each mode; therefore the unchanged COPY traffic totals must not
be generalized to READ. WRITE preserves its original traffic counts. Bare WRITE
has a 55-cycle drain in both variants. Per-row raw counts, hashes, oracle outputs,
and inclusive metric values are in the evidence index.

## Layered qualification and limits

The small [evidence index](split-prefetch-tracking-evidence.json) binds receipts,
artifact hashes, original source heads, profiles, and exact input checks. Commit
labels do not transfer qualification to different bytes. Production was introduced
by `ce31409957105a5fe64bb383cca05810da018595`; focused fixtures by `18195d7`,
`a8002cd`, and `f467762`. Publication checks recorded production Scala bytes
against the final source. The independent test-only `CanonicalStoreGsim.scala`
fixture addition described below is explicitly listed as a source-snapshot delta;
the CPU/cache results are not presented as fresh runs of the final publication tree.

- Constructor/CLI checks cover explicit routing, illegal combinations, and
  unchanged omitted-option presets.
- The actual cache/Mixed-home/AXI component gate passes ten OFF/ON lifetime-1
  cases: simultaneous residence/usefulness, same-set protection, dirty ReleaseAck,
  no eligible read victim, full-PA reuse/probe, failed refill, flush/refill priority,
  opposite-token consumption/refill, and demand/flush cancellation. Independent
  memory/protocol/token/policy checks include expected nonzero negative controls.
- The separate lifetime-1/16 gate preserves the original eight-beat dirty-demand
  release and acknowledgement. Lifetime 16 retains the read candidate through
  that boundary and later consumes it; lifetime 1 expires it. Demand/flush
  cancellation passes in both. This is a component result, not a CPU claim.
- The generic boundary gate passes actual one-way no-eligible-victim cancellation
  with ordinary-demand progress, and LRU1 selection that skips the opposite token
  while preserving dirty C8/ReleaseAck1. Each has an exact expected-failure poison.
- The separate canonical hit-flow fixture from `de867c9590c887336374fde9acecddfe2c8db8fa`
  preserves its four test-only source files and independent adapterflow evidence:
  93 requests, 62 certificates, and five negative controls. Its tested production
  adapter/translation-service bytes equal this publication's; the four original
  files matched before applying the patch and observation interfaces were checked
  statically. This gate used `adapterflow --skip-config`; it supplies no new CPU,
  ISA, physical, or final-tree rerun qualification.
- The executing-CPU COPY, READ/WRITE, and passive origin-observer gates have the
  separate scope and comparison controls above.
- Native OFF1/OFF16/ON16 exports pass the literal state/array census: cache scalar
  bits 8605/8609/8683, cache array bits 271876 in all three, and ten fixed storage
  groups with unchanged geometry/ports. Lifetime adds 4 scalar bits; splitting
  at lifetime 16 adds 74; the combination adds 78. Reachable board scalar bits are
  83809/83813/83887 with 708807 array bits. The added valid[512] selection and
  full-PA/index logic are real costs. Native syntax adds six ternary expressions,
  five equalities, and two variable bit selects for splitting at lifetime 16;
  these are not gate/mux counts, mapped LUTs, or timing evidence.

Mapped LUT/FF/BRAM, STA/fmax, board execution, broad workload coverage, preset
promotion, and globally optimal throughput remain unqualified. No local Vivado,
full GSIM regression, long Linux run, or bit generation was used for this change.

Focused reproduction uses the pinned tools and a fresh output directory:

```sh
python simulator/gsim/dual_prefetch_tracking.py \
  --output /tmp/valence-dual-focused --run-grant
python simulator/gsim/dual_prefetch_retention.py \
  --donor /tmp/valence-dual-focused \
  --output /tmp/valence-dual-retention --run-grant
```

The runners require a clean committed source and `VALENCE_CLOUD_ENV` pointing at
the recorded tool installation. Their receipts retain exact commands and hashes;
rerunning them requires an available serial build slot. Evidence archives remain
outside Git; the source publication includes only this document, the small index,
and source/fixture changes.
