# A1 efficiency refactor — second experimental checkpoint

2026-10-26; direct control `b556969360a262fb7efcd08e3bd1eec32f56e258`,
explicit `full-r1-m3-efficiency-refactor`. The second candidate is **that baseline
plus the frozen dirty precommit source snapshot**, not an implied later commit or a new
default preset. See [the first checkpoint](a1-efficiency-refactor.md) for the
preceding experiment and its preserved limitations.

**Measured result:** same-condition CoreMark ROI throughput improves another
**1.7630% / 1.8029% at equal clock**, with unchanged independent architectural
observations, CRCs and external traffic counts. Thirty bounded CPU cases and
82 component cases pass, including independently reviewed real prepared-Bare
store faults and canonical forwarding witnesses. This is not full ISA, Linux,
formal-equivalence or physical-release qualification.

**The single cloud normal-tile map exited successfully:** logic LUTs are
**186653→184793 (−1860, −0.9965%)**, while **FFs remain 54970**. Independent
resource review passed and the result is sealed. This is a modest roughly 1%
incremental LUT reduction, not a fundamental catch-up to Nax. No
packed physical area, depth, critical-path, Fmax or power improvement is
established by these primitive counts.

## What changed and what did not

`CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2`
(`full-r1-m3-efficiency-refactor-2`) extends the first efficiency profile with
exactly two additional true flags:

| New flag | Implemented boundary |
|---|---|
| `decodedNaturalPmp` | Project the existing decoded PMP regions into an asserted four-byte-granule view; share 53-bit beat relations and exact one-bit endpoints for naturally aligned 1/2/4/8-byte checks in buffered load preparation, guarded-natural DTA, FP memory, and both page-table walkers. |
| `preparedBareHeadStoreOperands` | Reuse the existing full-owner numerical prepared-store row for aligned ordinary Bare RAM stores; let its exact current-head owner select the whole issue payload and the existing generic backend PMP query before redundant head-time operand preparation. |

Both new flags default **OFF** and remain OFF in previous profiles. They are
independently controlled, not mutually required. The first-batch five flags and
256-entry original-index/original-training bimodal remain inherited; no gshare
or predictor redesign is included. `registeredPmpRegions` remains **false**.
The current raw CSR state still feeds one combinational region decoder; this is
not a new region-register bank or removal of a second existing decoder.

Two issue / two writeback, ROB16, PRF48, LSU4, SB2, full 64-bit generation tokens,
13 logical / 26 bank PRF reads, I/D 32 KiB two-way caches and D2/T1/R2 load-proof
capacity are retained. No ISA, FP, AMO, PMP, coherence or debug capability was
deleted. No fast-store-retirement or fast-head-load-retirement flag was enabled.
The benchmark safe-fetch interval remains **128 KiB
`[0x80200000,0x80220000)`**, not the total RAM capacity.

### Typed PMP is a restricted representation, not weaker authority

`DecodedPmpGranuleState.fromDecoded` checks each participating **active** decoded
region for ordered bounds below `2^56`, low bits `00` and inclusive end bits
`11`; its 54-bit word indices retain that complete physical domain. Inactive
entries impose no bound restriction, including empty-TOR underflow garbage.
The stateless checker has combinational latency, II1, and no storage, queue,
credit or backpressure change.

Full 64-bit request addresses remain visible. Nonzero bits 63:56 cause **no
region hit**, not unconditional denial: original M-mode/no-hit permission and
S/U-mode/no-hit denial remain. Eight-byte accesses can partially overlap a
four-byte NA4/TOR region; first-overlap priority must still deny incomplete byte
coverage even if a later region covers the access. Permissions, lock,
privilege, read/write/execute/readWrite policy and the zero-entry allow policy
are retained. The unchanged generic checker still handles its separate
arbitrary-65-bit-bound/unaligned/overflow domain; the typed checker does not
replace that contract.

Callers retain checker-only normalization, precise original address/tval,
misalignment priority, live-owner checks, epoch snapshots and accepted permission
boundaries. Preparation remains actual **read authority**, including for a load
that completes by canonical forwarding without any DTA request. Neither its
checker nor the DTA checker was deleted. Generic backend PMP, fetch/line PMP,
next-line authorization and CSR producer logic are not naturalized by this flag.
DTA previously had unshared natural endpoint relations; other callers already
shared bounds, so there is no second four-to-two-comparator saving to claim for
them.

