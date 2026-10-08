# Virtual RAM load precheck candidate

Status: explicit `OooParams.virtualRamLoadPrecheck = false` by default. This is a bounded CPU-side concurrency candidate, not a routed timing/PPA result or a board acceptance claim. It does not change issue width, the cache's physical indexing, the external bus protocol, or the ordered response contract.

## Scope and timing contract

- One read-only DTLB peek per cycle; only already-successful entries may hit. A miss never starts a walker or changes TLB replacement state.
- Exact root PPN, ASID, mode, effective privilege, read permission class, SUM, MXR, VPN and existing superpage/NAPOT rules are shared with demand translation.
- Register cut 1 captures the full ROB allocation token, original VA, size, PA, PBMT classification and authorization epoch.
- A physical PMP read check, whole-transfer RAM containment, alignment and normal-memory qualification operate on that registered payload.
- Register cut 2 captures a positive or negative certificate. Preparation is opportunistic: a ready head uses a matching completed certificate if available, otherwise immediately takes the existing serial translation path. Only younger speculation requires the positive certificate. There is no current-cycle TLB-hit-to-issue path.
- Issue uses a matching full token, original VA, size and current epoch. A positive certificate enters the existing parallel LSU owner machinery. A miss, denied permission, misalignment, NC/IO mapping, device address or atomic/store uses the existing precise head path.
- The two issue lanes and configured LSU slot count remain unchanged. A two-slot profile can have two ordinary virtual RAM reads in flight. A new candidate does not become an additional LSU owner until the existing start handshake.

## Address and authorization contract

The LSU keeps the original VA for alignment, byte extraction and all exception `tval` values. A prechecked request carries its frozen PA and epoch to the translation adapter. The backend's alias/replay bookkeeping records PA only. Untranslated virtual serial operations are never marked canonical.

This first slice blocks a virtual speculative load behind every older live store and every older memory instruction lacking canonical PA. It does not speculate across unknown memory addresses or forward from an older virtual store. StoreBuffer local acknowledgements and forwarding explicitly exclude prechecked requests, so all such requests reach the physical authorization boundary. Disjoint buffered physical stores retain the existing ordering behavior.

The adapter never sends prechecked requests through the already-physical identity shortcut. It rechecks read-only shape, active virtual context, epoch, physical PMP and full RAM aperture, then clears the authorization metadata before the cache/MMIO fabric. Cache set/tag lookup remains PA-based, including PA bits 12 and 13 for the 32 KiB/two-way geometry.

## Context, recovery and ownership

VM context and implemented PMP CSR changes advance an adapter-local epoch. The wide snapshot comparison ends at the registered authorization boundary; the backend sees a registered epoch/stability signal. The final physical gate compares only narrow epoch/flush metadata. Architectural CSR, return and trap sequencing must drain accepted prechecked requests before changing context; an assertion tracks ingress-to-response prechecked owners and enforces that requirement.

Unused certificates are disposable and do not assert irrevocable memory busy. Context barriers, interrupts and recovery discard them without blocking an older CSR. Full allocation tokens plus pending-slot qualification prevent a killed proof from authorizing a reused ROB slot. Accepted cancellable reads still drain through existing request and response ownership, and stale completion rejection remains in the ROB. No outstanding response is abandoned on redirect.

## Verification and promotion

New focused fixtures and independent software expectations cover the preparation stage, real DTLB/adapter and backend integration. See the associated test reports for actual pass/fail/not-run status. The acceptance target includes warm-TLB overlap, aliases, MMIO/PBMT/permission fallback, original-VA faults, context changes, cancellation/token reuse, drain and external-coherence ordering. Missing test cases must remain explicitly unverified.

Before enabling this option in any board preset: run the focused short correctness/performance comparison, measure both warm overlap and cold/dependent-load behavior, then perform a combined local Vivado implementation against the saved 100 MHz baseline. The current design has limited timing margin; Scala elaboration and GSIM cycle counts cannot establish Fmax, routing margin, area or board behavior.

### Policy 1 focused cloud result (2026-10-08)

`build/gsim/virtual-load-precheck-cloud-r5/receipt.json` is the frozen focused result:

- Main Scala compile and test compilation passed.
- Seven GSIM models/variants passed: preparation; committed StoreBuffer drain; adapter off/on plus the enabled identity-flow combination; backend off/on.
- All deliberately poisoned oracle controls were rejected.
- Fourteen decoded-backend cases matched architectural results between off/on, including real branch cancellation/token reuse, older uncanonical memory, physical aliases, MMIO/PBMT serialization, actual PMP CSR drain/redirect/reissue, SFENCE remap and precise original-VA faults.
- The forced-latency warm-pair fixture observed peak physical outstanding reads 1 → 2 and 155 → 115 fixture cycles. A cold pair cost 142 → 148 cycles. These are directed backend fixture results, not a full-core workload or general IPC claim.

A separate same-ELF full-core experiment is prepared in `simulator/gsim/virtual_load_board.py`, with `build_virtual_load_core.py` and `payloads/virtual_load_core.S/.ld`. Its 768-byte guest was reproducibly assembled twice to identical ELF and binary bytes. It measures separate warm independent, cold-page and dependent-pointer-chain retirement intervals, with startup/warmup outside the intervals. The guest also checks wrong-path RAM/MMIO cancellation, one precise page fault and a physical alias store. The independent host uses the real selected board CPU/cache/fabric and fixed AXI model without artificial response holds. Execution status and exact source/image hashes belong to that experiment's own receipt; preparation alone is not a pass.


