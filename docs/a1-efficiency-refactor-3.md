# A1 efficiency refactor — third experimental candidate

**2026-10-27: the source-rebuilt normal-tile map exited successfully and
independent final resource review passed. The measured identity is the frozen
precommit source snapshot; a later commit requires a separate continuity record.**

The direct control is hardware commit `ad7e67544ef77635b2be8e8bbd97c71564313f52`,
with its documentation correction at
`c0ef611bea5a339e6d4c50a9d7b024b7ef9602de`. The candidate is the explicitly
identified dirty source snapshot on that base, not an implied later commit.
See [the second checkpoint](a1-efficiency-refactor-2.md).

The experiment moves ROB completion **data, next PC and trap value** into
writer-owned memories. It does not remove ownership checks, narrow tokens,
change retirement semantics, add pipeline stages or reduce the two-wide CPU.
The previous execution summary records **no cycle improvement** in either
CoreMark seed or the dependent-load control. The mapped primitive-count saving
is therefore an area-oriented result, not an IPC or bandwidth improvement.

The new mapping reports **184793→177202 logic LUTs (−4.1078%)** and
**54970→51918 FFs (−5.5521%)**, at a cost of **648→698 LUTRAM primitives**
(+50 RAM32M16 instances). BRAM36 and DSP counts remain 16 and 30. Independent
review passed; packed area and physical frequency remain unmeasured.

## Exact configuration and scope

`CommonA1RebuildProfile.FullR1M3EfficiencyRefactor3`
(`full-r1-m3-efficiency-refactor-3`) adds exactly one default-OFF flag,
`bankedRobCompletionData`, to the second efficiency profile. Older profiles keep
it OFF. The existing separate `WriterBankedRobCompletionPayload` option remains
unchanged and is mutually exclusive with this new implementation.

Retained: two issue/two writeback, ROB16, PRF48, LSU4, SB2, full 64-bit owner
and generation tokens, 13 logical/26 bank PRF reads, 256-entry original-index
bimodal predictor, I/D 32 KiB two-way caches, PMP, FP, AMO, coherence, debug,
precise exceptions and original admission/recovery/retirement authority.
No fast retirement option is newly enabled. The normal `CommonA1CpuTile` ABI
remains 256 ports and 4482 bits, including unchanged port names and directions.
The benchmark safe-fetch window remains `[0x80200000,0x80220000)`.

## Storage and timing contract

`DualWriterRobCompletionData` is payload storage, **not an authorization unit**.
Its writes are driven only by the unchanged ledger's `completionAccepted`.
Full-token matching, stale/duplicate rejection, recovery suppression, done and
exception state, cause, ordered retirement and existing same-cycle bypasses
remain in the caller.

For the 16-row candidate:

- Each of two accepted writers owns two parity banks of packed
  `Cat(data64,nextPc64)`: four 128-bit × 8-row memories.
- Each writer also owns one 64-bit × 16-row `tval` memory: two more memories.
- These six memories contain 6144 stored bits. A shared, unreset 16-bit
  latest-writer directory selects the most recent writer for each row.
- Each memory has one clocked write and one asynchronous read port. Data and
  next PC supply two consecutive ordered retirement rows, including wraparound;
  trap value supplies the head row only.
- Two distinct completion rows may be written in one cycle even if they have
  the same parity, because the writers own separate banks. Same-row simultaneous
  writes violate the module contract and are asserted against.
- Combinational read latency is zero, sustained initiation interval is one,
  and no ready/credit/backpressure interface or added pipeline stage exists.
  There is no internal write-through; existing caller bypasses remain intact.

Allocation, recovery, retirement and reset do not clear these memories or the
latest-writer directory. Unwritten memory is not assumed to be zero. The
caller's unchanged done-state projection reconstructs the original
allocation-zero semantics, including raw output fields when their enclosing
valid is false. A previously completed row retains its raw payload after
retirement or rollback, as before. Cause stays in the original register
structure; token, destination and authoritative metadata are not banked here.

