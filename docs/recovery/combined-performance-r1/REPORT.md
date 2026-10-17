# Four-feature CPU performance candidate

## Status and scope

One coherent native 100 MHz model passed 15 short positive executions and six deliberately failing independent-observer checks. The candidate enables robust early-load descriptor capture, a 64-entry D-only miss cache, virtual operand-only resident store lookahead, and writer-banked store payload. Existing I8/D16 TLBs, full owner tags, address CAM, head-only store launch, precise exceptions, real-response virtual-store retirement and posted-store restrictions remain. Every library default stays OFF/zero; only the diagnostic emitter enables the four features.

Base is local `e2237bd0725ea6a73703f4d75c95eb826b51fef8` (same source tree as published L2 commit `d51f6ccf064a11eefdde6a7e9e4e730cc9c352be`), plus reviewed store candidates. Baseline is the saved `50cb0c5d4b17318904d6cf818ad23829821d5d93` model. CRC, cache-aperture and shared-backend-PMP experiments are not part of this CPU model.

Native OFF/ON and GSIM ON elaborations checked actual constructed switches at every core level and actual translation-service capacities. All existing profile fields and fabric configuration match the saved 50cb reference; Q remains 276 bits, with 12 PRF read ports and eight issue-payload groups. These configuration checks do not replace hardware equivalence or timing analysis.

## Matched-work results

| Diagnostic | 50cb cycles | Combined cycles |
|---|---:|---:|
| Bare warm store, 8192 writes | 32881 | 32881 |
| Sv39 4K warm store, 8192 writes | 81945 | 65561 |
| Sv39 2M warm store, 8192 writes | 81945 | 65561 |
| Dependent hot ring, 512 loads | 4096 | 3584 |
| Independent hot ring, 512 loads | 762 | 762 |
| Sv39 sequential READ, 64KiB ×2 | 74093 | 74093 |
| Sv39 sequential COPY, 64KiB ×2 | 175018 | 172018 |
| Fixed CoreMark one-iteration ROI | 579036 | 569969 |
| Sparse READ 16 pages ×128 | 12052 | 12052 |
| Sparse READ 17 pages ×128 | 131716 | 28934 |
| Sparse READ 32 pages ×128 | 247300 | 53894 |

Warm-store diagnostics reuse the same guest, seed, memory-service law and independent PA/data/owner checks. Each mode verifies 9216 writes including warmup and 1024 final words. Sv39 physical reply remains start+4, integer reply start+5 and retirement start+6; the usual retirement-to-next-start gap drops from four to two cycles. The pure-store ROI reduction is 16384 cycles, about20.0%. Bare timing and event distributions remain unchanged. This is measured combined behavior, not a separate causal A/B for each switch.

COPY improves about1.71%, almost entirely matching the earlier L2-only result of172020 cycles; the combined result saves only two additional cycles. It would be incorrect to apply the pure-store percentage to Linux memcpy. Sequential READ is unchanged. Sparse page tests read8bytes per page with4160-byte stride; the17/32-page ROI has zero walks and2176/4096 L2 hits. This is a fixed assembly diagnostic, not the user's board C benchmark.

CoreMark uses the same sealed official source and GCC14.2 `-O3` RV64IM diagnostic image as the earlier earlyQ experiment, standard2000-byte data, one iteration. All five CRCs,345530 retired instructions,54195 loads,14223 stores and PC/instruction hashes agree. ROI improves about1.566%, matching earlyQ alone. Its expected duration error remains: this is neither a formal CoreMark score nor the user's GCC13.2 binary. Accepted LSU starts and microarchitectural scheduling need not be identical when architectural work matches.

## Correctness and independent checks

The same model passes actual L2 target-hit witnesses around guest SFENCE/PTE remap and SATP root+ASID changes with MPRV S-mode data access, plus SUM/MXR/PMP revocation with exact cause/PC/tval and no extra physical side effect. Six observer mutations reject wrong data, missing L2 coverage, stale physical data and wrong exception causes. These prove oracle sensitivity, not injected RTL-fault tolerance. No new atomic/LRSC execution coverage is claimed.

Independent review recomputed all warm-store CSV distributions, verified the matched CoreMark work/CRCs and33 command-log hashes, and reviewed merge conflicts/actual parameter forwarding. Separate focused store qualifications are documented in their own reports; their counts are not added to the15 full-model runs.

## Resource and timing limits

Independent banked-backend lowering using the production assertion-disable flow removes the entire1024-bit assertion-only shadow. Both writer banks retain one live fresh read and one write; the unused head read is eliminated in this qualified configuration. That is structural evidence, not an integrated LUT saving. The earlier isolated2W/2R component estimate is not summed into CPU area.

