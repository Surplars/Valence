# Opt-in older-prefix retirement: focused independent qualification

## Scope and invariant

This fixture instantiates the real `RenameRob` on the selected MLP4 profile:
ROB16, PRF48, tag64, rename/complete/commit width 2, recovery width 4, physical
load ingress ON, virtual precheck and prechecked flow OFF. Its configuration
retains DMA depth 4/yield 0, although DMA is outside this component. The emitted
baseline/effective parameter snapshots must differ only in
`loadOrderOlderRetire=false -> true`.

The independent oracle is a FIFO of allocated transactions. An asserted limit
must exactly match a live `(index, full generation tag)` owner. That transaction
is an exclusive stop marker: only its program-order predecessors may retire.
Unknown/stale/out-of-window owners authorize zero retirement. A deasserted limit
must ignore its payload entirely. A two-lane commit is always a ready, nonfaulting
prefix, respecting global holds, system single-step, registered producer holds,
and recovery priority.

Expected order is never derived from DUT head/index/rank outputs. The software
oracle walks a deque until the exact token marker; it does not copy the RTL age
subtraction or circular comparator. Allocated tokens and commit identity/data,
PC, instruction and next-PC are checked separately. The fixture uses non-writing
allocations to isolate this contract; existing full independent ledger tests
continue to own RAT, register allocation and free-list coverage.

## Files

- `src/test/scala/ooo/OlderPrefixRetirementGsim.scala`: scalar wrapper and exact-profile emitter
- `simulator/gsim/harness/older_prefix_oracle.h`: transaction FIFO and strict comparison
- `simulator/gsim/harness/older_prefix_retirement.cpp`: directed and seeded hardware stimuli, host oracle checks
- `simulator/gsim/older_prefix_retirement.py`: portable source-bound runner and evidence receipt

No existing correctness oracle is patched, weakened or used as the new expected
retirement decision. All negative controls mutate observations, not expectations.

## Coverage

- Every physical head position, occupancy 1–16 and live limit rank: 2,176 cases;
  all full/wrapped positions and both two-lane boundary positions.
- Exact checked-load suffix preserved across repeated retirement cycles; invalid
  limit payload ignored when `valid=0`.
- All 64 generation bits wrong at all 16 heads; old owners rejected after every
  index is reused; out-of-window and empty-ROB limits fail closed.
- Simultaneous allocation/completion/one-lane retirement; full ROB cannot borrow
  same-cycle released capacity; next-cycle single-slot allocation remains a prefix.
- Same-cycle completion blocked by the registered branch qualifier and subsequently
  retired; global commit hold remains stronger than an older-prefix limit.
- Legal strictly-older trusted fast-head completion; blocked pending candidates
  are withheld by the test caller. Direct blocked `fastHeadRetire.valid` pulses
  are illegal and the production assertion is preserved.
- System instruction single-step, younger fault stopping the commit prefix,
  faults at/after the checked limit, precise head exception, head-trap priority and trusted head-system recovery.
- Inclusive/exclusive rollback, limits kept or discarded, multi-cycle rollback
  and stricter recovery shrink; stale limits remain rejected after discarded indices
  are reallocated. A discarded limit continues to fail closed until
  the caller deasserts/replaces it.
- Three deterministic seeds, 3,000 cycles each: random valid/stale completions,
  faults, held branch completions, limits, dispatch/retire stalls, allocation,
  recovery and reuse; bounded drain to a quiescent empty ledger.
- Eleven required observation negatives: checked load admitted, younger lane
  admitted, stale limit admitted, older commit lost, global hold bypassed, branch
  hold bypassed, wrong retirement token/data, invalid recovery accepted, hidden
  head exception and invalid completion accepted.

The oracle itself has a separate pure-host contract self-check: all head/count/
limit-rank/first-two readiness/fault combinations (39,168), 16,384 full-width
stale-token challenges, registered handoff checks and comparator sensitivity.
This is explicitly not production RTL evidence.

## Commands and resource contract

From the checkout root:

```sh
# No compilation or simulation:
python3 simulator/gsim/older_prefix_retirement.py

# Light pure-host C++ oracle checks only; use a fresh tag:
python3 simulator/gsim/older_prefix_retirement.py --host-only --tag older-prefix-host-r1

# Only after the parent coordinates the single heavy slot and source is stable:
VALENCE_GSIM_SOURCE=/path/to/clean/pinned/gsim-src GSIM_CXX=clang++-19 \
  python3 simulator/gsim/older_prefix_retirement.py --build-run --tag older-prefix-component-r1
```

The GSIM runner uses an already built pinned toolchain; it never installs,
fetches, builds a replacement simulator or invokes Verilator. It elaborates one
narrow model, compiles one translation unit at a time, enables ASan/UBSan, and
requires every negative to exit 1 at its expected oracle check with `fired=1`.
Each output directory is new; existing results are never overwritten. The JSON
receipt records full input hashes, baseline/effective parameters, generated model,
objects, executable, logs and negative outcomes. Source changes during the run
invalidate the receipt. No full regression, Linux run, synthesis or FPGA claim is
made by this target.

## Required later executing-CPU cases (not covered or executed here)

A component pass does not prove that `IntegerBackend` captured the correct
checked-load generation, held pending replay globally, selected the correct
replay owner or canceled outstanding memory safely. Use a short guest and the
actual existing registered `LoadReplaySelector`; do not fabricate response
latencies or remove load-load checks to force a result.

1. Delayed older load address: use a real long-latency DIV dependency to produce
   the address of an older load. Let independent younger loads execute first,
   including an overlapping read of the same address/byte lanes. Require a real
   selector event, registered pending replay, and accepted full-token recovery.
   Check the exact committed PC/data sequence against independently specified
   program/ISA behavior (and NEMU where supported), plus token identity at all
   three replay boundaries. Require older-prefix retirements during the checking
   window while the checked owner and younger suffix never retire early. The
   replay witness must occur even when memory values do not change.
2. Recovery with four live loads: make an actual delayed taken branch resolve
   after cold younger loads have acquired four distinct live LSU owners. Require
   killed-owner cancellation/drain, no wrong-path commit or writeback, eventual
   completion of survivors, then deliberate owner/index reuse. A stale returned
   response must not corrupt the new owner. Observe real request/response timing;
   avoid an oracle that merely assumes a future latency.
3. Pair the same guest and memory schedule against the unchanged MLP4 freeze and
   opt-in candidate. Preserve precise exception, pending-replay global hold,
   partial-forwarding, MMIO/head-only and backpressure checks. Mutation controls
   should remove the load-load checker or corrupt one replay generation/kill
   observation and be rejected by the executing-CPU oracle.

These are concrete acceptance requirements for the later CPU slot, not claims
made by the component fixture. Routed timing and the initial throughput
hypothesis remain separate measurements.