The new normal export and recursive `proc` inventory independently confirm
**54→60 memory instances**, exactly the old 54 plus these six banks, and the
16-bit directory. This is structural confirmation, not a final mapped saving.
The old 48 × 64-bit payload vectors disappear from the export, but counting
those 3072 bits is not a substitute for post-mapping FF/LUT counts.

## Verification evidence: separate historical and current epochs

The cloud workspace reset after the original mapping interruption. Source was
preserved, but the third batch's original runtime logs, generated simulation
object and RTLIL checkpoint were not in its durable source backup. The table
below deliberately separates a **reported earlier result** from evidence that
can be inspected or rerun in the present workspace.

| Evidence | Earlier 2026-10-26 execution summary | Current 2026-10-27 recovery |
|---|---|---|
| Scala compilation | Passed after the documented initialization fix | Fresh compile passed, exit 0, 162.09 s, owned cleanup empty |
| Pure configuration/elaboration checks | 40 tests / 12 suites reported passed | **39 tests / 12 selected suites passed**, exit 0; this is not the same count |
| Components | 13 bounded cases reported passed | Not rerun in this epoch; original third-batch raw logs are absent |
| CPU | 30 bounded cases reported passed | Not rerun in this epoch; original third-batch raw logs/object are absent |
| Source restoration | Frozen third candidate | 17 modified + 5 new Scala files match all preserved SHA-256/size records |
| Normal export/proc inventory | Prepared before interrupted map | Newly executed and independently checked, normal ABI and six new banks confirmed |
| Complete normal map | **Not completed**, exit status unknown | New source-rebuilt attempt exited 0; final independent resource review passed |
| Physical implementation/Fmax | Not established | Not run or established |

The earlier component summary describes eight raw-storage cases and five
paired-ledger cases. It records 4/8/16/32-row storage coverage, same-parity dual
writers, all 16 retirement head positions and wraparound, all 64 token bits,
held outputs, recovery retention, reversed writer order, system-head behavior,
precise exception fields, and assertion-negative cases. Its independent oracle
uses flat 24-byte rows plus an ordered ledger, rather than duplicating the DUT's
parity-bank/latest-writer equations. The exact three successful C++/header
sources survived and are listed in the migration plan, but source availability
alone does not recreate missing execution logs or constitute a new pass.

The earlier CPU summary reports all 30 candidate stdout streams, including
passive `DIAG_` lines, and stderr exactly matching the second-candidate control.
It identifies independent architectural/CRC/traffic checks and unchanged FP,
PMP, VM fault, canonical-forwarding and recovery cases. This report retains that
historical result with its evidence limitation; the new pure tests and normal
RTL export do **not** independently re-establish CPU behavioral qualification.
Neither epoch is full ISA, formal equivalence, Linux or board qualification.

### Preserved failures and recovery

1. The first historical pure-test pass failed 18 of 40 tests because an early
   `FpgaNextConfig` requirement read a later-defined `issueWidth` value during
   initialization. The retained fix removes only the redundant early
   `issueWidth == 2` conjunct; the fixed width and actual parameter width guards
   remain. The restored source includes this fix, not the failed revision.
2. A historical ledger-host accessor macro missed a token-pasting operator.
   The qualified accessor-r2 host is preserved separately from that failed host.
   Historical host-preparation parser failures were likewise not DUT changes.
3. The original map stopped after a checkpoint had been written. Its tool wait
   was reported as aborted, the session later became unknown, and neither a
   successful exit nor owned-process cleanup was established. The actual cause
   was not established. The lost checkpoint is **not** being used now.
4. The current export inspector initially assumed an incorrect generated
   memory-module naming/instance shape. Only the inspection code was corrected;
   failed inspection evidence was kept, the design was not edited, and RTL was
   not re-exported merely to make the check pass.