### Bare store preparation is numerical only

The prepared row remains capacity1, minimum latency1, II1 pre-head refresh and
no empty bypass. It stores full owner and numerical address/data/size, not a
permission, privilege or physical-address certificate. A new source is eligible
only when valid, live, exact current-head, not already done, ordinary store,
current Bare mode, aligned and inside RAM. Unsupported, stale, nonhead,
misaligned, MMIO/atomic and absent-row cases keep the old staged fallback.

The early source choice does **not** depend on PMP denial, late ready/credit,
commit or recovery. It selects the held address/size/write query of the existing
**generic** backend PMP checker, using current privilege and current PMP state.
A denied selected owner stays selected and propagates its own precise fault;
it cannot disappear into an allowed fallback or use another staged owner's
permission result. Whole-payload selection keeps token, PC, data and sidecars
with that owner; Bare does not acquire virtual/canonical/load-proof authority.

Only actual `lsu.start.fire`, after registered PRF-ready, serial capacity and
`othersIdle`, commit/system/FP/interrupt/context and late exception/recovery
gates, creates request rights. Physical response, WB, retirement, cancellation,
ordering and drain boundaries are unchanged. The earlier head handoff is not
permission to issue a speculative future-head store or retire before response.

## Why these changes were selected

The b556 object was reused for passive diagnosis with the fixed original guests,
service and oracles. All four diagnostic executions reproduce the qualified
functional stdout/stderr after removing only `DIAG_` lines; no new DUT object
was built for diagnosis.

Every observed CoreMark store owner, 14421 / 14325 per seed, had one cycle from
first current-head observation to its exact staged-head descriptor. All 6120
owners per seed of the dominant list-reversal `sd` at `0x802011f0` were already
numerically prepared before head; 5911 started on their first staged-head edge.
Start-to-response and response-to-retirement were each one cycle for those
6120 owners. That evidence motivated bypassing redundant numerical handoff,
not deleting the response or architectural retirement boundary. Stage absence
can overlap serial drain or a late veto; descriptive counters cannot be added
as a saved-cycle budget.

The first-batch normal map's independent cone audit found 28855 LUTs in the
PMP named-intermediate/carry union and 51573 in the backend union, with 4343 in
their intersection. The sole load-preparation boundary was 12430 LUTs; its
inclusive five-valid-D union was 24391. These are **overlapping connectivity
conventions**, not module utilization, removable area or timing paths. The audit
preserves 1222 source-stripped `FF:unknown` cells. It also records a historical
line-zero parser defect affecting seven aliases; none belongs to the selected
seed predicates, so reported results were unaffected, not silently rewritten.

## Matched architectural performance

Same common-r2 RV64IM_zicsr ELFs, one iteration / 2000-byte CoreMark, independent
instruction/CRC/physical-memory oracle and ROI retirement boundaries at
`0x80200040` / `0x80200048`:

| Seed | b556 ROI cycles | Second candidate | ROI instructions, both | Cycles saved | Cycle reduction | Equal-clock throughput gain |
|---|---:|---:|---:|---:|---:|---:|
| performance | 386328 | 379635 | 360525 | 6693 | 1.7325% | 1.7630% |
| validation | 387078 | 380223 | 360366 | 6855 | 1.7710% | 1.8029% |

Throughput gain is `baseline_cycles / candidate_cycles - 1`, not cycle reduction.
Total cycles including the recorded setup/drain are **411910→404809** and
**412989→405730**; these totals must not be mixed with ROI cycles. Complete
retirement counts remain 384330 / 384290. Architectural hashes remain
`eb74228486f9b622` / `fe7c19b5e0fe46c4`; CRCs remain
`8e3a1fd7e714e9f5` / `8d840747e3c118f2` and final CRCs `e714` / `e3c1`.
These validate the executed instruction streams, not coverage of the full ISA.

