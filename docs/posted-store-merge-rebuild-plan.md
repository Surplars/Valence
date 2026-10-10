# Posted-store merge reconstruction, review checkpoint 1

This is a new design against published dev tree
`7cd0de740e4f565e48a8355844315c3f7740bf7b` (published commit
`c3534055846c5eca1697ffff1feddb2282cba65a`; local publication replica
`a1e450589d52c20f6a99439519ced0cfd40480cb`). The isolated source directory is
`posted-store-merge-rebuilt-r1`, branch `rebuild/posted-store-merge-r1`.
It does not contain the separate translated-response-flow experiment.

No lost production body, old execution receipt, old PASS, or historical speedup
is restored or claimed. The rescue manifest is a reference inventory only.
The initial review had no production changes. Checkpoint 1 now adds only the
standalone disabled owner/proof/config source and host oracles. No existing
production file changed and no hardware execution ran. The current frozen
interface and limitations are in simulator/gsim/posted_merge_rebuild/README.md.

## Opportunity and scope

The published IntegerBackend already authorizes naturally aligned physical RAM
stores at the real ROB head using the current data privilege and PMP result.
StoreBuffer assumes an explicit no-write-error RAM aperture and retires such
stores before they reach the cache. The private cache currently makes a store
miss a barrier until its normal response, preventing younger buffered stores
from joining that miss. The optimization transfers that existing irrevocable
responsibility into a bounded cache owner, releases the ordinary response
credit early, and combines younger contiguous same-line posted stores.

Sv39 stores stay on their current precise, recoverable fault path. Translation
or PMP success does not imply that a later RAM transaction cannot fail. An
independent virtual late-ACK merge would retain retirement serialization while
adding ownership machinery; it is excluded from this reconstruction.

## Production files and exact responsibilities

All paths below are inside this new source namespace.

- `src/main/scala/core/ooo/PostedStoreMerge.scala` (new): bounded two-line,
  sixteen-token owner; immutable full owner identity; byte overlays; ordered
  ACK/drain ledger; sealed runs; generation exhaustion; held install/release
  offers. No permission checking and no invented resource credits.
- `src/main/scala/core/ooo/PostedStoreProof.scala` (new): CPU-only sidecar
  bundles and optional transport payload wrappers. Capture the full RobToken,
  context epoch, original physical address/size/mask/data, actual head/PMP
  authority, StoreBuffer acceptance, and final checked boundary status.
  A proof refers to the captured request, never a current ROB lookup.
- `OooParams.scala`, `CoherentCacheConcurrency.scala`, `BoardSocTop.scala`:
  separate default-OFF merge feature plumbing. ON requires the staged checked
  coherent path, explicit successful physical-RAM contract, and initially the
  existing two-MSHR geometry. OFF preserves existing MSHR 1/2/4 and WB 1/2/4
  legal configurations and elaborates no merge storage/ports. WB reservations
  are a later independent flag and delta.
- `IntegerBackend.scala`: capture at the actual direct head-store transfer or
  accepted head LSU start, from the already evaluated PMP decision and full
  ROB token. Carry proof with the registered request FIFO. Produce no proof
  for virtual/FP/atomic/load/MMIO/uncached or uncommitted speculative stores.
  Incorporate aggregate external posted busy into memory drain/CSR/trap rules.
- `LoadStoreUnit.scala`, `ParallelLoadStoreUnit.scala`: optional captured
  sidecars selected with the real request owner and existing held arbiter.
  The shared `DataRequest` definition and its fields remain unchanged.
- `StoreBuffer.scala`: store optional proof in the same slot and on the same
  enqueue/flow/drain events as its original request. Only its accepted legacy
  posted store can gain the accepted-buffer responsibility bit. Direct bypass
  and speculative read paths cannot manufacture a proof.
  Gate new locally forwarded loads while external posted responsibility is
  live; the downstream ordered gate alone cannot constrain local responses.
- `IntegerCore.scala`, `MachineCore.scala`: optional proof/epoch/busy wiring.
- `DataTranslationAdapter.scala`: sidecars in actual ingress, saved, translated
  and checked payloads; every bypass uses the same source as its DataRequest.
  Preserve captured original authority through identity routing; do not turn
  identity-path fault=false into physical permission. Capture checked status
  with the checked request. An older held proof cannot acquire a new epoch.
- `MappedMachineCore.scala`: ordered drain gate immediately after the checked
  physical boundary and before both APLIC routers. Older accepted posted work
  must still pass during a global fence/recovery wait. A non-posted request
  waits for aggregate posted drain; it is not a global prohibition on draining
  the very stores that the fence is waiting for.
