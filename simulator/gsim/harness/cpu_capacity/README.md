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
For that parent qualification, the preserved executed-source epoch precedes its
documentation-only update; executable Scala/C++/guest/oracle bytes were unchanged.
The separately reviewed host-only follow-up below is a new source epoch. The complete
source-bound result is identified by SHA256
`0377742ff77691e0ef928b20c315dc33a9c328a9881fd7fd740b5d0593d3e70f`.

Parameter legality and exported constructor identity do **not** automatically
upgrade to universal CPU qualification. The existing identity qualification
flags intentionally remain unchanged: the source-bound report above qualifies
only these configurations and cases. ROB64 and LSU2 are not CPU-execution
qualified by this batch, and retaining RV64GC hardware is not full ISA/FP proof.

## Separate fixed-input capacity comparison

A subsequent host-only epoch starts from public qualification commit
`1bbf4845120259c3401ddc7bef5fa4fc64e5dae3`. The sole executable source change
admits `performance` as well as `smoke` in `common.cpp`; the already sealed
signature table, independent ISA oracle, service, observers and DUT are unchanged.
Three fresh common hosts link the exact three qualified model objects. All three
smoke outputs first matched their corresponding parent output byte for byte;
then all three fixed performance cases passed. This does **not** rewrite the
parent 21-positive/9-negative gate or qualify the other nine CPU tuples.

These are **generic, full-feature two-wide A1 configurations**, not the older
experimental optimized/efficiency profiles. In particular, effective
`postedStoreMerge=false`, `fastBufferedStoreRetire=false`, and
`dataNextLinePrefetch=true` are preserved. LSU4 denotes owner capacity, not four
load/store issue ports. All other hardware and service parameters stay fixed.

| ROB / PRF / LSU | ROI cycles | ROI IPC | Whole-work cycles | Whole-work IPC | ROI equal-clock speedup | Whole-work speedup |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 / 48 / 4 | 470604 | 0.766090 | 500689 | 0.767602 | baseline | baseline |
| 16 / 64 / 4 | 470604 | 0.766090 | 500689 | 0.767602 | 0% | 0% |
| 32 / 64 / 4 | 449274 | 0.802461 | 478890 | 0.802543 | +4.74766% | +4.55198% |

Speedup is `baseline_cycles / candidate_cycles - 1`; cycle reduction is
`1 - candidate_cycles / baseline_cycles`. For 32/64/4, ROI cycles decrease
4.53247% and whole-work cycles decrease 4.35380%. PRF48→64 alone gives **0%**
on this input. The PRF64 pair isolates ROB16→32 capacity; no internal stall
mechanism is inferred from these aggregate results.

All three retire 384330 total / 360525 ROI instructions, architectural hash
`eb74228486f9b622`, x11 CRC `8e3a1fd7e714e9f5`, x13 CRC `e714`. Each reports
157 I requests / 9936 bytes, 65 D reads / 4160 bytes, 0 external D writes,
65 grants and 0 release acknowledgements. Dirty resident flush is not requested;
zero external write traffic does not mean zero guest stores. All physical stores,
final GPRs and owner drain still pass their independent checks. Drain is 7 cycles
and post-drain GPR inspection is 32 cycles, excluded from whole-work cycles;
total cycles are 500728, 500728 and 478929.

### Fixed input and reproduction boundary

Use the original one-iteration performance workload, not a rebuilt guest or
newly selected seed/input:

- ELF: 20176 bytes, SHA256
  `9a8e716320ec08591fd25a2dfdf4c73b7714908ab8a190b607dc8e10cd1b43ac`.
- Symbols: 1845 bytes, SHA256
  `671642be3f3323baf72147820ab26dbad86bf6c3f298f8e5aa3db4e83440e67d`.
- Same cold reset, boot image, half-open ROI markers, 3-cycle memory service,
  8-byte beats, 16 live slots, line assembly, trap and full-owner-drain semantics.
- Generate `CommonA1CapacityGsim` for the chosen ROB/PRF with LSU4 using the
  qualified pinned GSIM flow; independently verify its ABI before reuse. Compile
  `common.cpp` with its model header, shared headers and harness include path,
  `-DCAPACITY_ROB_ENTRIES=16` or `32`, then link that model's objects. The recorded
  native flags are `-std=c++20 -O1 -g -fsanitize=address,undefined
  -fno-sanitize-recover=all`, Clang 19. Never mix objects between specs.
- Invocation: `common PERFORMANCE_ELF SYMBOLS performance 3000000`.
  Run each model's original smoke first with `smoke 100000` and require its exact
  saved output. Each run has an external 180-second wall limit; native host
  compile/link limits are 300/180 seconds, 4 CPU affinity, sampled owned-tree
  RSS limit 4 GiB and 512 MiB reserve, not a hard kernel memory-limit claim.

The fixed-input binaries and raw receipts are hash-identified reproducibility
inputs, not embedded in this source fixture; without their exact bytes the table
is not freshly reproduced. The completed result manifest SHA256 is
`83f544bfdb65ad84fc501010ef8b28b4a11a6c7299f54ae9f283d7169520e344`.
All six runs pass without sanitizer findings or timeout; no alternative input,
model, service law or budget was substituted after observing results.

This measures **equal-clock CPU-tile cycle cost under a fixed host service**,
not actual clock frequency, area/PPA, physical DDR bandwidth, an official
CoreMark score, NaxRiscv parity or full-SoC performance.

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
new model; historical models cannot establish evidence for a different model.
The follow-up below reuses only these exact three qualified model objects, with
fresh hash/source/ABI binding checks and newly compiled host executables.

Source/ABI review and a durable source checkpoint preceded this validation.
Sequential fresh GSIM model groups only; 4 CPUs, 3 GiB JVM, sampled owned process
RSS 4 GiB and 512 MiB reserve (not a hard cgroup promise). Preserve failure
receipts on capacity overflow; no feature cuts to force a fit. `RANDOMIZE_INIT`
remains unqualified. Model storage is zero-initialized before construction by
the existing `GsimModelStorage`, followed by real reset; no uninitialized payload
is treated as valid.