Both variants and seeds retain 159 I requests (10008 bytes), 65 D reads
(4160 bytes), zero external D writes, 65 grants, zero release acks and seven drain
cycles. Dirty-resident flush was **not requested**. The matched service retains
independent I-read/D-read/D-write channels, 64-byte lines and 64-bit beats, first
beat +3, interval1, earliest complete line +10, FCFS/capacity16/backpressure,
read-at-accept snapshots, write-last-beat atomic commit and ack +3. The host is
a single-hart RAM home, not an external coherence-probe generator.

One candidate execution per seed included passive observations: **7259 / 7230
actual first-head direct store starts**, each with a prior real full-token row
capture; no missing capture or denied start in these benchmark runs. Those
counts demonstrate use of the new path, not individual-flag causality or an
additive explanation for 6693 / 6855 saved cycles. The two flags were measured
as one combined candidate. No general peak/sustained memory-bandwidth gain is
established by unchanged external traffic counts.

### Earlier starts did not make every local phase faster

Offline full-owner timeline analysis pairs the two runs by architectural store
retirement ordinal and exact PC sequence; full `(index,64-bit tag)` identifies
owners **within** each run, not across runs. At the hotspot `0x802011f0`, all
**6120 stores in each seed now start on their first-head edge**, versus at least
one head-to-start cycle previously. This was analysis of the existing frozen
logs, not additional DUT execution.

The same analysis exposes a local counterexample: **204 hotspot owners in each
seed**, every 30th observed hotspot store (zero-based ordinals29,59,...,6119),
change phase spacing as follows:

| Local phase for these 204 owners per seed | b556 | Second candidate |
|---|---:|---:|
| First head to accepted start | 5 | 0 |
| Accepted start to saved response | 1 | 1 |
| Saved response to retirement | 1 | 4 |
| First head to retirement | 7 | 5 |

Thus saved-response-to-retirement is **three cycles slower**, even though this
owner's complete head-to-retirement interval is shorter. Saved-response is the
LSU slot's internal accepted response, which writes its result and done state;
it is not ROB completion, retirement or an external physical-write completion.
The logs lack the
per-cycle aggregate LSU/completion/ROB/commit/recovery observations needed to
locate the extra wait, so its specific cause remains **unresolved**. Periodicity
does not prove branch recovery, WB contention or any other proposed cause.
Neither `204×3` nor the earlier-start deltas is an additive recoverable-cycle
budget. The bound source-DAG/missing-tap audit is in
`S/STORE_RETIRE_DELAY_AUDIT.md`. Some non-hotspot head-to-start intervals also
worsen; this is not a universal store-latency improvement. The sole overall throughput evidence is
the complete matched ROI reduction of **6693 / 6855 cycles**.

### Cumulative and Nax context

Relative to the original e9 ROI of 418254 / 418674, the second candidate's
379635 / 380223 gives **10.1727% / 10.1127% cumulative equal-clock throughput
gain**. Those are cumulative comparisons, not the second batch's incremental
1.7630% / 1.8029%.

Across both batches, normal-map logic LUTs are **198291→184793 (−6.8072%)** and
FFs **59318→54970 (−7.3300%)**. The second batch itself saves only **0.9965%** of
its direct-control LUTs and **no FFs**; do not present cumulative reductions as
this batch's gain. The independent normal-map qualification is recorded below.

The matched Nax program still takes 268873 / 269245 ROI cycles. The second
candidate therefore takes **1.41195× / 1.41218×** as many cycles; Nax remains
about **1.412× faster at equal clock**. FP, PMP, coherence, physical-address,
cache and debug scope differ. This is not an equal-feature PPA ranking or a
frequency-adjusted speed claim; no per-LUT efficiency ratio is inferred.

### Unchanged dependent-load and zero-gain controls

The 65-self-pointer-load guest, excluding its first warmup retirement, still
has **64 intervals of six cycles**, ROI **384**, 65 physical requests/replies,
one external D refill and four I requests during ROI. There is **no additional
second-batch gain**. The earlier 7→6-cycle improvement belongs to the first
batch; this is retirement spacing, not an isolated bare L1 latency measurement.

