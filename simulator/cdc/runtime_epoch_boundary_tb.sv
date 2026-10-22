`timescale 1ns/1ps
// Independent native COMPONENT oracle: test-owned CPU/fabric endpoint models.
// This is not a real core/cache/Home/DDR test, nor a CDC physical signoff.
// No DUT hierarchy, internal state poke, reset shortcut, or combinational busy
// flag is used as the owner/retirement ledger.
module runtime_epoch_boundary_tb;
    reg aonClock=0, cpuClock=0, fabricClock=0, commonColdReset=0, pause_cpu=0;
    integer cpu_half=3, fabric_half=7, aon_half=5, phase_ps=1300;
    integer drain_cycles=64, cleanup_cycles=128, selected_case=0, negative=0;
    initial begin
        if($value$plusargs("cpu_half=%d",cpu_half))begin end
        forever begin #(cpu_half); if(!pause_cpu) cpuClock=~cpuClock; end
    end
    initial begin
        if($value$plusargs("fabric_half=%d",fabric_half))begin end
        if($value$plusargs("phase_ps=%d",phase_ps))begin end
        #(phase_ps/1000.0); forever #(fabric_half) fabricClock=~fabricClock;
    end
    initial begin
        if($value$plusargs("aon_half=%d",aon_half))begin end
        #0.371; forever #(aon_half) aonClock=~aonClock;
    end
    reg [1:0] req_valid=0, resume_valid=0, cancel_valid=0, result_ready=0;
    reg [31:0] req_bits[0:1], resume_bits[0:1], cancel_bits[0:1];
    reg [7:0] resume_epoch[0:1], cancel_epoch[0:1];
    wire [1:0] req_ready, resume_ready, cancel_ready, held_valid, result_valid;
    wire [31:0] held_token[0:1], result_token[0:1];
    wire [7:0] held_epoch[0:1], result_epoch[0:1];
    wire [1:0] result_canceled, result_timedOut;
    wire busy, activeLane, timeoutSelected, cleanupFault, epochExhausted;
    wire [7:0] activeEpoch;
    wire [31:0] activeToken;
    wire proofObserved, drainDeadline;
    reg cpuHeld_valid=0, fabricHeld_valid=0;
    reg [7:0] cpuHeld_bits=0, fabricHeld_bits=0;
    reg cpuLinkReady=0, cpuTransportEmpty=0, fabricEmptyInCpu=0;
    reg fabricLinkReady=0, fabricTransportEmpty=0, cpuEmptyInFabric=0, fabricAllIdle=0;
    wire prepare_valid, prepare_ready, prepare_invI, prepare_invT;
    wire [7:0] prepare_epoch;
    wire runtimeResume_valid, runtimeResume_ready, runtimeCancel_valid, runtimeCancel_ready;
    wire [7:0] runtimeResume_bits, runtimeCancel_bits;
    wire complete_valid, complete_ready, complete_canceled;
    wire [7:0] complete_epoch;
    CommonRuntimeEpochBoundary dut(
        .aonClock(aonClock), .cpuClock(cpuClock), .fabricClock(fabricClock), .commonColdReset(commonColdReset),
        .io_requests_0_valid(req_valid[0]), .io_requests_0_ready(req_ready[0]), .io_requests_0_bits(req_bits[0]),
        .io_requests_1_valid(req_valid[1]), .io_requests_1_ready(req_ready[1]), .io_requests_1_bits(req_bits[1]),
        .io_resume_0_valid(resume_valid[0]), .io_resume_0_ready(resume_ready[0]), .io_resume_0_bits_token(resume_bits[0]), .io_resume_0_bits_epoch(resume_epoch[0]),
        .io_resume_1_valid(resume_valid[1]), .io_resume_1_ready(resume_ready[1]), .io_resume_1_bits_token(resume_bits[1]), .io_resume_1_bits_epoch(resume_epoch[1]),
        .io_cancel_0_valid(cancel_valid[0]), .io_cancel_0_ready(cancel_ready[0]), .io_cancel_0_bits_token(cancel_bits[0]), .io_cancel_0_bits_epoch(cancel_epoch[0]),
        .io_cancel_1_valid(cancel_valid[1]), .io_cancel_1_ready(cancel_ready[1]), .io_cancel_1_bits_token(cancel_bits[1]), .io_cancel_1_bits_epoch(cancel_epoch[1]),
        .io_held_0_valid(held_valid[0]), .io_held_0_bits_token(held_token[0]), .io_held_0_bits_epoch(held_epoch[0]),
        .io_held_1_valid(held_valid[1]), .io_held_1_bits_token(held_token[1]), .io_held_1_bits_epoch(held_epoch[1]),
        .io_result_0_valid(result_valid[0]), .io_result_0_ready(result_ready[0]),
        .io_result_0_bits_token(result_token[0]), .io_result_0_bits_epoch(result_epoch[0]),
        .io_result_0_bits_canceled(result_canceled[0]), .io_result_0_bits_timedOut(result_timedOut[0]),
        .io_result_1_valid(result_valid[1]), .io_result_1_ready(result_ready[1]),
        .io_result_1_bits_token(result_token[1]), .io_result_1_bits_epoch(result_epoch[1]),
        .io_result_1_bits_canceled(result_canceled[1]), .io_result_1_bits_timedOut(result_timedOut[1]),
        .io_busy(busy), .io_activeLane(activeLane), .io_activeEpoch(activeEpoch), .io_activeToken(activeToken),
        .io_timeoutSelected(timeoutSelected), .io_cleanupFault(cleanupFault), .io_epochExhausted(epochExhausted),
        .io_proofObserved(proofObserved), .io_drainDeadline(drainDeadline),
        .io_cpuHeld_valid(cpuHeld_valid), .io_cpuHeld_bits(cpuHeld_bits),
        .io_fabricHeld_valid(fabricHeld_valid), .io_fabricHeld_bits(fabricHeld_bits),
        .io_cpuLinkReady(cpuLinkReady), .io_cpuTransportEmpty(cpuTransportEmpty), .io_fabricEmptyInCpu(fabricEmptyInCpu),
        .io_fabricLinkReady(fabricLinkReady), .io_fabricTransportEmpty(fabricTransportEmpty),
        .io_cpuEmptyInFabric(cpuEmptyInFabric), .io_fabricAllObligationsIdle(fabricAllIdle),
        .io_externalMaintenance_valid(prepare_valid), .io_externalMaintenance_ready(prepare_ready),
        .io_externalMaintenance_bits_epoch(prepare_epoch),
        .io_externalMaintenance_bits_invalidateInstructions(prepare_invI),
        .io_externalMaintenance_bits_invalidateTranslations(prepare_invT),
        .io_runtimeResume_valid(runtimeResume_valid), .io_runtimeResume_ready(runtimeResume_ready),
        .io_runtimeResume_bits(runtimeResume_bits),
        .io_runtimeCancel_valid(runtimeCancel_valid), .io_runtimeCancel_ready(runtimeCancel_ready),
        .io_runtimeCancel_bits(runtimeCancel_bits),
        .io_runtimeComplete_valid(complete_valid), .io_runtimeComplete_ready(complete_ready),
        .io_runtimeComplete_bits_epoch(complete_epoch), .io_runtimeComplete_bits_canceled(complete_canceled));

    // Fabric endpoint model retains prepare and decision until actual terminal
    // fire. Completing a dirty epoch requires all four synthetic writeback beats
    // AND a CPU-domain resume acknowledgement. None is inferred from DUT busy.
    reg allow_prepare=1, allow_dirty=1, allow_ack=1, allow_proof=1, allow_complete=1;
    reg allow_cpu_progress=1, allow_fabric_proof=1, allow_decision=1;
    integer dirty_config=0, model_dirty_expected=0;
    reg endpoint_owned=0, endpoint_decided=0, endpoint_canceled=0;
    reg [7:0] endpoint_epoch=0, cpu_model_epoch=0;
    integer dirty_issued=0, dirty_retired=0, cpu_work_left=0, resume_delay=0;
    integer cpu_seen_serial=0, prepare_serial=0, cpu_resumed_serial=0;
    integer dirty_base=0, model_ack_serial=0;
    assign prepare_ready=allow_prepare&&!endpoint_owned&&!commonColdReset;
    assign runtimeResume_ready=allow_decision&&endpoint_owned&&!endpoint_decided&&fabricHeld_valid;
    assign runtimeCancel_ready=allow_decision&&endpoint_owned&&!endpoint_decided;
    assign complete_valid=endpoint_owned&&endpoint_decided&&allow_complete&&
        cpu_resumed_serial==prepare_serial&&model_ack_serial==prepare_serial;
    assign complete_epoch=endpoint_epoch;
    assign complete_canceled=endpoint_canceled;

    integer aon_edges=0, cpu_edges=0, fabric_edges=0;
    integer requests=0, prepares=0, decisions=0, terminals=0, receipts=0, next_epoch=1;
    integer ledger_lane=0, ledger_epoch=0, accepted_edge=0;
    reg [31:0] ledger_token=0;
    reg ledger_owned=0, ledger_result_seen=0, ledger_timeout=0, ledger_decided=0;
    // Corrupt only the monitor observation; the normal receipt checker is unchanged.
    wire observed_result_seen = negative==2 ? 1'b0 : ledger_result_seen;
    reg ledger_canceled=0, saw_timeout=0, saw_held=0;
    integer timeout_edge=-1, proof_edge=-1, exact_edge_witnesses=0;
    realtime result_fire_time=0, complete_fire_time=0;
    integer held_checks=0, stalled_result_checks=0, fault_checks=0, blocked_prepare_checks=0;
    integer reject_checks=0, reset_count=0, canceled_results=0, normal_results=0;
    reg result_was_stalled[0:1];
    reg [41:0] result_hold[0:1];
    reg [7:0] complete_hold;
    reg complete_was_stalled=0, complete_canceled_hold=0;
    integer a;

    always @(posedge cpuClock) begin
        cpu_edges=cpu_edges+1;
        if(commonColdReset) begin
            cpuHeld_valid<=0; cpuHeld_bits<=0; cpuTransportEmpty<=0; fabricEmptyInCpu<=0;
            cpu_model_epoch<=0; cpu_seen_serial<=0; cpu_resumed_serial<=0;
            cpu_work_left<=0; dirty_issued<=0; resume_delay<=0;
        end else if(allow_cpu_progress) begin
            if(endpoint_owned&&cpu_seen_serial!=prepare_serial) begin
                cpu_seen_serial<=prepare_serial; cpu_model_epoch<=endpoint_epoch;
                cpu_work_left<=model_dirty_expected; cpuHeld_valid<=0;
                cpuTransportEmpty<=0; fabricEmptyInCpu<=0; resume_delay<=0;
            end else if(endpoint_owned&&cpu_seen_serial==prepare_serial) begin
                if(cpu_work_left>0&&allow_dirty) begin
                    dirty_issued<=dirty_issued+1; cpu_work_left<=cpu_work_left-1;
                end
                if(cpu_work_left==0&&model_ack_serial==prepare_serial) begin
                    cpuTransportEmpty<=1; fabricEmptyInCpu<=1;
                    cpuHeld_valid<=allow_proof&&!endpoint_decided;
                    cpuHeld_bits<=cpu_model_epoch;
                    if(endpoint_decided) begin
                        if(resume_delay==2) cpu_resumed_serial<=prepare_serial;
                        else resume_delay<=resume_delay+1;
                    end
                end
            end else if(!endpoint_owned) begin
                cpuHeld_valid<=0; cpuTransportEmpty<=1; fabricEmptyInCpu<=1;
            end
        end
    end
    always @(posedge fabricClock) begin
        fabric_edges=fabric_edges+1;
        if(commonColdReset) begin
            endpoint_owned<=0; endpoint_decided<=0; endpoint_canceled<=0; endpoint_epoch<=0;
            prepare_serial<=0; dirty_retired<=0; model_ack_serial<=0; dirty_base<=0;
            fabricHeld_valid<=0; fabricHeld_bits<=0; fabricTransportEmpty<=0;
            cpuEmptyInFabric<=0; fabricAllIdle<=0; complete_was_stalled<=0;
            prepares=0; decisions=0; receipts=0; complete_fire_time=0;
        end else begin
            if(prepare_valid&&prepare_ready) begin
                if(!ledger_owned||prepare_epoch!==ledger_epoch[7:0])
                    $fatal(1,"EPOCH_ORACLE_PREPARE epoch=%0d expected=%0d",prepare_epoch,ledger_epoch);
                endpoint_owned<=1; endpoint_decided<=0; endpoint_canceled<=0;
                endpoint_epoch<=prepare_epoch; prepare_serial<=prepare_serial+1;
                model_dirty_expected<=dirty_config; dirty_base<=dirty_issued;
                prepares=prepares+1;
                $display("EPOCH_PREPARE epoch=%0d fabric_edge=%0d",prepare_epoch,fabric_edges);
            end
            if(endpoint_owned) begin
                if(allow_ack&&dirty_retired<dirty_issued) dirty_retired<=dirty_retired+1;
                if(allow_ack&&dirty_retired==dirty_base+model_dirty_expected&&cpu_seen_serial==prepare_serial)
                    model_ack_serial<=prepare_serial;
                fabricAllIdle<=model_ack_serial==prepare_serial;
                fabricTransportEmpty<=model_ack_serial==prepare_serial;
                cpuEmptyInFabric<=cpuTransportEmpty;
                fabricHeld_valid<=cpu_seen_serial==prepare_serial&&cpu_work_left==0&&
                    model_ack_serial==prepare_serial&&allow_fabric_proof&&!endpoint_decided;
                fabricHeld_bits<=endpoint_epoch;
            end else begin
                fabricHeld_valid<=0; fabricTransportEmpty<=1; cpuEmptyInFabric<=1; fabricAllIdle<=1;
            end
            if((runtimeResume_valid&&runtimeResume_ready)||(runtimeCancel_valid&&runtimeCancel_ready)) begin
                if(!endpoint_owned||endpoint_decided||(runtimeResume_valid&&runtimeCancel_valid))
                    $fatal(1,"EPOCH_ORACLE_DUPLICATE_DECISION");
                if((runtimeResume_valid&&runtimeResume_bits!==endpoint_epoch)||
                   (runtimeCancel_valid&&runtimeCancel_bits!==endpoint_epoch))
                    $fatal(1,"EPOCH_ORACLE_DECISION_TAG");
                endpoint_decided<=1; endpoint_canceled<=runtimeCancel_valid;
                decisions=decisions+1;
                $display("EPOCH_DECISION epoch=%0d canceled=%0d fabric_edge=%0d",endpoint_epoch,runtimeCancel_valid,fabric_edges);
            end
            if(complete_was_stalled&&(!complete_valid||complete_epoch!==complete_hold||complete_canceled!==complete_canceled_hold))
                $fatal(1,"EPOCH_ENDPOINT_TERMINAL_HOLD");
            complete_was_stalled<=complete_valid&&!complete_ready;
            complete_hold<=complete_epoch; complete_canceled_hold<=complete_canceled;
            if(complete_valid&&complete_ready) begin
                if(!observed_result_seen||$realtime<=result_fire_time)
                    $fatal(1,"EPOCH_ORACLE_RECEIPT fabric terminal consumed before end consumer receipt");
                if(!endpoint_decided||cpu_resumed_serial!=prepare_serial||dirty_issued!=dirty_retired)
                    $fatal(1,"EPOCH_ORACLE_FAKE_TERMINAL");
                endpoint_owned<=0; endpoint_decided<=0; receipts=receipts+1;
                complete_fire_time=$realtime;
                $display("EPOCH_FABRIC_RECEIPT epoch=%0d fabric_edge=%0d ns=%0.3f",endpoint_epoch,fabric_edges,$realtime);
            end
        end
    end
    always @(posedge aonClock) begin
        aon_edges=aon_edges+1;
        if(commonColdReset) begin
            requests=0; terminals=0; next_epoch=1; ledger_owned=0; ledger_result_seen=0;
            ledger_timeout=0; ledger_decided=0; ledger_canceled=0; saw_timeout=0; saw_held=0;
            accepted_edge=0; proof_edge=-1; timeout_edge=-1;
            result_was_stalled[0]=0; result_was_stalled[1]=0;
        end else begin
            if((req_valid&req_ready)==2'b11) $fatal(1,"EPOCH_ORACLE_TWO_OWNERS");
            for(a=0;a<2;a=a+1) begin
                if(req_valid[a]&&req_ready[a]) begin
                    if(ledger_owned&&(!ledger_result_seen||receipts!=requests||$realtime<=complete_fire_time))
                        $fatal(1,"EPOCH_ORACLE_RETIREMENT new request before fabric retirement receipt");
                    if(next_epoch>255) $fatal(1,"EPOCH_ORACLE_EPOCH_WRAP");
                    ledger_lane=a; ledger_epoch=next_epoch; next_epoch=next_epoch+1;
                    ledger_token=req_bits[a]; ledger_owned=1; ledger_result_seen=0;
                    ledger_timeout=0; ledger_decided=0; ledger_canceled=0; saw_timeout=0; saw_held=0;
                    accepted_edge=aon_edges; requests=requests+1; proof_edge=-1; timeout_edge=-1;
                    $display("EPOCH_ACCEPT lane=%0d token=%08x epoch=%0d aon_edge=%0d",a,req_bits[a],ledger_epoch,aon_edges);
                end
                if((resume_valid[a]&&resume_ready[a])||(cancel_valid[a]&&cancel_ready[a])) begin
                    if(!ledger_owned||a!=ledger_lane||ledger_decided||ledger_timeout)
                        $fatal(1,"EPOCH_ORACLE_BAD_DECISION_ACCEPT");
                    if((resume_valid[a]&&resume_bits[a]!==ledger_token)||
                       (cancel_valid[a]&&cancel_bits[a]!==ledger_token)||
                       (resume_valid[a]&&resume_epoch[a]!==ledger_epoch[7:0])||
                       (cancel_valid[a]&&cancel_epoch[a]!==ledger_epoch[7:0]))
                        $fatal(1,"EPOCH_ORACLE_BAD_TOKEN_ACCEPT");
                    ledger_decided=1; ledger_canceled=cancel_valid[a]&&cancel_ready[a];
                end
                if(held_valid[a]) begin
                    if(!ledger_owned||a!=ledger_lane||held_token[a]!==ledger_token||held_epoch[a]!==ledger_epoch[7:0]||ledger_timeout)
                        $fatal(1,"EPOCH_ORACLE_FALSE_HELD");
                    if(dirty_issued!=dirty_retired||cpu_work_left!=0)
                        $fatal(1,"EPOCH_ORACLE_UNDRAINED_HELD");
                    held_checks=held_checks+1; saw_held=1;
                end
                if(result_was_stalled[a]&&(!result_valid[a]||
                    {result_token[a],result_epoch[a],result_canceled[a],result_timedOut[a]}!==result_hold[a]))
                    $fatal(1,"EPOCH_ORACLE_RESULT_HOLD");
                result_was_stalled[a]=result_valid[a]&&!result_ready[a];
                result_hold[a]={result_token[a],result_epoch[a],result_canceled[a],result_timedOut[a]};
                if(result_valid[a]) begin
                    if(!ledger_owned||a!=ledger_lane||result_token[a] !== (ledger_token ^ (negative==1?32'd1:32'd0))||
                       result_epoch[a]!==ledger_epoch[7:0]) $fatal(1,"EPOCH_ORACLE_TOKEN terminal ownership mismatch");
                    if(result_timedOut[a]!==ledger_timeout||result_canceled[a]!==ledger_canceled)
                        $fatal(1,"EPOCH_ORACLE_RESULT_KIND timedOut=%0d expected=%0d canceled=%0d expected=%0d",
                            result_timedOut[a],ledger_timeout,result_canceled[a],ledger_canceled);
                    if(!endpoint_owned||!endpoint_decided||cpu_resumed_serial!=prepare_serial)
                        $fatal(1,"EPOCH_ORACLE_EARLY_RESULT");
                    if(!result_ready[a]) begin
                        stalled_result_checks=stalled_result_checks+1;
                        if(complete_ready||receipts==requests) $fatal(1,"EPOCH_ORACLE_EARLY_COMPLETE_READY");
                    end
                    if(result_ready[a]) begin
                        if(ledger_result_seen) $fatal(1,"EPOCH_ORACLE_DUPLICATE_RESULT");
                        ledger_result_seen=1; terminals=terminals+1; result_fire_time=$realtime;
                        if(result_canceled[a])canceled_results=canceled_results+1;else normal_results=normal_results+1;
                        $display("EPOCH_RESULT epoch=%0d canceled=%0d timedOut=%0d aon_edge=%0d ns=%0.3f",
                            ledger_epoch,result_canceled[a],result_timedOut[a],aon_edges,$realtime);
                    end
                end
            end
            if(drainDeadline&&ledger_owned&&aon_edges-accepted_edge!=drain_cycles)
                $fatal(1,"EPOCH_ORACLE_DEADLINE age=%0d expected=%0d",aon_edges-accepted_edge,drain_cycles);
            if(proofObserved&&drainDeadline)begin
                proof_edge=aon_edges;
                $display("EPOCH_EXACT_PROOF_DEADLINE epoch=%0d aon_edge=%0d age=%0d",ledger_epoch,aon_edges,aon_edges-accepted_edge);
            end
            if(proofObserved&&ledger_owned&&proof_edge<0)begin
                proof_edge=aon_edges;
                $display("EPOCH_PROOF_OBSERVED epoch=%0d aon_edge=%0d age=%0d",ledger_epoch,aon_edges,aon_edges-accepted_edge);
            end
            // Sample registered timeout after this AON edge. The deadline oracle
            // is derived only from the public request.fire and fixed test config.
            #0.001;
            if(timeoutSelected&&!saw_timeout)begin
                if(!ledger_owned||saw_held||ledger_decided) $fatal(1,"EPOCH_ORACLE_SPURIOUS_TIMEOUT");
                if(aon_edges-accepted_edge!=drain_cycles)
                    $fatal(1,"EPOCH_ORACLE_TIMEOUT_EDGE age=%0d expected=%0d",aon_edges-accepted_edge,drain_cycles);
                ledger_timeout=1; ledger_canceled=1; ledger_decided=1; saw_timeout=1; timeout_edge=aon_edges;
                if(proof_edge==aon_edges)exact_edge_witnesses=exact_edge_witnesses+1;
                $display("EPOCH_TIMEOUT epoch=%0d aon_edge=%0d age=%0d simultaneous_proof=%0d",
                    ledger_epoch,aon_edges,aon_edges-accepted_edge,proof_edge==aon_edges);
            end
        end
    end

    task automatic aon_wait(input integer count);
        begin repeat(count)@(negedge aonClock); end
    endtask
    task automatic reset_all;
        begin
            @(negedge aonClock); commonColdReset=1; pause_cpu=0;
            req_valid=0; resume_valid=0; cancel_valid=0; result_ready=0;
            cpuLinkReady=0; fabricLinkReady=0;
            allow_prepare=1; allow_dirty=1; allow_ack=1; allow_proof=1;
            allow_complete=1; allow_cpu_progress=1; allow_fabric_proof=1; allow_decision=1; dirty_config=0;
            repeat(12)@(negedge aonClock);
            repeat(6)@(negedge cpuClock); repeat(6)@(negedge fabricClock);
            @(negedge aonClock); commonColdReset=0; reset_count=reset_count+1;
            repeat(10)@(negedge cpuClock); cpuLinkReady=1;
            repeat(10)@(negedge fabricClock); fabricLinkReady=1;
            aon_wait(10);
            if(busy||result_valid||held_valid||timeoutSelected||epochExhausted||cleanupFault)
                $fatal(1,"EPOCH_ORACLE_RESET_STATE");
        end
    endtask
    task automatic request_one(input integer lane,input [31:0] token);
        integer before_count, guard_count;
        begin
            before_count=requests; @(negedge aonClock); req_bits[lane]=token; req_valid[lane]=1;
            guard_count=0;
            while(requests==before_count)begin aon_wait(1); guard_count=guard_count+1;
                if(guard_count>1000)$fatal(1,"EPOCH_REQUEST_WATCHDOG");end
            req_valid[lane]=0;
        end
    endtask
    task automatic wait_held;
        integer n;
        begin n=0;
            while(!held_valid[ledger_lane])begin aon_wait(1); n=n+1;
                if(timeoutSelected)$fatal(1,"EPOCH_UNEXPECTED_TIMEOUT_WAIT_HELD case=%0d",selected_case);
                if(n>1000)$fatal(1,"EPOCH_HELD_WATCHDOG");end
        end
    endtask
    task automatic wait_timeout;
        integer n;
        begin n=0;while(!timeoutSelected)begin aon_wait(1);n=n+1;
            if(n>drain_cycles+100)$fatal(1,"EPOCH_TIMEOUT_WATCHDOG");end
            if(held_valid)$fatal(1,"EPOCH_LATE_HELD");
        end
    endtask
    task automatic choose(input integer cancel_it);
        integer n;
        begin
            @(negedge aonClock);
            if(cancel_it)begin cancel_epoch[ledger_lane]=ledger_epoch;cancel_bits[ledger_lane]=ledger_token;cancel_valid[ledger_lane]=1;end
            else begin resume_epoch[ledger_lane]=ledger_epoch;resume_bits[ledger_lane]=ledger_token;resume_valid[ledger_lane]=1;end
            n=0; while(!ledger_decided)begin aon_wait(1);n=n+1;if(n>100)$fatal(1,"EPOCH_DECISION_WATCHDOG");end
            resume_valid=0;cancel_valid=0;
        end
    endtask
    task automatic wait_result;
        integer n;
        begin n=0;while(!result_valid[ledger_lane])begin aon_wait(1);n=n+1;
            if(n>1000)$fatal(1,"EPOCH_RESULT_WATCHDOG");end
        end
    endtask
    task automatic consume_and_retire;
        integer n;
        begin
            wait_result(); @(negedge aonClock); result_ready[ledger_lane]=1;
            n=0;while(!ledger_result_seen)begin aon_wait(1);n=n+1;if(n>100)$fatal(1,"EPOCH_RESULT_CONSUME_WATCHDOG");end
            result_ready=0;
            while(busy)begin aon_wait(1);n=n+1;if(n>1000)$fatal(1,"EPOCH_RETIREMENT_WATCHDOG");end
            if(receipts!=requests||terminals!=requests||prepares!=requests||decisions!=requests)
                $fatal(1,"EPOCH_ORACLE_COUNTS req=%0d prep=%0d dec=%0d result=%0d receipt=%0d",
                    requests,prepares,decisions,terminals,receipts);
        end
    endtask
    task automatic invalid_decisions(input integer count);
        integer n, lane;
        begin
            @(negedge aonClock); lane=ledger_lane;
            resume_epoch[lane]=ledger_epoch;resume_bits[lane]=ledger_token^32'h01000000; resume_valid[lane]=1;
            cancel_epoch[1-lane]=ledger_epoch;cancel_bits[1-lane]=ledger_token; cancel_valid[1-lane]=1;
            for(n=0;n<count;n=n+1)begin
                aon_wait(1);
                if((resume_valid&resume_ready)||(cancel_valid&cancel_ready)||runtimeResume_valid||runtimeCancel_valid)
                    $fatal(1,"EPOCH_ORACLE_STALE_DECISION_ACCEPTED");
                reject_checks=reject_checks+1;
            end
            resume_valid=0;cancel_valid=0;
        end
    endtask
    task automatic blocked_fault;
        integer n;
        begin
            wait_timeout(); n=0;
            while(!cleanupFault)begin aon_wait(1);n=n+1;
                if(n>cleanup_cycles+100)$fatal(1,"EPOCH_CLEANUP_FAULT_WATCHDOG");end
            repeat(24)begin
                aon_wait(1); if(!cleanupFault||!busy||result_valid||held_valid||complete_valid||complete_ready)
                    $fatal(1,"EPOCH_ORACLE_FAKE_TIMEOUT_TERMINAL");
                fault_checks=fault_checks+1;
            end
            $display("EPOCH_PERSISTENT_CLEANUP_FAULT checks=%0d aon_edge=%0d",fault_checks,aon_edges);
        end
    endtask
    integer first_lane, first_epoch, n, attempt, delay_edges, before_decisions, before_cpu;
    reg [31:0] first_token;
    initial begin
        req_bits[0]=0;req_bits[1]=0;resume_bits[0]=0;resume_bits[1]=0;cancel_bits[0]=0;cancel_bits[1]=0;
        result_was_stalled[0]=0;result_was_stalled[1]=0;
        resume_epoch[0]=0;resume_epoch[1]=0;cancel_epoch[0]=0;cancel_epoch[1]=0;
        if($value$plusargs("case=%d",selected_case))begin end
        if($value$plusargs("negative=%d",negative))begin end
        if($value$plusargs("drain_cycles=%d",drain_cycles))begin end
        if($value$plusargs("cleanup_cycles=%d",cleanup_cycles))begin end
        reset_all();
        case(selected_case)
            0: begin
                // Both requesters are simultaneously eligible, but just one
                // public request.fire may enter the independent owner ledger.
                @(negedge aonClock);req_bits[0]=32'h10203040;req_bits[1]=32'h89abcdef;req_valid=3;
                while(requests==0)aon_wait(1);
                first_lane=ledger_lane;first_token=ledger_token;first_epoch=ledger_epoch;
                req_valid[first_lane]=0;
                if(first_lane!=0)$fatal(1,"EPOCH_RESET_ARBITRATION_PRIORITY");
                wait_held(); invalid_decisions(6); choose(0);
                @(negedge aonClock);resume_epoch[first_lane]=first_epoch;resume_bits[first_lane]=first_token;resume_valid[first_lane]=1;
                repeat(6)begin aon_wait(1);
                    if(resume_ready[first_lane])$fatal(1,"EPOCH_DUPLICATE_DECISION_ACCEPTED");
                    reject_checks=reject_checks+1;
                end
                resume_valid=0;
                wait_result();
                repeat(cleanup_cycles+24)begin aon_wait(1);
                    if(requests!=1||!busy||complete_ready||receipts!=0||cleanupFault||timeoutSelected)
                        $fatal(1,"EPOCH_TERMINAL_BACKPRESSURE_RELEASED_OWNER");
                end
                consume_and_retire();
                while(requests<2)aon_wait(1);
                req_valid=0;
                if(ledger_lane!=1||ledger_epoch!=2)$fatal(1,"EPOCH_SECOND_OWNER_ORDER");
                wait_held();
                @(negedge aonClock);cancel_epoch[1]=ledger_epoch;cancel_bits[1]=first_token;cancel_valid[1]=1;
                repeat(6)begin aon_wait(1);if(cancel_ready[1])$fatal(1,"EPOCH_STALE_TOKEN_ACCEPTED");reject_checks=reject_checks+1;end
                cancel_valid=0; choose(1); consume_and_retire();
                if(requests!=2||normal_results!=1||canceled_results!=1||stalled_result_checks<cleanup_cycles+24||reject_checks<18)
                    $fatal(1,"EPOCH_ARBITRATION_COVERAGE");
                // Opaque request tokens may intentionally be reused, including
                // zero; the non-reused internal epoch is what prevents replay.
                request_one(0,first_token);wait_held();
                @(negedge aonClock);resume_bits[0]=first_token;resume_epoch[0]=first_epoch;resume_valid[0]=1;
                cancel_bits[0]=first_token;cancel_epoch[0]=first_epoch;cancel_valid[0]=1;
                repeat(8)begin aon_wait(1);
                    if(resume_ready[0]||cancel_ready[0]||runtimeResume_valid||runtimeCancel_valid)
                        $fatal(1,"EPOCH_REUSED_TOKEN_STALE_EPOCH_ACCEPTED");
                    reject_checks=reject_checks+1;
                end
                resume_valid=0;cancel_valid=0;choose(0);consume_and_retire();
                if(ledger_epoch!=3)$fatal(1,"EPOCH_REQUEST_TOKEN_REUSE_EPOCH");
                $display("EPOCH_ARBITRATION_RECEIPTS owners=%0d rejected_decision_edges=%0d stalls=%0d",requests,reject_checks,stalled_result_checks);
            end
            1: begin
                allow_prepare=0; request_one(0,32'h11000001); blocked_fault();
                if(prepares!=0||decisions!=0)$fatal(1,"EPOCH_UNSENT_PREPARE_ESCAPED");
                repeat(8)begin @(negedge fabricClock);
                    if(!prepare_valid||prepare_epoch!=1)$fatal(1,"EPOCH_UNSENT_PREPARE_NOT_RETAINED");
                    blocked_prepare_checks=blocked_prepare_checks+1;
                end
                allow_prepare=1;consume_and_retire();
                if(!cleanupFault||!saw_timeout||canceled_results!=1)$fatal(1,"EPOCH_UNSENT_TIMEOUT_COVERAGE");
                $display("EPOCH_TIMEOUT_UNSENT checks=%0d persistent_fault=%0d",blocked_prepare_checks,cleanupFault);
            end
            2: begin
                dirty_config=4;allow_dirty=0;request_one(1,32'h22000002);blocked_fault();
                if(prepares!=1||cpu_work_left!=4||dirty_issued!=0||dirty_retired!=0)
                    $fatal(1,"EPOCH_DIRTY_OWNER_NOT_BLOCKED");
                allow_dirty=1;consume_and_retire();
                if(dirty_issued!=4||dirty_retired!=4||model_ack_serial!=1||cpu_resumed_serial!=1||!cleanupFault)
                    $fatal(1,"EPOCH_DIRTY_OWNER_LOST");
                $display("EPOCH_TIMEOUT_DIRTY issued=%0d retired=%0d resume_receipt=%0d",dirty_issued,dirty_retired,cpu_resumed_serial);
            end
            3: begin
                allow_fabric_proof=0;allow_decision=0;request_one(0,32'h33000003);wait_timeout();
                allow_fabric_proof=1;
                n=0;while(!proofObserved)begin aon_wait(1);n=n+1;if(n>200)$fatal(1,"EPOCH_LATE_PROOF_NOT_OBSERVED");end
                @(negedge aonClock);resume_epoch[0]=ledger_epoch;resume_bits[0]=ledger_token;resume_valid[0]=1;
                repeat(12)begin aon_wait(1);
                    if(held_valid||resume_ready[0]||runtimeResume_valid||!timeoutSelected)
                        $fatal(1,"EPOCH_LATE_PROOF_REOPENED_OWNER");
                    reject_checks=reject_checks+1;
                end
                resume_valid=0;allow_decision=1;consume_and_retire();
                $display("EPOCH_LATE_PROOF_REJECTED checks=%0d",reject_checks);
            end
            4: begin
                @(negedge cpuClock);pause_cpu=1;before_cpu=cpu_edges;
                request_one(1,32'h44000004);blocked_fault();
                if(cpu_edges!=before_cpu||cpu_seen_serial!=0||held_valid||proofObserved)
                    $fatal(1,"EPOCH_PAUSED_CPU_FALSE_PROOF");
                pause_cpu=0;consume_and_retire();
                if(cpu_edges<=before_cpu||cpu_resumed_serial!=1||!cleanupFault)
                    $fatal(1,"EPOCH_CPU_RESUME_NOT_DRAINED");
                $display("EPOCH_PAUSED_CPU_RESUMED stopped_edge=%0d resumed_edge=%0d",before_cpu,cpu_edges);
            end
            5: begin
                allow_prepare=0;request_one(0,32'h55000005);wait_timeout();
                // This discards every test endpoint and all three domains;
                // it is explicitly not a single-sided/hot reset test.
                reset_all();aon_wait(drain_cycles+cleanup_cycles+16);
                if(result_valid||held_valid||busy||prepares||decisions||receipts||requests)
                    $fatal(1,"EPOCH_RESET_STALE_REPLAY");
                request_one(1,0);wait_held();choose(0);consume_and_retire();
                if(ledger_epoch!=1)$fatal(1,"EPOCH_RESET_ALLOCATION");
                $display("EPOCH_COORDINATED_RESET resets=%0d epoch=%0d",reset_count,ledger_epoch);
            end
            6: begin
                // Sweep only public source proofs/request timing. No hierarchy
                // or force/release is used. A pass requires an actual observed
                // proofObserved && drainDeadline on an independent-ledger edge.
                attempt=0;
                while(exact_edge_witnesses==0&&attempt<drain_cycles*12)begin
                    if(attempt!=0)reset_all();
                    allow_proof=0;allow_decision=0;
                    aon_wait(attempt%13);
                    request_one(attempt%2,32'h66000000+attempt);
                    delay_edges=attempt%drain_cycles;
                    aon_wait(delay_edges);allow_proof=1;
                    n=0;
                    while(!timeoutSelected&&!held_valid)begin aon_wait(1);n=n+1;
                        if(n>drain_cycles+100)$fatal(1,"EPOCH_EDGE_SWEEP_WATCHDOG");end
                    aon_wait(1);
                    attempt=attempt+1;
                end
                if(exact_edge_witnesses==0)$fatal(1,"EPOCH_EXACT_EDGE_NOT_WITNESSED attempts=%0d",attempt);
                if(!timeoutSelected||held_valid||!ledger_timeout||proof_edge!=timeout_edge)
                    $fatal(1,"EPOCH_TIMEOUT_DID_NOT_WIN_EXACT_EDGE");
                allow_decision=1;consume_and_retire();
                $display("EPOCH_EXACT_EDGE_PRIORITY witnesses=%0d attempts=%0d proof_edge=%0d timeout_edge=%0d",
                    exact_edge_witnesses,attempt,proof_edge,timeout_edge);
            end
            7: begin
                for(n=1;n<=255;n=n+1)begin
                    request_one(n%2,0);wait_held();choose(0);consume_and_retire();
                    if(ledger_epoch!=n)$fatal(1,"EPOCH_EXHAUSTION_ALLOCATION expected=%0d observed=%0d",n,ledger_epoch);
                end
                if(!epochExhausted)$fatal(1,"EPOCH_EXHAUSTION_MISSING");
                @(negedge aonClock);req_valid=3;req_bits[0]=32'hffffffff;req_bits[1]=0;
                repeat(24)begin aon_wait(1);
                    if(req_ready||requests!=255||busy||result_valid||held_valid)
                        $fatal(1,"EPOCH_ORACLE_EPOCH_WRAP");
                    reject_checks=reject_checks+1;
                end
                req_valid=0;reset_all();request_one(0,0);wait_held();choose(0);consume_and_retire();
                if(epochExhausted||ledger_epoch!=1)$fatal(1,"EPOCH_EXHAUSTION_RESET_FAILED");
                $display("EPOCH_EXHAUSTION_NO_WRAP transactions=255 blocked_edges=%0d coordinated_reset=%0d",reject_checks,reset_count);
            end
            8: begin
                request_one(0,32'h88000008);wait_held();
                // Revoke a true CPU-domain proof; false snapshots must revoke
                // AON held after propagation, not latch a perpetual permit.
                @(negedge cpuClock);allow_proof=0;
                n=0;while(held_valid[0])begin aon_wait(1);n=n+1;
                    if(n>100)$fatal(1,"EPOCH_FALSE_SNAPSHOT_NOT_PROPAGATED");end
                @(negedge aonClock);resume_bits[0]=ledger_token;resume_epoch[0]=ledger_epoch;resume_valid[0]=1;
                repeat(drain_cycles+cleanup_cycles+24)begin aon_wait(1);
                    if(held_valid||resume_ready[0]||runtimeResume_valid||runtimeCancel_valid||
                       timeoutSelected||cleanupFault||result_valid||complete_valid||!busy)
                        $fatal(1,"EPOCH_REVOKED_PROOF_REOPENED_OR_FAKE_TERMINAL");
                    reject_checks=reject_checks+1;
                end
                resume_valid=0;choose(1);consume_and_retire();
                if(ledger_timeout||!ledger_canceled)$fatal(1,"EPOCH_REVOKED_PROOF_RESULT_KIND");
                $display("EPOCH_FALSE_SNAPSHOT_REVOKED rejected_resume_edges=%0d explicit_cancel=1 watchdog_restarted=0",reject_checks);
            end
            default:$fatal(1,"EPOCH_BAD_CASE");
        endcase
        aon_wait(12);
        if(result_valid||held_valid||busy||endpoint_owned||requests!=terminals||terminals!=receipts)
            $fatal(1,"EPOCH_ORACLE_FINAL_LEDGER");
        $display("RUNTIME_EPOCH_COMPONENT_PASS case=%0d requests=%0d prepares=%0d decisions=%0d terminals=%0d receipts=%0d cpu_half=%0d fabric_half=%0d aon_half=%0d",
            selected_case,requests,prepares,decisions,terminals,receipts,cpu_half,fabric_half,aon_half);
        $finish;
    end
    initial begin #100000000;$fatal(1,"EPOCH_GLOBAL_WATCHDOG");end
endmodule
