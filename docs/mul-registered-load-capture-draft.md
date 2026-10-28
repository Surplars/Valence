# Default-OFF MUL registered-load capture — unexecuted draft

## Status and matched control

This source-only experiment starts from `4d3668da7e708b693796f4e6a67208bd882cf42d`
in an independent worktree. No Scala compilation/elaboration, GSIM model build,
hardware test, synthesis, PPA, or new performance run has qualified this draft.
It does not change the published tree or any public/default profile.

Recommended A/B: the same new source/tool epoch, original fixed guest/service,
`FullR1M3EfficiencyRefactor4` versus
`FullR1M3MulLoadOperandCaptureExperiment`. Their `FpgaNextConfig` and core params
must differ only in `registeredMulLoadOperandCapture`. Both context-owned
instruction prefetch and fifth-batch load nomination remain OFF. Reject mixed
profiles rather than conflate effects.

The preceding passive observation used **last-stale prefetch ON**, not this OFF
control. It observed 6,480 ROI dependency/rank frames and 6,477 fully authorized
frames; every authorized shared M port was originally idle, with no ready
MUL/DIV displaced. Original execution stdout was byte-exact. These are unchanged
trajectory opportunity counts, not a promise of 6,477 saved cycles, and not
frequencies measured for the proposed prefetch-OFF experiment.

## One coherent change and contract

Use an existing successful **registered LSU result** only as the numerical source
for an ordinary pending MUL's existing `PipelinedMultiply` operand capture.
Do not forward the incoming memory response, add a register/queue/credit, publish
PRF readiness early, retire a load early, change DIV, or change load/PMP/fault
permission. The multiplier still reserves its old result slot at its original
start handshake. Its count `< 8` old credit cannot borrow a same-edge pop.

1. Construct the two original registered-ready eligibility masks independently.
   `oldAvailableAny = (oldMUL.orR && mulReady) || (oldDIV.orR && divReady)`.
   Only when it is false can stable-load readiness extend MUL eligibility.
   DIV's mask and `SplitMulDivSelector` implementation/age arbitration are unchanged.
   Never derive this guard from the expanded selector or late authorization.
2. The promise cone reads only registered LSU completion destination metadata,
   original owner-ready bits, class/pending metadata and old FU availability.
   Recovery, tag comparisons, completion acceptance and reserve events do not
   feed that cone. Late rejection can therefore waste only an originally idle M
   port, not suppress an original ready MUL or DIV winner.
3. After the shared winner is selected, only MUL operands whose PRF source is
   unready and exactly matches the stable load destination substitute old LSU
   result data. Already-ready sources and all DIV operands retain original data.
4. A new numerical capture additionally needs successful ordinary-load producer
   ownership, memory-live and full 64-bit producer token match, exact nonzero
   destination, current live pending consumer full token, strict circular age
   order, both within the current ROB occupancy, neither owner killed, exact
   owner-ready/PRF-ready agreement, and no same-edge reservation of a forwarded
   physical source. It keeps all original system/recovery/head-exception gates.
   Current local issue-token metadata and pending/memory-live lifetimes bind the
   backend owners through the inherited live-row invariant: allocation is the
   unique row writer, the fixed row index and full token identify that allocation,
   and pending is cleared on start/completion/kill. Selected one-hot metadata must
   match that same local live row. This is not a new independent ROB-tag read/check
   (the passive observer had an extra ROB-tag cross-check); no new ROB read port
   or truncated token comparison is added.
5. Capture authorization never requires or creates LSU completion acceptance.
   The old result remains valid under CDB backpressure; simultaneous old result
   consumption and slot replacement must use the old token/data/destination.
   Existing result-hold, cancellation and full-token writeback/retirement rules
   remain unchanged. Payload and assertions change together; the original
   registered-ready assertion is retained for original winners and all DIVs.

Free original M port does **not** mean free global performance: a new accepted
MUL can contend for original dispatch/completion/ROB resources or affect later
traffic. Only matched CPU runs can establish net throughput/latency effects.
Even a late-authority-rejected new selection retains `reserveMulDiv` for the
current ALU side-dispatch budget: it can suppress one ALU dispatch without a MUL
start. This is an explicit conservative scheduling cost, not zero-impact rejection.
Do not feed late authority back into rank or reservation to remove it: that could
close a recovery/branch/dispatch combinational loop. Rejection leaves pending set
and consumes no multiplier result-slot credit, so a surviving owner may retry.

## Focused verification plan — not yet run

Freeze and independently review the complete diff before any compilation.

* Pure config checks: new flag defaults OFF; every existing profile stays OFF;
  exactly-one-flag A/B equality; matching explicit memory policy; reject absent
  registered capture/forwarding/shared-read prerequisites, shortened tags,
  legacy bypass/fast retire, prefetch and nomination combinations. Added
  `MulLoadOperandCaptureConfigSpec` covers the source-level configuration cases.
* Component wrapper must instantiate the actual `IntegerBackend` with its exact
  candidate parameters and inject allocation/load responses; observe the actual
  multiplier start token/left/right, registered capture and completion. Do not
  copy the inline DUT eligibility/authorization equations into a mock component.
  Independent software oracle derives oldest
  eligible class, signed/unsigned MUL/MULH/MULHSU/MULHU/MULW results and ownership.
* Cover source1, source2 and both-sources-same-load; ordinary PRF-ready paths;
  unrelated/two-producer sources (one stable value cannot satisfy both); zero
  register/destination; full 64-bit high-tag mismatch; stale/reused slot and
  destination; producer/consumer kill separately and together; wrong age and
  wrapped head; error/pageFault/store/atomic/rebind rejection; stalled completion
  and same-edge result replacement. Check numerical payload, selected token,
  pending clearing, reservation count and exactly one original start handshake.
* Arbitration/credit: ready older or younger MUL/DIV always blocks expansion;
  unavailable DIV does not claim the M port; full MUL count never borrows a pop;
  stalled/late-rejected candidate cannot change an original winner. Confirm
  a late rejection neither clears pending nor consumes a MUL result slot; record
  its original ALU side-dispatch reservation cost, then demonstrate subsequent
  normal surviving MUL issue and ALU progress rather than claim no ALU effect.
  Keep this authority out of rank/reservation. Confirm
  default-OFF emitted control is unaffected, no new state and no combinational
  ready/cancel/selection cycle. Negative tests must independently fail when the
  full-tag, kill, reserve, old-credit or original-port-free gate is deliberately
  removed; do not weaken the expected oracle to accept the mutation.
* Then one coherent short affected CPU batch with independent architectural and
  retirement checks: sustained MUL supply, load-dependent MUL chain, independent
  work, shared DIV/ALU contention, memory misses, faults/recovery and backpressure.
  Matched prefetch-OFF control/candidate must use identical guest/service laws,
  ROI boundary handling, tool identity and source epoch. Record accepted starts,
  useful completions/retirements, end-to-end ROI and I/D traffic; no static trace
  replay can claim saved cycles. Do not use prior prefetch-ON ROI as the control.

Stop/reject on any ownership/fault/credit/oracle failure, unexpected default-OFF
change or added state, lost original M winner, hidden service change, or unmatched
performance conditions. A correct candidate with no meaningful end-to-end gain
or with relevant sustained/dependent regressions stays OFF and is not promoted.