## Qualification follow-up (2026-10-17)

The first two gates listed at the original 9b5cf10 snapshot are now closed at their stated scopes, using the existing emitted graphs and mapped envelope. No production source/configuration changed, no DUT rebuild or new mapping was run, and no Vivado or board execution was performed for this follow-up. The original execution/source seals remain unchanged.

### Default-OFF hardware graph

All 291 production assertion-stripped, nonflattened generic modules match the saved 50cb baseline graph. The comparator checks exact connection bit IDs, ports, cell types/parameters/directions/attributes, memory geometry and initialization; it ignores generated cell names and source metadata only. An altered edge is rejected. Re-execution produced the identical original receipt SHA256 `de48d5322f80f687b8e7c40c6331ab63da50097a30c28c0fc12de15d2172209f`.

This closes four-option-OFF hardware composition, including I8/D16 and the descriptor/backend. It is not raw FIR equality, assertion-behavior equivalence, or mapped/routed timing equivalence. Vendor blackbox behavior is inherited, with interface/parameter/connectivity contracts compared. Enabled-candidate equivalence is not claimed.

### Actual integrated payload resource and path screen

The matched envelope has 66 destination-state bits and the same 9,861 source-Q/native-input boundary bits. Complete payload writer DATA/ADDR/EN/CLK and destination D/EN/reset closure is retained. OFF retains 1,024 payload FF; ON retains two original 16x64 writer banks and 16 latest-writer FF, with one surviving functional read per bank. This is the actual combined four-feature model, not a banked-only causal A/B or whole-backend/device area estimate.

| Matched envelope | OFF | ON | ON minus OFF |
|---|---:|---:|---:|
| Logic LUT | 19,536 | 17,538 | -1,998 |
| Allocated LUTRAM sites | 0 | 80 | +80 |
| Total allocated LUT sites | 19,536 | 17,618 | -1,918 |
| FF | 1,090 | 82 | -1,008 |
| CARRY4 | 396 | 396 | 0 |
| BRAM | 0 | 0 | 0 |

ON maps to ten RAM32M16 primitives: 2,048 useful storage bits, 5,120 allocated bits and 80 allocated LUT sites. This includes padding/write-address costs. Extraction omits source net initialization attributes, so this envelope is a cost/dependency screen, not a sequential/startup-equivalence proof. The separate full OFF graph comparison above includes initialization.

The structural mapped timing screen regresses by three LUT levels:

| Endpoint input | OFF LUT levels | ON LUT levels |
|---|---:|---:|
| Q.savedData / Q.saved D | 13 | 16 |
| Payload CE | 18 | 21 |
| Q.valid D | 18 | 21 |
| Q.valid reset | 1 | 1 |

The continuous ON read chain is Q.token.index -> 15-LUT fresh-index selection -> the same RAM32M16 asynchronous address-to-read output -> one bank-selection LUT -> Q.savedData D. Thus the 16 logic levels also traverse one asynchronous RAM read. RAM delay is not represented as LUT delay. Writer DI/WE/write-address paths are separate edge-triggered state inputs, with no fabricated same-cycle write-through arc. Payload registers have constant mapped reset pins; only Q.valid has the reset-control path.

The longest CE/Q.valid-D paths do not traverse RAM. They run from LSU completion/slot state through forwarding, the existing RAM-range comparison, LSU start.ready, memoryIssued, planner.issued and resident transfer/capture. Both arms include two CARRY4 along their worst-LUT control path. ABC restructuring and this four-feature comparison do not establish that banked payload alone causes the regression.

These are conservative unsited primitive dependencies, not sensitized STA paths or nanosecond delays. The resource screen is complete; timing qualification is not PASS. Do not transfer the old 50cb physical pass to this candidate or describe this as a routed Fmax improvement.

### Reverification and remaining gate

Read-only revalidation checked all 663 files in the integrated artifact manifest, all 3,762 sealed source files and both native emissions without mismatches. Re-running the exact OFF comparator and both mapped resource/path analyses reproduced their original receipts byte-for-byte. The compact `qualification-followup.json` records input/script/result hashes and scope. Historical failed conversion/guard attempts and successful normalization receipts remain preserved with the generated evidence.

The remaining release gate is whole-candidate physical/routed timing and actual board qualification, including review of the +3 mapped-level control regression and continuous asynchronous RAM read. This payload screen does not qualify all earlyQ, virtual-preparation, MMU L2 or full-board paths. Source integration can preserve defaults OFF/zero; enabling these options for a timing-sensitive board remains unqualified.

The compact `paired-summary.json` binds source snapshot, emission/model manifests and individual paired-report hashes. Full generated models, logs, CSV traces, checkpoints and binaries remain outside source control.
