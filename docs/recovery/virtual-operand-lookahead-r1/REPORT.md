# Virtual store operand-only lookahead r1

Status: independent default-OFF candidate passed focused qualification. Full-CPU simulation and performance measurement are deliberately held for the subsequent coherent early-Q + D-only L2-64 + virtual-operand + banked-store-data candidate. No synthesis, routed timing, board, or default-promotion claim.

Base commit: `50cb0c5d4b17318904d6cf818ad23829821d5d93`.

## Change and API

Append `virtualStoreOperandLookahead: Boolean = false` to the native/board/platform/core/backend constructor chain and the corresponding test assembly helpers. `FpgaNextConfig.managedBoard` forwards the switch without changing the production default. The only production datapath change is the prepared-store fallback candidate pool in `IntegerBackend` plus a pure qualification helper in `PreparedStorePool`.

When ON and virtualized, an already-prepared ordinary younger store can provide its saved VA, data and full token to existing Q/S storage. Qualification requires pending/live, non-head, matching row index, ordinary memory store/add/non-control-flow, no atomic/system/muldiv/fetch exception, and prepared/address-known. Numeric VA safeRange is not a translation, PMP, memory-type or physical-disjointness proof. The literal Bare eligibility expression is preserved.

The original candidate pool still has priority before issued-owner exclusion. A nonempty original pool does not expose fallback merely because its candidate is already issued. Actual LSU launch remains at the head. Existing full-token/live-source checks, kill/context clear, current-epoch translation/PMP, physical reply ownership, precise exceptions and retirement are untouched. Virtual stores still cannot use posted/local-ACK retirement.

ON is constructor-constrained to the qualified two-wide ROB16/PRF48/tag64, four-LSU-slot, Sv39 machine-system profile with parallel preparation, registered address, resident reuse, prepared-store lookahead, factored pool, registered descriptor, registered head mask, banked issue payload and unconditional payload capture. Posted preparation priority, fast retire/frontier, translatedResponseEmptyFlow and frozenStoreCheckedFlow must remain OFF. No early-Q or L2 change is present in this independent source.

## Focused results

- Scala compile and 20 illegal-combination rejection cases passed. Some combinations are rejected by pre-existing OooParams validation before the candidate contract.
- Actual raw qualification SAT passed over 15 Boolean inputs, six-bit operation and four-bit control encoding, including virtual mode and irrelevant safeRange.
- Actual fallback/Q/S helper test passed 1,085,443 checks: 203,687 virtual captures, 543,055 Bare checks, 262,204 original-issued suppressions and 185,998 stale-high-tag exercises.
- All three helper negative oracles failed as intended: VA-range trust, full-tag truncation, and exposing fallback after issued-owner exclusion.
- Native actual-profile OFF/ON emissions matched all existing saved production profile fields. State inventories were identical: 2,205 explicit Reg/Mem declarations and 1,617 module-port declarations. Actual backend has 12 physical reads and eight issue-payload reads, unchanged.
- OFF CHIRRTL matched saved 50cb after bijective local generated-node renaming and diagnostic assertion-line normalization. Normalized SHA256: `afad0c40b3ac24a48d0e5f50c3107b7eac72403fb9a9e79d0f30bdcc05afe7a1`. This is an elaborated structural comparison, not mapped PPA or formal sequential equivalence.
- All 14 actual-backend positive scenarios and six negative oracles passed their expected outcomes under ASAN/UBSAN.

### New actual-backend reach and safety checks

`virtual_store_operand`: saved Q capture and 87 non-head resident-idle cycles at VA 0x40000000, outside numeric physical RAM; original younger load selected for 38 cycles; no early LSU start or physical request. Independent byte/architectural/full-owner oracle and real response completion passed.

`virtual_store_epoch`: 65 exact-owner prefill observations, clear=1 and context-barrier cycle=1. SATP publication canceled the speculative store without physical effect. Same-VA replay under a new ASID carried the exact full token and new canonical-origin epoch (5→6), used the newly mapped PA 0x80204000 and retired after its real response. The barrier phase assertions passed unchanged.

