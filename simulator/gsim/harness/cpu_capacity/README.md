# Generic A1 capacity execution fixture

**Bounded execution verified: 21 positive cases and 9 precise expected observer
rejections across three fresh generic CPU-tile models.** Actual generic
`CommonA1CpuTile`, LSU4, ROB/PRF 16/48, 16/64 and 32/64; unchanged two-wide RV64GC,
L1 geometry, MMU/PMP/FPU and ordered native transport. No experimental profile,
feature enable, CPU/ISA/cache reduction, AXI migration or production API change.

## Small matrix

Per spec: RAM independent ALU and dependent chain (480 operations each), branch
240-event source/ISA dual oracle, dependent loads, independent loads, smoke, and
MPRV TOR revoke-load. Three negative controls: branch retirement data, branch
trap cause, and fault first-trap tval. Total 21 positives + 9 negatives. Budgets:
ALU 30k, loads/fault 10k, branch/smoke 100k cycles. These are bounded execution
checks, **not** performance, complete ISA/FP, full SoC, Linux or PPA qualification.

| ROB / PRF / LSU owners | Positive cases | Expected negative rejections |
| --- | ---: | ---: |
| 16 / 48 / 4 | 7 | 3 |
| 16 / 64 / 4 | 7 | 3 |
| 32 / 64 / 4 | 7 | 3 |

Each fault run retired exactly 87 instructions, reported access-fault cause 5
with tval `0x80210000`, accepted exactly one upstream-private-L1 physical read
and its reply, and observed the fault plus handler-terminal EBREAK (two traps).
All owner/drain and final register checks passed. The nine observer negatives
matched their exact expected two-line stderr, nonzero exit and empty stdout;
positive stderr was empty. No sanitizer finding was accepted.

The three models were freshly generated and compiled from public base
`f318ea9d28f4f2575190fe12dfb1660784114263` plus this test-only source addition.
Each fresh FIR/header/step implementation received an independent, hash-bound
ABI/wiring/phase review before native build. No historical model/PASS was reused.
The preserved executed-source epoch precedes this documentation-only update;
all executable Scala/C++/guest/oracle bytes remain unchanged. The complete
source-bound result is identified by SHA256
`0377742ff77691e0ef928b20c315dc33a9c328a9881fd7fd740b5d0593d3e70f`.

Parameter legality and exported constructor identity do **not** automatically
upgrade to universal CPU qualification. The existing identity qualification
flags intentionally remain unchanged: the source-bound report above qualifies
only these configurations and cases. ROB64 and LSU2 are not CPU-execution
qualified by this batch, and retaining RV64GC hardware is not full ISA/FP proof.

## Architectural and service independence

Inputs come from hash-verified historical CPU and branch qualification archives; see
`SOURCE_INPUTS.json`. Do not rebuild guest ELFs or regenerate expected data from
DUT output. Branch `source-gold.h` and `branch_isa.h` retain dual independent
expectations; branch raw input hashes remain bound by the preparation manifest.
The dependent/independent hosts retain their own literal-LD oracle, 65 physical
requests/replies, one cache grant and no writes; they do not use smoke CRCs.
Shared image/memory/ISA headers are byte copies of the input archive.

Fault expectations are **fixed host-generated architectural gold**, not a
historical literal 87-row table. `fault_guest.h` retains the original constructor
unchanged. `fault_gold.cpp` is a software-only freezer, run before any new DUT:
`fault-gold.txt` contains 516 program words and 87 retirement records, including
84 before fault, fault PC `0x80000150`, cause 5, tval `0x80210000`. SHA256:
`12e0f88246e3a7817af5a6f80171fd4c19e289cecec7ab52aa60d7e136026ba8`.
The faulting LD and wrong-path EBREAK must not retire; the handler reads
mcause/mtval/mepc and then EBREAKs. Register x4 remains unchanged.

The first permitted load warms L1D, followed by FENCE and an actual pmpcfg CSR
revoke. The host checks exactly one physical accepted read and one reply for the
**whole run** at DTA.io.physical, upstream of private L1D. An unauthorized second
read cannot hide as a warm cache hit. This must not be weakened to no external
DataA/DDR request. No phase boundary is inferred from a same-edge CSR retirement.

## Deliberate extraction changes

- Model type/header becomes `CommonA1CapacityGsim`; historical internal
  `benchmark$$dataD` becomes explicit wrapper `io$$dataD` for ReleaseAck.
- Common/dependent/independent remove only marked MUL capture audit code and
  relocate shared includes. Dependent/independent also omit historical private
  VM/fetch-privilege audit: there is no extra VM tap or generic feature enable.
  Their literal guest ISA and physical non-virtualized request checks remain.
- ALU exact case filter selects only the two RAM cases, and the ROB bound comes
  from the model-bound `CAPACITY_ROB_ENTRIES`. Metric-only accepted/frontend
  observations and associated printed metrics are omitted, not reported as zero.
- Fault private m3 start/completion, proof-row/canonical, DTA-internal/FP witness
  code and their final counters are removed. The architectural expected sequence,
  all precise traps, physical request/reply accounting, manager conservation,
  clear-reservation ownership and drain remain. No old witness PASS is inherited.
- New narrow observer checks: prefix retirement, ROB index/capacity bound,
  occupancy bound and full `(index,tag)` uniqueness. Fault did **not** previously
  check prefix/token uniqueness. Common/branch now inspect all 32 public GPRs
  after drain, like the original load hosts; metrics separate inspection cycles.
- Raw fault InstructionManager and independently stateful ManagerOracle are
  extracted unchanged into `fault_instruction_service.h`, without the old
  successful-load Run observer or experimental wrapper include.

No service law changes: input drive → `step()` → current event observation →
host state updates. Retirement lane0 precedes lane1 and same-edge trap. Original
response consume before new read snapshot before release write sequencing stays
intact. Three-cycle service latency, eight-byte beats and original owner limits
remain. Four consecutive fully drained cycles and final GPR checks are required.

## Wrapper and ABI

Public bus/retirement/trap/hold/GPR/memoryBusy IO carries the business contract.
Only narrow passive test bores observe fetchIdle, privateIdle plus cache
quiescence, ownersIdle, ROB occupancy, and DTA physical request/reply. No
canonical/FP/proof optional taps. Token index is 4/4/5 bits, occupancy 5/5/6;
tag and architectural values 64, instruction32, rd5, PRF destination6.
Generated FIR/header inspection and compile-time binding are required for every
new model; old model headers/objects/PASS records are not reusable evidence.

Source/ABI review and a durable source checkpoint preceded this validation.
Sequential fresh GSIM model groups only; 4 CPUs, 3 GiB JVM, sampled owned process
RSS 4 GiB and 512 MiB reserve (not a hard cgroup promise). Preserve failure
receipts on capacity overflow; no feature cuts to force a fit. `RANDOMIZE_INIT`
remains unqualified. Model storage is zero-initialized before construction by
the existing `GsimModelStorage`, followed by real reset; no uninitialized payload
is treated as valid.
