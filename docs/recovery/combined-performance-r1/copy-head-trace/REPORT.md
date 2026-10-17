# COPY head/preparation bottleneck follow-on

## Result

The unchanged guest and saved model again produced 172,018 ROI cycles, 40,984 retired instructions and the identical complete original stdout. The original 32-pair CSV is byte-identical. No DUT rebuild or source change was made. Only a passive host timeline was added, in this sibling directory; the sealed original copy-trace directory was untouched.

For all 32 selected stores, prepared → Q spans 23–26 cycles. Continuous full-token records now account for all 780 waiting pair-cycles:

- 748 cycles: the store is not the actual full-token ROB head and is excluded from preparationMask.
- 32 cycles: the store is the actual head and eligible, exactly one capture cycle per store.
- Q has a live owner in all 780 cycles. S has a live owner in 716; S is empty in 64. These are observations, not a claim that Q occupancy independently caused exclusion.
- Every store reaches Q one cycle after becoming head, then S/accepted start one cycle later.
- Adjacent store starts are 10 cycles apart in 28/31 intervals, 13 in two, and 12 in one.
- Start → commit is 7–8 cycles (existing trace). Previous-store commit → next-store start is 3 cycles in 28/31 intervals, 5 in three.

The sample therefore identifies serialized head-store service/retirement and head-time preparation as the next limiter. Late load-data readiness is not the limiter: captured data becomes prepared well before head. The fallback preparation pool is suppressed by original memory candidates while these stores are younger. There is no measured extra head-eligible Q contention beyond the ordinary registered capture.

## Minimal next candidate, not implemented or qualified

Focus a coherent next change on one-cycle-early preparation for a guaranteed next head store, rather than another load-data bypass or global translated-response empty flow. A narrowly guarded head-successor Q capture can reuse already-prepared VA/data when the older head's accepted retirement guarantees this store becomes the next head; actual transfer/start must retain full-token, current-head, ordering, translation/PMP, recovery and backpressure gates. Preserve ready-load behavior outside that window. This targets the measured two-cycle head→Q→S/start tax, with only one cycle of saving defensibly targeted by a one-cycle-early Q capture. It is a design hypothesis, not a measured speedup.

Do not merely merge all younger prepared stores into the ready pool: an older but non-launchable store could occupy S and block younger loads. Do not turn on fastBufferedStoreRetire as a switch: the frozen profile explicitly excludes it, and its direct fast candidate is Bare-only. The 7–8-cycle accepted-start→retirement chain is also worth shortening, but this trace does not break it into translation, acknowledgement, completion and retirement subphases, so it cannot select a particular return-path bypass safely. Global translatedResponseEmptyFlow remains off.

Required focused proof/tests for a successor capture include full-token wrap/reuse, one/two-wide accepted commits and intervening nonstores, faults/traps/redirects, interrupt/context flushes, ready-load priority, store backpressure, and no early externally visible store. Keep the same COPY/READ/pure-store guests and service laws for the eventual combined candidate comparison.

## Integrity and execution

The first host compile failed on a generated field that does not exist; it ran no workload. The field was removed, the failed header retained as copy_trace-link-r1.h, and link-r2 completed in 16.61 seconds, peak sampled RSS 420 MiB. One workload execution completed in about 39.5 seconds, peak sampled RSS 229 MiB; all original CPU/oracle checks and COPY_TRACE_PASS passed.

The wrapper then exited 1 because another task added qualification-followup.json and advanced publication HEAD during the run. Its fixed two-document whitelist rejected that third document. Independent post-run checks in verification.json confirm all original source bytes, git diff hash, and every frozen model artifact remain identical. The exact added paths and hashes are recorded. The workload was not rerun. The stdout comparison removes only COPY_TRACE_PASS from simulation output; the separately identified wrapper Python traceback is not treated as simulation output.

## Files and interpretation

waiting.csv records each selected store from first prepared timestamp inclusive to Q entry exclusive, with immutable 68-bit owner identity, current head identity, live Q/S identities, preparation mask and accepted start identity. Stale Q/S token fields must be ignored when the corresponding live flag is zero. Sampling retains the original post-step/current-state semantics and does not read NEXT fields. analyze_wait.py checks complete contiguous per-owner ranges, exact previous CSV and stdout, and writes wait-results.json. verification.json binds source/model and run artifacts. The existing run.py preserves its original fixed publication guard; it is intentionally not silently widened.

