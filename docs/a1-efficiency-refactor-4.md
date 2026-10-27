# A1 efficiency refactor — fourth experimental candidate

**2026-10-27: matched GSIM validation and the normal-tile resource map passed
independent review and were sealed. This remains a default-OFF experimental
option, not a promoted baseline.** The measured source is a frozen dirty candidate on
`a419511f8d98ea865a6dc82cb99318496d45313c`, not an implied later commit.
See [the third checkpoint](a1-efficiency-refactor-3.md).

The experiment removes one avoidable request-capture edge for qualified,
already-registered ordinary physical loads, while retaining the checked register
and the existing certified-load path. It improves the tested dependent-load
latency and both CoreMark workloads. It **does not improve the measured sustained
independent-load bandwidth**, and no achieved frequency or physical-area result
is established. The independently reviewed map reports **2.4853% more logic LUTs**
and **21.0641% more MUXF primitives**, with FF/RAM/DSP counts unchanged. This is
a latency-versus-resource trade, not a free or universally better implementation.

## Configuration and preserved contracts

`CommonA1RebuildProfile.FullR1M3EfficiencyRefactor4`
(`full-r1-m3-efficiency-refactor-4`) copies the third configuration with exactly
one additional default-OFF flag: `coexistingPhysicalLoadIngress`. Earlier profiles
keep it OFF. The legacy `physicalLoadIngressFlow` remains OFF, with its old guards
unchanged; this is not a relaxation of that mutually exclusive legacy feature.

Two issue/two writeback, full 64-bit owner/generation authority, precise traps,
PMP, FP, AMO, coherence, caches and debugging remain. The ROB completion banking
from the third candidate is retained. This batch does not change the PRF/ROB/LSU
response boundaries, StoreBuffer scheduling, return credits or physical-memory
service law.

Incoming and checked remain the existing two-entry non-flow queues. Translated
storage, outstanding translation ownership and the backend registered request
FIFO remain unchanged. The direct route requires an empty incoming queue, no
older translated result or waiting page walk, and real incoming occupancy credit.
Upstream ready remains **old incoming occupancy-ready**, independent of bypass
eligibility, checked readiness and physical/cache readiness. A full queue cannot
borrow a same-cycle dequeue slot.

The classifier operates on the final port after integer/FP arbitration. Eligible
requests are ordinary reads: not virtualized, prechecked, stores, atomics or
uncached; no enabled posted/canonical/frozen valid sidecar; legal Bare/M context;
natural alignment, exact byte mask, and the complete nonwrapping RAM interval.
Stable authorization/context and no current flush/change are required. In
particular, `!virtualized` alone would be insufficient because prechecked VM
requests can also have that bit clear.

A qualified request can enter checked on the upstream acceptance edge instead
of first entering incoming. Checked still registers the request before physical
arbitration. If checked is blocked or the request is ineligible, acceptance goes
**once**, with original payload/context, through the old incoming path. Older
owners retain priority. Candidate assertions enforce exactly one accepted sink
among incoming enqueue, ordinary physical pass and certified pass, along with
payload, ownership and no-competing-handshake constraints. The old two-way
assertion remains when the flag is OFF. No new storage or outstanding credit is
introduced; the target initiation interval remains one, not more than one request
per cycle.

### Authorization is inherited, not invented by classification

Integer requests pass live PMP and LSU exception/forward rejection before the
registered request queue and StoreBuffer. FP uses a distinct live-PMP followed by
`LoadStoreUnit(registerStart=true)` path, then the drained FP epoch mux. Both are
registered producers, but FP does not traverse the integer FIFO.

Ordinary physical/identity requests already depend on that upstream authorization;
the DTA fallback does **not** independently recheck their PMP permission. A rejected
shortcut classification is therefore not a newly permission-denied operation.
Do not describe fallback as enforcing a fabricated direct-path PMP denial.
Certified/prechecked traffic retains its existing descriptor, PMP, epoch and shape
checks. Actual integer and FP PMP-denied CPU cases establish zero downstream data
reads with the expected precise exception; arbitrary unauthorized standalone DTA
injection would violate the producer precondition rather than prove security.

## Current-epoch verification

All numbers below come from the new retained execution logs, not the third
candidate's incomplete historical runtime archive.