The current result must be called a **new source-rebuilt mapping attempt**, not
an uninterrupted map or a checkpoint continuation. Original unknown exit and
cleanup remain unknown; a new clean exit cannot retroactively prove them.

## Performance: historical third-batch result is zero incremental gain

These values come from the prior execution summary. The second baseline's
archived logs remain available; the third batch's raw logs were not recovered.
Both use the unchanged common RV64IM_zicsr CoreMark guests, one iteration,
2000-byte working set, independent ISA/CRC/physical-memory oracles and the same
ROI retirement boundaries and memory service law.

| Seed | Second baseline ROI | Third candidate, earlier reported run | Incremental throughput gain |
|---|---:|---:|---:|
| Performance | 379635 cycles | 379635 cycles | 0% |
| Validation | 380223 cycles | 380223 cycles | 0% |

Reported ROI instruction counts remain 360525 / 360366, architectural hashes
`eb74228486f9b622` / `fe7c19b5e0fe46c4`, and CRCs
`8e3a1fd7e714e9f5` / `8d840747e3c118f2`. The dependent 65-load guest retains
64 retirement intervals of six cycles, ROI 384; unrolled work/total cycles stay
2306/2332. No new bandwidth gain, saved dependency cycle, or predictor benefit
is established by this storage-only batch.

The earlier two batches' cumulative equal-clock CoreMark throughput gains versus
e9 remain **10.1727% / 10.1127%**, not a third-batch gain. The matched Nax program
still records 268873 / 269245 ROI cycles: the Valence/Nax ROI cycle ratio is
approximately 1.412, or about 29.2% fewer cycles for Nax. At equal clock that
corresponds to approximately 1.412× throughput. FP/PMP/coherence/address/cache/debug scope differs;
this is not an equal-feature PPA comparison or a frequency-adjusted ranking.
This short one-iteration experiment is not an official CoreMark score.

## Normal mapping comparison

The current recipe retains the second baseline's xcup `synth_xilinx` flow,
normal top, flattening and `-noiopad -noclkbuf` options, manual coarse suffix
with `memory -nomap -nosat`, and the same Yosys/ABC/mapping-library identities.
There is no baseline resynthesis, SAT-sharing substitution, probe-rich top or
new timing-driven implementation. The owned-resource guard uses four CPUs,
6 GiB sampled RSS, 512 MiB reserve and a 3600-second bound; this is not a kernel
hard memory limit. This new attempt completed in **1858.953 seconds**, with
peak sampled owned-group RSS **4,249,190,400 bytes**, actual exit 0, check 0 and
verified empty owned-process cleanup. All 32 warnings match the baseline; no
residual generic memories or processes remain. Independent final resource review passed.

| Primitive category | Second baseline | Third candidate | Delta |
|---|---:|---:|---:|
| Logic LUT | 184793 | 177202 | −7591 (−4.1078%) |
| FF | 54970 | 51918 | −3052 (−5.5521%) |
| LUTRAM primitives | 648 | 698 | +50 (+7.7160%) |
| BRAM36 | 16 | 16 | 0 |
| DSP | 30 | 30 | 0 |
| MUXF | 28460 | 25636 | −2824 (−9.9227%) |
| CARRY4 | 5592 | 5592 | 0 |
| INV | 1968 | 1966 | −2 |

Independent mapped-cell inspection traces all six new memories to the 50 added
RAM32M16 primitives: each of four packed banks uses ten, and each of two trap
value banks uses five. All 3072 old payload FFs disappear. The replacement
requires 16 latest-writer-directory FDREs plus four shared trap-value read-address
FDREs, giving the observed net **−3072 + 16 + 4 = −3052 FFs**. The four read-address
FFs are synthesis extraction/replication of existing head state, not a new RTL
stage or an additional architectural cycle. The total LUT result already
includes directory and readback costs. ABC shares logic across boundaries, so
no exact exclusive readback-mux LUT cost or additive saving is inferred from
an inclusive connectivity cone.

