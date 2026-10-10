# Actual cache component qualification

The frozen implementation at bc518ec83fc51bbef9e5376f9cee0e1e10200848, tree 5081747bbe83f8c4fa02c25244f94552066f9132, passed the complete actual-cache component gate on 2026-10-10. Session 49373 exited 0. The final documentation commit adds no executable changes. Default selection remains OFF.

## Scope and results

The model contains the actual private cache, original acquire engine, original response/MSHR/WB resources and SRAM writes. CPU authority and successful-RAM guarantees are explicit fixture premises; the TileLink manager is an independent synthetic environment. This result does not qualify an executing CPU, the real coherent home, whole-board behavior, CPU speedup or synthesis resources. CPU integration source compiles, but its runtime lineage gate is separate.

The gate passed 22 independent host-contract tests, 10 detected semantic mutants, three transport tests and three Scala/configuration tests. Four separately generated native models ran 15 positive scenarios and six negative scenarios requiring exact RTL assertions. The models are OFF/gen64/WB2, ON/gen64/WB2, ON/gen2/WB2 and ON/gen64/WB1. ASan/UBSan found no failures. All 23 steps exited 0; expected assertion processes are checked inside the negative scenarios. The 200 MiB output budget and 700 MiB free-space floor never triggered. Steps took 128.443 seconds and the complete attempt contains 54,879,161 bytes.

Configuration checks cover original MSHR counts 1/2/4, legal WB capacities, disabled sidecar/state pruning, exact ON geometry and aperture requirements. Both OFF and ON retain exactly ten physical SRAM write mports: eight data banks and two tag ways. No native-state or synthesis area claim follows from this port check.

Actual SRAM is verified through subsequent reads, dirty probe data and complete backing bytes after flush, in addition to line-install observations. The independent reference captures coherence base bytes at actual Grant ownership and applies authored store masks/data. Full owner/token/epoch and response ticket associations are checked independently. Synthetic schedules are not evidence that every order is reachable through the real home.

The successful scenarios include repeated reuse of two response tickets before first refill, two lines with younger refill and oldest install, held request becoming a legacy hit after install, probes before A and after E, held ACK plus post-install invalidation without resurrection, clean and dirty victims with C-last to Acquire overlap, pre-capture victim cancellation, flush and explicit episode boundaries. WB1 has a separate basic merge/read/flush gate; the WB2 overlap claim is not extended to WB1.

## Fallback responsibility correction and causal evidence

A gen-exhausted store may use the original legacy dirty-miss path. Its CPU ACK can complete before the real victim ReleaseAck. The owner module correctly ends its fallback-response obligation at CPU ACK, but exported cache busy must retain the independent coherence tail. The repaired cache saves fallbackDrainActive and its epoch on the actual fallback transfer and conservatively drains all already accepted resources from that episode. It does not claim precise per-owner WB reclamation. Raw unaccepted requests, a held next proof, raw flush and episodeActive do not block old responsibility from clearing. A newly accepted probe on the clear edge does retain responsibility.

The independent manager rejected the pre-fix, fully built gen2 binary at cycle 266: CPU ACK had completed, accepted Release source 2 still awaited Ack, and cache busy was zero. The pre-fix executable was reused without rebuilding; emit/generate/compile/link had all completed with exit 0 before its encompassing run was interrupted with exit 130. That encompassing run remains interrupted, not PASS. Its original receipt, interruption record and artifact hashes are preserved.

On the repaired gen2 model the same dirty-fallback tail scenario passes in 418 cycles. Busy stays high through held ReleaseAck, two actual probes complete including the clear-edge probe, a younger held proof cannot prevent flush/drain progress, and the next fallback succeeds after the old resources clear. Changing contextEpoch from 0 to 1 after CPU ACK while that WB remains unacknowledged fails with the exact guard: cache fallback context changed before real coherence drain. The expected busy is derived from the independent manager's accepted C/source ledger, never the RTL WB mask.

## Provenance and retained limitations

The full source/tool/model/log binding is in posted-cache-component-bc518ec-attempt3/receipt.json, SHA-256 03f7d8022bd8423e43fc0b89e6c822f6bb03aabc2ff5a67446a9bd53254999b3. The machine-readable checked summary is simulator/gsim/posted_cache_rebuild/component-results.json. Earlier source checkpoints, the first fixture-guard failure and interrupted second attempt remain preserved. No historical source, speedup, area or lost-volume result is inherited.

This initial ON design retains each posted owner/MSHR until all its tokens and exact attached WB ReleaseAck drain. That installed-owner tail and full token metadata may be costly; actual throughput and resource measurement must decide later optimization. No writeback reservation capacity optimization is included. Successful physical RAM remains a platform environmental contract, never an inference from identity translation or PMP success. Sv39 stores retain the legacy precise-fault path in the CPU source, which still requires its independent executing-CPU gate.