| Check | Result and qualification |
|---|---|
| One frozen Scala compilation | PASS; 1123 source/resource inputs, 5276 compiled classpath files |
| Pure configuration/elaboration | 44 tests / 13 suites PASS |
| Default-OFF control | Old 5263-file compiled classpath was preserved and used to emit profile-3 CHIRRTL before the new compile; normalized graphs match except one assertion diagnostic source-line change, 153→160 |
| Whole-hierarchy structure | Candidate CPU and DTA firtool loop/lowering checks exited 0 |
| DTA components | 11/11: two positives, seven observer negatives, two actual production RTL-assert negatives |
| CPU | 30/30: 24 positive executions, six candidate observer negatives; eight host types per reusable model |
| GSIM model compilation | Each control/candidate whole CPU object generated and compiled once, sequentially; component candidate compiled once, control object reused through host-only repairs |
| Runtime cleanup | Expected terminal codes, output markers/hashes, ASAN/UBSAN and empty owned-process cleanup independently checked |
| Normal FPGA resource map | Exit 0; final independent review and sealing passed |
| Physical frequency/area/power | Not measured |

GSIM is the sole hardware simulation flow. The restored pinned GSIM plus known
initialization-span fix passed its separate tiny ASAN/UBSAN qualification; that
qualification is not itself CPU validation. No Verilator, full regression, Linux
boot, board run or new Nax run was performed.

The component oracle uses independent PTE/PMP rules and an ordinal/full-payload
owner ledger. Fifteen matched scenario traces retain equal functional traffic.
Coverage includes stalled spill, old occupancy/no borrowed credit, older
translation owners and a specifically exercised walker-waiting boundary. The
seven observer mutations are not seven production RTL failures; two separate
actual RTL-assert negative executions cover that distinct category.

CPU cases include real integer/FP PMP denials, successful FP execution, VM and
noncanonical paths, full-token forwarding, short smoke, dependent and independent
loads, and two CoreMark seeds. An optional direct FP route observation was
optimized away in both generated models. No accessor or constant-zero witness was
invented to claim an FP route hit; successful/denied FP architectural coverage is
retained without that extra claim.

## CoreMark: distinguish ROI and whole-work metrics

Same fixed RV64IM_zicsr guests, architectural/CRC oracle, one iteration, 2000-byte
working set and memory-service law were used for both profiles. Equal-work speedup
is `control cycles / candidate cycles - 1`; cycle reduction is a different number.
These are cycle comparisons under an equal-clock assumption, not measured wall-time
or achieved-frequency speedups. This short experiment is not an official CoreMark
score.

| Metric | Performance seed | Validation seed |
|---|---:|---:|
| Whole-work cycles, control → candidate | 404802 → 384017 | 405723 → 384639 |
| Whole-work cycle reduction | 5.1346% | 5.1966% |
| Whole-work equal-work speedup | **5.4125%** | **5.4815%** |
| ROI cycles, control → candidate | 379635 → 359572 | 380223 → 359864 |
| ROI cycle reduction | 5.2848% | 5.3545% |
| ROI equal-work speedup | **5.5797%** | **5.6574%** |
| ROI retired instructions, unchanged | 360525 | 360366 |
| ROI IPC, control → candidate | 0.949662 → 1.002650 | 0.947775 → 1.001395 |
| Total retired instructions, unchanged | 384330 | 384290 |
| Total cycles including 7-cycle drain | 404809 → 384024 | 405730 → 384646 |

Both seeds preserve their architectural hashes and CRCs:
`eb74228486f9b622` / `8e3a1fd7e714e9f5` and
`fe7c19b5e0fe46c4` / `8d840747e3c118f2` respectively.
All eight **reported external memory counters** match in each comparison:
159 instruction requests / 10008 instruction bytes, 65 data reads / 4160 data
read bytes, zero data writes / write bytes, 65 grants and zero release acks.
Dirty-resident flush was not requested. The host does not provide a complete
per-request trace of every internal/speculative physical read, so equal external
counters must not be expanded into a claim that all such internal traffic is
identical.

## Dependencies improve; sustained supply does not

| Workload/metric | Control | Candidate | Interpretation |
|---|---:|---:|---|
| 65 dependent loads: 64 warm retirement intervals | all 6 cycles | all 5 cycles | Verified one-cycle dependency interval reduction |
| Dependent-load ROI | 384 | 320 | 16.6667% fewer cycles; 20% equal-work ROI speedup |
| Dependent whole-work cycles | 443 | 378 | 14.6727% fewer cycles; 17.1958% equal-work speedup |
| Dependent total including drain/inspection | 482 | 417 | Keep this boundary distinct from work and ROI |
| Independent-load ROI | 90 | 90 | **No improvement** |
| Independent physical-request span | 105 | 105 | **No sustained bandwidth improvement** |
| Independent whole-work cycles | 149 | 148 | Only a one-cycle startup saving |
| Independent total including drain/inspection | 196 | 196 | **No total-cycle improvement** |
| DTA component: 64 supplied requests | 72 | 71 | First physical offer 2→1; acceptance/physical span stays 64 and II stays 1 |