The original branch-free LD/MUL/DIV/W control remains **2306 work / 2332 total
cycles**, 247 retirements and 53 physical requests/replies. Its original
zero-gain result is preserved, now unchanged against b556 as well. It uses the
separately named **historical whole-line latency3** service, not the matched
CoreMark 64-bit-beat service or a Nax comparison. Both controls retain exact
observation-negative checks; all eight positive/negative stdout/stderr streams
are byte-identical to the frozen b556 controls.

## Focused validation and actual CPU witnesses

The recovered frozen build passed **37 pure tests across 12 suites**. This
includes actual `CommonA1CpuTile` policy/range elaboration, not only config-object
checks. Pure checks are not hardware execution. Full-hierarchy firtool lowering
passed the combinational-loop gate. The old profile's emitted graph passed a
bounded structural/expression comparison: source annotations and generated
assertion line numbers, helper alpha-renaming, transparent node aliases,
one-bit AND identity and the unique DTA access-input alias were explicitly
normalized. It was **not byte-identical FIR or formal equivalence**.

Exactly one successful candidate CPU model/object compilation was reused by
all nine host adapters and all **30 CPU cases: 16 positives and 14 exact
observation negatives**. No control CPU was rebuilt. The object SHA-256 is
`fb2f40d6f04efdca3a74472d532b1b224bbfa0c0ee6714ab4f9fe9efeb164761`.
The independent final runtime review binds the sealed validation summary and
checks both seeds, controls, all 30 cases and same-object lineage.

| CPU group | Cases | Scope |
|---|---:|---|
| Native supplement | 2 | 80 retirements, 11 AMOs and 8 FP retirements, plus exact result negative |
| Noncanonical supplement | 2 | Four page/high-bit subcases in the positive run, plus exact negative |
| VM basic | 4 | Four guest programs, plus manager/retire/stage observation negatives |
| Common matched cases | 5 | Smoke and two exact negatives, plus both CoreMark seeds |
| PMP faults | 8 | Seven fault guests and exact tval negative |
| Canonical forwarding | 5 | One actual stream and four reached observation negatives |
| Dependent load | 2 | Positive and exact negative |
| Historical unrolled | 2 | Positive and exact negative |
| **Total** | **30** | Finite cases, not a broad regression |

### Permission paths actually reached

- **Prepared Bare denial:** locked-NA4 and MPRV/TOR-revoked stores each selected
  the actual prepared-Bare source at accepted start after an earlier full-owner
  numerical capture. The exact held query, current generic PMP denial, precise
  cause7/tval `0x80210000`, and absence of a forbidden physical write were
  checked. These are generic upstream denials, **not typed DTA denials**.
- **Typed DTA/preparer denial:** low- and high-half partial-NA4 VM cases each
  reached one actual DTA fault and five denied-preparer samples, with precise
  cause5/original VA `0x40000000`. Each had exactly one allowed warm data read;
  do not describe them as zero total data traffic.
- **PTW denial:** actual PTW access fault and cause5/original VA, with zero PTE
  bus reads and zero physical data accesses for the denied guest.
- **FP denial:** actual prepared FP envelope and precise LSU cause5/original PA
  `0x80210000`, with no physical data access.

### Forwarding with independent read authority

The fixed virtual stream produced **49 successful stores and 57 guest loads:
48 actual canonical forwards plus nine DTA/physical reads**. All 48 forwarded
owners retired. Each witness required accepted start, complete source/load
tokens, successful same-cycle source completion, current independent read
proof/epoch and per-token absence of a forwarded-load DTA request. Four exact
observation negatives mutate data, high source tag, epoch or forwarding count
after a real forward and are rejected. They test checker sensitivity, not
mutated production RTL. This witness uses its historical VM-host service and
is not another matched performance result.

### Component qualification is separately classified

| Component model | Effective cases |
|---|---:|
| Typed decoded-natural PMP | 19 |
| Generic arbitrary-65-bit PMP | 7 |
| Shared natural/line PMP bounds | 12 |
| Typed buffered load preparation | 7 |
| Source-local advisory exclusion | 13 |
| Typed Sv39 walker | 2 |
| Typed FP memory pipeline | 2 |
| Typed certified-ingress DTA | 7 |
| Typed integer/FP/StoreBuffer/DTA chain | 8 |
| Prepared Bare numerical row/policy | 5 |
| **Total** | **82** |

