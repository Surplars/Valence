# M2: registered data translation result boundary

Status: focused module and actual-CPU four-control validation passed on 2026-10-24. M2 remains an opt-in **potential timing-for-latency tradeoff**, not a demonstrated performance improvement. It adds 50 work cycles to each measured VM guest. No new STA, Fmax, area, board or DDR-bandwidth result exists. Public Selected/A1 and `full-candidate` defaults are unchanged.

For the next development comparison, prefer the explicit `full-r1` experimental control: R1 preserved all measured CPU cycles and frontend metrics without M2's measured VM latency cost. This is not promotion to a default or physical qualification.

## Explicit controls and unchanged defaults

`CommonA1RebuildProfile` retains `full-candidate` exactly as the control and adds `full-m2`, `full-r1`, and `full-m2-r1`. M2 changes only `registeredDataTranslation=true` and `translationHitFlow=false`; R1 changes only `circularFetchPayload=true`. The public Selected/A1 defaults are unchanged. Profile validators reject incompatible routes rather than silently overriding a supplied configuration. `M2R1ProfileSpec` compares the complete configuration and effective core parameter products.

M2 retains two-wide issue/completion/retirement, ROB16, PRF48, LSU4, DTLB16, F/D, Sv39, PMP16, 32KiB two-way private caches, and the original two cache/Home miss owners. DTLB entries are not outstanding request credits. Neither this stage nor the four LSU slots invent external cache MSHRs, TileLink sources, or shared DDR credits.

## Module boundaries

| Boundary | Latency / initiation interval | Capacity and credit |
|---|---|---|
| Existing registered virtual ingress | At least one cycle, II1 | 2; captured request, complete VM context and canonical origin |
| Existing real DTLB / walker | Warm hit same-cycle; one miss walker | 16 TLB entries; result-queue occupancy grants admission |
| `DataTranslationResultBuffer` | One cycle, sustained II1 | Existing 8 results; no empty bypass or full-pop credit borrowing |
| `DataPhysicalPermissionEvaluator` | Combinational, no accepted ownership | No storage/credit; registered result plus epoch/PMP inputs |
| Existing checked request capture | One cycle, II1 | Existing 2; captures request/fault/next-line permission |
| Existing ordered physical-response ownership | Response latency is external | Existing 8 ordered owners including local fault placeholders |

The result buffer's READY is occupancy-only, so downstream physical READY and permission logic do not propagate into DTLB request admission. A full buffer cannot accept on its first pop edge. Admission resumes on the next cycle and can then sustain simultaneous enqueue/dequeue every cycle. This one-edge full-release cost is deliberately measured, not hidden in average throughput.

M2 removes the fast demand-hit result-to-checked bypass. A warm, non-atomic, normal-PBMT demand hit that formerly bypassed an empty result queue pays one additional cycle; a miss already traversed result storage. Identity/prechecked/atomic/uncached paths retain their existing conservative handling. Do not generalize this to “all MMIO latency is unchanged”: a normal-PBMT virtual mapping to MMIO PA with `uncached=false` could also have used the old bypass. MMIO ordering and permission are not relaxed. Warm prechecked loads are not evidence that the new demand-hit edge was traversed.

## Owner and permission contract

`TranslatedDataRequest` retains every existing request field, captured effective privilege, page/access fault, physical-check qualification, original VA, and complete canonical token/index/tag/epoch. Untagged ordinary requests retain ordered response ownership; the new record does not claim a nonexistent ROB token for them. Full VM context is captured before lookup; successful PA translation does not create new authority.

The pure evaluator preserves current read/write/LR/SC/AMO PMP access classes, full-width RAM interval checks, stale prechecked faults, sticky translation faults, and independent next-line READ authorization. A stale canonical store origin suppresses the certificate without fabricating a fault on an otherwise valid store. The canonical output is only a qualification preview. The adapter still emits a certificate only on exact checked enqueue FIRE from the translated owner route.

PMP and authorization epoch are evaluated under the existing architectural drain contract. Legal VM/PMP/SFENCE changes require all accepted adapter owners to drain. There is no flush input on the result buffer and no accepted-descriptor cancellation. The illegal undrained-flush negative test must trigger the precise production assertion; it is not support for arbitrary in-flight context mutation.

## Focused validation entry points

After the coordinated Scala compile, `simulator/gsim/m2_data_translation.py --gsim <binary> --tag <fresh-tag>` builds four small models:

1. `M2TranslationBufferGsim`: accepted-descriptor deque checks all 351 represented bits, long continuous supply, full hold/pop/recovery, backpressure, and an exact payload-observation negative control.
2. `M2DataPermissionGsim`: independent raw 16-entry PMP and byte-interval oracle, LR/SC/AMO, MMIO/out-of-RAM, faults, stale precheck/canonical epoch, exact canonical payload, next-line permission/page boundary, and two negative controls.
3. `M2DataTranslationGsim baseline`: actual FullCandidate DTA plus real 16-entry DTLB/single walker.
4. `M2DataTranslationGsim registered`: identical full parameters and external service law, with the explicit M2 result/evaluator modules.

