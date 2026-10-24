# M2/R1 actual Common A1 CPU comparison contract

This private test fixture instantiates `CommonA1CpuTile` directly, with the actual
`full-candidate`, `full-m2`, `full-r1`, and `full-m2-r1` profiles. It is not a
predecoded backend or a reduced-cache frontend. ROB16, PRF48, four LSU entries,
DTLB16, RV64GC, PMP/MMU, and both real 32 KiB, two-way L1s are retained.

## Fixed workloads and independent expectations

The unchanged RAM independent-ALU and branch byte images are copied from the P1
host. Two additional raw-instruction ROM programs each retire 233 instructions:
a virtual-store stream and a dependent load/add/store/readback chain. Each has
49 ordinary virtual stores, including the cold warm-up store, and independent
final readback of all eight data words. Stores remain conservative and serial;
these programs do not constitute a high-MLP or memory-bandwidth test.

Execution remains M mode. CSR instructions establish MPRV=1, MPP=S, Sv39 ASID0,
and a PMP TOR RWX interval [0, 4 GiB). The page table at 0x80300000, with lower
levels at +0x1000 and +0x2000, maps supervisor VA 0x40000000 to PA 0x80210000.
The leaf is R/W, U=0, with A/D preset. A cold ordinary store, FENCE rw,rw and
load precede the reported warm continuation. Instruction fetch remains M-mode
identity fetch. The host independently interprets CSR values, page-table bytes,
PMP whole-range permissions, arithmetic, branches, loads and stores before the
DUT is constructed. Every retirement PC, raw instruction, register destination,
writing data and next PC is checked; x0, final GPRs, and precise EBREAK are checked.

The old P1 fixture and host remain byte-for-byte unchanged. Their historical
metrics are read, not rerun as an additional baseline. Only the two selected
old guest rows are compared. New VM programs have no claimed historical result.

## Service law and stage observations

The instruction manager offers capacity for sixteen owners, fixed latency three,
and one D beat per cycle. Native physical page-table reads also have fixed
latency three. One legal L1D AcquireBlock is served by a fixed-latency whole-line
Grant; source and sink ownership remain distinct through Grant acceptance and
mandatory E acknowledgement. There are no fabricated store acknowledgements:
stores and dependent loads run through the actual translation, permission,
canonical-store and coherent L1D paths. The one-line working set does not evict;
its dirty bytes are verified by architectural load readback, not falsely claimed
to have reached external RAM.

Passive wrapper observations distinguish accepted ordinary virtual requests,
translation requests/replies, same-cycle demand hits, first misses, prechecked
load bypass, translated and checked enqueue, canonical certificates and physical
requests. An independent ingress-order demand queue associates a translation
request with its accepted owner despite the existing registered ingress stages.
Store hit latency is keyed by the full ROB index and generation tag, never by a
same-cycle upstream offer. The final oracle requires actual hit samples and
owner/count conservation. M2 must cross translated registration before checked
acceptance and must not use the old same-cycle hit pass.

Work is reset-release through terminal trap. Setup and warm continuation cycles
are separate. Owner drain and the final 32-register inspection are also separate.
All cycles are hardware step counts, never host runtime. Packet partial-consume,
flush and expected-next observations are recorded. The actual selected
accepted-prefix-validation option is false and remains false.

## Comparison and scope

R1 is compared at fixed M2 setting: baseline versus R1, and M2 versus combined.
All reported CPU fields must match for those pairs. M2 cycle costs are reported
per guest, without hiding regressions in an average. Effective configuration
comparisons permit only the explicit two flags and M2's disabled hit-flow route.
Comparing the baseline to P1 permits exactly the two newly added false fields,
not any other configuration drift.

Two negative controls mutate sampled retirement data and checked-stage PA
observations. Both require their exact reached marker and independent oracle
failure; sanitizer failure is never acceptance. They are not RTL mutations.
Fresh DUT models are generated for every control. Each generated header is used
for a real host syntax/API gate before model compilation. Content-bound objects
may be reused only within that freshly generated model for another host.