The 82 effective cases are **10 positives, 29 test-only RTL-peer mutations,
36 observation mutations and seven production-contract assertion negatives**.
Expected failures must reach their exact diagnostic/marker/exit contracts;
generic nonzero exit is insufficient. Sanitizer errors and remaining owned
processes are rejected. The independent raw-CSR/byte oracle, not DUT-vs-DUT
agreement, supplies permission expectations.

Selected positive coverage: typed PMP has 224880 trials / 1124400 independent
checks; buffered proof has 11846 cycles, 59 PMP cases and 5000 randomized cycles;
walker has 41 cases / 408 raw-oracle observation cycles; FP has 320 completions,
182 faults and 782 stalled cycles; Bare row/policy has 741 cycles, 512 random
PMP tables, 33 stale-owner and 70 wrong-head cases. The FP compatibility fixture
has tag32 ports, so it does **not** establish full64 ABA coverage. The Bare
fixture uses the production row/policy/PMP with mock admission, not integrated
backend/LSU write authority; the CPU witnesses above provide the separately
bounded integration evidence. The chain includes real modules and full64
completion checking but is not itself the full CPU.

## Normal RTL resource mapping

**The single map and independent final resource review passed; receipts are
sealed.** One fresh second-candidate map uses normal `CommonA1CpuTile`, not
the observation-heavy benchmark wrapper, with the historical **256 ports /
4482 bits** and unchanged safe-fetch range. It reuses the saved first-batch map
without control rebuild, export, conversion or resynthesis. Exact
firtool1.135.0, sv2v0.0.13 and all36 Yosys/ABC/Xilinx identities are bound. The
historical pass chain is unchanged except the input path: `begin:coarse`,
comparator maps/alumacc/opt, `memory -nomap -nosat`, then `map_memory:edif` and
check/stat/JSON. There is no SAT-based SHARE pass or unsupported `-noshare`
option; historical structural OPT_SHARE is unchanged.

| Primitive measure | Frozen first-batch control | Second candidate | Change |
|---|---:|---:|---:|
| Logic LUT | 186653 | 184793 | −1860 (−0.9965%) |
| FF | 54970 | 54970 | unchanged |
| LUTRAM instances | 648 | 648 | unchanged |
| BRAM36 | 16 | 16 | unchanged |
| BRAM18 | 0 | 0 | unchanged |
| DSP | 30 | 30 | unchanged |
| MUXF | 31270 | 28460 | −2810 (−8.9862%) |
| CARRY4 proxy | 5812 | 5592 | −220 (−3.7853%) |
| SRL | 0 | 0 | unchanged |
| INV | 1962 | 1968 | +6 (+0.3058%) |
| VCC | 0 | 0 | unchanged |
| GND | 0 | 0 | unchanged |

LUTRAM is a primitive-instance count, not logic-LUT-equivalent area. The complete
17-type primitive census, including LUT1/LUT6 increases, is retained in
`M/REPORT.md` and the resource receipt. All streamed primitive counts match final
Yosys statistics; 245 `$scopeinfo` metadata cells are excluded. Normal ABI is
exactly 256 ports / 4482 bits, residual memories/memory bits/processes are zero,
and reported check problems are zero. All **32 warning messages and
multiplicities** match the saved map, as do DSP/BRAM/LUTRAM/SRL/FF parameter-mode
multisets; there are no newly reported warnings or novel modes. Mode equality
is not timing qualification.

Map launch was 2026-10-26 13:04:43 UTC. Exit0 came after **2923.9502 seconds
(about 48 minutes44 seconds)**; peak **sampled owned RSS was 4,576,452,608 bytes**
(about 4.58 GB), and owned descendants were verified empty. The 4CPU affinity,
6GiB sampled-RSS threshold, 512MiB reserve and 3600-second timeout were retained
without a stop condition. This sampled monitor is not a hard kernel memory
limit. These are host mapping costs, not hardware performance. The final reviewer rehashed all6624 admission bindings;
sealed receipts bind resource acceptance, source/class/tool continuity and cleanup.