A/B first measure one warm request, then 256 continuously offered warm demand stores with physical READY/response READY high and one-cycle physical service. Both upstream and physical acceptance spans must be exactly 256; first physical/response latency and total elapsed cycles disclose M2's one-cycle cost. A second 256-request stream holds physical READY for 64 cycles and response READY for 96, then reports actual full-release events and next-accept gap. Mixed real walks, canonical lineage, page/PMP faults, MMIO, atomic requests, fresh/stale prechecked loads, delayed errors, and legal drained epoch changes follow. Negative controls deliberately corrupt observations or violate the drain contract; ordinary execution remains unaffected.

The coordinated independent `CommonA1VmPipelineGsim` four-control CPU witness is separate. It uses actual ordinary translated stores so the new edge cannot be bypassed by load prechecks. Serialized store cycle cost and correct dependent loads are meaningful; they are not a high-MLP or shared-DDR throughput claim. Existing P1 retirement fixture/host bytes and unrelated baseline evidence remain untouched.

## Measured module and complete-CPU cost

The four small models and all nine negative controls passed. The buffer conserved 1,236 accepted/returned descriptors, including 512 continuously supplied cycles and 512 consecutive post-full push/pop cycles. The independent permission oracle passed 4,661 cases: 2,672 faults, 618 canonical qualifications, 1,464 allowed next-line hints, 844 atomics and 109 stale-precheck cases. Each actual-DTLB A/B run conserved 614 accepted/returned requests; these are module results, not CPU retirement counts.

| Actual DTA service scenario | FullCandidate | M2 | Interpretation |
|---|---:|---:|---|
| Warm single request, total test cycles | 9 | 10 | One additional result edge |
| Warm 256 requests, total test cycles | 264 | 265 | Same traffic/service, plus one tail cycle |
| Warm 256 upstream acceptance span | 256 | 256 | Sustained II1 |
| Warm 256 physical acceptance span | 256 | 256 | No hidden II2 loss |
| First physical / first return latency | 2 / 3 | 3 / 4 | Exact one-cycle increase |
| Congested 256, total test cycles | 357 | 357 | Existing backlog hides this edge here |
| Congested first full-pop to next acceptance gap | 1 | 1 | Full-pop credit is not borrowed |

Actual `CommonA1CpuTile` comparisons use unchanged complete resource/ISA parameters, raw instruction traffic, real CSR/PMP/Sv39 and L1D. The VM guests start with a cold ordinary store, one fence and dependent load, then 48 ordinary store/load iterations. Instruction fetch remains in M mode; MPRV/MPP=S makes the data requests genuinely translated. The independent oracle compares retired instructions, results, all final GPRs and precise EBREAK. The bounded external manager and single hot-line workload are not a shared-DDR bandwidth model.

| Actual CPU guest, work cycles | full-candidate | full-r1 | full-m2 | full-m2-r1 |
|---|---:|---:|---:|---:|
| Independent ALU, RAM | 1027 | 1027 | 1027 | 1027 |
| Branches, RAM | 375 | 375 | 375 | 375 |
| VM store stream | 1024 | 1024 | 1074 | 1074 |
| VM dependency | 1173 | 1173 | 1223 | 1223 |

The VM setup costs 168→169 cycles; stream ROI costs 856→905 and dependency ROI 1005→1054. Thus M2 costs **+50 work / +49 ROI cycles**, or +4.88% and +4.26% total cycles respectively. R1 preserves all compared CPU metric fields on both M2 settings. No clock-frequency gain has been measured to offset M2's extra cycles, so the results do not establish a wall-time improvement.

Both VM guests observe 49 ordinary stores through checked/certificate/physical acceptance, one cold write miss, three PTE reads, and 50 total demand TLB hits. The exact 48 warm-store owner samples have translation-to-checked latency sum 0→48; `hitPass` changes 50→0 and result-buffer store captures 1→49. Prechecked loads are reported separately (55 / 103) and do not stand in for the demand-hit evidence. Data-line acquire/grant/ack counts remain 1/1/1. These results establish the new edge's real CPU cost, not high memory-level parallelism.

Evidence leaves:

- `build/gsim/m2-translation-20261024-r3/receipt.json`: four module controls and nine negatives, including exact source/tool hashes and explicit reused model lineage.
- `build/gsim/m2-r1-common-vm-20261024-r1/receipt.json`: four actual CPU controls and two observation-oracle negatives; SHA256 `76d3b7cb6e77dbaf5c14098452abf837d2b9bce28a1c647294d829f58c2cb558`.

Two test-interface failures were preserved and repaired without changing production RTL: r1 exposed unsupported simulator top-level Vec setters, fixed by 32 scalar PMP test pins with identical sixteen-entry stimulus; r2 attempted a BoringUtils tap on a static false literal, fixed only by a static false observation in that profile. Failed FIR/header/elaboration logs and original input hashes remain in the r1/r2 leaves. The r1 original Vec fixture was recovered by reversing that known test-only edit and matching its exact SHA256 `469b2ce911cf6e5560e3f65a88eeda9081363fcffdf6e0cb887fd4574553c578`. Passed buffer/permission/baseline models were reused rather than rerun; no production logic or simulator source was patched to make the tests pass.
