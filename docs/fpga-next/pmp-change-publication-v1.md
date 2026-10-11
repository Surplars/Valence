# Exact raw-PMP state-change publication

## Current result

The isolated default-off implementation passes the focused real CSR-to-adapter matrix, native edge checks and matched full-board PMP-ON acceptance. Bare and Sv39 each reproduce all 105 baseline fields and complete AXI/supply traces. No physical synthesis/timing or mapped-resource claim is made.

Native declaration measurements:

- 8 entries: adapter scalar registers 813 → 317 bits, plus one producer event bit, net −495 bits
- 16 entries: adapter scalar registers 1309 → 317 bits, plus one producer event bit, net −991 bits
- The 68-bit VM history remains in both detector variants. The published variant has no previous-PMP bank or full-image comparison. Queue instances and direct array declarations are unchanged. A single optional Boolean crosses the existing producer-to-adapter interface.

These are emitted RTL module declaration counts, not mapped FF/LUT or whole-board totals. The 16-entry raw cfg image includes hard-zero reserved bits, so declaration reduction must not be converted directly into an FPGA FF saving. Raw PMP CSRs, registered decoded regions and parallel PMP checkers are retained.

## Design

`publishedPmpChanges` defaults false in OooParams and FpgaNextConfig, with explicit `--published-pmp-changes` native and GSIM CLI wiring. Effective publication additionally requires machine CSR ownership, implemented PMP, VM, and a precheck or posted-epoch consumer. No sideband or publication state exists without those consumers. Standalone DataTranslationAdapter users retain the snapshot fallback unless explicitly opting into the producer contract.

The producer registers the exact filtered raw-image change each cycle from the same legal executing non-IMSIC write branch that updates the raw cfg/address bank. Local comparisons share the existing cfg sanitization, own lock and successor locked-TOR conditions. OFF-mode address changes count; no-op/filtered/locked/illegal/unexecuted/read-only/held-completion cycles do not. The narrower permission/refetch predicate stays separate. There is no new complete-image producer comparison or request stage.

The registered change level is visible in the raw write edge's post-edge interval. Authorization/posted epochs consume it only at the next edge; contextChanging and the existing mapped CPU blockNew/cache seal fanout remain immediate. Consecutive actual image changes remain consecutive high levels. Producer and consumer inherit the same CPU clock/reset through the current BoardSocTop → MachinePlatform → MappedMachineCore → MachineCore → IntegerCore → IntegerBackend/MSU chain. No independently stopped/reset consumer is supported by this contract.

The initial M=3 live privilege versus zero previous VM privilege is preserved. The native pre-first-release-edge total change is therefore high even when reset PMP is unchanged.

## Focused coverage

Four real MachineSystemUnit → paired fallback/published DataTranslationAdapter models passed 79,689 per-cycle boundary checks:

- 8 entries, live regions, precheck plus posted: 19,119 checks
- 8 entries, registered regions, posted only: 19,040 checks
- 16 entries, live regions, precheck only: 20,765 checks
- 16 entries, registered regions, precheck plus posted: 20,765 checks

The independent software CSR model checks every raw entry and decoded range, CSR results, legal/illegal and RW/RS/RC/immediate operations, reserved/W-without-R filtering, own lock, successor locked TOR, OFF raw addresses, TOR predecessor bounds/underflow, all NAPOT carry lengths, 54-bit extremes, MPRV/privilege and VM changes. The expanded boundary oracle checks full context-change phase, epoch/stability phase, request/response ownership, physical backpressure, response holds, reset with an owner, and current/stale prechecked requests. Candidate invalid request payloads are poisoned; payload comparisons are qualified by VALID while VALID, READY and context signals are compared directly.

Each model rejects five deliberately wrong event sources: pre-edge combinational, one edge late, permission-only, unfiltered write enable, and readiness-gated history. An additional real-adapter abstract-image test passed 2,060 cycles, 1,379 raw changes, 853 consecutive changed cycles and 23 resets; it rejects the same five mutations. The capacity-one real CSR producer cannot execute adjacent-edge writes, so the abstract-image test is explicitly a consumer contract stress test, not a CPU throughput claim.

Pinned firtool 1.135.0 emitted the same real paired fixtures for existing Icarus. Both 8-entry live and 16-entry registered variants passed 29 independent native edge checks covering held reset, deassertion before the first released edge, the initial VM change/epoch, OFF raw write publication, no-op/filter/lock suppression and reset/repeat. The supported `disallowLocalVariables` output style enabled Icarus compatibility; no RTL was hand-edited.