`virtual_store_faults`: invalid PTE, read-only PTE, A=0, D=0 and misaligned store all remained inert while non-head (76 resident observations each, 380 total). At the head, exact cause/tval and no physical acceptance were checked: cause15 for the four page-fault cases, cause6 for misalignment. No speculative exception or physical write occurred.

Retained scenarios passed: owner reuse (48 owners/32 reused slots), ready-all-phase, normal/fault overlap, full kill, recovery held/cancel, clocked reset, live-Q cancel, proof-control scenarios/block-new, and Bare preparation through both SATP and privilege-mode transitions (194 fallback cycles). The Bare fixture intentionally stops before launching buffered stores; it is preparation-only coverage.

Six backend negative oracles deliberately corrupt observed full token, early-start indication, replay epoch, execution data, killed retirement and Bare address. Each failed with its specific independent error. These are oracle-sensitivity checks, not production RTL fault injection.

## Resource and performance interpretation

The candidate adds qualification/mode-selection logic and reuses existing Q/S storage. Source and native inventory show no new explicit production state or PRF port. They do not quantify mapped LUTs, logic duplication, switching, critical path or timing.

The saved production warm-store result remains Bare32,881 ROI cycles and Sv39-4K/Sv39-2M81,945 cycles for 8,192 measured stores. Physical reply was start+4 in all three; retirement was start+2 Bare versus start+6 virtual, and typical commit-to-next-start was two versus four cycles. This candidate targets preparation gaps only. No candidate ROI reduction has been measured, and no recovery of all six extra cycles is claimed.

## Evidence and failures retained

Local artifact directory: `virtual-operand-lookahead-r1/`.

- `source-snapshot.json` and `check_source.py`: all source entries and diff unchanged since first compile.
- `backend-summary.json`: all 14 positive and six negative result strings, exits and log hashes.
- `native-inventory.json`: profile/state/port/OFF-equivalence audit.
- `logs/*.json`: exact commands, elapsed time, sampled process-tree RSS, watchdog outcomes and log hashes.
- `candidate.patch`: reviewed production/test-Scala patch, including the new emitter; SHA256 `dbb98f589e92bfd3211c9d9a1038dc7697be5bc700fd8b837da87022a14c452a`.
- `qualification-tests.patch`: minimal relocated C++/SAT fixtures; only three lines change in the retained interpreter to parameterize expected store-fault cause, with default7 preserving existing behavior. New fault tests select6/15 explicitly. Relocated backend test sources have syntax checks in `logs/portable-*-syntax.*`; full behavioral runs used the original artifact harnesses. The relocated test bodies are unchanged except the fault interpreter include; only syntax is claimed for the relocated packaging.
- `run_helpers.py`, `run_backend.py`, `run_board.py`, `analyze_warm.py`: exact local recipes. Board/performance stages were prepared but never executed.

One C++ harness link initially failed because a single auto declaration mixed unsigned and uint64_t values. It was split into two declarations; the failed receipt and successful retry are retained. No DUT source or oracle expectation changed. No functional failure was hidden or assertion relaxed.

Saved baseline tracked source entries, model, guest, host and harness hashes were verified unchanged. A temporary unrelated untracked-file event was inventoried and excluded; its owner later moved those files into an isolated worktree. The baseline is clean again. Neither baseline model nor frozen release was rebuilt.

Independent source/test review preceded compilation. The final source seal and all 20 backend result/log hashes were independently reviewed as PASS. Per-command runs were bounded by a 600-second wall watchdog and 4-GiB sampled process-tree RSS; Java used a 2-GiB heap. Native inventory and backend component qualification do not prove full-CPU integration, exhaustive VM/exception coverage, performance or physical timing.

## Integration boundary

Apply the source/test/docs patches to the agreed combined source, preserving both appended early-Q and virtual constructor flags when resolving append-only conflicts. Keep the production defaults OFF. The final explicit configuration is owned by the combined qualification stage; do not use this independent 50cb emitter as evidence that early-Q/L2/banked interactions have been exercised. Preserve both historical flow flags OFF and all original production repairs ON. Cache aperture and shared-PMP changes are outside this candidate.
