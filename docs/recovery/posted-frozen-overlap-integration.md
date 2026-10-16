# Posted/frozen cache-overlap integration qualification

Test-only overlay on `48d0b15fb28b5e9c9774fe5c1a1e749d9aedb3bf`, in an isolated worktree. No production changes. This is a component-chain GSIM test, not an executing CPU, retirement test, Linux benchmark, or board timing result.

## Boundary and actual producers

`PostedFrozenOverlapChainGsim` connects the actual four-slot ParallelLoadStoreUnit, RegisteredRequestQueue (including atomic sidecars), two-entry StoreBuffer, DataRequestBuffer, DataTranslationAdapter, permission/translation service, physical routers, native cache, coherent home, and DDR bridge. The native profile supplies 512 cache lines, two ways, 256 sets, two read MSHRs, two response entries and two writeback entries. RAM aperture is 0x80200000 plus 2 GiB; the independent host backing model supplies only the touched 64 KiB. DDR service is four read credits, 80-cycle read latency, one cycle per beat. OFF and ON differ only in the static cache overlap option.

The MemoryOperation input is an explicit bounded backend/ROB-head authority premise. This wrapper does not generate ROB authority, translate a frozen VA upstream, or test retirement. Physical posted operations carry originalPhysical/integerOrigin/headAuthorized/physicalPmpAllowed at that boundary. Their legacyPostedAccepted and finalChecked input bits are false. The actual StoreBuffer produces legacyPostedAccepted; the actual translation/permission adapter produces finalChecked. Checks observe every accepted transition. Virtual frozen operations carry the distinct canonical/frozen binding and never posted authority. The existing LSU assertion prohibiting frozen+posted remains intact. A registered comparison of host PMP CSR inputs publishes changes at the CSR boundary; the final permission checker is actual hardware.

## Cases and independent checks

1. Two physical posted stores on one line create one real posted context and join it. Cache responses are held while both original LSU owners finish early. Full-token/context/ticket ACKs then drain exactly once, the real StoreBuffer completes both members, sealing releases the context, and all owner/response credits drain.
2. A conflicting dirty replacement is followed by a resident virtual frozen store. ON accepts exactly one resident store in eCapture; OFF accepts none. The actual integer handle domain is 0–3; posted buffered owners use 4–5. Frozen permission checking and actual return are required.
3. PMP denies a frozen store without physical escape and preserves its original VA/cause.
4. A stale prechecked permission epoch produces a fault without physical escape.
5. A canceled queued owner consumes its actual response and releases its handle without architectural completion.

Intent-derived bytes, observed request payloads, actual accepted handles, full high-generation tokens, held response stability, posted member identity, completion order, and final flushed backing memory are checked independently of DUT assertions. The unmodified shared oracle and DDR model are hash-bound. Six host-observation mutations per model must report ACTUAL_CORRUPTION and fail: premature store success, stale handle, wrong owner, duplicate return, high generation corruption, and returned data corruption.

## Result

Both OFF/ON five-case suites pass with ASan/UBSan. All twelve mutation runs fail as expected. In the fixed frozen scenario, OFF cache acceptance/reply/completion cycles are 354/356/358; ON is 353/355/357. This is a one-cycle overlap witness, not a CPU throughput measurement. In both models physical posted starts are 11/14, local completions 13/16, and cache ACKs 26/27. Response holding and two sequential starts are deliberate test service, not a maximum-throughput workload.

The original r3 receipt remains at `build/gsim/posted-frozen-overlap-r1/qualification-r3/receipt.json`. Its 51 artifact hashes were checked, but its reuse path bound only the wrapper before hashing existing objects. It does not prove complete original production-source/tool provenance and must not be upgraded retroactively.

The hardened fresh build, exact-manifest reuse and all six provenance-negative checks PASS. The latter reject a legacy manifest, stale revision, changed production source, changed tool identity, an actually corrupted generated header and a missing compiled object; original bytes are restored and revalidated. The hardened fresh qualification uses `build/gsim/posted-frozen-overlap-bound-r7/`. Its original manifest is created only after the runner itself performs both elaborations, GSIM generation, C++ compilation/linking and positive/negative qualification. It binds the full production and test Scala tree, project/build inputs, runner/host/shared-oracle headers, exact original revision, tool binaries, Mill distribution, Java runtime and resolved compiler/elaboration jars. Every emitted FIRRTL/header/model/object/executable is inventoried. Missing/legacy manifests, changed source/revision/tool/flags, and changed or missing model files fail before any reuse execution. Reuse runs the original executables without relinking or relabeling their source revision.

## Reproduce

From the isolated repository, source the established cloud environment. Scala dependency inventory must already exist from the normal Scala compile. Use a new build root for each fresh qualification:

```
python3 simulator/gsim/posted_frozen_overlap_build.py --build-root build/gsim/posted-frozen-overlap-fresh
python3 simulator/gsim/posted_frozen_overlap_build.py --build-root build/gsim/posted-frozen-overlap-fresh --reuse-models --qualification reuse
```

The first command owns both focused elaborations and builds both models once. Reuse also requires identical JAVA_TOOL_OPTIONS, including launcher/environment options; changed options deliberately fail closed. The recorded run restored the original options from its immutable fresh emit log before reuse. GSIM may be overridden with GSIM; compiler uses GSIM_CXX. A new qualification directory is mandatory to preserve prior evidence. Run `python3 simulator/gsim/posted_frozen_overlap_provenance_test.py build/gsim/posted-frozen-overlap-fresh` once after reuse to check provenance rejection. Profile eligibility assertions mirror the production cache factory before enabling shared-write controls. As in MachinePlatform, the core posted configuration is shape-only; actual geometry and enabled state are supplied from the checked physical profile.

## Virtual-store supply question

StoreBuffer.scala excludes virtualized requests from buffered local ACK (57–62,128–130). A virtual frozen store follows the direct precise-response path. LoadStoreUnit.scala only completes the ordinary store after its actual response (149,249,299). IntegerBackend.scala's bound-head qualification (1568–1582) requires the exact unfinished current head. Consequently head advancement and the next virtual store depend on completion/retirement despite a cache that can accept disjoint stores more frequently. This source dependency is a bottleneck hypothesis; it is not a measured Linux ceiling.

A safe next measurement would use the exact current native board and short matched physical M-mode versus warm-TLB S-mode store loops, recording full-token start/queue/checked/cache/response/completion/retirement and inter-store spacing, plus LSU/SB/response occupancy, cache blocked reason and AXI service. Existing `held_alu_forwarding/held_observer.h` has actual started/completed/retired owner timestamps; `tagged_store_return_board/host/cpu_passive_bandwidth.cpp` has ROI/physical/LSU occupancy counters. This component fixture stops at completion. Any future translated posted path requires a new terminal translated/permission-checked physical authority at the correct commit/epoch/drain boundary; relabeling frozen permission as posted is invalid.
