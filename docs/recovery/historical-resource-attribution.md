# Historical 223453b FPGA resource attribution

## Scope and identity

Read-only inspection on 2026-10-16 of commit
`223453bae0185dcc59b9ea5414ddb266e1f5af93`, top `soc_top_fpga_next_ddr`,
part `xczu15eg-ffvb1156-2-i`, Vivado 2025.1 Fully Placed checkpoint.
This is **not a measurement of current dev**. Subsequent changes may already
reduce some named cones; compare current source before selecting another change.

- DCP: 83,857,374 bytes; SHA-256
  `6b2d34c47326d130b4fde46552d9870aaad5ad7e7d608f48aca4cb686cff5928`.
- Readable EDIF: 301,409,838 bytes; SHA-256
  `19e8d63c6555cbd642f5d067a2bbc6f19f2bffbe28433d9537873a668ad7c4a4`.
- Original manifest SHA-256:
  `8ada9a130649422e73c85a28ced2c804b60cbfac327a6413889eceac36fc81cf`.
- Original bundle Library ID: `libfile_5254f9d921e8819194a36c55da5056fe`.
- All 38 original members and original manifest remained unchanged.

## Counting method and reconciliation

RapidWright 2025.1.3 loaded the explicit DCP+EDIF with automatic data downloads
and Vivado disabled, a 4 GiB Java heap, two active CPUs and 600-second timeout.
No design modification, route construction or checkpoint write occurred.

All 358,689 physical cell records were inventoried by physical name/type,
EDIF mapping where available, site and BEL. LUT occupancy counts unique
`site + [A-H]` slots for BELs `[A-H][56]LUT`, so two 5/6-LUT occupants count once.
242,106 LUT-BEL records occupy 194,715 slots; 47,391 slots contain two records.
The independently counted families exactly reconcile with the original
`original-post-place/utilization.rpt`:

| Resource | Physical slots | Vivado report | Difference |
|---|---:|---:|---:|
| Logic LUT | 185,956 | 185,956 | 0 |
| LUTRAM | 8,328 | 8,328 | 0 |
| SRL | 431 | 431 | 0 |
| Total LUT | 194,715 | 194,715 | 0 |

There are 33 distinct DSP sites, despite multiple expanded DSP sub-BEL records
per DSP; these records are not independent DSP blocks. Physical BRAM types are
75 RAMB36E2 and one RAMB18E2.

4,300 physical records lack direct EDIF cell linkage, chiefly vendor-IP and
port/locked records. They were **retained**, using physical names and types.
This is a complete physical inventory with partial EDIF linkage, not a claim
that every logical cell was independently mapped.

## Disjoint major scopes

Let `P = u_soc/board/platform/` and
`B = u_soc/board/platform/core/core/core/backend/`.
More-specific PMP/PRF/ROB/LSU/FPU prefixes take precedence over enclosing scopes.
A slot containing occupants from different scopes is assigned only to the
separate shared bucket, never to both. The full partition sums to 194,715.

| Scope | Exclusively owned LUT slots |
|---|---:|
| B children, excluding separately listed scopes | 29,036 |
| P fetchCache/privateCache/coherentHome, excluding PMP | 28,604 |
| Twelve PmpChecker instances | 18,604 |
| Direct B cells, excluding child hierarchy | 17,783 |
| B systemUnit/floatingPoint, excluding PMP | 14,802 |
| Remaining design outside listed scopes | 13,369 |
| P core/core/core outside backend | 11,397 |
| u_ddr | 11,376 |
| Interconnect and u_axi_cdc | 8,920 |
| Translation and request adapters, excluding PMP | 8,637 |
| u_soc/board/nativeBank | 7,190 |
| B lsu | 6,339 |
| B ledger | 6,321 |
| P frontend, excluding PMP | 5,538 |
| P packetDma | 3,938 |
| B physicalFile | 2,833 |
| Cross-scope shared slots | 28 |

Interconnect means exact P children `manager`, `crossbar`,
`crossbar_io_masters_0_boundary`, `crossbar_io_masters_1_boundary`, `arbiter`,
`bridge`, `romManager`, `platformRouter`, plus `u_axi_cdc`.
Translation means P `core/adapter`, `fetchAdapter`, `physicalData_adapters_0/1`,
`physicalData_walkers_0/1`, `physicalFetch_requests`, `physicalRequests`, with
PMP subtrees removed. Remaining design is the exact complement, not a single
module. Do not add overlapping Vivado hierarchy totals to this partition.

## Backend detail

The 29,036-slot residual-child scope decomposes by exact B child prefixes:

| Child prefix | Slots after prior exclusions | Notable raw physical types |
|---|---:|---|
| systemUnit, excluding floatingPoint | 6,566 | 4,044 FDRE; 171 MUXF7, 51 MUXF8 |
| pendingStoreProof, excluding pmp | 5,369 | 1,427 FDRE; 1,554 MUXF7, 760 MUXF8 |
| alu | 3,175 | bitManip subtree; combinational integer lane |
| alu_1 | 3,174 | second integer lane; not proven redundant |
| payload_2 | 2,535 | 2,232 RAMD32 + 328 RAMS32 raw records |
| multiplier | 1,663 | 2,728 FDRE |
| Other residual children | 6,554 | ownerReady, mulDiv, stores, selectors, etc. |

Direct-backend name groups below count exclusive LUT slots after splitting
only the 17,783-slot own scope. Generated names are attribution clues, **not
netlist-isolated functional cones**. `[n]` is normalized to `[]`; the sixteen
`storeData_n` and `storeAddress_n` banks are grouped by family. Generated
`_i_n`, `_INST_n` and `_reg...` suffixes are stripped. Cells such as
`B/executionStages_0_i_...` remain backend-own, distinct from child cells under
`B/executionStages_0/`.

