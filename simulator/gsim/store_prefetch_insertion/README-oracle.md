# Store-origin prefetch insertion: independent preparation

Source inspected: frozen combined-reconstructed HEAD d31bbf3afc7fb4fd4e6682a036c382f63d811773.

This directory is separate from all active and frozen source/model trees. The C++ program is an authored host-only replacement and origin specification. It includes no DUT source, generated model, or RTL; it uses an oldest-to-newest list rather than the cache's victim bit. It does not establish that the DUT implements the specification, prove coherence or permissions, predict performance, or substitute for actual cache/CPU tests.

## Candidate boundary

- Default OFF. Enable MRU insertion only for successfully installed, captured store-origin prefetch fills. Keep read-origin prefetch LRU and demand MRU.
- Reuse storePrefetchOwner(fillMshr), gated by prefetchOwner(fillMshr). PF requests have write=false; fillRequest.write is not origin evidence.
- Change replacement metadata only. Do not change prediction/history, permission checks, candidate admission, MSHR/response/WB capacities, victim selection, dirty state, TL ownership, request/reply ordering, or line tracking.
- Require the new option to imply storeNextLinePrefetch. MSHR=1 continues to reject prefetch ON. Ways=1 remains a no-op for replacement, not an unproven two-way behavior claim.
- Current demand victim selection is invalid-first then LRU, not clean-first. The prefetch victim chooser is clean-first, then permits a store-origin dirty victim. MRU can move an A demand eviction onto a dirty alternate; it therefore needs writeback/data checks and AW/W measurements.

## Host checks

replacement_oracle.cpp checks policies OFF/ON, ways 1/2 and owner capacities 2/4:

1. Authored two-way A/B conflict: a store PF replaces clean way 0; the next distinct same-set A demand evicts it under LRU, but evicts the alternate under MRU. The following B lookup is correspondingly miss/hit.
2. Read-origin prefetch remains oldest with either policy.
3. Both directions of candidate-origin change between allocation and refill leave captured origin intact.
4. A freed owner deliberately retains stale store origin; demand allocation overwrites it and receives a demand completion.
5. An error neither installs data/tag validity nor updates replacement order, with the snapshot taken after prior victim invalidation.
6. One-way placement and absence of replacement metadata remain unchanged.
7. All 2/4 slots allocate independently to separate sets with one live PF and the remaining owners demand, then complete in reverse order with correct owner identity and drain. Both read and store PF origins are covered.
8. Five intentionally wrong mutations must exit 1: store still LRU, read wrongly MRU, live candidate substituted for captured origin, stale demand origin, and error updating replacement/install state.

The host owner generations are an independent test oracle to reject stale completion bookkeeping; they are not a proposed DUT register or claim that the current RTL implements generation tags. Capacity traces keep at most one live PF owner, matching the actual cache's admission restriction. They do not model cycle-level scheduling or the acquire engine.

## Focused actual DUT test plan (NOT RUN here)

### Configuration and elaboration

- Add the flag at the cache configuration and FPGA profile/CLI boundary with OFF defaults and unchanged capacities. Test both FPGA emitters accept it and profile naming distinguishes it. It should not need an OooParams permission/LSU switch.
- Check MSHR=1 OFF retains the legacy path and ON is rejected. Check MSHR=2/4 with enough sets (sets >= MSHRs), responseEntries >= MSHRs, legal WB=1/2/4, and valid overlap choices.
- Elaborate ways=1/2 and full/compact/banked tag configurations. The MRU way-bit expression must remain inside replacement.foreach so one-way elaboration does not introduce a bogus way bit or new replacement state.
- Verify disabling the new flag leaves the existing refill assignment and architectural/configuration choices unchanged.

### Small real cache + home + backing-memory fixture

The existing CoherentCacheHomeGsim wrapper hardcodes ways=2 and does not expose storeNextLinePrefetch. Adapt it explicitly; existing read-prefetch tests alone do not exercise this feature.

