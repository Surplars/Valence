# A1 registered raw demand with certified checked flow

Status: focused Scala, fresh actual-DTA A/B and paired full-CPU validation pass.
The new register has measured cycle costs; it remains optional and does not
replace the higher-throughput control. No FPGA frequency or PPA is claimed.
The c17245c control and all of its historical receipts remain unchanged.

## Explicit policy and scope

The new default-false `registeredRawCertifiedFlow` mode is selected only by
`full-r1-m3-checked-flow-store-row-elastic-proof-registered-raw`. Relative to
the preceding elastic-proof control, the final configuration changes exactly:

- `registeredRawCertifiedFlow`: false to true;
- `registeredDataTranslation`: false to true;
- `translationHitFlow`: true to false;
- `combinedCheckedDataFlow`: true to false.

The prechecked PA shortcut, M3 completed-store forwarding, prepared-store row,
elastic D/T/R preparation, two-wide backend and all capacities remain. The
RebuildProfile recipe constructs the old checked/store-row/elastic chain first,
then applies the new policy atomically; its recipe booleans are not substitutes
for inspecting the final FpgaNextConfig and OooParams. The new memory policy
validates the final configuration rather than overwriting caller parameters.

Old M2, old combined-flow, old named profiles and public defaults retain their
original mode contracts. The new mode does not change runtime/SoC selection.
Backend, LSU, cache, DTLB and elastic preparation production modules are not
modified. There is no additional functional request/proof storage capacity,
MSHR, TLB/PRF port or completion authority:
LSU4, ingress2, translated8, checked2, ordered response-owner8 and two cache/Home
miss owners remain. DTLB16 is not a sixteen-entry request queue.
The reused M2 result wrapper includes its existing held-payload assertion
monitor registers; this is not a claim of zero extra emitted verification bits
or of a measured synthesis-pruning/area result.

## Data and control boundary

Every raw translation response enters the existing registered translated
queue. It cannot flow directly into checked authorization. A delayed miss
retains its original waiting/saved-request ownership and subsequently enqueues
its result; an accepted descriptor is never deleted by a context flush.

The single main PMP evaluator selects either the registered translated head
or a separate certified descriptor built solely from registered ingress request
and context. This second descriptor does not reuse translated.enqueue payload:
that generic payload still contains raw TLB PA/PBMT/fault mux inputs, and
functional mutual exclusion alone would not demonstrate a timing-path cut.

The certified descriptor retains the incoming PA, request, captured privilege
and epoch, sets checkPhysical, clears pageFault and canonical-origin validity,
and computes malformed-form/stale faults from the registered input and current
authorization state. PMP, read permission, whole RAM interval, alignment/mask,
epoch/change/flush and final checked-stage stale checks remain. Alignment/mask
fault enters the evaluator's own fault result so next-line authorization sees
the same rejection. Old M2's malformed-sideband policy is not changed.

Head selection depends on registered translated occupancy. Checked valid and
credit depend on registered ingress/queue occupancy and waiting state, not raw
translation reply/hit/fault. The existing next-line checker is retained; a
second main PMP checker is not introduced. VM/PMP comparisons and permission
logic remain combinational, so this is not an assertion that all paths are now
short or that 300 MHz is achieved.

## Ownership and special accesses

An older translated head always wins. A younger certified request spills once
if the older FIFO is occupied or checked cannot accept. Old-head pop and new
spill may legally occur together. Immediate incoming ownership goes exactly
once to checked or translated, while a cold demand may instead first occupy
waiting/saved-request state. Full queues do not borrow same-cycle pop credit.

Bare and already-physical identity accesses retain their authorization semantics,
but not necessarily the same latency: an eligible virtualized Bare demand now
crosses the raw-result register, whereas an empty-FIFO physical identity request
retains its direct checked route. Atomic/LRSC, uncached/MMIO, PBMT and faulting
translations already used the translated queue and gain no further register stage. Ordered fault placeholders and physical responses retain their
original owner queue and drain rules. Canonical store events require the exact
FIFO dequeue and checked enqueue FIRE, fresh original store identity and full
permission; certified loads cannot create events. Stores still require their
actual replies and precise retirement.