Five focused Scala tests passed, including no publication state/port at 0/8/16 entries without a VM consumer, all consumer combinations and explicit standalone fallback. Twelve complete board host contracts and four PMP CLI contracts passed. The separate matched-board acceptance below qualifies the production assembly; focused checks do not substitute for it.

## Reset-driver findings

The initial strict VM oracle exposed a GSIM reset-driver issue shared by both detector variants. GSIM applies reset before settling NEXT; the original driver let the next deasserted step consume NEXT recomputed while reset was held. The driver now keeps the public reset active through settle with resetAll(), retaining the original independent VM expectations. Native edge checks establish the hardware behavior independently. The later abstract random-reset oracle was corrected to compare the already reset image on a reset-applied step, while preserving the initial VM difference. Original failures, exact generated models and diagnostic host copies are retained.

A separate traffic driver incorrectly awaited physical-response acceptance while holding the upstream response sink not ready. The adapter intentionally has no return-data buffer. The corrected test holds response VALID/data through the shared handshake. No production behavior was changed to satisfy either driver.

Earlier registered-region tests had no adapter VM-history/epoch boundary, so their raw CSR/range/access evidence is not retroactively invalidated. The new focused/native tests add the previously uncovered boundary. Details and original evidence are in reset-driver-diagnosis.md and focused-completion-r1.json.

## Source and publication

Production narrow patch SHA256: 09e953dd362e4fa60ef9f3bf6cdb6d05a45bb20fa6c11320f1ab6b1f1d01fe22.

Current source checkpoint: d02b01436bfdf6f6a09e88d14a26bdc530886b40. The final matrix's production/real fixture/real host bytes are identical to 4f8cac1; the receipt explicitly bridges the later abstract-host correction and checked-board CLI flag whitelist. The newer published combined documentation is preserved exactly.

The published base is development 6b27c67153709f5d2ddd1bc46b6f2a824a8551df, tree d793961ee08bb2f7c9e77c0ea081ba89798253cb, equivalent to local 6cedacc. Its tested production identity is b37d8f1bffb1e053a1ed7dd0a3d81c4aec8ceb70. No remote push has been performed by this worker and main is untouched. A 422,864-byte thin source/evidence checkpoint is already in Library as libfile_75b090072cfc81919d201412fe8deb84, version 0; the final evidence package adds the complete focused, native and matched-board results.

## Matched-board qualification and explicit entry

The primary candidate command is `python3 fpga/next/board_pmp_publication.py --output build/fpga-next-pmp-publication` (source-only preflight). Add `--emit` for a separately authorized native export. This new versioned entry enables published PMP changes while `board_timing_cdc.py`, its v1 manifest, and generic defaults remain preserved as the OFF rollback. Native/physical output is not part of this source publication.

The saved complete constructor and the actual emitted CPU/cache/DDR parameters exactly match the new entry. The only source-control additions after executed d02b014 are host entry/manifest/tests and documentation; no Scala, hardware, fixture, or C++ model input changes. The exporter serializes the new Boolean earlier in its argument list; removing the unique flag restores the identical historical sequence, and full constructor equality confirms semantics. Fifteen board host tests pass; no second full model is needed.

One fresh PMP-ON production board model used the actual checked emitter, the unchanged 17 host files, guest bytes and service flags. All 35 official split translation units were compiled serially with ASan/UBSan and no object reuse. OFF uses the existing qualified 6b-equivalent saved model. Bare remains 251,815 cycles and 49.639616385 MiB/s; Sv39 remains 250,604 cycles and 49.8794911494 MiB/s. Every 105-field result, counts/ledger/adoption section and complete AXI/supply stream is identical. All original read/memory/trap negative controls were rejected. This is a structural resource reduction with zero observed benchmark or traffic change, not a bandwidth gain.

Board receipt SHA256: 162c974e254ff5fc1001c8715702350a3dc1e0825517cdbe51eb5666d5972055.
Focused receipt SHA256: 4f71e160392484bfce0782dc09968c4c34adb513a873daac33a0587ade878273.

The versioned `fpga/next/board-pmp-publication-profile-v1.json` pins the qualified source/model/profile identities and explicitly retains open physical gates. `docs/experiments/pmp-change-publication-evidence-v1.json` records the thin machine-readable result.