The new mapped JSON SHA-256 is
`03ab14cba22d4ace5f622a3e2caf7a641a0d75c63a2b06f32e26c9fce035c48b`;
the saved first map is
`a1511d2584e99245b88049365285111fcaa6064f66a43422d160d396b3c2c2dc`.
This is the same-flow **cloud mapping** result, not packed implementation area
or an equal-feature Nax comparison. The combined two-flag map does not isolate
either flag's saving or attribute each removed cell to a source edit.

The exact historical depth verifier remains unavailable. A new substitute must
not be compared with cached historical depth64. Source aliases and cone reach
are not STA. No Vivado/routed timing, Fmax, power, bitstream or board result is
established by this map.

## Recovery history remains part of the result

1. Initial source review unnecessarily required registered PMP regions although
   b556 uses combinational decoded regions. The guard was removed before build;
   the oversight and correction remain recorded. Current-false and optional-true
   producer support are separately checked; the optional producer was not
   enabled to manufacture a saving.
2. The first compile and 36 pure checks passed, but actual candidate tile emission
   failed its explicit profile-policy whitelist before a model was generated.
   r1 source/compile/logs and 5196 compiled class files were retained. Exactly
   two source files changed: the precise Profile2 whitelist and an actual-tile
   positive/negative policy-range regression. One separately authorized necessary
   incremental compile and the resulting 37-test r2 pass followed. Thus **one
   CPU object does not mean only one Scala compile attempt**.
3. Walker negative originally passed unsupported `--inject-raw`; it failed before
   its target. Argument-only recovery used `--inject-raw-denied` with the same
   binary and required the original exact diagnostics. The failed attempt is
   not coverage.
4. DTA host was incorrectly built with `REGISTERED_RAW_CERTIFIED_FLOW=1` although
   both qualified wrappers use `registeredRaw=false`. Its cycle31 unrelated
   raw-register failure is preserved. Independent review admitted only host
   macro0 recompilation/link; DUT object, frozen host source, independent oracle,
   seven cases and expected diagnostics were unchanged. This is a harness-binding
   recovery, not weakening the DUT or checks.
5. Eleven shared-bounds negatives were initially mislabeled as observation
   mutations. They actually select test-only RTL peers through `io.mutation`.
   Classification-only correction yields 29 RTL-peer / 36 observation / seven
   assertion / ten positive cases, still82. Original plan/summary/report and
   review remain; no runtime or oracle expectation changed.
6. Passive b556 gate diagnosis retains its overall FAIL because concurrent,
   separately authorized typed-PMP edits changed whole-worktree status. Both
   executions individually passed, and an independent continuity review binds
   the unchanged executable/object/FIR/guest/service/oracle inputs. This was
   old-object diagnosis, not a WIP-candidate execution. A prior PATH launcher
   failure occurred before compiler launch and was resolved using the restored
   environment, without tool installation. Preparation-only field-binding and
   generator-anchor failures are also retained, not counted as hardware results.

## Evidence and restoration boundaries

Paths are repository-relative. Generated `build/` evidence is not provided by a
clean checkout. Restore the archived source/tool/object/oracle/receipt bundle,
verify hashes, then review paths before any authorized rerun. Frozen runners
contain fixed output destinations, absolute paths, affinity/resource assumptions
and one-shot guards; never rerun them in place or overwrite failed receipts.

Aliases used below:

- `V = build/second-efficiency-validation-20261026-r2`
- `P = build/second-efficiency-validation-plan-20261026-r1`
- `C = build/second-efficiency-components-20261026-r1`
- `M = build/second-efficiency-full-cpu-mapping-20261026-r2`
- `D = build/second-efficiency-performance-diagnosis-20261026-r1`
- `S = build/second-efficiency-performance-results-20261026-r1`
- `A = build/second-efficiency-current-cones-20261026-r1`