The native DTA request has no load ROB full token. CPU verification binds actual
LSU full tokens to independently tracked ordered tickets; it must not invent
token fields in this adapter descriptor. Context changes with accepted owners
still require the original drain contract, not arbitrary in-flight permission
updates.

## Latency and throughput hypotheses, not results

- Eligible raw hits, including ordinary stores: minimum DTA upstream-to-physical
  latency 2 to 3 cycles; canonical publication is likewise one cycle later.
- Pure certified traffic with empty translated FIFO: minimum latency remains 2.
- Mixed continuous traffic can keep translated nonempty, making certified loads
  spill and take 3 cycles. Certified-first traffic can have a one-time startup
  gap when it transitions from the short path to the queued path.
- Steady component capacity remains one accepted result per cycle when not full;
  the original full-release bubble remains. This is not a CPU load/cycle claim.

Elastic preparation's two registered lookup/permission stages, its measured
non-unit supply interval, four LSU slots and downstream latency are unchanged.
The new raw-store delay may worsen real VM cycles and forwarding windows. Every
net regression, mixed-flow penalty and backpressure difference must be reported,
not hidden behind the possible timing benefit.

## Required bounded validation

One unified compile follows static review and complete source freeze. A fresh
actual-DTA/real-DTLB control and candidate compare raw, certified and mixed
continuous supply, cold walk, prefilled FIFO, checked/full backpressure, held
payload, direct/spill ownership, subword canonical events, Bare, atomic, PBMT,
page/access faults, PMP, epoch/drain and malformed shape. Independent oracles
check request/reply/canonical identity and bytes, not a copy of the DUT predicate.

Fresh control and candidate CPU models use the same newly restored toolchain,
each running the same two VM and hot/cold supply guests. ISA/byte/PMP/PTE/service
oracles remain protected from accidental changes. Report actual raw and certified
latency categories, full-token 48 forwarding / 49 store conservation where
applicable, retirement, work/ROI, accepted duty and real miss traffic. Historical
objects are not silently reused across the restored tool epoch.

Generated structure must additionally demonstrate a register cut from raw
translation.response PA/PBMT/fault/valid to the head/PMP input, checked data/valid,
canonical event and next-line hint cones. Register/memory boundaries, control
conditions, dynamic selection and child ports must be explicit; unsupported
syntax cannot be silently omitted from a passing dependency graph. A bounded
combinational perturbation check may supplement, but not replace, that evidence.
Count the main PMP instance separately from existing next-line/walker checkers.
No Vivado, full GSIM, Linux or additional architectural feature is part of this
batch.


## Measured actual-DTA component result (October 25, 2026)

The frozen batch compiled once with the restored pinned toolchain. Seven focused
Scala suites pass 20 tests. The independent actual-DTA runner then freshly emitted,
generated and compiled both control and candidate using the same tool binaries;
no historical simulator objects were reused.

Both models pass 15 cases with 1,170 accepted and returned requests each:
1,129 real physical requests plus 41 ordered fault placeholders. Exact per-case
addresses, response data/faults, canonical ownership and trace hashes match.
All ten deliberate negative controls fail as expected, including undrained
flush hardware assertions. ASan/UBSan report no errors.

Flush coverage follows the production drain contract: ten fully drained authorization
maintenance transitions, stale/fresh certified requests and drained PTE remapping
pass. A separate negative test blocks one accepted certified request, then flushes;
both models reject this with the general adapter-drain assertion. This does not
qualify legal in-flight context changes, automatic cancellation/draining on flush,
all occupancy combinations, or independent firing of every drain assertion.

Measured raw load/store acceptance-to-physical latency is 2 → 3 cycles; their
first response latency is 3 → 4. Empty-FIFO certified latency stays 2 physical /
3 response cycles. For 128 continuously supplied requests:

| Scenario | Total test cycles, control → candidate | Accepted span | Physical span, control → candidate |
| --- | --- | --- | --- |
| Raw loads | 136 → 137 | 128 | 128 → 128 |
| Raw stores | 136 → 137 | 128 | 128 → 128 |
| Certified loads | 136 → 136 | 128 | 128 → 128 |
| Alternating, raw first | 136 → 137 | 128 | 128 → 128 |
| Alternating, certified first | 136 → 137 | 128 | 128 → 129 |
| Congested raw | 277 → 277 | 256 | 169 → 169 |
| Congested alternating | 277 → 277 | 256 | 169 → 169 |

The total test cycle count includes the same settle/drain overhead in both
models. In raw-first mixed traffic all 64 certified requests spill and have
three-cycle physical latency. Certified-first mixed traffic has one two-cycle
certified request and one real startup bubble. Full translated-FIFO release
retains the original one-cycle no-borrow gap. Eligible virtualized Bare demands
show the same extra raw-result cycle; physical identity shortcuts retain their
previous latency. The explicit Bare/identity next-line tests each observe one
allowed hint and two denied hints, preserving READ PMP and RAM-end checks.

The fresh FIR dependency gates pass on both actual generated hierarchies:
control retains positive raw-response combinational witnesses, and the candidate
cuts the specified raw response-to-head/PMP/checked/canonical/next-line cones at
registers or memories. Both retain one main PMP evaluator and the separate
next-line checker. This is structural evidence, not physical delay or 300 MHz
qualification. The component's read data is independently generated synthetic
beat data; actual CPU store/load-memory behavior is covered separately below.

Receipt: `build/gsim/registered-raw-certified-flow-20261025-r1/receipt.json`.
SHA-256: `35a6c1fadeb3d02a21288d79a497d4ebdfbbfe489a412393832a7e133ade409e`.
The receipt binds every main/test Scala source, harness and oracle, cone checker,
model FIR/header/object/binary, tool binary and log. Its final source/tool drift
checks pass. Neither project defaults nor public branches changed.


## Fresh full-CPU comparison (2026-10-25)

Both models were generated and compiled using the same restored toolchain; no
historical objects were reused. The control reproduces c17245c measurements,
and its FIR matches the historical control after source annotations alone.

| Measured region | Control | Registered raw | Cycle increase |
| --- | ---: | ---: | ---: |
| VM stream work | 681 | 731 | 50 (7.34%) |
| VM dependency work | 1018 | 1068 | 50 (4.91%) |
| Hot 256-load ROI | 531 | 532 | 1 (0.19%) |
| Cold load ROI | 360 | 361 | 1 (0.28%) |

Each VM retains 48 forwards, 49 stores and 233 retired instructions, with exact
architectural outcomes, accepted physical owners and traffic conservation.
Warm raw latency changes from two to three cycles for 48 stores and two loads;
certified latency remains two, and the initial cold store remains 24 cycles.
These CPU guests have zero certified spills, unlike the component mixed-stream
coverage. Hot steady supply still has 253 two-cycle gaps; one startup gap changes
from seven to eight. Cold demand still occupies two real MSHRs concurrently.
Independent load-byte, ISA, physical identity and source/tool drift checks pass.
An injected prechecked-PA observation mutation is rejected by the independent
oracle; this is an observation negative, not an RTL fault injection.

Full-CPU structural checks independently confirm the raw-response register cut,
with the old control as a positive path witness and one main PMP in both modes.
The five additional DTA bypass mutants are rejected. These checks do not provide
physical delay, area, routed timing or 300 MHz qualification.

Receipt: `build/gsim/registered-raw-certified-cpu-20261025-r1/receipt.json`.
SHA-256: `870131f244a4796d2c3caac3bbbb055fe8bff18426ff0b1d5989356043a29377`.
The optional candidate trades cycle cost for a structural timing boundary; no
net wall-clock performance improvement is established. Defaults, public branch,
local execution state and the previously delivered control RTL are unchanged.