- `MachinePlatform.scala`: proof passes alongside the existing request through
  the combinational external-memory branches of the platform routers; assert
  exact request association and no proof for local MMIO. Route aggregate cache
  responsibility back to the core. No DMA/PTW request gains CPU authority.
- `NonBlockingCoherentLineCache.scala`: atomic owner/MSHR/set/victim/response
  reservation; separate posted MSHR kind and acquire return tag kind; actual
  refill-to-overlay capture; true SRAM/tag/dirty installation; ordered ACK,
  token drain and owner/resource release. Preserve the original acquire engine
  entry/source counts and existing WB mechanism.

Any additional real request register found during integration must transport
the complete sidecar under the same handshake. A disconnected test-only proof
producer is not an integration result. Shared downstream CPU/DMA/PTW request
buffers are after the cache and do not need posted-store authority fields.

## Owner interface contract

The names below describe the proposed interface; implementation review may
rename them without changing the contract.

- `enq`: immutable request plus full CPU proof only. On a new line, a separate
  acceptance-time cacheAdmission supplies the actual free MSHR, set,
  way, victim address/state and owner generation. A join retains that exact
  reservation. Admission is a payload/state query, independent of enq.valid.
  Resource candidates are not immutable offer payload or speculative resource
  ownership; they may change while the original upstream store remains held.
- `accepted`: observed enq.fire with full token, full line owner, new/join and
  reservation. Cache responseTail is reserved on the same event.
- `acknowledged`: input event from actual cache upstream.response.fire with
  the matching full token and owner. Merely making response.valid true is not
  ACK. The ordered response ticket may be reused after this handshake.
- `acquireIssued`: observed actual TL A.fire, associated with the original
  owner. Engine request.fire reserves an engine slot but does not prove A.fire.
- `refill`: successful real engine completion, including original posted
  kind, full owner, eight data beats, T permission, hasData and completed E.
  Per-owner storage accepts out-of-order returns without blocking the older
  return behind a held younger engine result.
- `install`: irrevocable oldest-ready full owner/address/merged line offer.
  Actual fire writes all eight SRAM banks, tag, valid and dirty state once.
  Same-edge admission/refill/install priorities are explicit; a sealed or
  refilling owner cannot accept a late join.
- `drained`: oldest accepted full token whose real ACK and installation both
  occurred. No duplicate token and no success drain after a contract error.
- `released`: full owner/reservation after every member drains and no acquire
  responsibility or attached original WB ReleaseAck remains. Only this event
  releases the corresponding posted MSHR/set reservation. The conservative
  first merge therefore cannot reuse an MSHR beneath an older WB. Release
  never writes the old response ticket.
- `busy`: registered accepted responsibility, including response ownership,
  line owners, held install/release offers, exhausted fallback and any older
  attached WB responsibility. Never infer busy solely from current ingress
  valid. Recovery seals accepted owners but cannot cancel them.

The checked ordered gate queries older downstream posted responsibility; it
must not gate against a raw upstream FIFO-busy bit that includes the blocked
request itself or younger stores. The backend separately prevents new
non-posted load/LSU launches during a live posted epoch, preserving already
accepted irrevocable drain.

Owner identity is slot plus a monotonic full generation, separate from both
ROB token and normal response ticket. Generation exhaustion is sticky until
reset: seal, drain, then hand the exact original held request/proof to the
legacy path. Do not wrap, fabricate a new generation, or drop an offer.

## Coherence, ordering and prefetch

The minimum admission policy admits only an otherwise admissible physical
posted store or a join of the newest unsealed same-line run. Different-line
allocation seals the earlier run; same-line-after-seal waits and later falls
back or obtains a new generation. New non-posted work is an ordered boundary.

Before actual A.fire the absent target line can answer a real probe with N.
After A.fire and through E/refill/installation it is transient and a probe
waits. Once installed, probes must progress even if the transfer ACK is held;
a later ACK/drain/release cannot write SRAM or resurrect invalidated bytes.
The old victim remains a distinct coherence responsibility, including a clean
valid victim whose protocol still requires a voluntary Release.

No new prefetch candidate or acquire is admitted during a posted epoch or a
held posted transfer. Existing prefetch, WB and miss owners drain before the
first posted epoch is admitted. Probes and already owned C/D/E traffic remain
live. Loads, MMIO/APLIC, LRSC/AMO, fences, instruction synchronization,
PMP/SATP/privilege changes and traps respect aggregate responsibility. Ordinary
fence needs coherent installation; instruction synchronization retains the
existing dirty-flush requirements.

An error after legacy ownership ACK violates the platform's successful-RAM
premise. Record/assert that violation, seal and retain responsibility; never
report a recoverable virtual-style success or erase an errored owner. Precise
pre-ACK virtual and ordinary faults are separately tested on the unchanged
path.