The fixed 32-pair window is not a whole-workload distribution. No RTL, guest, traffic law, READ behavior, timing or physical performance claim follows from this passive run alone.

## Why non-head preparation was excluded

Non-head status is not inherently a bar to preparing operands. IntegerBackend.scala:896 defines the original candidates as ready loads or head stores. Lines 947–960 construct virtual prepared-store fallback operands, but PreparedStorePool.scala:17–24 selects Mux(original.orR, original, prepared), before excluding existing Q/S owners. The original pool's presence therefore suppresses the virtual-store fallback, even when only younger load owners would otherwise occupy preparation. The dataReady capture that sets storePrepared also sets storeAddressKnown (IntegerBackend.scala:3086–3092); selected owners have ordinary COPY sd instructions and live full tokens.

Across the 748 non-head waiting pair-cycles, the preparation mask is never empty. Live Q is eligible in all 748. Q is younger than the waiting store in 684 cycles and older in 64. S is younger in 620, older in 64, absent in 64. Joint Q/S age states are younger/younger 556, older/younger 64, younger/older 64, younger/absent 64. Of younger Q tokens, 616 records directly match a selected load full token and 68 lie outside the fixed pair window. Of younger S tokens, 575 directly match a selected load and 45 lie outside; none matches a selected store. See owner-age-results.json. Thus there is direct positive evidence of younger-load preparation priority, not merely an inference from non-head status.

Example at cycle 89327: waiting prepared store (15,20711), current head (5,20701), Q (2,20714), S (0,20712), preparationMask=21. Q/S both match younger load tokens. The store's index15 is absent from the mask.

An age-ordered merge of virtual prepared stores into the original pool could preposition Q/S and save up to the observed two head-time preparation cycles, but its net benefit is unmeasured. MemoryPreparationDescriptor.scala's descriptorAge < residentAge transfer rule would then let an older, non-launchable store replace a younger load in S; resident retention would park it until head or older-owner preemption. This blocks new younger-load preparation/launch during a real observed window, though already accepted LSU requests continue and an older head store can preempt it. The current trace is not a counterfactual performance simulation and cannot establish whether this trade wins. Prefer a guaranteed-next-head capture or explicitly distinct speculative-store descriptor/transfer eligibility, with existing ready-load service preserved outside the narrow window, over a global pool merge.

## Candidate A rejected; candidate B deferred

A proposed fallback-presence test after excluding live Q/S owners exposes 105 waiting pair-cycles, but these represent only 37 unique CPU cycles. Every such cycle has both Q and S occupied by younger loads, no accepted start, and no Q→S transfer at the next observed cycle. Thus the measured genuinely free Q opportunity is **zero**. The 105 count is not a speedup estimate. Simply changing the pool mux would remove existing load eligibility or preempt occupied load preparation, rather than fill an idle slot. Reject this simple A rewrite; no RTL experiment is justified from this window.

B is an independent single prepared-store holding slot or narrowly guarded retirement-successor/head pre-read, preserving younger-load MLP and actual head-only side effects. It remains an unimplemented option, not a qualified candidate. No real response, alias, fence, translation/PMP or precise-exception rules may change.

The banked store-data source instantiates two asynchronous read ports, but the qualified mapped envelope has one surviving functional read port per writer bank (POST_QUALIFICATION.md). Port1 supplies fresh Q savedData; port0 is the disabled fast-store/head assertion path. A separate holding slot that reads a different row on the same cycle as ordinary saved-store Q capture would require read arbitration or physical read replication. Prefer existing-port arbitration with normal saved-store capture priority, or capture from the already-authorized early preparation write payload. Neither needs another PRF port. Reviving head port0 as a functional pre-read must be accounted as an added physical read port, not free capacity.

No policy or RTL changes were made. Further strategy experiments are deferred until the independent strict-domain timing candidate finishes, avoiding simultaneous perturbations.
