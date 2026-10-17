# Banked store payload candidate, 50cb

Independent branch: candidate/banked-store-data-50cb-r1. Public API: appended `bankedStoreData: Boolean = false`. Constructor propagation reaches FPGA/native/GSIM entry points without changing the board profile case class. See INTEGRATION-CONTRACT.md for exact ON prerequisites and write/read authorization. The coordinator merges this independently with earlyQ, D-only L2 and virtual operand lookahead; no full CPU build was performed here.

## Implementation and correctness boundaries

Only payload changes. Full 64-bit generation tags, row indices, memory/proof/credit/return ownership, address CAM, valid/kill/retirement logic remain intact. Two writer banks and per-row last-writer bit implement arbitrary-address 2W/N-R, including same-address lane1 priority. Reads are asynchronous, pre-edge old/post-edge new, with no combinational write-through; disabled reads return zero. Memory and ownership metadata are unreset, like the old payload. Caller-owned valid/prepared/full-owner state authorizes consumption.

The old Reg(Vec) is retained as independent assertion-only shadow for ON. Both authorized functional reads compare against it, and all existing descriptor/resident invariants remain. No extra RAM read ports service assertions. Source component differs from the mapped standalone component only in its header comment (current hash 03a3a9d95591c59b6322d50a549b359078ff95b56297de200402cfb3d692661a); this comment correction preceded actual-backend emission.

## Structural result

ON and OFF use identical actual core/profile JSON and 12 PRF/8 issue-payload reads. Both emit through the actual backend wrapper. The production firtool 1.135.0 assertion-disabling flags eliminate all 1024 shadow payload bits in ON; OFF retains 16 x 64 Reg payload. The native profile has fastBufferedStoreRetire=false: head output is dead, so ON has only fresh io_data_1, two mem_16x64 banks each one R0/W0, and 16 latestWriter bits. See structural-receipt.json and audit_structure.py. This is structural verification, not a backend FPGA resource/timing result.

## Standalone mapped evidence (conservative two-read interface)

The separate store-data-payload-50cb-r1 artifact tests 4/16/32 entries with the original Reg golden and independent software/live-row oracle, directed collisions/zero-enable/reset/reuse and randomized traffic under ASAN/UBSAN. Four expected-failing oracle-sensitivity controls per size are not RTL mutation tests. Same-address collisions are covered there because legal backend invariants normally exclude them.

For equal 16x64, 2W/2R interfaces, Yosys 0.52 xcup mapping: Reg 1819 logic LUT, 0 LUTRAM, 1024 FF; banked 174 logic LUT plus 20 RAM32M16 (160 allocated LUT sites), 16 FF, 0 BRAM. Total LUT 1819 to 334; FF 1024 to 16. Four useful bank/read copies contain 4096 bits, allocated primitive capacity 10240 bits. Structural longest logic depth 3 LUT levels in both; banked adds at most one async memory read level. No routed ns/Fmax conclusion, no claimed whole-backend savings. Actual native one-read result is deliberately not extrapolated to a resource number.

## Build and coverage history

The first independent backend compile hit Scala StackOverflowError with Xss512k; its failure receipt is retained. With Xss2m, Xmx2g, two active processors and a 4GiB process-tree limit, emission succeeded (203.876 seconds, 3.180GiB observed peak). GSIM generation and 18 sequential clang units succeeded; all qualification uses ASAN/UBSAN. Production source is sealed and unchanged throughout the successful emission/tests.

The first store-reuse traffic ran correct ISA/byte/owner/assertion checks but failed its final coverage threshold: the legal head fast path produced only 24 preparation writes and zero double writes. The failed log is retained. Holding retirement briefly places both stores behind the head; the unchanged threshold then passes: 48 stores, 32 full-tag row reuses, 48 RAM writes and 24 dual-lane write cycles. This is a stimulus fix, not a DUT change or waived gate.

## Completed backend gates

All 12 positives passed: store_payload_reuse-r2, owner_reuse, ready_all_phase, normal_fault_overlap, full_kill, recovery_phase_positive, recovery_cancel_negative (a positive cancellation scenario despite its historical filename), reset_clocked, qlive_cancel, proof_control_scenarios, proof_control_block_new, pool_bare_preparation. Three observer/oracle mutations were rejected for the expected data, killed-retirement and bare-resident-address reasons. See backend-qualification-receipt.json. Negative controls are not RTL mutations.

An independent read-only reviewer also confirmed the hardware SV's complete shadow elimination and one read per writer bank; the unused io_address_0 declaration is not a RAM read port. Integration with the other candidates and full-board resource/timing qualification remains outstanding.

## Reproduction

From the repository, emit only the focused model with `mill -i IonSoC.test.runMain ooo.BankedStoreDataBackendMain OUT on` (or off), using a new OUT directory. Generate GSIM from the emitted ReadyStoreQuery77BackendGsim.fir and compile its numbered C++ units. Compile simulator/gsim/banked_store_data/store_payload_reuse.cpp with model and simulator/gsim/ready_store_query77 include directories; its observed_backend.cpp contains the independent execution/byte/order oracle. The external qualification artifact includes bounded.py, run_backend.py, exact command receipts, original failed attempts, all retained harness scenarios, and source/model hashes. The standalone component artifact retains the randomized Reg/software oracle, mapping commands and primitive JSON. No unrecorded claim relies on rerunning a full CPU.
