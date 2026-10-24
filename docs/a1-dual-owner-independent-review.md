# A1 dual-owner backend: independent static review

Review scope: the first A1 rebuild candidate, not an FPGA frequency sign-off.
The actual baseline is `CommonCpuProfile.A1`; the four controls are
`CommonA1RebuildProfile.{Baseline,Backend,Memory,Combined}`. No production source
was modified by this review. No compilation, hardware simulation, synthesis, or
implementation was run by this reviewer.

## Snapshot and disposition

Backend owner declared the production Scala frozen on 2026-10-24 at approximately
04:36 UTC. The files reviewed at that point have these SHA-256 hashes:

| File | SHA-256 |
|---|---|
| `core/ooo/config/OooParams.scala` | `59d237551f1098c717cbe7512df2107673991ff172ed667b5994d33cb2df1ac4` |
| `core/ooo/integration/IntegerBackend.scala` | `31dc773de096cb1b019670a525640e18b5603fbdcb065f1ee35d8516a9f246b1` |
| `core/ooo/retire/DualCompletionSelector.scala` | `374a8684ce7cbefd2d04d94cda51ac48e49426ca6b1fbb80da93efb64041928a` |
| `core/ooo/lsu/ParallelLoadStoreUnit.scala` (04:38 UTC integration review) | `839f9e417a2a2fbb5e612e7a44b6e7d4f0a5e06db916dc939d4f328239638a70` |

Paths in the table are relative to `src/main/scala`. Hashes identify the inspected
working-tree contents, not a committed release or validated bitstream.

**Static disposition:** no architectural blocker was found in the frozen backend
and subsequently reviewed LSU-turnover correction. This is not a simulation
PASS. The candidate may proceed to the already planned joint compile and short,
affected validation. The existing public A1 preset remains `legacy`.

## Findings reported during review

1. **Real LSU throughput integration gap, corrected before joint compile.**
   The previous [parallel LSU](../src/main/scala/core/ooo/lsu/ParallelLoadStoreUnit.scala)
   selected a completing slot whenever `complete.valid`, even if another slot
   was empty. This was compatible with an always-ready completion sink. The
   dual-owner backend can now hold that result under writeback contention. An
   independent load then targets the held slot, `start.ready` is false, but
   `issueAvailable` and the backend's memory reservation can still be true.
   This wastes a dispatch ticket and prevents useful load issue despite an empty
   physical slot. This is a throughput defect, not evidence of result corruption.
   The corrected policy uses `completionReclaimable = complete.fire` only in
   dual-owner mode, and preserves the legacy expression otherwise. This is safe
   in the inspected integration because LSU `complete.ready` comes directly
   from the selector's registered-owner choice, not from late
   `completionAccepted` or recovery authorization. A held unselected result
   now permits an empty slot, and a full unselected LSU advertises no capacity.
   Serial-owner exemptions and candidate/observational capacity views use the
   same reclaimability rule. An assertion requires replacement of a busy slot
   to correspond to the actual consumed completion's chosen slot.

2. **Configuration boundary tightened after review.** The frozen
   [parameters](../src/main/scala/core/ooo/config/OooParams.scala) require the
   two-wide ROB16/PRF48/full-tag64 topology, LSU2 or LSU4, registered execution,
   parallel ranks/recovery, LVT PRF and registered retirement. They reject
   lane-fixed experiments and `memoryProofFrontier`. The frontier retained an
   unconditional-start/always-ready-completion assumption. The backend also
   rejects its separate always-ready LSU shadow-bind experiment. The actual four
   A1 controls satisfy the supported contract; unrelated profiles are not
   validated by the A1 tests.

3. **Generation-sensitive completion-selection proof added.** The selector
   intentionally compares only ROB slot indices. An independently held old
   generation could otherwise hide a new generation at the same slot. The
   frozen backend now checks every raw offer against the full issue-queue token
   and the current live ROB window, independently of the selection logic.
   The standalone selector oracle alone does not establish this invariant.

## Physical execution lane is not writeback lane

The [backend](../src/main/scala/core/ooo/integration/IntegerBackend.scala) now has
six held producer classes: LSU, DIV, MUL, SYS, physical ALU0, physical ALU1. The
two writeback ports select among these owners. The review followed the dependent
paths, rather than merely checking the new arbiter:

- The actual `BackendCompletion`, full token, exception, and same-cycle-retire
  class travel together through each writeback payload selection.
- PRF writes, owner-local readiness updates, pending clear, and observed issued
  results use the selected writeback port's `completionAccepted`. They do not
  derive the destination from that port's former ALU owner.
- ALU-stage dequeue and overlap accounting use `producerAccepted(4 + lane)`.
  An occupied ALU slot is not released merely because another producer used its
  former writeback lane.
- Branch results and redirect capture still use the physical execution owner's
  token. When both physical lanes resolve mispredictions, their actual circular
  ROB ages choose the older owner; the old “lane 1 is oldest” dispatch convention
  is not used as a recovery proof.
- Control-flow completion remains barred from same-cycle retirement. Existing
  registered redirect and branch-retirement hold protect the precompleted
  branch until its redirect is processed.
- Full exceptions reach the ROB and suppress PRF/ready effects. Moving a branch
  or fault between writeback ports does not change its authorization.

