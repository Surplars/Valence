# Identity data-request pass-through

Opt-in typed `OooParams.identityDataRequestFlow` defaults false. BoardSocConfig.boardParams, BoardSocTop, EthernetSocTop and BoardSocGsim expose `identityDataFlow=false`; board exporters accept `--identity-data-flow`. Registered ingress and checked-request stages remain required. Existing profile defaults and MSHR selection do not change.

Only a captured request with virtualized=false can pass through an empty translated FIFO. Older queued/pending translations retain priority. A stalled direct offer spills unchanged into the existing FIFO. Capacities, response ownership/order, captured context, fault placeholders and accepted-token draining remain intact. No payload registers, TLB/PMP combinational bypass or load-to-AGU forwarding are added. Effective privilege and unvirtualized PMP authorization remain the upstream CPU's existing responsibility.

Two adapter models passed16 independent external-token scenarios each under ASan/UBSan, plus the earlier64-context VM oracle on the same models and data/context corruption negatives. Coverage includes M-mode with nonzero SATP, S/U Bare, effective-S virtualized requests, immediate/delayed TLB replies, PBMT, page/access/PMP faults, locked M-mode PMP, atomic range faults, context/PMP snapshots, FIFO spill and held requests/responses, accepted canceled-token drain and coordinated reset. Raw MPRV CSR computation and CPU rollback were not reimplemented in this wrapper.

Measured request acceptance to physical acceptance:3→2 cycles. Response latency:4→3 with one-cycle memory,8→7 with five-cycle memory. A64-token dependency-paced adapter stream takes320→256 cycles. Virtualized-only event traces/timings are identical between flags. These are adapter measurements, not CPU IPC predictions or physical timing proof.

Normal paged Linux S-mode requests, including TLB hits, retain the old path. Keep M1 as the current board fallback. Final CPU comparisons must hold firmware, forwarding, cache geometry, DDR model and MSHR choice fixed. Routed100MHz timing and Linux performance remain unverified.