| Evidence | SHA-256 |
|---|---|
| `V/source-freeze.json` | `d2e04e1772bade28ea1f1788eaee265ae3b559e7ec55aac3268f032b3c5d3467` |
| `V/scala/compile-receipt.json` | `63a71bf67bf45810190d34f39bd2a3889a798ed12d813a600bec7058786e47ef` |
| `V/pure-specs.json` | `7e326063cc0d059c3b29ff6c4f9263d57537dc04510fdda0ac366f38cdeb62ae` |
| `V/completion-binding.json` | `35a6481b582b000d4fd901f5934f62ba8c7b93995e1535848f5780eff1203959` |
| `V/validation-summary.json` | `2a7c4bbf48cc55b1f069d8c067a69fe78e41cd5cbe230616392e1685b20a6889` |
| `P/final-cpu-runtime-independent-review.json` | `e957eeea5d03ac93fb9d6bd5843ded72f56d7a52d3c2d8254fadd9f35f0a92ea` |
| `P/cpu-witness-final-runtime-review.json` | `f094ae4b83f78606294461926ea33298b0ef4d72022b7f2336088da47f66aaef` |
| `P/single-object-host-lineage-review.json` | `4e6db31182c45208dad86a39a044cf1aeae634349681e399bdbe4767f938ab3a` |
| `P/cpu-structure-admission-r2.json` | `1a9273cd3f2d1605b57823cf30ea083efdb36b03167b5e3910af0ed9efbc6fe0` |
| `P/off-emission-independent-review-r1.json` | `db1d1bf705de6bd40c6932bc3dc5f357d17f5ca06ee91efccb3517f9a43f5f8e` |
| `C/summary-recovery-r2.json` | `7bfb60e9ef2b9931f7901e7739840c68c3351bb9879c4806916a5ddf6100df33` |
| `P/component-summary-r2-binding-review.json` | `a31568645e89003d9b9026ad9011dd9af98671931ff2017e4ba4f1e72e839062` |
| `P/components-final-runtime-review-r2.json` | `d3f23119d031327d009c49a7d91efe7594348a23f4b378116cfdc720c520aac3` |
| `P/recovery-lineage-r2.json` | `d58e15ecdf4a088d3380e7f52de628d3af3291b9376d9c0a0efafaa44392465e` |
| `S/REPORT.md` | `f3f65f2f7932d426eaea12b183697aa49209b9eb29e6578e8684e8ed1908891e` |
| `S/report-manifest.json` | `1c6471fd6ad36bc92ffbefd864944e89ddb1c460cfa9979963a2789b4a0af1e2` |
| `S/STORE_RETIRE_DELAY_AUDIT.md` | `2dad4200cd07798d7091b98dadbcacf579899e38665770797f1f2d09d5912e38` |
| `S/comparison.json` | `25e6f3d54e6a66c54c7087a2a2ad08aff2ff55454c875e25302a6012cc453c8e` |
| `S/additional-evidence.json` | `a8401b65ec113df268077797766e6e6a3ebdb07a28456bd2e2dc3bbed526f6f2` |
| `P/offline-store-pair-independent-review.json` | `30a4b45acf8404307af4abac0085daa05da1707c0056912b962cbcee1773c139` |
| `D/report-manifest.json` | `54e45c52a03970be4bd8979442b8c93b62f661949af37597b14953998e467975` |
| `A/manifest.json` | `26591a89808bac12bad2b0bda405cb993f15b4b5afb7c4a2465dbdb3a3cba3e9` |
| `M/receipt.json` | `bb8e1ddd4da206fe827fb3b847b7b3ba581d481c2b21aea2df1e07b8c66dc8f5` |
| `M/resource-receipt.json` | `71eae136140980728fa8f98167e8783e5fc6f9a0fec7e445704929ba40bab3f7` |
| `M/manifest.json` | `ff79c6b174c28b96f386ef6ee24fd314486820d4fec922adcf62d5a5d3f6ec24` |
| `M/candidate/mapped.json` | `03ab14cba22d4ace5f622a3e2caf7a641a0d75c63a2b06f32e26c9fce035c48b` |
| `M/REPORT.md` | `90e29ace2454ecdf86587d4c7b4e586bb24b2099c93e5328475cd3f4e07a2ba0` |
| `P/second-map-final-resource-independent-review.json` | `f3aeef95a94dfaada928b047babbcbc4181c46a0d941f6c01571d5a7015a281e` |
| `M/source-manifest.json` | `eb9cdfc109491d638d0133013f02f77264db4dea8d304aad582a2fd697531907` |
| `M/compile-binding.json` | `44a4a1357140de5defbcf55f86976cbc4119780f7c06f3e0a877bd796ef7adde` |

