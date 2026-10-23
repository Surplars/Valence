# R36 measured CPU quiescence timing cut

R36 routed CPU300 setup worst path is `dt/fastWriteTag_14_reg[10]/C` to
`runtime/cpuObservation/held_reg[3]/D`: 20 logic levels, data 5.637 ns
(1.310 logic + 4.327 route), skew -0.206 ns, slack -2.619 ns.
The actual path passes late TLB permission, translation READY/physical VALID,
D-cache upstream VALID, cache quiescence, privateDrained, and runtimeHeld.

## Structural change

The management observation now uses a conservative early request/owner bound,
not a delayed held bit. Translation exports a registered owner observation:
non-idle stateStorage or separately pending response. Instruction pending also
includes fetchRequest.valid **after** the parcel aligner; a second word can be
issued after the original core offer disappears. Data pending includes both
translators, original data/fetch offers, and private arbiter active/offered.

This bound replaces only the cache upstream-request veto and the private
arbiter's request-valid reduction in quiescence. All response/probe/B/D/E,
lineGrant, flush, classify, forward, stateStorage and effective-state vetoes
remain live. Assertions prove each physical/walk request has an original offer
or registered translator owner, and each cache request is covered by its bound.
No late permission signal is ORed back into the management proof.

Normal request admission, ownership, queue capacity, credits, and throughput are
unchanged. Management drain may conservatively wait for a pending early owner
that ultimately emits no request; it cannot release earlier. No added held
pipeline may conceal a newly arriving probe. No reset distribution is changed.

## Focused evidence

- Combined Scala compilation and I1CacheQuiescenceSpec passed.
- `build/gsim/i1-cache-quiescence-r37-early-owner/receipt.json`: actual GSIM PASS,
  including an early pending owner without an actual request, partial refill,
  held E, held CPU response, dirty ReleaseAck, post-flush probe and native response.
  Independent negative oracles and ReadFirst semantics witness retained.
- Independent source review checked aligner second-word, translation fastHold,
  send-to-receive override, result handoff, PTWs, and arbiter turnover coverage.
- Actual three-clock I1 runtime test passed under `out/r37-i1-runtime-cdc`:
  two unrelated/reversed clock configurations, each six terminal epochs,
  three actual AON timeouts and one coordinated reset abort; independent
  wrong-data/store/IRQ negative oracles rejected. Frozen source hashes passed.

Component live-probe veto and modeled epoch-proof revocation are not claimed as
an injected end-to-end post-held probe test. New physical timing and board
qualification remain pending; no frequency improvement is inferred from code.

## Additional measured translation lookup family

The focused CPU top30 also identifies saved_address[37] -> superPageHit2 ->
wide selected-entry control -> state/result fault outputs, slack -2.422 ns
(data 5.545 ns, route 4.515 ns). Lookup now evaluates the direct-mapped leaf hit
without first selecting its index through superPageHit. Per-entry permissions
are computed before selecting a one-bit leaf grant; dominant superpage grant
selection is last. No cycle, capacity or PA-payload path is added/changed.
This is the identity `super || leaf[index(super)] == super || leaf[leafIndex]`
with superpage priority preserved for permissions. All canonical/stale,
privilege, SUM/MXR and R/W/X/U/A/D checks remain required.

This does not fix the separate memPacket-to-cache BRAM address/classify family.
Those functional payload paths need further measured design work rather than
an unverified admission pipeline. No claim that every setup violation is closed.

The added lookup rewrite passed the real 16-entry banked I/D MMU-interface RTL
oracle (`out/r37-setup-batch/tlb-check/receipt.json`): 144 trace rows, 11,101
checks, 8,071 data and 3,030 instruction responses, maximum one physical data
owner. New directed 2 MiB/1 GiB superpage slices and dynamic SUM checks join the
existing permission, canonicality, SFENCE, PMP, context and backpressure cases.
The independent PA-corruption negative was rejected. This is MMU-interface
verification, not a new complete CPU program or physical-timing claim.