This is bounded functional and cycle evidence. It does not qualify arbitrary VM
faults, multiple pages, replacements, FPU operations, full ISA compliance, Board
fabric/CDC/Linux, FPGA frequency, PPA, or board operation. Results and failures
belong in immutable per-attempt receipts; this document does not assert a PASS.

## 2026-10-24 bounded result

All four fresh actual-tile models passed their four fixed programs, plus the two
combined-model observation negatives. CPU receipt:
`build/gsim/m2-r1-common-vm-20261024-r1/receipt.json`, SHA-256
`76d3b7cb6e77dbaf5c14098452abf837d2b9bce28a1c647294d829f58c2cb558`.
Source and tool hashes remained unchanged throughout this CPU batch.

| Fixed guest | Retired | Baseline work | M2 work | R1 work | M2+R1 work |
|---|---:|---:|---:|---:|---:|
| independent ALU, RAM | 484 | 1027 | 1027 | 1027 | 1027 |
| branches, RAM | 454 | 375 | 375 | 375 | 375 |
| virtual store stream, ROM | 233 | 1024 | 1074 | 1024 | 1074 |
| virtual dependency chain, ROM | 233 | 1173 | 1223 | 1173 | 1223 |

Each R1 pair matches all 100 CPU metric fields exactly at fixed M2 setting.
All stage fields also match except the explicit circular-payload flag. Actual
partial packet consumption is witnessed on the branch guest (one cycle) and
both VM guests (109 and 205 cycles). This remains the real selected
accepted-prefix-validation=false configuration.

M2 costs **50 additional work cycles in each VM workload**. Setup rises from 168
to 169 cycles; warm continuation rises from 856 to 905 and from 1005 to 1054 cycles.
The separate post-trap drain stays seven cycles and final GPR inspection stays
32 cycles. This is a measured end-to-end cost, not a performance improvement.

For each VM workload, all configurations retain 49 accepted ordinary virtual
stores, 49 checked stores, 49 canonical certificates and 49 physical stores.
The first translation miss is a write and causes exactly three physical PTE
reads. There are 50 demand hits, including 48 independently associated full-token
store-hit samples. Store-hit translation-to-checked latency sums rise from 0 to 48;
all store upstream-to-checked latency sums rise from 71 to 119. The old same-cycle
hit pass count changes 50 to 0. Prechecked loads remain separately counted at 55
and 103; they are not substituted for proof of M2 demand-hit coverage.

Each VM case uses one accepted L1D AcquireBlock, one whole-line Grant and one E
acknowledgement. Instruction requests/beats remain 136/136. No additional memory
traffic, ownership capacity or fabricated early response accounts for the cycle
comparison. Both selected old RAM programs reproduce their P1 metrics exactly;
baseline effective config and core parameters match P1 except the two explicitly
new false-valued fields.

The corresponding component results are separate evidence: M2's 256-request warm
adapter stream retains II1 but costs 265 rather than 264 total cycles, while both
backpressured streams take 357 cycles. R1's 9 cold plus 6 warm whole-frontend
scenarios match all 570 P1 fields. These component results do not replace the CPU
retirement comparison above.

### Necessary test-only repairs retained in the record

The initial Scala compile and ten focused configuration tests passed. Real-header
checking then caught GSIM's invalid setters for top-level Vec inputs in the new
permission fixture. That fixture's PMP pins and the not-yet-generated CPU
fixture's eight Grant words were flattened without changing production RTL or
stimulus. A second independent issue was a test tap attempting to bore an unbound
false literal in the registered adapter configuration; its observation was made
statically false. These required two minimal incremental test compiles, not a
repeated broad regression.

The already-passed buffer, permission and baseline adapter models were reused
under their original source and artifact bindings. Both failed attempts, exact
original Scala archives and repaired-source manifests remain separate. The
baseline undrained-flush log retains its exact hardware assertion; its original
runner verified nonzero exit before advancing, but that aborted process's
numeric exit code was not retained and is not invented in the resumed receipt.
No new SV export, physical run, FPGA frequency, PPA or board qualification was
performed in this cloud-only batch.
