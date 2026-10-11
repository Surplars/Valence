# Route-local legacy cache grants

Status: the candidate at `db8394529f960622263e3c0d75fec4e2456285d4`
passed 24 affected component cases, seven intended negative controls and the
bounded native structure checks described below. It has since been integrated
without changing its production bytes into the combined timing/CDC board
candidate, whose actual constructor, native export and matched CPU replay also
passed. See [the combined evidence](experiments/timing-cdc-combined-evidence-v1.json).
No synthesis, STA, routed timing or board qualification is claimed.

## Contract

The cache separates legacy execution from total posted enqueue acceptance.
Upstream READY, posted enqueue, actual CPU/posted/fallback acceptance, response
tickets and ownership/state transitions retain their original expressions.
No state, pipeline, capacity or public option is added.

Ordinary legacy acceptance uses VALID, neither posted route, ordinaryReady and
not postedBusy. Exhausted-generation fallback uses VALID, the fallback route and
its existing drain-qualified ready. An exhausted offer joining an existing
posted line remains posted. Assertions compare this event with
`cpuFire && !postedAccept`, check fallback equality and reject double execution.

The event drives direct victim capture, hit SRAM reads, store SRAM writes and
the resident-hit metadata update. The sibling hit branch keeps its source-order
priority before later refill/install writers. With adoption, ordinaryReady is
legacyReady or attachReady; direct capture additionally excludes attachReady.
An attached demand retains its existing PF owner and response ticket and does
not allocate or evict a second owner.

## Bound results

The finite route-equation proof covers 786432 combinations and rejects five
mutation classes. Dynamic adoption OFF2/ON18 positive logs exactly match their
qualified predecessors. Four tiny-generation fallback cases cover exhaustion,
dirty writeback tails, cancellation and resident fallback held behind a real PF
ReleaseAck. The context-before-WB-drain negative reaches its intended RTL
assertion. Focused receipt SHA256:
`8e4a175de6d93226b9161e2be2076024d280f78195dc400c24c7ccf643bfba44`.

The independently exported production B cache, dirty retry/adoption ON, retains
all register identities, 8729 scalar bits, 271876 array bits, ports and RAM
geometry. Only the cache module changes. Original posted-SEAL paths to
`directEviction`, `hitRead`, `storeWrite`, `readIndex` and `postedInstall` are
absent; an injected SEAL dependency is detected. The native syntax adds seven
ternary occurrences, with unchanged equality and variable-index counts. Native
census SHA256:
`effef53be23246d71f2df60bb6829fac87198251bb9aa796f1b0ea105f837605`.

The combined native cache subtree was separately checked using the same strict
parser grammar. All five cuts and the injected direct-SEAL negative passed.
Different surrounding constant propagation means this full-SoC subtree is not
byte-identical to the standalone export; its actual census is reported separately.

The graph stops at registers, does not parse replacement-register D and does not
prove Boolean sensitization or general sequential equivalence. Upstream total
readiness and posted ownership retain lawful SEAL dependencies. These results
do not establish mapped LUT/FF cost, electrical fanout, slack or Fmax. The
original estimated post-place failure remains a distinct physical result.