- Build the authored same-set conflict with two valid ways, an eligible clean PF victim, a verified store-origin allocation and successful installation. With identical accepted requests, require OFF to evict the live PF line and ON to evict the alternate, then witness the real B-store hit/miss. Also swap the two physical ways.
- Repeat with the alternate clean and dirty. Check every released dirty byte against an independent backing-memory oracle, acquire/release source identity, exact reply count/order and terminal drain. MRU changes the victim; it must not erase dirty data.
- Read-origin negative control under both flags; ordinary demand fill/hit MRU; invalid-first selection regardless of replacement; two intervening same-set conflicts to show MRU is not a pin/lock.
- Test captured origin and free-slot reuse: store PF -> freed slot -> direct demand eviction, queued demand eviction, then read PF; read PF -> store PF. Hold ReleaseAck so saved WB origin outlives MSHR reuse. Keep the existing directEviction stale-origin exclusion unchanged.
- Exercise WB=1 serialized and WB=2/4 overlap paths where legal, MSHR=2/4, different-set hit simultaneous with refill, held CPU response, and same-set CPU offer during refill. Same-set admission must remain blocked; both different-set recency updates must survive.
- Denied/corrupt PF response: no install or replacement update, no spurious CPU response, error/busy/owners drain. Follow immediately with a new owner to catch stale origin.
- Probe incoming PF line before installation (must wait); probe installed PF line; probe alternate way in the refill set; probe/dirty release and delayed acknowledgement. Full-data and owner ledgers remain authoritative.
- Flush, bypass/atomic/MMIO and context/protection transitions while candidate/fill/release exists. Confirm no unauthorized line request or changed barrier ordering. Retain existing page-boundary, PMP, PTE and RAM-aperture negative controls.
- Ways=1 run the legal owner/backpressure/error controls as applicable and show that flag ON/OFF cannot change replacement choices. It cannot solve a one-way conflict.

### Matched actual CPU replay

- Isolate policy by comparing frozen C-equivalent configuration with MRU OFF against that same configuration with MRU ON. Prepared-store lookahead and checked-store PF remain ON on both sides. Historical B vs C toggled two features and does not isolate this change.
- First use the exact same recovered 1472-byte S kernel and 128-KiB case 20 WRITE and case 21 COPY, Sv39 4-KiB. Pin DUT/config/model/guest/kernel/observer hashes and start each case from reset with original initialization/warmup/verification/flush.
- Report elapsed ROI ticks and flush-tail ticks separately, candidate/allocation/useful counts by origin, PF error/probe/install/live-eviction counts, AR/AW requests, declared/accepted R/W beats, B responses, owner occupancy/stalls and accepted terminal full drain. No fixed speedup threshold or expected counter total is imposed.
- COPY success evidence must follow actual allocation -> captured PA/slot/origin -> installation -> live generation -> same-set A decision -> actual B-store hit/use or invalidation. Do not infer useful work merely from chronological later accesses, and do not treat lower AR counts alone as a correctness pass.
- Compare WRITE usefulness and traffic as well as ticks; preserving WRITE cannot be assumed from the isolated replacement edit. Examine new dirty alternate evictions and writeback stalls if COPY read traffic falls but ticks do not.
- If 20/21 pass, extend only the agreed short acceptance to 18/19 Bare and 22/23 Sv39 2-MiB with the same measurement contract. No full GSIM, Linux, FPGA synthesis/timing, Vivado, or board claim follows from this preparation.

## Why this before load-stream suppression

MRU is a small direct test of the witnessed two-way conflict. Suppression can also remove waste but needs a defined accepted-load/history lifetime and transition tests. The current read-history lastValid is sticky across ordinary stores when prefetchBreakOnStore=false; using it as a load-stream-present gate could suppress a later pure WRITE indefinitely. Do not widen stream classification in this candidate.

## Source findings

- NonBlockingCoherentLineCache.scala:91-92 origin registers; 353-354 demand overwrite; 590-591 PF capture.
- :425-459 successful refill and existing LRU insertion; :295-317 reserved-set/admission protection.
- :254-260 saved WB lineage and direct demand stale-owner exclusion; :603-605 dirty PF victim assertion.
- :281-285 demand invalid-first/LRU; :544-550 PF clean-first selection.
- CoherentCacheConcurrency.scala:17-24 prefetch/capacity restrictions.

No frozen or active source tree was edited. Validation details and exact hashes are recorded beside this document.

## Validation result

The final host source passed 472 checks with GCC AddressSanitizer and UndefinedBehaviorSanitizer; all five mutation controls exited 1 with the intended oracle failure. The compiler emitted no warnings. LeakSanitizer cannot run under this environment's ptrace runtime, so the validated runs used ASAN_OPTIONS=detect_leaks=0. The initial LeakSanitizer failure is preserved in positive-lsan-unavailable.log; no leak-check pass is claimed. No Scala, elaboration, GSIM, DUT/model build, synthesis, install, push or Vivado command ran for this preparation.
