# Default-off local selection rewrites

This candidate adds five default-off controls to the tested 785e3db 59-option profile. The explicit 64-option entry retains the existing two-issue topology, tri-speed Ethernet, MAC T1 and BSCAN USER2. The default 52-option and existing 59-option command paths remain unchanged.

| Control | Structural change | Controls retained |
| --- | --- | --- |
| `fetchReadyDataClear` | Clear inactive adapter response data from the existing ready state; real response assignment retains priority. | Request authorization, state, faults and response ownership |
| `memoryPreparationHeadMask` | Derive the memory-preparation head row from the existing registered head mask. | Eligibility, ranking and guarded PRF access |
| `directRank0MemorySourceIds` | Remove redundant valid-to-zero selection from one-hot rank-0 source IDs. | Selected-owner validity and data capture |
| `retirementSlotIdentity` | Specialize same-cycle finishing identity to the two actual head rows. | Full index/tag, raw duplicate priority, completion admission, faults and commit recovery |
| `localCacheReadSelection` | Remove direct-eviction dependence from SRAM-row and posted collision-index selection using existing queued/probe priority. | Enables, capture, accepted ownership and WB1 retirement veto |

## Bounded qualification

- Compiled all 201 production and 384 test Scala files; 19 targeted configuration tests passed across six suites. This is not a full test-suite run.
- Address: 2,612 paired cycles; retirement: 719 backend and 2,351 independent ROB cycles; cache: 3,518 cycles, 17 positive and six exact RTL negative controls. Fetch adapter and staged frontend pairs passed their component gates. Component coverage remains bounded to those fixtures.
- Compared all 290 native modules. Interfaces, register/memory declarations and instance identities match, with zero added state bits. Functional changes are limited to `InstructionTranslationAdapter`, `IntegerBackend`, `RenameRob` and `NonBlockingCoherentLineCache`. This is not formal equivalence or a mapped resource result.
- The original phase-0 64-KiB COPY workload, two repetitions, matched actual 78559 at 191,618 Sv39 and 198,642 Bare inclusive cycles. Inclusive, ROI and clean-tail deltas are zero. All original 105 result fields and all remaining metrics match; complete stdout and raw AXI/supply traces are byte-identical. The three original read/memory/trap negative controls passed.
- Reused the same 36 ON model objects for two existing NEMU guests (1,883 and 967 cycles), with identical counters/stdout and three PC/GPR/memory negative controls. Both short/word PMP guests matched their retained trap results and stdout. No additional DUT generation, OFF build, guest build or reference build was used for these checks.

The first combined CPU emission rejected a missing cache-flag forwarding argument in its service fixture. The preserved correction adds exactly that argument to `MatchingManagedBoard`; production source did not change. Exact source and native-byte bridges bind the reused native evidence. Historical profile checks retain explicitly named field projections; new false fields are not silently discarded.

Physical timing has not been run for this candidate. The previous 785 placement failed setup and hold (WNS -1.640 ns, TNS -16467.553 ns, WHS -0.359 ns). No Fmax, LUT/FF savings, throughput improvement, routed result or board qualification is claimed.

## Explicit entry and reproduction sources

Run `python3 -B fpga/next/board_timing64.py --output build/fpga-next-locality64` for source preflight only. Add `--emit` only when a real native export is intended. `fpga/next/timing-batch-locality64-profile.json` pins the reviewed production leaves and exact 59-plus-five options. Historical mapped/library certificates do not qualify the new RTL.

The eight source-only CLI/entry test groups use a pre-overlay candidate tree as their baseline. To reproduce them, copy this candidate source into a separate directory and replace only its `fpga/next/export.py` with that file from 785e3db. Then run `python3 -B fpga/next/test_timing64_export.py --baseline-root PATH_TO_COPY`. A plain 785 checkout lacks the new production leaves; this candidate checkout alone no longer has the old exporter. The tests compare old 52/59 commands and dictionaries, exact 64-option consumption, invalid flag/topology rejection, T1/USER2, and source binding without invoking hardware tools.

The component fixtures include `ooo.FetchReadyDataClearComparison`, `ooo.AddressLocalityPairGsimMain`, `ooo.RetirementSlotPairGsimMain` and `ooo.CacheReadSelectionPair`; independent hosts are retained under `simulator/gsim/harness` and the cache fixture under `simulator/gsim/posted_cache_rebuild`. `ooo.R3ReadLocalityFullCpuMain` and `ooo.R3ReadLocalityProfileMain` expose the combined CPU and exact constructor profile. Use the repository's pinned GSIM/Mill flow and fresh output directories for new runs.

The Python export overlay was added after qualification. All frozen Scala production/test inputs and host inputs remain byte-identical to the qualified source. It changes option parsing and explicit entry binding only; no new IR or CPU run was inferred from the source-only export tests. The compact JSON beside this document binds the explicit 64 options and identical production source to terminal CPU/native qualification receipt `2ea5ea4635f0f8f29bf51e5e92dff162485b2a82dbfcaba5eb1d729ecc072607`, binds published source bytes, and records the bounded results. Detailed execution evidence remains separate from the source tree.