`P/component-summary-r2-binding-review.json` explicitly connects the corrected
82-case summary to the independently checked execution evidence; the earlier
runtime review's original-summary hash must not be silently relabeled.
`V/validation-summary.json` binds each CPU receipt and both matched results.
`M/source-manifest.json` binds 1,116 compilation source/resource inputs, not
documentation bytes. The recovery archive's separate full-source snapshot retains
the earlier documentation bytes; later documentation/commit continuity needs its
own receipt.
A preparation plan's old pending status is historical, superseded only by the
specifically completed and bound review, not a claim that every gap disappeared.

`M/receipt.json` records the terminal successful one-map result and binds its
resource receipt and independent review. `M/manifest.json` seals the complete
mapping evidence, including the final report. The measured input is the
**precommit snapshot**; documentation changes made after sealing are not part of
that measurement. Any later commit must be connected by a separate continuity
receipt, not relabeled as the commit on which these tools originally ran.

### Recorded entrypoints for a separately authorized restoration

1. Restore verified tools using the archived environment/init receipt. Inspect
   `P/reusable-inputs.json`, `V/source-freeze.json`, recovery lineage and the
   component freeze. The Scala receipt entrypoint remains
   `python3 fpga/common/scala_compile_receipt.py --out <fresh-batch>/scala`.
2. Pure suites and component cases are listed in `P/validation-plan.json`,
   `P/components-plan-r2.json` and `C/freeze.json`; actual source compile receipt,
   `runClasspathEntries`, command receipts and recovery bindings determine the
   qualified inputs. Do not infer successful runtime from an emitter or a pure
   configuration check.
3. With that exact verified classpath as `CP`, the distinct entrypoints are:

   ```sh
   java -cp "$CP" soc.core.ooo.EfficiencyRefactor2BenchmarkGsimMain <fresh-benchmark-dir>
   java -cp "$CP" platform.CommonA1RebuildTileMain \
     full-r1-m3-efficiency-refactor-2 <fresh-normal-dir> 0x80200000 131072
   ```

   These are benchmark and normal-tile emission, respectively, not simulation
   passes or synthesis results. Default-OFF comparison must use its documented
   bounded graph normalization, not a new ad hoc text filter.
4. Review `P/run_batch.py`, `P/build_cpu.py`, `P/cpu_hosts.py`, the admission
   receipts and actual per-command JSON. Components use `C/run_components.py`
   and separate exact-case/finalizer receipts. Keep one candidate CPU object,
   the nine qualified host adapters, independent oracles, sanitizer settings,
   reached negatives and exact cleanup contracts. The two recovery paths are
   explicit exceptions, not permission to rerun failed attempts in place.
5. Normal mapping requires its separate explicit admission after validation,
   exact frozen export/tool/flow inputs and one combined normal map. Its
   preparation scripts and guard are restoration references, not authorization
   to launch another map. Never run a broad regression, Linux or physical flow
   as an undocumented supplement.

**GSIM only; never invoke or fall back to Verilator.** This documentation
was prepared by read-only source/receipt inspection and arithmetic, without new
builds, hardware simulation, synthesis, local-machine work or public publication.

## What remains unqualified or deferred

Finite tests do not prove arbitrary simultaneous permission/context/exception/
replay/high-tag-ABA interleavings. Cross-epoch actual forwarded faults remain
unestablished: CSR serialization can drain that window. No illegal W-only CSR
state is fabricated to claim such coverage. Original eight held-WB padding
cases remain **INCONCLUSIVE**; the first batch's successful ordinary Bare
held-WB→AGU numerical-capture witness does not establish active-VM, early/partial
store, fault/context or high-generation intersections in that held window.

Global RF port redesign, compact leases/token narrowing, frontend RAM conversion,
gshare, ownership-protocol changes, widened capacities, permission-check removal
and faster retirement are not delivered here. Typed natural PMP is now
implemented only at the caller scope above; it is not a wholesale generic PMP
replacement. No default promotion, full ISA/Linux certification, external
coherence-probe validation, physical-release claim, local rerun or public push
is implied.