The two ranked issue candidates still choose their source IDs and read their
operands independently of physical execution credit. A local 2-by-2 mux exchanges
the **whole already-read operand packet** when the oldest rank needs the other
free execution slot. `dispatchFire`, forwarding witnesses, and pending clear
refer to the original issue rank; result generation refers to the physical
holder. Store preparation is not enqueued into an ALU holder and retains its
separate issue ticket.

## Full-token ownership and cancellation

[RenameRob](../src/main/scala/core/ooo/retire/RenameRob.scala) remains the actual
completion authority: full generation match, live-window membership, not already
done, no duplicate accepted token, and recovery survival are required. The new
selector is not an alternative authorization mechanism.

The reason index-only selection is admissible is the producer lifecycle:

1. An uncompleted owner cannot retire normally. If it completes and retires on
   the same edge, that producer also consumes its result on that edge.
2. Recovery blocks rename during its accepted/active cycle, so the killed slot
   cannot be reallocated before the producer processes cancellation.
3. ALU occupied state is cleared; DIV leaves its operation; MUL clears the
   reservation's live bit. A cancelled load may retain an external response
   obligation, but its registered cancelled state hides `complete.valid` while
   the response drains. This response obligation is not a live completion offer.
4. SYS owns a protected current-head transaction until completion/retirement.

Therefore an old completion generation should never coexist with a reused
generation in the selector. The new raw-offer full-token/live-window witness
checks this premise, without lengthening the functional selector cone. A short
backpressure + recovery + slot-reuse scenario is still needed to exercise it.

Same-cycle cancellation can leave an old registered offer visible for arbitration.
It does not authorize its effect: ALU dequeue-valid is cancelled, LSU's selected
result can drain while RenameRob rejects it, and DIV/MUL cancellation removes
their reservations. This can waste a completion slot on the recovery edge, but
is not permission to publish a killed value.

## Held operand promises and combinational direction

Both ALU holders may promise a legal ordinary result while waiting for writeback.
The promise derives from the old registered owner and registered legality class;
the data is the ALU result of its saved operands. It does **not** set global PRF
ready, update the ROB, or commit. A consumer only captures after its own current
kill/exception authorization. The existing assertion rejects a captured consumer
that relies on a same-edge-cancelled ALU producer.

The load promise similarly uses the selected LSU slot's saved destination and
result. A retained successful load may feed an operand before writeback, but if
it drains on that edge its exact producer must be accepted. Its token and saved
destination are checked against the current queue owner. Per-slot LSU results are
held; the internal round-robin arbiter is not an irrevocable output interface and
may select another registered slot between cycles. Correctness must depend on
the owner/data pair sampled on the actual consumer edge, not an assumption that
the global LSU output remains locked indefinitely.

For the actual A1 registered-redirect/registered-replay configuration, the inspected
combinational direction is:

`registered presence/index → completion selection → holder dequeue credit → local operand-packet routing → authorized capture`.

The selector does not read ALU arithmetic data, `completionAccepted`, same-cycle
kill, or issue grants. Held ALU readiness does not read dequeue credit or kill.
Thus the review found no direct readiness/selection combinational cycle in the
frozen backend. Elaboration/lowering remains the independent structural check.
The LSU correction adds the forward path `early completion choice → reclaimable
slot/capacity → new memory start`; it does not add an edge back into completion
presence, index, or choice.

The four explicit profiles were also inspected: all derive from the actual
`CommonCpuProfile.A1.fpga`, memory validation checks the final supplied config
rather than overriding it, and `FpgaNextConfig.coreParams` explicitly carries
`completionTopology`. The unrelated `managedBoard()` factory rejects nonlegacy
completion instead of silently discarding that option. None changes the CPU
clock specification or creates a qualified whole-SoC bitstream entry point.

## Two dispatch tickets and independent verification

Memory and one MUL/DIV launch may coexist, but consume both tickets. SYS excludes
memory and M launch. With one side-unit reservation only one ALU/store-preparation
rank may launch; with two none may launch. The candidate asserts both reservation
count and actual accepted dispatch count at most two, and rejects a live ROB
owner dispatched into two execution classes on the same edge.

The standalone selector test uses a software circular-ROB walk, not the RTL's
pairwise-rank formula. Its duplicate-index, wrapped-age, side-pair, payload, and
mutation checks are useful **selector** evidence. They do not validate physical
lane exchange, precise branch/fault recovery, full-generation reuse, or held
forwarding. These belong to the planned short real-A1 backend fixture, preserving
an independent architectural oracle and matched offered instruction/memory service
laws across legacy and dual-owner. No extra full regression or long simulation
is requested by this review.

## What is, and is not, borrowed from NaxRiscv

The source-pinned [NaxRiscv study](naxriscv-a1-microarchitecture-study.md) explains
the relevant mechanisms. This candidate follows the useful principles: separate
narrow scheduling identity from wide payload, retain result ownership locally,
keep recovery authorization out of early availability, and budget actual accepted
work rather than merely widening configured queues. It does not import NaxRiscv's
ROB/IQ capacities, recovery semantics, speculative wakeup contract, or frequency
numbers.

The six-producer all-pairs age comparison and two wide completion muxes may become
new critical paths. Local 2-by-2 operand routing also has a physical cost. Static
structure alone establishes neither a net timing gain nor 300 MHz. The 300 MHz
target requires the eventual exact FPGA part/constraints, routed setup and hold
results, and clock-domain checks; those results are absent here.
