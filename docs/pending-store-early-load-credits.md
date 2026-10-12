# Bounded pending-store early-load responsibilities

Optional bandwidth candidate qualified by focused, board-model and native checks;
physical implementation remains unqualified.

`pendingStoreEarlyLoadCredits` is independently selectable as 1 or 2 and defaults
to 1. The CLI spelling is `--pending-store-early-load-credits=2`. Two requires the
existing pending-store proof profile; proof-row capacity remains independently
1 or 2. The joint profile selects two rows and two credits without
changing LSU4, ROB16, PRF48, DTLB16, issue width 2 or the query/PMP pipeline.

## Contract

- At most one reservation and one consume per cycle, through the existing scalar
  full-token interfaces. Reserved and active entries share the total capacity.
- A reservation selects the lowest pre-edge free entry. Capture may consume that
  fresh reservation on the same edge, as in the original one-credit integration.
- A held reservation remains reserved when its owner is absent from the LSU.
  Only an exact-token cancellation can release an unconsumed reservation.
- Each active entry is independently reclaimed only on an edge where its full
  token is absent from every pre-edge busy LSU slot. Availability depends solely
  on registered free state, so reclaim cannot be borrowed on that same edge.
- Another already-free entry may reserve while an active entry reclaims. A full
  two-entry bank cannot reserve on an edge where both active owners disappear;
  it can reserve one new token on the following edge.
- Every nonfree credit has a distinct full token. Consume/cancel must match
  exactly one qualified entry. Each accepted full token has at most one live LSU
  slot. Equal low indices with different generation tags remain distinct.

The lifetime witness is `ParallelLoadStoreUnit.live/owner`, which comes from
`LoadStoreUnit.busy/operation.token`. Busy covers request, response and done.
Accepted cancelled reads retain their request/response and completion-discard
obligations. A completing physical slot may capture a different owner, but this
only changes the visible token after the completion/capture edge. No ROB payload
read or request-FIFO absence is used for credit return.

## Preserved authority

The existing proof-bank scheduler and its query context are unchanged. A bound
store proof persists until the exact real store handoff or that store's own
kill; load completion/cancellation does not release it. Every new load still
passes all original older-store exact-token/epoch/PA-byte, ready-head/store
priority, precise-fault and recovery gates. B2 still checks every saved live load
and selects a truly idle physical slot for the protected store.

The measured native declaration delta is 314 scalar register bits: 70 for the
extra full token and responsibility state, and 244 for the second proof row
(including its newly nonconstant one-bit translated-row selector). Array bits,
instances and top-level port bits are unchanged; internal port bits increase by
310. These are native declaration counts, not mapped LUT/FF/BRAM/DSP or timing
results. Availability has no new LSU-live return path.

## Qualification boundary

The dedicated tests compare independent owner accounting for one/two credits,
combined row/credit eligibility, and the real backend's cancellation/drain and
oldest-store fault behavior. Constructor/CLI tests cover all four row/credit
settings, reject unsupported/duplicate options, and preserve explicit defaults.
Old complete constructor expectations add the new field only on the expected
side; missing or changed fields on the actual side must still fail. Frozen
published manifests and archived executed receipts remain unchanged.

The final focused gate passes eight Scala checks, six models, and 28 injected
negative controls with combined ASan/UBSan. The real decoded backend observes
two early owners and two protected proofs, idle-slot B2, ready-head priority,
precise oldest-store faults, and redirect/response drain. Earlier failed host
revisions remain preserved. See [the measured board comparison and reproduction
instructions](fpga-next/dual-proof-credit-v1.md) for the complete qualification
boundary and exact evidence identities.

The credit diagnostic `reserved`, `active` and `owner` outputs are now vectors.
Old scalar causal observers need rebinding against the newly generated header;
they cannot be reused by assuming old field names. The existing ordinary board
host does not depend on those diagnostics. This interface change is not a change
to the architectural LSU start or response ports.