The LUTRAM total comprises RAM32M16 **316→366** and RAM64M8 **332→332**.
These are primitive-instance counts, not equivalent logic LUT area; do not
subtract the additional 50 instances one-for-one from logic-LUT savings or
claim a packed-area percentage. Compared with the original e9 reference,
logic LUTs are **198291→177202 (−10.6354%)** and FFs
**59318→51918 (−12.4751%)**. Those are cumulative changes across three batches,
not this batch's incremental saving.

Do not predict the table from removed source registers or add overlapping
connectivity-cone counts. LUTRAM uses storage/logic resources too, so any trade
must show all categories. Primitive counts are not packed area, path depth,
critical-path delay, routed Fmax or power. A nominal 3.333 ns target, if carried
in project metadata, does not establish an achieved frequency.

## Current reproducibility and identity

Let `B = build/third-efficiency-full-cpu-mapping-20261027-r1` and
`R = build/third-efficiency-recovery-review-20261027-r1`.

- `B/source-restoration.json`: exact 22-file restoration on c0ef611.
- `B/source-freeze.json`: 1120 compilation inputs; not an all-documents manifest.
- `B/scala/compile-receipt.json`: new compilation epoch and 5263 compiled
  classpath files, separately bound from source.
- `B/prep.py`, stage command/runtime receipts and logs: fresh compile,
  39 pure tests, normal export, sv2v and proc inventory. Do not rerun these merely
  to query an existing result.
- `B/receipt.json`, SHA-256
  `18837ca2a41cbd312fe682a8503718ce3c6a526d3a6dc2bb0acc0444694220fc`,
  and `B/manifest.json`, SHA-256
  `41fd52678065397ffe859b217f1f6fde00a2b1f68359b1b5d53d548cd683e7c2`:
  sealed current-epoch mapping and artifact identity.
- `B/admission-proposal.json`, SHA-256
  `49e06bd24d2ef5973b16d29c35785fd81f45b5e56d29fe118c8c26d34e8f65fc`:
  535 bound tool/input files for the admitted new map.
- `R/map-admission-independent-review.json`, SHA-256
  `5d24e1b492be4a3d2c0b5f396aff3acb209619ccf8a5c5e979357c6bc93228ad`:
  independent source, tools, ABI, recursive memory inventory and preparation
  cleanup review.
- Tool restoration independently matches Yosys/ABC plus 34 mapping files,
  firtool 1.135.0, sv2v 0.0.13 and 39 prior runtime JARs. Newly bound compiler
  dependencies and environment are a new epoch, not a claim of identical OS.
- The durable PRE_MAP source package includes c0ef611 history, the exact dirty
  patch and five new Scala files, with the three future harness files isolated.
  It is a source recovery package, **not** proof of a completed map.

The mapped JSON has SHA-256
`178720ad61c83ef926ee9e90e344b9efcd25208645c2c6c1c853cfdcf53fafdc`.
`B/map-completion.json`, `B/resource-receipt.json` and
`B/owned-process-cleanup.json` contain the new terminal runtime and primitive
counts. `R/final-mapping-independent-review.json`, SHA-256
`a634e02ea96c748a628cc9cf916c784ea03bdd222a38b5398f801323e993a9a4`,
independently validates the terminal result, exact primitive census, warning
equality, source/ABI/tool continuity and mapped bank mechanism. The archive
manifest and post-commit continuity are separate records and must be added only
after they exist. The three preserved harness files are copied byte-for-byte
into tracked
`simulator/gsim/harness` locations after the map was sealed. This is a real
source-tree addition, not a documentation-only delta, and does not trigger or
prove new executions by itself. The compile-input freeze remains unchanged; a
separate migration receipt records the new host bytes. Keep generated models,
tool binaries and checkpoints out of Git.
