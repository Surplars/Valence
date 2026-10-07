# Opt-in two-to-four memory-slot experiment: feasibility only

Follow-on implementation and measured results: [opt-in four-slot experiment](memory-capacity-experiment.md).
The text below is the original feasibility record.

Status: read-only inspection, 2026-10-07. No implementation, additional model,
simulation or physical-design run is authorized or performed by this plan.

## Evidence and scope

The selected two-slot board has 19198 ROI cycles where the selected younger load
passes every actual non-capacity issue guard but has no physical slot/replacement.
This is 3.95% of all ROI cycles, not a count of distinct loads or a speedup bound.
See [the verified attribution](data-path-ownership-attribution.md).

The capacity predicate excludes interrupt drain, system reservation, older system
or atomic work, FP epoch, recovery, early recovery, pending exception and serial
exclusion. For a younger selected request the reserve predicate necessarily takes
`speculative && !blockedByStore`; ordinary RAM classification and the actual older
store disambiguation/forwarding checks therefore remain in force. Registered
memory preparation supplies operands before this gate. The observer compares its
predicate with production reserveMemory and start.valid on all 1953690 nonreset
samples. No unselected ready ROB load is counted.

## Feasibility and configuration coupling

`OooParams.scala:170` permits memoryEntries 1, 2, 4 or 8, and
`ParallelLoadStoreUnit.scala` sizes slots, arbiters and owners from that parameter.
No production staged-fetch-turnover guard was found that prohibits four memory
slots. The existing “two-slot” execution guards constrain completionWidth2 and the
ranked execution pipeline, not memoryEntries.

A memoryEntries2→4 change has these derived effects even with every other explicit
configuration value fixed:

- Physical LSU slots: 2→4
- Registered LSU request FIFO: 2→4
- LSU response-owner FIFO: 2→4, owner index width1→2
- StoreBuffer physical-response owner credits: 3→5
- StoreBuffer direct-outstanding counter width expands as needed

These are part of the existing parameter coupling, not additional independent
knobs. StoreBuffer write entries remain2. A claim of changing physical slots alone
would be inaccurate unless the dependent capacities were separately decoupled,
which would be a different and broader experiment.

The production board currently has no explicit memory-capacity override:
`BoardSocTop.scala` privately constructs its parameters through boardParams, and
`BoardSocConfig.params` pins memoryEntries2. An experiment needs an explicitly
opt-in override with the default unchanged, plus an emitted configuration receipt.
Baseline configuration tests should remain unchanged and keep asserting2.

Keep all other selected values fixed: issue/rename/commit/completion width2,
ROB16, PRF48, full64-bit tags, predictor32, StoreBuffer2, staged-fetch-turnover,
I-cache32 lines /2KiB /2ways, current D-cache geometry, RV64GC/FPU,100MHz,
UART460800, DDR2GiB and registered load-issue forwarding=false. Use the exact
existing RV64IMC BIN and ROI.

## Test and measurement plumbing that must be scoped

- BoardSocGsimMain currently requires two LSU slots for passive backend probes;
  its token/state ports and backend sample arrays/capacity checks assume2.
- backend_ownership_ledger.h and the physical lineage ledger currently consume
  two-slot BackendSample owners. A capacity-aware observer must preserve full
  tokens, count conservation, cancellation and all corruption rejections.
- Idle-slot histograms must become0..4 for the candidate; selected capacity
  eligibility must retain exactly the same non-capacity predicate.
- throughput_perf.py hard-codes two slots in compiler definitions, metadata and
  measurement parsing. An opt-in experiment needs capacity-specific provenance.
- RetireTimingGsim's four-slot wrapper also changes predictor entries to64;
  it is not a clean selected-board A/B without separate scoping.
- ThroughputMachineCoreGsim/AuthorizationMachineCoreGsim require the pinned
  two-slot fixture. Preserve those guards and create an explicit experiment
  variant rather than weakening unrelated baseline tests.

## Existing independent invariants and test assets

- OooParamsSpec: elaboration of memory capacities1/2/4/8.
- IntegerBackendGsim + integer.cpp::parallelCancellation: four outstanding loads,
  cancellation, same-index new-generation ROB reuse, four delayed errored old
  responses, no stale fault/writeback contamination, eventual response draining.
- integer.cpp: irrevocable-store protection, request stability under backpressure,
  load turnaround, precise errors, store-to-load forwarding and cancellation.
- core.cpp: independent accepted-request and architectural memory models;
  request payload stability; read/write/owner capacity limits; independent-load
  occupancy reaching MEMORY_ENTRIES; early younger-load bypass; wrong-path load
  cancellation; same-address/overlapping DMA load replay; precise non-RAM access;
  NEMU retirement/register/memory comparison.
- StoreBufferGsim + store_buffer.cpp: held direct request versus buffered write,
  byte forwarding, local reply delay/backpressure, physical ownership, guaranteed
  write-error and read-value corruption rejection. Write depth remains2 while
  the coupled owner-credit capacity changes.
- Current backend/data-path host ledgers: full-generation identity, physical
  write lifetime beyond retirement, every registered boundary, ordered local
  fault placeholders, reset/discard conservation and wrong-lineage negatives.

Existing generic/default-profile tests are assets, not proof that the exact
staged-fetch-turnover four-slot board is correct. A future authorized acceptance
should select only short affected scenarios under the exact timing profile and
capacity, retaining their independent oracles rather than running broad suites.

## Critical-path and bottleneck risks

The request and completion RR arbiters, request/response/completion payload muxes,
owner selection, empty-slot priority and noOtherSerial/othersIdle reductions grow
from two to four inputs. The completion-choice→replacement/availability→start-ready
path and recovery-cancel fanout deserve particular physical review. Two more LSU
state/payload banks also add registers and routing pressure. Registered load-issue
forwarding remains disabled; do not silently add its separate wake/bypass paths.

The core still starts at most one memory operation per cycle and has one LSU
completion stream sharing completion lane0 with multiply/divide/system work.
The following remain fixed: translation ingress2, translated8, checked2,
translation owner8, relocated return buffer2, mapped/platform router owner8,
cache hit-response queue2 and one active miss. More slots may hide pipeline
latency, but can also shift pressure to these boundaries or increase completion
contention. This experiment does not add MSHRs or prove more concurrent misses.

## Clean A/B acceptance proposal

1. Introduce only the explicit capacity override and its necessary test/observer
   parameterization; leave all defaults and other selected settings unchanged.
2. Run scoped independent four-owner cancellation/reuse/backpressure, ordered
   read/store/fault/return and architectural short checks. Preserve sanitizers and
   negative tests; confirm actual four-slot occupancy instead of just elaboration.
3. Reuse the exact accepted two-slot reference and compare one selected four-slot
   board run with the same BIN/ROI. Verify architectural results and byte-exact
   ROI retired-PC sequence. Cycle/tick counters are the outcome and may change;
   do not require byte-identical performance counters for this functional A/B.
4. Report cycle/tick change, selected capacity exclusions, physical occupancy,
   serial exclusions and downstream pressure separately. Do not interpret19198
   blocked observations as guaranteed cycle savings.
5. Only after functional acceptance and separate authorization, perform one
   bounded physical comparison. Judge effective throughput using measured
   cycle ratio and achieved clock ratio, with LUT/FF/BRAM/resource consequences.

No candidate has been implemented or tested by this feasibility inspection.