The dependent guest preserves 70 retired instructions, architectural hash and
65 physical requests/replies, with 9 I requests / 408 bytes and one 64-byte data
refill. Local bypass hits or its 20% dependency speedup are not substituted for a
whole-CPU or general bandwidth improvement. The successful native CPU case also
improves 327→323 cycles, while other unchanged/zero-gain cases remain in the logs.

### Cumulative reference and existing Nax comparison

Against the earlier e9 ROI references 418254 / 418674, the present 359572 / 359864
represent cumulative equal-work ROI speedups of **16.3200% / 16.3423%**. They are
not this batch's incremental gains and do not establish a frequency-adjusted gain.

The previously recorded matched Nax program used 268873 / 269245 ROI cycles.
Valence/Nax cycle ratios are now **1.33733 / 1.33657**; Nax used about 25.22% /
25.18% fewer cycles in that recorded same-program comparison. This is arithmetic
against retained earlier results, **not a newly executed Nax measurement**.
FP, PMP, coherence, address width, cache geometry and debug/boundary scope differ,
so it is not an equal-feature PPA comparison or an area-efficiency ranking.

## Normal mapping: measurable resource cost, timing still unverified

The completed map uses normal `CommonA1CpuTile`, not the observation-rich GSIM
wrapper; the third baseline's xcup recipe and pinned tools; no baseline
resynthesis or SAT-sharing substitution. ABI remains 256 ports / 4482 bits and
all 60 memories retain their geometry. The completed attempt reports exit 0,
1902.922 seconds, peak sampled owned-group RSS **4,435,226,624 bytes**, check 0,
no residual generic memories/processes, and verified empty owned-process cleanup.
Its 32 warnings match the third baseline. Final independent review confirms
these terminal receipts, exact source/tool/ABI binding and primitive counts;
the result is sealed.

| Primitive category | Third baseline | Fourth candidate | Delta |
|---|---:|---:|---:|
| Logic LUT | 177202 | 181606 | +4404 (+2.4853%) |
| FF | 51918 | 51918 | 0 |
| LUTRAM primitive instances | 698 | 698 | 0 |
| MUXF | 25636 | 31036 | +5400 (+21.0641%) |
| BRAM36 | 16 | 16 | 0 |
| DSP | 30 | 30 | 0 |
| CARRY4 | 5592 | 5596 | +4 |
| INV | 1966 | 1979 | +13 |

LUTRAM remains 366 RAM32M16 plus 332 RAM64M8 instances. Compared with the original
e9 reference, the fourth candidate has **198291→181606 logic LUTs (−8.4144%)**
and **59318→51918 FFs (−12.4751%)**. These are cumulative counts across four batches,
not this batch's savings: the fourth batch gives back some of the third batch's
logic-resource reduction in exchange for lower tested cycle counts.

The +4404 LUT and +5400 MUXF differences are **whole-design mapped results**.
ABC can restructure and share logic across module boundaries; these totals must
not be attributed one-for-one to an exclusive local shortcut cone without
additional evidence. Unchanged source storage geometry does not imply unchanged
logic or physical cost.

The candidate therefore stays default OFF and the third profile remains a useful
lower-resource control. The tested ROI speedups of 5.5797% / 5.6574% and whole-work
speedups of 5.4125% / 5.4815% assume equal frequency. A sufficiently lower achieved
clock could cancel them. No routed Fmax, timing slack, packed area, path depth or
power was measured, and the MUXF increase is not itself a quantified timing
regression. The longer classifier-to-checked logic requires physical timing
qualification before calling the candidate a superior implementation. A loop-free
design is not a timing proof.

LUTRAM instance count is not equivalent logic LUT area. Do not subtract RAM macros
one-for-one from logic LUT counts or combine these resource categories into an
unsupported total-area percentage.

## Retained failures and recovery

1. Initial component-host C++ compilation failed on one mixed-type `auto`
   declaration. Revision r2 only split declarations and reused the successful
   control DUT object.
2. r2's mixed scenario missed its `ordinaryWaiting` coverage witness. Payload,
   ownership and traffic checks had not failed. Diagnosis retained the missing
   coverage, rather than deleting the assertion.