## WB reservation handoff, deferred delta

The merge checkpoint does not relax wbFree/wbSpace masks or add WB capacity.
It reuses the current scheduler and conservative admission, and retains a
posted MSHR/owner through its attached WB ReleaseAck. The subsequent WB
optimization needs an explicit reserved/live ledger, keyed by full posted
owner/cohort/epoch/generation and real victim identity. Reserve every valid
victim, including clean ones when Release is required; bind that reservation
to the C source at actual eviction start; preserve it through final C and real
ReleaseAck even if the originating MSHR is reusable. Cancel only a genuinely
removed pre-eviction victim. Reserved+live must never exceed physical slots;
two reservations must each be able to consume their own slot. No ACK/cancel
slot may be reassigned on the same edge. Old WB lineage cannot authorize a
new posted cohort. The merge owner exposes the lifecycle above for this work.

## Minimum chunk order and qualification

1. Review and pin this design; build new host-only event/provenance/byte models
   and mutation checks. Reuse recovered exact helpers only as labeled
   immutable references. No old test result is inherited.
2. Implement and freeze default-OFF standalone owner/proof/config checkpoint.
   One accepted store/cycle and one response/drain per cycle when uncongested;
   capacity two 64-byte line owners and sixteen store tokens; one real SRAM
   install/cycle; held offers stable. No resource or speedup claim yet.
3. Connect real CPU lineage, queues, StoreBuffer and common ordered gate.
   Freeze source and obtain the parent-granted heavy slot before Scala/GSIM.
4. Integrate actual cache/home lifecycle and independent component/CPU gates.
   Compile once after the coherent chunk; run bounded affected GSIM fixtures.
   Repair failures before measuring. Do not invoke Verilator or Vivado.
5. Run fresh identical-guest A/B and native resource/port census against the
   exact published baseline. Qualify one optimization at a time. Checkpoint
   source and evidence, then parent publishes verified qualified commit to dev
   only with CAS. Do not accumulate an unrelated unpublished WB delta.
6. Assess and implement WB reservations only after the merge lifecycle is
   qualified, as a separate default-OFF commit and measurement.

### Independent oracles and required cases

- Author scalar stores as address/value/size and expand byte expectations
  independently of aligned DUT lane masks. A separate memory/home model
  supplies fill bytes at actual coherence ownership, not at store acceptance.
- Record instruction/head full tokens from the executing CPU. Compare exact
  request/proof payload at each actual boundary fire, including FIFO/SB flow
  paths and identity translation. Corrupt each field in negative host tests.
- Count architectural response handshakes independently of offered response
  valid; deliberately wrap response tickets while line owners remain live and
  detect any late write to a reused ticket.
- Exercise duplicate/stale full tokens, same slot/new generation, tiny
  generation exhaustion, held fallback, ordered barrier progress, two lines,
  overlapping bytes, subword masks and readback/flush backing bytes.
- Independently schedule A/C/D/E stalls, D return order, Grant permission/error,
  dirty and clean victims, probes before A, after E before install, and after
  install while ACK is held. DMA writes before A affect refill base bytes;
  DMA writes after install must survive all later ACK/drain/release events.
- Hold every offer; change context attempts while proof is held; stop new
  head authority for fence/recovery while older accepted stores keep draining.
  Ordered load, local APLIC/MMIO, AMO, SFENCE/PMP/SATP/trap cases are mandatory.
- OFF elaboration must prune owner/proof storage and preserve all existing
  legal capacity geometry. ON illegal geometry fails at elaboration. Native
  census checks original acquire/MSHR counts, SRAM banks/ports, new storage
  and combinational structure. Routed timing remains unverified without a
  separately authorized synthesis run.

The salvaged cache oracle snapshots each line's original bytes at acceptance
and its dma_write helper rejects pre-install writes. It therefore cannot by
itself establish the required before-A DMA case. The new independent home/byte
oracle must cover that case rather than silently claiming the old helper does.

## First standalone execution checkpoint

The coherent d0408c0 component gate passed: host 22 cases/10 semantic mutants,
three transport checks, three Scala/config/elaboration checks, eight positive
and eleven expected-assertion generation64 GSIM cases, and a distinct
generation2 exhaustion/fallback case. ASan/UBSan reported no error. Exact
source/tree/receipt binding and case results are in
`simulator/gsim/posted_merge_rebuild/component-results.json`. This qualifies
only the environmental standalone owner; actual CPU authority, cache SRAM and
TileLink/home reachability still require the independent integration gates
described above. No prior lost-source result or speed claim is inherited.
