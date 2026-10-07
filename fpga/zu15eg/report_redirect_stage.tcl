# Query the same real-ROM, clock-free checkpoints. No synth/place/route.
# BASELINE_DCP CANDIDATE_DCP OUT_DIRECTORY [timing candidate profile]
if {$argc ni {3 4}} {error "Expected BASELINE_DCP CANDIDATE_DCP OUT_DIRECTORY ?PROFILE?"}
lassign $argv baseline candidate out profile
if {$argc == 4 && $profile ni {staged-preparation staged-payload staged-return staged-fetch-address staged-fetch-control staged-recovery-control staged-execute-select staged-frontend-select staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}} {error "Unknown extra profile"}
set word_destination [expr {$profile in {staged-word-destination staged-request-capture}}]
set rank_legality [expr {$profile in {staged-rank-legality staged-word-destination staged-request-capture}}]
set decode_align [expr {$profile in {staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
set sensitive_paths [expr {$profile in {staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
set frontend_select [expr {$profile in {staged-frontend-select staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
set execute_select [expr {$profile in {staged-execute-select staged-frontend-select staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
set recovery_control [expr {$profile in {staged-recovery-control staged-execute-select staged-frontend-select staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
set preparation [expr {$profile in {staged-preparation staged-payload staged-return staged-fetch-address staged-fetch-control staged-recovery-control staged-execute-select staged-frontend-select staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
set payload [expr {$profile in {staged-payload staged-return staged-fetch-address staged-fetch-control staged-recovery-control staged-execute-select staged-frontend-select staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
set registered_return [expr {$profile in {staged-return staged-fetch-address staged-fetch-control staged-recovery-control staged-execute-select staged-frontend-select staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
set fetch_address [expr {$profile in {staged-fetch-address staged-fetch-control staged-recovery-control staged-execute-select staged-frontend-select staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
set fetch_control [expr {$profile in {staged-fetch-control staged-recovery-control staged-execute-select staged-frontend-select staged-sensitive-paths staged-decode-align staged-rank-legality staged-word-destination staged-request-capture}}]
file mkdir $out
set_param general.maxThreads 8
set core platform/core/core/core
set backend $core/backend
foreach kind {baseline candidate} {
    open_checkpoint [set $kind]
    if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]]} {error "Functional black box remains"}
    if {[llength [get_clocks -quiet]]} {error "Expected clock-free checkpoint"}
    set captures [get_cells -quiet -hier -filter {REF_NAME =~ EarlyRedirectCapture*}]
    set compares [get_cells -quiet -hier -filter {REF_NAME =~ BalancedBranchCompare*}]
    puts "REDIRECT_STAGE: $kind early_captures=[llength $captures] balanced_compares=[llength $compares]"
    if {$kind eq "candidate" && ([llength $captures] != 1 || [llength $compares] != 0)} {
        error "Candidate capture/native-comparison contract missing"
    }
    if {$kind eq "candidate" && $preparation} {
        set planners [get_cells -quiet -hier -filter {REF_NAME =~ MemoryPreparationSelector*}]
        puts "PREPARATION_STAGE: planners=[llength $planners]"
        if {[llength $planners] != 1} {error "Parallel preparation planner missing"}
    }
    if {$kind eq "candidate" && $payload} {
        set selectors [get_cells -quiet -hier -filter {REF_NAME =~ CircularIssueSelector*}]
        puts "PAYLOAD_STAGE: selectors=[llength $selectors]"
        if {[llength $selectors] != 1} {error "Circular one-hot issue selector missing"}
    }
    if {$kind eq "candidate" && $profile eq "staged-return"} {
        set operands [get_cells -quiet -hier -filter {REF_NAME =~ IssuePhysicalOperands*}]
        puts "RETURN_STAGE: physical_operand_selectors=[llength $operands]"
        if {[llength $operands] != 1} {error "Parallel physical operand selector missing"}
    }
    if {$kind eq "candidate" && $fetch_address} {
        set operands [get_cells -quiet -hier -filter {REF_NAME =~ IssuePhysicalOperands*}]
        set decoders [get_cells -quiet -hier -filter {REF_NAME =~ TwoBankAddressDecoder*}]
        puts "FETCH_ADDRESS_STAGE: physical_operand_selectors=[llength $operands] prefix_decoders=[llength $decoders]"
        if {[llength $operands] || [llength $decoders] != 2} {error "Compact PRF or exact prefix decoder contract missing"}
    }
    if {$kind eq "candidate" && $fetch_control} {
        set guards [get_cells -quiet -hier -filter {REF_NAME =~ DirectPredictionQualification*}]
        set replies [get_cells -quiet platform/romManager/produced_replies]
        puts "FETCH_CONTROL_STAGE: prediction_guards=[llength $guards] rom_reply_queues=[llength $replies]"
        if {[llength $guards] != 2 || [llength $replies] != 1} {error "Prediction/reply queue contract missing"}
    }
    foreach {mode period} {20ns 20 10ns 10 150mhz 6.666666667} {
        reset_timing
        create_clock -name redirect_query_clock -period $period [get_ports clock]
        report_timing_summary -delay_type min_max -file [file join $out ${kind}_summary_${mode}.rpt]
        if {$mode eq "20ns"} {
            report_timing -max_paths 80 -nworst 1 -file [file join $out ${kind}_endpoints_20ns.rpt]
            set faults [get_pins -quiet -hier -filter "NAME =~ $backend/branch*/io_misaligned"]
            set commits [get_pins -quiet -hier -filter "NAME =~ $backend/ledger/io_commit_*_valid"]
            if {![llength $faults] || ![llength $commits]} {error "Missing fault/retirement boundary"}
            set paths [get_timing_paths -quiet -through $faults -through $commits -max_paths 1]
            puts "REDIRECT_STAGE: $kind alignment_to_commit_paths=[llength $paths]"
            if {[llength $paths]} {error "Previous retirement alignment cut was lost"}
        }
        if {$mode eq "10ns"} {
            if {$profile eq "staged-request-capture"} {
                set native [get_cells -quiet -hier -filter {NAME =~ platform/physicalFetch_requests/* && REF_NAME =~ RAM*}]
                set write_enable [get_pins -quiet -of_objects $native -filter {REF_PIN_NAME == WE}]
                if {![llength $write_enable]} {error "Native instruction capture storage missing"}
                report_timing -to $write_enable -max_paths 5 -nworst 1 \
                    -file [file join $out ${kind}_instruction_capture_we_10ns.rpt]
                set request_state [get_pins -quiet -hier -filter {NAME =~ platform/physicalFetch_requests/*reg*/D}]
                if {![llength $request_state]} {error "Instruction request pointer state missing"}
                report_timing -to $request_state -max_paths 5 -nworst 1 \
                    -file [file join $out ${kind}_instruction_capture_state_10ns.rpt]
                if {$kind eq "candidate"} {
                    set ready [get_pins -quiet platform/physicalFetch_requests/io_downstream_request_ready]
                    set feedback [get_timing_paths -quiet -through $ready -to $write_enable -max_paths 1]
                    puts "REQUEST_CAPTURE_STAGE: write_enable_pins=[llength $write_enable] downstream_ready_to_storage_we=[llength $feedback]"
                    if {[llength $feedback]} {error "Downstream ready still controls instruction capture WE"}
                    set matches [get_cells -quiet -hier -filter {REF_NAME =~ ParallelHomeLineMatch*}]
                    set owned [get_pins -quiet -of_objects $matches -filter {REF_PIN_NAME == io_owned}]
                    if {![llength $matches] || ![llength $owned]} {error "Parallel directory comparisons missing"}
                    report_timing -through $owned -max_paths 5 -nworst 1 \
                        -file [file join $out candidate_parallel_home_ownership_10ns.rpt]
                    set negative [get_timing_paths -quiet -slack_lesser_than 0 -max_paths 1000 -nworst 1]
                    puts "REQUEST_CAPTURE_STAGE: negative_endpoint_count=[llength $negative]"
                    foreach path $negative {
                        puts "NEGATIVE_ENDPOINT: [get_property SLACK $path] [get_property STARTPOINT_PIN $path] -> [get_property ENDPOINT_PIN $path]"
                    }
                }
            }
            if {$kind eq "candidate" && $preparation} {
                set late [get_pins -quiet -of_objects $planners -filter {REF_PIN_NAME == io_issued}]
                set addresses [get_pins -quiet -hier -filter "NAME =~ $backend/stagedMemoryAddress_reg*/D"]
                if {[llength $late] != 1 || ![llength $addresses]} {error "Missing late-exclusion/address boundary"}
                report_timing -through $late -to $addresses -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_late_exclusion_to_address_10ns.rpt]
            }
            if {$kind eq "candidate" && $payload} {
                set invalidate [get_pins -quiet platform/frontend/io_invalidate]
                set addresses [get_pins -quiet -hier -filter {NAME =~ platform/frontend/checker_*/io_address*}]
                set valid [get_pins -quiet platform/frontend/io_instructions_0_valid]
                if {[llength $invalidate] != 1 || ![llength $addresses] || [llength $valid] != 1} {
                    error "Missing fetch payload/validity boundary"
                }
                set payload_paths [get_timing_paths -quiet -through $invalidate -through $addresses -max_paths 1]
                set validity_paths [get_timing_paths -quiet -through $invalidate -through $valid -max_paths 1]
                puts "PAYLOAD_STAGE: invalidate_to_pmp_address_paths=[llength $payload_paths] invalidate_to_instruction_valid_paths=[llength $validity_paths]"
                if {[llength $payload_paths] || ![llength $validity_paths]} {
                    error "Raw fetch payload isolation or late validity guard was lost"
                }
            }
            if {$kind eq "candidate" && $registered_return} {
                set response_in {}
                set response_out {}
                foreach field {bits_data* bits_error bits_pageFault valid} {
                    set inputs [get_pins -quiet -hier -filter "NAME =~ platform/core/responses/io_downstream_response_$field"]
                    set outputs [get_pins -quiet -hier -filter "NAME =~ platform/core/responses/io_upstream_response_$field"]
                    if {![llength $inputs] || ![llength $outputs]} {error "Missing registered response field $field"}
                    set response_in [concat $response_in $inputs]
                    set response_out [concat $response_out $outputs]
                }
                set paths [get_timing_paths -quiet -through $response_in -through $response_out -max_paths 1]
                puts "RETURN_STAGE: response_data_fault_valid_flowthrough_paths=[llength $paths] inputs=[llength $response_in] outputs=[llength $response_out]"
                if {[llength $paths]} {error "CPU response data/fault/valid still flows through without a register"}
                set storage_data [get_pins -quiet -hier -filter {NAME =~ platform/core/responses/responses/ram_ext/W0_data*}]
                set credit_state [get_pins -quiet -hier -filter {NAME =~ platform/core/responses/responses/*reg*/D}]
                if {![llength $storage_data] || ![llength $credit_state]} {error "Missing response storage/credit-state boundary"}
                report_timing -through $storage_data -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_response_storage_10ns.rpt]
                report_timing -to $credit_state -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_response_credit_10ns.rpt]
            }
            if {$kind eq "candidate" && $fetch_address} {
                set late_d [get_pins -quiet platform/fetchCache/fallback/io_tl_d_valid]
                set next_address [get_pins -quiet -hier -filter {NAME =~ platform/fetchCache/fallback/io_tl_a_bits_address*}]
                if {[llength $late_d] != 1 || ![llength $next_address]} {error "Missing fallback reply/address boundary"}
                report_timing -through $late_d -through $next_address -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_reply_to_fetch_address_10ns.rpt]
            }
            if {$fetch_control} {
                set d_ready [get_pins -quiet platform/romManager/io_tl_d_ready]
                set a_ready [get_pins -quiet platform/romManager/io_tl_a_ready]
                if {[llength $d_ready] != 1 || [llength $a_ready] != 1} {error "Missing ROM credit boundary"}
                set paths [get_timing_paths -quiet -through $d_ready -through $a_ready -max_paths 1]
                puts "FETCH_CONTROL_STAGE: $kind rom_external_d_ready_to_a_ready_paths=[llength $paths]"
                if {$kind eq "candidate" && [llength $paths]} {error "ROM reply queue failed to cut external ready feedback"}
                if {$kind eq "baseline" && !$recovery_control && ![llength $paths]} {error "Expected old ROM ready feedback missing"}
                report_timing -through $a_ready -max_paths 5 -nworst 1 \
                    -file [file join $out ${kind}_rom_request_credit_10ns.rpt]
                set arbiters [get_cells -quiet -hier -filter {REF_NAME =~ TwoMasterTileLinkArbiter*}]
                set raw_paths 0
                foreach arbiter $arbiters {
                    set late_valid [get_pins -quiet $arbiter/io_manager_d_valid]
                    set sources [get_pins -quiet -of_objects $arbiter -filter {REF_PIN_NAME =~ io_masters_*_d_bits_source*}]
                    if {[llength $late_valid] != 1 || ![llength $sources]} {error "Missing TL raw source lookup boundary"}
                    incr raw_paths [llength [get_timing_paths -quiet -through $late_valid -through $sources -max_paths 1]]
                }
                puts "FETCH_CONTROL_STAGE: $kind late_d_valid_to_reply_source_paths=$raw_paths arbiters=[llength $arbiters]"
                if {$kind eq "candidate" && $raw_paths} {error "TL reply source still waits for valid"}
            }
            foreach {family pattern} [list pending $backend/pending*_reg*/D \
                redirect $backend/branchRedirect*_reg*/D scoreboard $backend/ready*_reg*/D \
                ras_data $core/returnStack/entries*_reg*/D ras_enable $core/returnStack/entries*_reg*/CE \
                ras_control $core/returnStack/count*_reg*/D prf $backend/values*_reg*/D \
                rob $backend/ledger/*reg*/D issue_queue $backend/queue*_reg*/D frontend_pc $core/pc_reg*/D \
                fabric platform/*/owners/*reg*/CE preparation_address $backend/stagedMemoryAddress_reg*/D \
                fetch_mask platform/frontend/lockedMask_reg*/D \
                lsu_data $backend/lsu/slots_*/result_data_reg*/D] {
                set endpoints [get_pins -quiet -hier -filter "NAME =~ $pattern"]
                puts "REDIRECT_STAGE: $kind family=$family endpoints=[llength $endpoints]"
                if {![llength $endpoints]} {error "Missing requested family $family"}
                report_timing -to $endpoints -max_paths 5 -nworst 1 -file [file join $out ${kind}_${family}_10ns.rpt]
            }
            if {$fetch_address} {
                set state_enable [get_pins -quiet -hier -filter {NAME =~ platform/fetchAdapter/state_reg*/CE}]
                if {![llength $state_enable]} {error "Missing fetch adapter state enable"}
                report_timing -to $state_enable -max_paths 5 -nworst 1 \
                    -file [file join $out ${kind}_fetch_adapter_state_10ns.rpt]
            }
            if {$fetch_control} {
                set predictor_state [get_pins -quiet -hier -filter "NAME =~ $core/predictor/counters*_reg*/D"]
                if {![llength $predictor_state]} {error "Missing newly critical branch predictor state"}
                report_timing -to $predictor_state -max_paths 5 -nworst 1 \
                    -file [file join $out ${kind}_branch_predictor_10ns.rpt]
            }
            if {$kind eq "candidate" && $recovery_control} {
                set admissions [get_cells -quiet -hier -filter {REF_NAME =~ ParallelRecoveryAdmission*}]
                set qualifications [get_cells -quiet -hier -filter {REF_NAME =~ RedirectTokenQualification*}]
                if {[llength $admissions] != 1 || [llength $qualifications] != 1} {
                    error "Parallel recovery/token qualification boundaries missing"
                }
                set accepted [get_pins -quiet -of_objects $admissions -filter {REF_PIN_NAME == io_accepted}]
                set killed [get_pins -quiet -of_objects $admissions -filter {REF_PIN_NAME =~ io_killed*}]
                set matches [get_pins -quiet -of_objects $qualifications -filter {REF_PIN_NAME =~ io_matches*}]
                if {[llength $accepted] != 1 || ![llength $killed] || [llength $matches] != 2} {
                    error "Recovery authorization/kill/redirect endpoints missing"
                }
                puts "RECOVERY_CONTROL_STAGE: admissions=[llength $admissions] qualifications=[llength $qualifications] accepted=[llength $accepted] killed=[llength $killed] matches=[llength $matches]"
                report_timing -through $accepted -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_recovery_admission_10ns.rpt]
                report_timing -through $killed -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_recovery_kill_10ns.rpt]
                report_timing -through $matches -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_redirect_token_10ns.rpt]
            }
            if {$kind eq "candidate" && $sensitive_paths} {
                set sources [get_cells -quiet -hier -filter {REF_NAME =~ PredictionSourceQualification*}]
                set predicts [get_pins -quiet -of_objects $sources -filter {REF_PIN_NAME == io_predicts}]
                set requests [get_cells -quiet -hier -filter {REF_NAME =~ InstructionRequestBuffer*}]
                set downstream_ready [get_pins -quiet -of_objects $requests -filter {REF_PIN_NAME == io_downstream_request_ready}]
                set upstream_ready [get_pins -quiet -of_objects $requests -filter {REF_PIN_NAME == io_upstream_request_ready}]
                if {[llength $sources] != 2 || [llength $predicts] != 2 || [llength $requests] != 1 ||
                    [llength $downstream_ready] != 1 || [llength $upstream_ready] != 1} {
                    error "Sensitive path helper boundaries missing"
                }
                set feedback [get_timing_paths -quiet -through $downstream_ready -through $upstream_ready -max_paths 1]
                puts "SENSITIVE_PATHS_STAGE: sources=[llength $sources] request_buffers=[llength $requests] ready_feedback=[llength $feedback]"
                if {[llength $feedback]} {error "Instruction request enqueue borrows downstream ready"}
                report_timing -through $predicts -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_prediction_sources_10ns.rpt]
                report_timing -through $upstream_ready -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_instruction_request_credit_10ns.rpt]
            }
            if {$kind eq "candidate" && $decode_align} {
                set aligners [get_cells -quiet -hier -filter {REF_NAME =~ ParallelFetchAlignment*}]
                set legalities [get_cells -quiet -hier -filter {REF_NAME =~ ParallelIntegerLegality*}]
                set aligned [get_pins -quiet -of_objects $aligners -filter {DIRECTION == OUT && REF_PIN_NAME =~ io_instructions*_bits*}]
                set qualified [get_pins -quiet -of_objects $legalities -filter {REF_PIN_NAME == io_legal}]
                set rat [get_pins -quiet -hier -filter "NAME =~ $backend/ledger/rat*_reg*/D"]
                puts "DECODE_ALIGN_STAGE: aligners=[llength $aligners] legality_helpers=[llength $legalities] aligned_bits=[llength $aligned] rat_pins=[llength $rat]"
                if {[llength $aligners] != 1 || [llength $legalities] != 2 || ![llength $aligned] ||
                    [llength $qualified] != 2 || ![llength $rat]} {error "Decode alignment contract missing"}
                report_timing -through $aligned -to $rat -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_aligned_to_rat_10ns.rpt]
                report_timing -through $qualified -to $rat -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_legality_to_rat_10ns.rpt]
            }
            if {$kind eq "candidate" && $rank_legality} {
                set bit_helpers [get_cells -quiet -hier -filter {REF_NAME =~ ParallelBitLegality*}]
                set minmax_helpers [get_cells -quiet -hier -filter {REF_NAME =~ ParallelMinMaxResult*}]
                set ranks [get_cells -quiet -hier -filter {REF_NAME =~ RenameDestinationCandidates*}]
                set bit_legal [get_pins -quiet -of_objects $bit_helpers -filter {REF_PIN_NAME == io_legal}]
                set minmax_result [get_pins -quiet -of_objects $minmax_helpers -filter {REF_PIN_NAME =~ io_result*}]
                set rank_ids [get_pins -quiet -of_objects $ranks -filter {REF_PIN_NAME =~ io_destination*}]
                set ledger_data [get_pins -quiet -hier -filter "NAME =~ $backend/ledger/*_reg*/D"]
                set prf_data [get_pins -quiet -hier -filter "NAME =~ $backend/values*_reg*/D"]
                puts "RANK_LEGALITY_STAGE: bit_helpers=[llength $bit_helpers] minmax_helpers=[llength $minmax_helpers] ranks=[llength $ranks] bit_outputs=[llength $bit_legal] minmax_outputs=[llength $minmax_result] rank_outputs=[llength $rank_ids]"
                if {[llength $bit_helpers] != 2 || [llength $minmax_helpers] != 2 ||
                    [llength $ranks] != 1 || [llength $bit_legal] != 2 || ![llength $minmax_result] ||
                    ![llength $rank_ids] || ![llength $ledger_data] || ![llength $prf_data]} {
                    error "Rank/legality/early-word contract missing"
                }
                report_timing -through $bit_legal -to $ledger_data -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_bit_legality_to_ledger_10ns.rpt]
                report_timing -through $rank_ids -to $ledger_data -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_rename_ranks_10ns.rpt]
                report_timing -through $minmax_result -to $prf_data -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_minmax_result_10ns.rpt]
            }
            if {$kind eq "candidate" && $word_destination} {
                set raw_rd [get_pins -quiet -hier -filter "NAME =~ $backend/ledger/io_rawDestinations*"]
                set bit_datapaths [get_cells -quiet -hier -filter "NAME =~ $backend/alu*/bitManip && REF_NAME =~ IntegerBitManip*"]
                set address_results [get_pins -quiet -of_objects $bit_datapaths -filter {REF_PIN_NAME =~ io_addressResult*}]
                puts "WORD_DESTINATION_STAGE: raw_rd_pins=[llength $raw_rd] address_result_pins=[llength $address_results]"
                if {[llength $raw_rd] != 10 || [llength $address_results] != 128} {
                    error "Early architectural destination / Zba result contract missing"
                }
                report_timing -through $raw_rd -to $ledger_data -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_raw_rd_to_ledger_10ns.rpt]
                report_timing -through $address_results -to $prf_data -max_paths 5 -nworst 1 \
                    -file [file join $out candidate_address_result_to_prf_10ns.rpt]
            }
            if {$kind eq "candidate" && $frontend_select} {
                set pc_data [get_pins -quiet -hier -filter "NAME =~ $core/pc_reg*/D"]
                if {![llength $pc_data]} {error "Missing frontend PC boundary"}
                foreach {family ref_pattern expected} {
                    frontend_tag ParallelFetchTagLookup* 2
                    frontend_control FrontendControlDecode* 2
                    auipc_qualification AuipcPredictionQualification* 1
                } {
                    # Fixed halfword candidates retain the third lookup in the
                    # decode-align DCP; preceding board candidates retain two.
                    # Count synthesized boundaries, not the FIR instance count.
                    if {$family eq "frontend_tag" && $decode_align} {set expected 3}
                    set modules [get_cells -quiet -hier -filter "REF_NAME =~ $ref_pattern"]
                    set outputs [get_pins -quiet -of_objects $modules -filter {DIRECTION == OUT}]
                    puts "FRONTEND_SELECT_STAGE: family=$family modules=[llength $modules] output_pins=[llength $outputs]"
                    if {[llength $modules] != $expected || ![llength $outputs]} {
                        error "Missing frontend helper boundary $family"
                    }
                    report_timing -through $outputs -to $pc_data -max_paths 5 -nworst 1 \
                        -file [file join $out [format "candidate_%s_10ns.rpt" $family]]
                }
            }
            if {$execute_select} {
                set selectors [get_cells -quiet -hier -filter {REF_NAME =~ CircularIssueSelector*}]
                set first [get_pins -quiet -of_objects $selectors -filter {REF_PIN_NAME =~ io_first* && REF_PIN_NAME !~ io_firstIndex* && REF_PIN_NAME != io_firstValid}]
                set second [get_pins -quiet -of_objects $selectors -filter {REF_PIN_NAME =~ io_second* && REF_PIN_NAME !~ io_secondIndex* && REF_PIN_NAME != io_secondValid}]
                if {![llength $first] || ![llength $second]} {error "Missing issue rank boundary"}
                set serial [get_timing_paths -quiet -through $first -through $second -max_paths 1]
                puts "EXECUTE_SELECT_STAGE: $kind first_pins=[llength $first] second_pins=[llength $second] first_to_second_paths=[llength $serial]"
                # Record actual synthesized sharing; do not force a zero result
                # by suppressing paths or by assuming source rank independence.
                report_timing -through $second -max_paths 5 -nworst 1 \
                    -file [file join $out ${kind}_second_issue_rank_10ns.rpt]
                set alu_results [get_pins -quiet -hier -filter "NAME =~ $backend/alu*/io_result*"]
                if {![llength $alu_results]} {error "Missing ALU result boundary"}
                report_timing -through $alu_results -max_paths 5 -nworst 1 \
                    -file [file join $out ${kind}_alu_result_10ns.rpt]
                if {$kind eq "candidate"} {
                    set payloads [get_cells -quiet -hier -filter {REF_NAME =~ ParallelCompletionPayload*}]
                    set selected [get_pins -quiet -of_objects $payloads -filter {REF_PIN_NAME =~ io_selected_data*}]
                    if {[llength $payloads] != 1 || ![llength $selected]} {error "Missing complete writeback payload selector"}
                    puts "EXECUTE_SELECT_STAGE: completion_payloads=[llength $payloads] selected_data_pins=[llength $selected]"
                    report_timing -through $selected -max_paths 5 -nworst 1 \
                        -file [file join $out candidate_completion_payload_10ns.rpt]
                }
            }
        }
    }
    close_design
}