| Direct-cell family | Exclusive slots |
|---|---:|
| storeData row family | 1,793 |
| storeAddress row family | 1,598 |
| io_posted_starting | 1,339 |
| executionStages_0 / executionStages_1 | 1,306 / 1,279 |
| stagedMemoryAddress[] / stagedMemoryData[] | 715 / 594 |
| stagedMemoryToken_tag[] / replayPending_token_tag[] | 576 / 576 |
| multiplier / mulDiv / lsu | 703 / 661 / 656 |
| ledger / pendingStoreProof / systemUnit | 523 / 493 / 462 |
| canonicalStoreTracker / physicalFile | 457 / 453 |
| Slots shared between own-name groups | 1,151 |

Other smaller own-name groups remain in the 17,783 total. Neither the grouped
LUT counts nor repeated token-bit names establish identical Boolean functions.
Historical `IntegerBackend.scala` lines 417–435 define the per-ROB store state;
lines 806–808 define staged token/address/data; lines 943–952 and 1036–1068
show saved/selected/resident payload selection. These are concrete places to
inspect data layout, selection width and ownership transitions while preserving
accepted requests, replay, exceptions and backpressure.

The PRF itself has 2,833 slots: 1,205 logic and 1,628 LUTRAM, only 96 FFs and
zero BRAM. Its 1,628 RAMD64E records show distributed RAM already in use.
The evidence does not support treating it as a large flop array or assuming
that synchronous BRAM can replace its ports without an architectural change.
ROB `ledger` has 6,321 slots, including 352 LUTRAM; its 1,107 MUXF7 and 492
MUXF8 records make selection/ownership an inspection target, not proof of waste.

## PMP replication: same implementation family, different contexts

The twelve exact prefixes below total 18,627 inclusive Vivado LUTs and 18,604
exclusive slots. Similar module names or equal counts do not prove identical
input functions or permission decisions. Historical source was inspected at
the exact commit, not inferred from current dev.

| Prefix (relative to P unless marked B) | Vivado LUTs | Input context from historical source |
|---|---:|---|
| core/adapter/pmp | 2,168 | translated request address/size, saved head privilege, atomic/read/write access |
| core/adapter/nextAllowed_authorize/checker_0 | 1,677 | next cache line, size 64 B, READ permission; cannot reuse current store WRITE grant |
| B pmpCheck | 2,173 | selected memory address/size/data privilege, atomic/read/write access |
| B pendingStoreProof/pmp | 1,766 | translated proof payload, aligned physical address, owner epoch/validity context |
| B systemUnit/floatingPoint/memoryOption/pmp | 1,766 | prepared FP payload, FP size/store mode, data privilege |
| fetchAdapter/checker_0 and checker_1 | 1,049 each | two instruction word addresses; second may belong to a distinct translated page |
| frontend/checker_0 and checker_1 | 1,049 each | two fetch lanes from permission base/context; EXECUTE access |
| fetchCache/pmp | 1,673 | whole physical request line, size 64 B, EXECUTE access |
| physicalData_walkers_0/walker/pmp and _1/walker/pmp | 1,604 each | independent page-walk PTE addresses, 8-byte READ, S-mode permission |

Source anchors: `DataTranslationAdapter.scala:380–388,491–499`,
`NextLineAuthorization.scala:23–33`, `IntegerBackend.scala:1208–1216`,
`PendingVirtualStoreProof.scala:239–247`, `FloatingPointMemoryPipeline.scala:65–73`,
`InstructionTranslationAdapter.scala:171–188`, `InstructionRom.scala:439–455`,
`InstructionLineCache.scala:84–89`, `SvPageTableWalker.scala:59–65`.
These support exploring shared state decoding separately from independent
per-request permission evaluation. They do not establish safe time sharing,
mutual exclusion, stall tolerance or permission-result reuse.

## Fanout evidence and next inspections

The first CPU path in matched `read-only-export-r2/setup_paths.rpt` reports
`B/_planner_io_freshOwner[10]` fanout 214 (line 242),
`B/systemUnit/io_fetchPrivilege[1]` 180 (line 190),
`B/physicalFile/io_address_1[0]` 153 (line 254), and
`B/io_vmState_dataPrivilege[0]` 77 (line 194).
These are **Vivado report fanouts on that sampled path**, not an exhaustive
fanout ranking or newly queried EDIF fanouts. `B/bareOrdinaryRam2` has report
fanout 33 (line 198), separately confirmed by EDIF with 33 mapped sinks.
No fanout is inferred from primitive counts, repeated names or missing physical
site pins. The checkpoint is unrouted; route-delay estimates are not timing
qualification.

Priority for source inspection, not promised savings:
1. Proof-row selection/owner validation and backend store/payload selection:
   the 5,369-slot proof body and broad own-name families provide direct evidence.
2. Non-FPU system/CSR and PMP state decoding: 6,566 slots plus twelve request
   checkers; preserve distinct privilege, access kind, owner and translation age.
3. Banked issue payload and two execution-lane operand/control selection:
   keep multiwrite/read throughput and the two-issue baseline explicit.
4. Cache/coherence and interconnect selection/storage, then ROB ownership:
   their measured scope is larger than PRF storage alone.

No estimated area savings, timing improvement or safe port reduction is claimed.
No large physical inventory or checkpoint is required in Git; this report can
be preserved with the original hashes, counting method and source anchors.