3. r3 retained all original stimulus/assertions and added a directed raw miss,
   software-ledger waiting observation and ordinary request. Its host compilation
   failed because that ledger member was private.
4. r4 added only a const public read-only accessor. The resulting two-profile
   component suite passed. All failed sources, diffs, diagnostics and receipts
   remain. One diagnostic wrapper receipt itself is FAIL from an exact-stderr
   newline mismatch; it is not counted as a behavioral pass.

No DUT source change or regeneration was used to hide these host-only failures.
No independent oracle was weakened to accept the candidate.

## Evidence and reproducibility

Use `V = build/fourth-efficiency-validation-20261027-r1` and
`Q = build/fourth-ingress-independent-review-20261027-r1`.

- `V/source-freeze.json`, `V/scala/compile-receipt.json`, emission bindings,
  whole-hierarchy checks and OFF comparison bind the measured Scala/RTL identity.
- `V/components-result.json`, `V/component-runtime-freeze-r4.json` and all
  role/case raw logs preserve the 11 actual component executions.
- `V/cpu-matched-results.json`, SHA-256
  `8d1d40d87c66a6cc3f8223926ea1229deb89d5e5a21750ad544cb68cde36544a`,
  binds all 30 actual CPU cases and per-metric namespaces.
- `Q/final-cpu-independent-review.json`, SHA-256
  `01e64bebb1582a688adae286353bad28215ccce7fd3ee95b8996d5ba93ec3c42`,
  independently checks exits, required markers, hashes, sanitizer results,
  cleanup and matched metrics.
- `build/fourth-efficiency-full-cpu-mapping-20261027-r1/resource-receipt.json`
  contains the completed same-flow primitive census and runtime. Mapped JSON
  SHA-256 is `feda301192b011f4397881dcbbe000ca79abd354461a5a8e317f68fb1481051f`.
  Final map review at
  `build/fourth-map-independent-review-20261027-r1/final-map-independent-review.json`
  has SHA-256 `26318026ac55989ea21d0c355452dbe13215e4e74c7bdfad90eef5a41f92ca85`.
  The sealed mapping receipt has SHA-256
  `ede5bc1479477936bc18a7d9821d1264af13031cd93532b9d1ba1f73d68325ec`;
  its manifest is `ad25620da2cf2da7e0b0418546e148d896918fa8f66af328cf6278b515207830`.
  Postcommit continuity is a separate record and must not be implied before it exists.
- The PRE_MAP runtime recovery artifact retains 719 members: current raw logs,
  failure/recovery history, CPU/DTA generated C++/headers/FIR, host dependencies,
  fixed guest inputs and independent reviews. It is not a completed-map claim.
- Measured and archived source identities precede any later host migration,
  documentation edit or local commit. Record those changes separately; do not
  rewrite execution receipts to pretend a later commit was the measured input.

The successful component source is specifically revision r4. Portability changes
when promoting experimental CPU drivers must be recorded separately: an exact
source copy that still contains an absolute build-tree include is not a portable,
self-contained entry point. Generated model aliases, objects and executables
must not be committed as source.

## Post-seal host migration

The successful r4 component host, fixed independent-load assembly/linker inputs,
and three shared oracle/service headers are copied unchanged into tracked
locations. The independent CPU driver has one explicit portability edit: its
absolute build-tree oracle include becomes a relative include of the exact same
header bytes. That driver is **not** byte-identical to the originally executed
host. Separate hashes, the one-line diff and a host-only continuity replay record
are recorded separately. The relocated host was compiled and linked once per
role against each existing CPU object, then replayed only on the original
independent-positive case with the original guest. Both executions exited 0,
retained byte-identical stdout/stderr (ROI 90 and physical span 105), passed
ASAN/UBSAN and left no owned processes. MMD dependency evidence confirms use of
all three migrated headers and no old build-tree Nax header. No DUT, Scala or
guest was rebuilt for this include-only continuity check.

The host-only result at
`build/fourth-migrated-host-continuity-20261027-r1/result.json` has SHA-256
`25ca3f568fb4e055823d505fcfe12599f687875ece561d0ee443dc778a1c6eb3`.
Independent review at
`build/fourth-map-independent-review-20261027-r1/host-migration-continuity-review.json`
has SHA-256 `d55ef85c6f22676d95e95fa4b2eb2aa6de9992a6febed41063921490c46329a3`.
This is host-path portability continuity, not a second measurement of RTL
performance or an already-established postcommit source-tree proof.
