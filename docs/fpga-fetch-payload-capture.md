# Frontend payload capture candidate

Status: paired independent frontend-module validation passes for two- and four-word
packets. Integrated CPU validation remains pending. No routed timing result exists.

## Source-level timing path

The reported start/end points are cache MSHR phase and a SynchronousFetch packet-word
register clock enable. Source connectivity permits the following combinational path:

1. `NonBlockingCoherentLineCache` combines live prefetch MSHR phases into `prefetchBusy`.
2. `MachinePlatform` forwards that to the backend's external prefetch-busy input.
3. `IntegerBackend` includes it in `memoryBusy`; trap admission depends on memory idle.
4. Trap/system redirect qualification contributes to `invalidateFetch`.
5. `SynchronousFetch` originally gates all packet payload writes with `!io.invalidate`.

The selected instruction translation adapter already registers its virtual response
valid. Existing `RegisteredTileLinkBoundary` instances also isolate A/D traffic with
occupancy-only ready. Consequently another fabric skid would not necessarily cut this
invalidation-to-payload-enable path. This is a source-level causal path, not a substitute
for inspecting the complete routed timing arc.

## Proposed cut

The trailing `SynchronousFetch.independentPayloadCapture` flag defaults to false.
When enabled, response words, their access/page fault bits, base/context tags and
shifted address keys capture under `response.fire && !pendingStale`. Cache-valid
installation and replacement-policy changes retain the exact original condition
`response.fire && !pendingStale && !invalidate`.

On same-edge invalidation, every valid bit clears and offered instruction validity is
suppressed. Capturing otherwise live-owner data into that now-invalid slot has no
architectural effect. Keeping `!pendingStale` is essential: a delayed stale response
must not overwrite a still-valid resident when invalidate is no longer asserted.
Request turnover, locked-request staleness, reply ownership and reset priorities are
unchanged. No pipeline register, new queue capacity, or extra response cycle is added.

## Planned proof

The existing mixed-length/fault/wrapping-PC oracle is retained. A separate generation-
and-context-sensitive oracle changes instruction bytes across invalidation, stalls
request acceptance, delays replies, changes contexts, injects coordinated reset, and
checks every visible instruction and precise access/page fault address. Explicit
negative controls corrupt a visible word, bypass invalidation, or clear a delayed
owner's stale bit. Paired baseline/candidate runs must preserve all cycle/witness
counts for two- and four-word packet geometries. Integrated CPU/board checks and an
actual selected-profile clock-enable census are separate promotion gates.

The initial new oracle incorrectly attached memory context to an unaccepted request's
first offer. Source review confirmed that the downstream instruction translation
adapter captures context on request acceptance, and InstructionPort contains no
first-offer context token. The corrected fixture binds immutable context/generation
at request.fire, preserves address/mask under request backpressure, and never retags
an already accepted response using live context. Four baseline seeds pass with
hundreds of stale/wrong-context replies, locked invalidations and request/reply
turnovers. Word corruption, stale-owner bypass and invalidation bypass are rejected.
Candidate A/B now passes with identical cycle/witness counts for all four seeds at
each width. Integrated verification remains pending.


`docs/evidence/fpga-fetch-payload-capture-20261008.json` binds source and generated
artifact hashes. In addition to data/exception oracles, the scoped CHIRRTL census
checks eight payload write sites for two-word packets and sixteen for four-word
packets. Their write-enable/address expressions no longer depend on invalidate,
and every one still depends on pendingStale. The one/two valid-install sites retain
both guards. This establishes a source-level timing cut, not a mapped/routed result.
The shared module extractor was corrected to stop at public-module boundaries,
preventing the public test wrapper's similarly named wires from entering that census.
