# Efficiency operand focused tests

These are new candidate tests. Production oracles and earlier tests are untouched.
No Scala/GSIM/DUT build was run while preparing them; source-only C++ syntax was checked against declaration stubs (NOT model correctness evidence).

## Entrypoints (one batch compilation owned by validation lead)

- `ooo.RegisteredMemoryOperandAuthorityGsimMain OUT`
  - host `registered_memory_operand_authority.cpp`
  - actual production `RegisteredMemoryOperandAuthority` hit/ready/value/producerAuthority/allowed
  - scalar ports, full token index + all 64 tag bits retained in helper
- `ooo.SharedMulDivOperandReadsGsimMain OUT`
  - host `shared_muldiv_operand_reads.cpp`
  - actual `SplitMulDivSelector` and two actual `OwnerBankedPhysicalRegisterFile` instances, old four-read path versus selected two-read path
  - independent procedural age scan and architectural-word PRF model, pre-edge reads/new writes, higher write lane collision winner

Use the qualified GSIM initialization-fixed binary, Clang 19, ASan/UBSan. LeakSanitizer remains unavailable in this executor; do not claim it passed. Do not regenerate models for host-only fixes.

## Required positives and exact negatives

Registered helper positive prints `PASS_REGISTERED_MEMORY_OPERAND_HELPER` after all directed flag/tag/operand cases and 12000 randomized cases.

| Option | Exact expected host rejection prefix | Kind |
|---|---|---|
| --inject-ready | OPERAND_READY:ordinary | observation negative |
| --inject-value | OPERAND_VALUE:ordinary | observation negative |
| --inject-high-tag | PRODUCER_AUTHORITY:tag-high | observation negative |
| --inject-fault | CAPTURE_AUTHORIZATION:fault | observation negative |
| --inject-kill | CAPTURE_AUTHORIZATION:killed | observation negative |
| --inject-ready-priority | OPERAND_VALUE:registered-priority | observation negative |
| --inject-second | OPERAND_VALUE:second-only | observation negative |
| --inject-x0 | OPERAND_READY:zero-source | observation negative |

M/D positive prints `PASS_SHARED_MULDIV_READS`; directed coverage includes all 16 heads × 16 multiply positions × 15 distinct divide positions × four readiness combinations, 12000 randomized cycles, writes, collisions, no-owner and unselected invalid IDs.

| Option | Exact expected rejection | Kind |
|---|---|---|
| --inject-oldest | MD_OLDEST:age-wrap | observation negative |
| --inject-grant | MD_GRANT:both-ready | observation negative |
| --inject-left | MD_SHARED_DATA:data | observation negative |
| --inject-right | MD_SHARED_DATA:data | observation negative |
| --inject-zero | MD_SHARED_DATA:zero | observation negative |
| --wrong-write-priority | MD_SHARED_DATA:collision-result | independent oracle mutation |
| --invalid-write | PRF write address outside physical capacity | actual DUT assertion |
| --overlap-class | MUL/DIV candidate classes must be disjoint | actual DUT assertion |

Fail if a negative exits zero or rejects for a different reason. Observation negatives validate the comparison checks; they are NOT mutations of production RTL.

## Strict coverage boundary

The helper deliberately separates numerical ready/value from producer authorization. A matching physical promise may expose numerical bits before writeback, while bad owner/fault/kill rejects capture. The helper fixture covers full producer token equality, high-bit ABA, non-load/fault/dead/invalid promise/destination/kill cases, registered-value priority, both source operands and old/new producer token transitions.

It does **not** establish consumer owner lifetime, current context epoch, recovery/replay cancellation, final memory-start gating, D/T/R proof admission, permission correctness, or that a blocked writeback prevents actual LSU start. Those gates are in the real backend and need candidate CPU/actual-backend checks. The helper's `allowed` output alone cannot prove them.

The M/D fixture covers unchanged winning class/index and selected physical addresses/values under both FU readiness states. It does **not** instantiate the backend side-ticket budget, M operation/word/PC metadata routing, simultaneous LSU+M dispatch, precise traps or cancellation. Candidate CPU integration must check those. Four-versus-two PRF fixtures are a finite component equivalence check, not full backend equivalence.
