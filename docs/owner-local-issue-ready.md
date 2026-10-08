# Owner-local ALU readiness experiment

This explicit default-off experiment selects the existing per-ROB-owner ready
mirrors for the registered readiness portion of ordinary ALU scheduling.
`ownerLocalIssueReady` requires the existing exact mirrors, staged execution and
absence of the two legacy broad bypass modes. It adds no state, capacity, stage,
issue restriction or completion bandwidth. All issue promises remain live and
unchanged; actual grant, full-token, pending, kill and exception checks remain in
the original backend paths.

The source hotspot is 16 pending owners times two ordinary ALU sources. Each
previously reselected a Boolean from 48 physical-ready bits, although
`OwnerOperandReady` already mirrors those exact Boolean values for every pending
owner. The mirror consumes the same accepted wake and reserve events, with
reserve winning, and initializes allocation from the next physical state. The
existing invariant asserts equality to the physical ready file for active owners.

This experiment preserves oldest-two circular selection and unrestricted choice
of either execution slot. It does not use fixed issue columns. A lowered-cone
comparison is required before claiming even a structural reduction; physical
LUT/timing gains remain unmeasured. No request-stage flow change is part of this
experiment.

Required gates:
- Independent readiness model with allocation+wake coincidence, reserve-over-wake,
  same-packet dependencies, flush/reuse, inactive IDs, both operands, and load/ALU
  issue promises
- Explicit corrupted-readiness oracle rejection
- Backend/core same-seed/program comparison with dependencies, mixed memory/M/ALU,
  branch recovery, accepted result/physical-register reuse and all latency bins
- Ready-read cone/fanout ablation without counting verification logic as production
- Final shared exact-profile system/VM/PMP/RV64GC integration

Unit and two-way core qualification passed. The independent event oracle ran
16,000 cycles and335,520 comparisons, including5,625 allocation+wake cases,
2,458 reserve+wake coincidences and13,762 owner row reuses. Both readiness and
fault-aware allocation corruptions were rejected. Lowered cone counts are32
`comb.shru` operations in the global source selection and0 in local selection;
no new state is introduced. This is a structural observation, not mapped PPA.

Both frozen full-core variants completed the same15 benchmark bins and9,318 NEMU
retirements, with exactly equal cycle, event and full-token load-timing rows.
Both also passed pipeline recovery, timing smoke and corrupted-NEMU rejection.
Receipts are `build/gsim/fpga-next-owner-ready-unit-r1/receipt.json` and
`build/gsim/fpga-next-owner-ready-core-r1/receipt.json`. Exact-profile RV64GC/VM
integration and physical resource/timing qualification remain separate gates.
