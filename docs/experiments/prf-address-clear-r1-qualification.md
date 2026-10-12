# Rank-1 PRF source-ID clear qualification

Candidate: directRank1MemorySourceIds, default OFF. Base is published503f47c0f83411895b92bdd766e5c33ababf8bad / tree51af502db9c15961150f76fc46f709d0400b75c7. The source snapshot preserves current T1/BSCAN and shared lane-1 ROB ownership. No pipeline cycle, state, PRF port, memory selection pool or authorization change.

The production change removes only rank1 source1/source2's redundant secondValid clear. The selected source IDs already come from the owner-masked whole-entry payload and are zero with no second owner. Rank0, immediate-memory guard, PRF range-safe address and x0/initialization behavior, full-token/kill/PMP/pending checks and saved-store qualification remain intact. The option requires registered/parallel/compact preparation and excludes memoryProofFrontier.

## Completed focused evidence

- Configuration: 12/12 affected Scala tests. Full old constructor values remain checked; the only new profile/core field is explicit default-false directRank1MemorySourceIds.
- Component: 3,338 cycles, actual paired MemoryPreparationSelector, whole-entry masked metadata helper, guarded BankedIssuePayload and owner-banked PRFs. Independent host circular-order/word-value oracle compares valid and invalid source IDs, operands, prepared and unconditionally captured payload. Includes all high IDs48–63 under empty and selected owners, empty/single/multi/wrapped pools, issued exclusion, second disappearance, saved stores, readiness transitions, same-edge read/write, lane collision, reset, x0 and uninitialized reads.
- Component sensitivity: nine controls rejected with actual corruption counts, including an actual RTL raw-index0 mask bypass. Other eight corrupt sampled candidate observations while leaving oracle expectations unchanged. The small request/completion sink is fixture-local; its results are not CPU evidence.
- Actual decoded backends: identical positive logs and complete passive cycle transcript over3,863 cycles. OFF/ON products have all156 fields checked against published47 with the same five pre-existing short-host exceptions. sharedLane1OwnerMatch stays ON on both sides. Five original controls on each side reject corruption of data, frozen physical address, acknowledgement, store error and retirement.
- Both gates run with combined ASan/UBSan. No sanitizer finding. Sixteen default-OFF objects are reused only after exact TU and entire local header identity, same pinned compiler/environment, equal non-include flags and exactly one model-local include directory. One changed assertion-location TU is rebuilt. System headers were not individually hashed in the original gate; no stronger claim is made.
- Paired native: default-OFF byte-identical to the saved qualified lane1 ON native model. ON changes exactly io_address_3 and io_address_4 in IntegerBackend; remaining native tokens are identical after restoring those two expressions. Selector, PRF, ROB and every other module are byte-identical. secondValid is absent from those PRF address cones and remains in saved-store qualification downstream.
- Full native: one successful48-option ON board emission, exact156-field core and66-field FPGA products, no fixture override, same target assembly/service contract. All239 native modules are identical to qualified lane1 except the same two backend port expressions; sequential inventory is unchanged. See full-native-r3/receipt.json and comparison.json.

## Full CPU status

PASS. One fresh ON model,36 official split translation units, one serial compiler job, and zero new OFF builds. Sv39 is exactly191618 inclusive cycles and Bare194153. All105 functional fields, complete metric/raw sections, ROI/tail partitions, tagged returns, raw supply/AXI event files and valid-first/per-channel duty measurements match the qualified ABC baseline and published lane1 result. Original read/memory/trap controls reject correctly. ASan/UBSan are clean. CPU generation, compilation and runs total203.305 seconds of serial child wall time with peak1,927,256KiB RSS.

The original two NEMU inputs pass using these same36 ON objects with zero DUT generations/object compiles/reference rebuilds or reference resynchronizations. Hot:1847 cycles,108 guest PC checks and2656 GPR values. Compressed:958 cycles,24 guest PC checks and672 GPR values. Both compare4,194,368 final memory bytes. Original PC/GPR/memory controls reject correctly. The qualified CPU receipt, artifacts and dependency output remain unchanged. These NEMU inputs cover short physical integer M-mode behavior, not VM, FP, CSR, permissions or concurrent DMA.

`qualification.json` is the independent final closure: raw CPU/NEMU logs re-parsed, all bound source/model/dependency artifacts checked, native audit re-run without rebuilding. Candidate source tree153a58bb49551f47214d78f6140d62e74ca91015 preserves all three base gitlinks. No remote branch or main was changed.

## Failures and limits

All failures are preserved in failures.md and their original outputs. They are setup/test schema maintenance or audit-parser failures; two full-board attempts stopped before elaboration because the entry allowlist and then serializer arity still reflected the older schema. The subsequent exact test-only four-file bridge preserves every old byte and permits only the one new option and updated66/156 arities. No short DUT was regenerated for those serialization repairs.

This is retained native structural and GSIM qualification. Mapped FPGA timing, placement, area and physical fanout remain unmeasured. Removing the duplicated PRF gate does not remove secondValid's downstream saved-store path, and no performance gain is claimed from native topology alone.

## Exact final source scope

The candidate has18 changed/new source files relative to published503f:

- Four production Scala files: IntegerBackend.scala contains the two-source-ID change; OooParams.scala declares/guards the flag; FpgaNextConfig.scala and BoardSocTop.scala forward it. RenameRob and the PRF implementation are unchanged.
- Two public Python front doors: fpga/next/export.py and simulator/gsim/fpga_next_board.py forward the explicit flag and reject duplicated/valued forms.
- Six existing test files: PendingStoreProofGsim.scala adds the matched backend argument; TimingBatchConfigSpec.scala checks the new default-false field; CpuMatchingBoardProfileGsimMain.scala adds the explicit allowed option; PostedStoreBoardLineageGsim.scala, MatchingFabricAudit.scala and FpgaNextProfileMain.scala update exact schema arities.
- Six new qualification files: three Scala fixture/emitter/config files, rank1_prf_address_pair.cpp, prf_address_clear.py and test_prf_address_clear_cli.py.

See qualified-source-tree.json for each exact path, blob, mode and SHA-256. The final entry author separately owns the report/48-option manifest/physical-entry overlay and the sole CAS publication list; this candidate does not create a competing CAS.
