# First narrow checked-translation oracle

Status: source-only preparation. This document does not authorize generation,
compilation, linking, imports, or DUT execution. Those gates belong to the parent
and independent reviewer. All files here are new host source; DUT and shared
classes are untouched. Header/API verification and source generation are pending
explicit parent clearance.

## Bound implementation

- Fixture: `../source/CollectionReadTranslationGsim.scala`.
- Isolated DUT: `../../store-full-line-progress-stagec-r1/source/DataTranslationAdapter.scala`
  and `PostedCollectionRead.scala`.
- Actual selected profile:
  `../../ethernet-mac-cpu-line275-r1/model/actual-combined-timing-repair-gsim.json`.
- Four integer handles and two store handles; first store is handle 4 and read is
  handle 2. Both DataRequest endpoints retain all 184 bits.
- The production fixture derives PMP regions from the 16 raw cfg/addr inputs.
  The host never supplies decoded permission summaries or route decisions.
- Driver setters/getters are purely mechanical. All ports, including dormant
  translation/precheck/canonical interfaces, are initialized and sampled. PMP
  vectors use the generated header's whole-array setters after collecting every
  scalar element. One complete input line produces one step and full JSON sample.

## One first case

Name: `posted-owner-held-physical-ingress-read`.

1. Reset empty. While truly drained, select supervisor privilege, bare SATP, and
   exactly one RWX TOR region: cfg0 OFF/address0 = 0x80200000 / 4;
   cfg1 = 0x0f/address1 = (0x80200000 + 2 GiB) / 4. Other entries are OFF/zero.
   Assert pmpRawChanged with the raw update for one observed cycle. Observe actual
   contextChanging, then wait for stable and both epoch outputs equal to one for
   two consecutive samples. Keep VM/PMP and epochs unchanged thereafter.
2. Submit an ordinary posted store at base + 0x80 with handle 4, complete matching
   full-token proof, current posted epoch, all required lineage flags set,
   legacyPostedAccepted = 1 and finalChecked = 0. This proof is an explicitly
   authored environment premise; the fixture does not prove backend minting.
3. Compare every physical request field and every proof field. Require exactly
   the expected finalChecked transition, actual physical acceptance and actual
   return with exact handle/data/error/pageFault. Add external responsibility only
   on the physical posted handshake. Its real response marks responded but does
   not retire external responsibility. Only the later separate completion does.
4. With that older owner still live, submit a qualified aligned bare read at
   base + 0x208 with handle 2. Hold physical READY low. Require a real registered
   physical-ingress/checked transfer, physical qualification, and at least four
   stalled samples. Compare all 184 request bits and sidecar every time; selected
   translationEpoch is cleared, incoming hint is replaced by independently
   expected next-line permission, and other fields retain authored values.
5. Accept the read exactly once with externalBusy still true. Supply a known
   nonzero 64-bit response and stall upstream response READY for two samples.
   Compare exact return handle/data/error/pageFault and stable response. Retire
   this response once. Keep the older external owner live for additional cycles.
6. Author the distinct older external completion, then require complete owner,
   pending-offer, held-channel and interface drain and three idle samples without
   duplicate physical requests or upstream replies. Exact totals are two ingress
   acceptances, two physical acceptances, two physical and upstream returns, one
   busy qualified-read acceptance and one external completion.

## Independence and boundedness

The accepted request ledger, FIFO of not-yet-issued accepted IDs, physical handle
map and independent external token map advance using public handshakes or the
authored external event. Passive route taps cannot create or retire an owner.
Expected PMP permission is the explicitly authored one-region TOR contract;
expected lane shape is an enumerated byte set. Expected response payload is the
authored service event. Every exposed request and response scalar is compared.
The tested memory backing is synthetic, and there is no CPU/TLB/walker/cache/Home
integration claim or claim that the new bit has a real production backend minter.

Raw complete scalar input/output plus parsed values and authored events are saved
losslessly as compressed JSONL. SHA-256 bindings include host sources, generated
driver/header, fixture, actual profile and isolated DUT. Existing traces/results
are not overwritten. Narrow driver ceiling: 512 cycles; wait ceiling: 24 cycles;
trace ceiling: 128 KiB. Parent task cap remains 16 MiB for all artifacts and an
800 MiB free-space floor. The harness checks task bytes/free space before and after
execution. Parent must enforce those limits during generation/build as well.

## Proposed later cases, intentionally absent from first executable suite

- Qualified bare read through registered identity: accept eligible read into the
  ingress queue while checked is full, release checked space while translated is
  empty, and prove actual identityPass with matching request/qualification.
- Real spill: fill both checked slots with older accepted requests while physical
  READY is low, inject additional eligible reads, observe ingressQueued and an
  actual translatedEnqueue/translatedDequeue pair, then drain in FIFO order with
  exact handle/sidecar correspondence. A single older checked head does not by
  itself guarantee spill because checked has two slots.
- Wrong masks/alignment, uncached, atomic, unqualified, virtual and prechecked
  sources must not gain this qualification. Preserve accepted or stalled owners
  until legitimate older completion; never clear busy just to admit the test.
- A denied bare input is a synthetic upstream-trust violation. Bare physical and
  identity paths historically set fault false. It tests readPmp qualification
  filtering and busy ordering only, never a synthesized access fault.
- Actual fault placeholders require translated or prechecked requests that use
  checkPhysical. Hold behind the accepted older external owner; after its separate
  completion require one exact fault response and no physical request. Later add
  translation page/access faults, stale prechecked epoch and drained context
  changes. Such sources remain excluded from qualification.
- Additional response credits, errors, exact held-token/sidecar observation
  mutations and independent OFF equivalence need separate reviewed receipts.

No broad cases, fault stimuli, observation mutations, reset with live obligations,
or automatic second DUT run are included in this initial file.