### Policy 1 same-ELF full-core result

`build/gsim/virtual-load-board-cloud-r1/receipt.json` passed the real selected two-issue/two-LSU board CPU, frontend, decoder, 32 KiB cache and 16-beat AXI path. The same guest ELF/binary and fixed AXI model were used for off/on. All six poisoned signature/trap/marker controls were rejected; the architectural signatures, precise trap and retired PC streams matched.

| Retirement-bounded region | Flag off cycles | Policy 1 on cycles | Retired instructions | Change |
| --- | ---: | ---: | ---: | ---: |
| Warm independent reads | 4422 | 1809 | 1159 | -59.09% |
| Four cold pages | 512 | 540 | 14 | +5.47% |
| Dependent pointer chase | 2311 | 2821 | 776 | +22.07% |

The warm region's live LSU peak increased from one to two. Its physical adapter request peak stayed one because of cache hits; the candidate reached physical peak two elsewhere in the run. Do not conflate LSU occupancy with downstream outstanding requests. No arbitrary host response holds were used. The full-core wrong-path checks passed, but late-response cancellation was not exercised there; that case remains covered by the focused backend fixture.

### Policy 2 verified candidate (still default-off)

The ready head no longer waits for the optional two-stage preparation. A completed matching positive certificate still selects frozen-PA parallel issue; otherwise the head immediately uses the unchanged serial virtual path. Non-head issue retains every proof, PA-domain, store, context and recovery guard. Serial acceptance clears the pending full-token owner, and the LSU captures its address mode once; a later unused certificate cannot relaunch or change that owner. The focused and unchanged-ELF results below establish the bounded effect of this policy. Earlier receipts remain historical evidence for Policy 1; physical promotion still requires local implementation.

Policy 2 focused verification passed in `build/gsim/virtual-load-precheck-cloud-policy2-r1/receipt.json`: seven GSIM model variants and all independent mutation controls, including eighteen backend A/B cases. Head-only warm/cold/bus-error cases matched flag-off cycles exactly (55/55, 72/72, 56/56). A head serial owner held under 95 cycles of physical backpressure retained its VA, token and serial mode while a later certificate arrived, then passed ROB reuse. Divider-backed non-head overlap still reached two reads; delayed cancellation and stale-response reuse remained covered. The same-ELF board rerun is tracked separately and was not part of this focused receipt.


Policy 2 same-ELF full-core acceptance passed in `build/gsim/virtual-load-board-cloud-policy2-r1/receipt.json` (SHA-256 `c3f3318bfacced9c1784e5be97aa1917a6cdaa63b5d47acda78c7402faa23e02`). Both variants retain the same ELF (`f765b74a970485008d9bd0e85d88f349f0e2ac9bbf5664706272d2a0e59e129e`) and binary (`3360eb85d6f376c2b1684eb2e7be01481b4bca02ef49efbfab3f2dabc582e449`). All six negative controls rejected their changed expected signature, trap or interval; architectural signatures and retired PC streams matched. The baseline metrics also match Policy 1's baseline.

| Retirement-bounded region | Flag off cycles | Policy 2 on cycles | Retired instructions | Change |
| --- | ---: | ---: | ---: | ---: |
| Warm independent reads | 4422 | 1809 | 1159 | -59.09% |
| Four cold pages | 512 | 538 | 14 | +5.08% |
| Dependent pointer chase | 2311 | 2311 | 776 | 0% |

Warm-region live LSU peak is one → two; physical-adapter peak is one in both cache-hit runs. Policy 2's full-core cancellation counter witnessed one outstanding cancelled owner; the longer late-response/ROB-generation-reuse proof remains in the focused fixture. These are directed CPU workload results under the pinned fixed AXI host model, not a general application IPC/Fmax/DDR-physics claim.

### Bounded residual-cold diagnosis

Passive replays in `build/gsim/virtual-load-cold-diagnosis-policy2/analysis.json` used the existing hash-verified model objects and unchanged guest. Only a trace-only host copy was relinked; production files and acceptance receipts were preserved.

The measured +26 cycles remain real, but their location is now known:

- The identical instruction-cache line at `0x80200080` begins its AXI read at cold-marker-relative cycle -39 with the flag off and -14 with the flag on. Both refill-to-install intervals are exactly 49 cycles, completing at +10/+35.
- The faster warm loop hides 25 fewer cycles of that frontend refill. Empty-ROB time is 13 → 38 cycles.
- First cold data request acceptance shifts +70 → +95, exactly the same 25-cycle shift. Its AXI AR acceptance shifts +76 → +102: the enabled run additionally has AR valid with ready low at +101, then accepts at +102.
- Cold load retirements are +138/+261/+384/+507 versus +164/+287/+410/+533. The last three inter-load gaps are exactly 123 cycles in both runs.

Thus this bounded trace attributes the region difference to changed frontend overlap at the ROI boundary plus one AXI backpressure-phase cycle. It does not show extra per-load preparation latency. Do not subtract those cycles from the published ROI or claim cold workloads universally match; the directed head-cold test independently matches 72/72 cycles, and broader workload/interrupt/external-DMA/PPA validation remains outstanding.
