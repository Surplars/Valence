# Captured implementation entrypoint source, 2026-10-16

These exact source files were captured at14:43:32UTC from the matched50cb+7dc9 local diagnostic. They are source references with explicit local paths and external sealed-package/IP/report dependencies, not a standalone portable launcher or permission to execute implementation.

The successful post-route command was one pass of `phys_opt_design -placement_opt -routing_opt -critical_cell_opt -hold_fix -path_groups clk_out1_clk_wiz_ddr`, at8threads,14:18:14–14:33:50UTC. Earlier memory-gate entries stopped before optimization. No additional route was needed. Final DCP SHA25623a4edd50f0c4852f89ffb549f5ba9d2c51dc2019f546479b1dbe538ce102743.

At capture, final-two-speed-sta-r1.tcl was performing read-only100/10Mbps checks; frozen-final-rom-and-bit-r1.tcl was queued for the separately authorized local ROM verification and bit generation. Their presence does not claim either step completed. No hardware programming entry is authorized by this source snapshot.

The source-only package deliberately excludes reports, logs, generated RTL, IP files, checkpoint/bitstream bytes and execution receipts. Retain the selected-ROM, clock, source identity and dependency checks. The original sealed export is an external input; do not execute with substituted hardware or reinterpret captured absolute paths as portable defaults.

## Captured per-file status

- `orchestration/postroute-physopt-session-r1.tcl`: initial_entry_loaded_baseline_then_memory_gate_failed_before_optimization; successful_actual_command_is_separate8thread_resume
- `orchestration/resume-postroute-physopt-8threads-r1.tcl`: executed_or_loaded_this_round
- `orchestration/final-two-speed-sta-r1.tcl`: executed_or_loaded_this_round
- `orchestration/prepare_rom_decoder.py`: executed_or_loaded_this_round
- `orchestration/network-generated-scope-r10.tcl`: executed_or_loaded_this_round
- `orchestration/network-clock-rename-r11.tcl`: executed_or_loaded_this_round
- `orchestration/network-generated-format-r12.tcl`: executed_or_loaded_this_round
- `orchestration/mac-clock-profile-r13.tcl`: executed_or_loaded_this_round
- `orchestration/mac-clock-mode-entry-r13.tcl`: executed_or_loaded_this_round
- `orchestration/network-postopt-feedback-r18.tcl`: executed_or_loaded_this_round
- `orchestration/install_control_lemma.tcl`: executed_or_loaded_this_round
- `orchestration/placed-release-buffer-only-r28.tcl`: executed_or_loaded_this_round
- `orchestration/install_media_csr_compat.tcl`: executed_or_loaded_this_round
- `orchestration/install_live_mailbox.tcl`: executed_or_loaded_this_round
- `orchestration/independent-placed-scenario-r28.tcl`: historical_retained_session_entry;100Mbps_initial_waiver_query_failed_then_continued;10Mbpscompleted;superseded_for_finalby_final-two-speed-sta-r1
- `orchestration/route-original-1000-r1.tcl`: executed_or_loaded_this_round
- `orchestration/diagnostic-place-r7b.tcl`: historical_loaded_definitions_and_partial_initial_flow; laterreviewed_continuations_r3_clock_fixes_supersede_initial_assumptions; do_not_run_wholesale
- `orchestration/frozen-final-rom-and-bit-r1.tcl`: queued_not_yet_executed_at_snapshot
- `orchestration/verify_final_bit_timing.py`: queued_not_yet_executed_at_snapshot
- `orchestration/prepare_routed_scenarios.py`: executed_final_scenario_preparation
- `orchestration/verify_routed_scenario_semantics.py`: executed_final_scenario_preparation
- `external-rom-polarity-minimal-r3/r3_rom_graph_leaf_r3.tcl`: previously_executed_reviewed_source_reused_by_final_flow
- `run-r28-scenario-100/report-procedures.tcl`: previously_executed_reviewed_source_reused_by_final_flow
- `run-postroute-physopt-r1/commands/005-final-two-speed-rom-and-authorized-bit.tcl`: active_coordinator_first_source_executing_second_source_pending

The generated PASS-stamped local-rom-contract.tcl is intentionally excluded; regenerate it with the matching verifier after actual asset checks.

## Supporting source scope

# Final runtime support source allowlist

These exact source bytes supplement the final 2026-10-16 entrypoint snapshot. No Tcl, Python verifier, PowerShell or vendor command was executed while staging. No generated output, evidence receipt, report, binary or checkpoint is included.

- `external-rom-polarity-minimal-r3/verify_local_rom.py` is the reviewed matching r3 contract producer. Run it with the exact selected package and actual vendor assets to regenerate the excluded `rom-preflight-official-r3/local-rom-contract.tcl`. The final r3 gate and all-word decoder remain mandatory. Its publication path is selected to accompany the final r3 gate; its bytes come from the reviewed deployment source.
- The memory scripts retain the actual placement/route checks. Generated thread-choice Tcl remains a runtime output.
- The r7b adapter, retained recovery/session source and command 001 preserve the actual Python `-I -B` and HDL `TOP`/`PART` corrections. They are historical source references, not standalone current launchers. The session retains normal live-session identity handling; HDL identity is checked independently.

The historical `diagnostic-place-r7b.tcl` references the superseded r2 gate and generated contract; command 001 references `diagnostic-place-r7.tcl`. Those historical dependencies are deliberately not republished here. Final ROM validation instead sources the reviewed r3 gate. Do not run the historical entries wholesale or substitute a generated historical PASS contract for fresh asset validation.

The captured original synthesis launcher remains `-B`-only. Neither it nor the separate unexecuted `-I` correction proposal is included. The final bit entry was queued, not completed, at the final-source snapshot. Publishing its source makes no bit-generation claim.

`orchestration/postroute-physopt-r1.tcl`, which initially loaded the baseline and stopped at its memory gate, is still absent from the available captures. The successful resume assumes that retained design. This is an explicit source-reproduction dependency, not a new gate on the already-running local flow. Immutable package sources, selected local vendor assets, checkpoints and runtime reports are external prerequisites.

Hashes and original source paths are in the adjacent staging manifest outside this directory.

## Supplement received

The original baseline-loading orchestration/postroute-physopt-r1.tcl is now included byte-exact from the final source supplement; this resolves its previously noted absence. Its initial memory gate stopped before optimization. The successful8-thread pass remains the separate resume script. The historical memory helpers record observed past guard behavior; they are not current memory policy or automatic authorization for another implementation run.
