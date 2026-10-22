`timescale 1ns/1ps
// Independent public-interface ledger around the production two-clock helper.
// This COMPONENT fixture does not model actual DDR queues or timer accumulation.
// No DUT hierarchy read/poke, surrogate mailbox, forced DUT signal or source edit.
module fixed_epoch_qualifier_tb;
    reg fabricClock=0, fixedClock=0, commonColdReset=0, pause_fixed=0;
    integer fabric_half=3, fixed_half=7, phase_ps=1300, selected_case=0, negative=0;
    initial begin
        if($value$plusargs("fabric_half=%d",fabric_half))begin end
        forever #(fabric_half) fabricClock=~fabricClock;
    end
    initial begin
        if($value$plusargs("fixed_half=%d",fixed_half))begin end
        if($value$plusargs("phase_ps=%d",phase_ps))begin end
        #(phase_ps/1000.0); forever begin #(fixed_half); if(!pause_fixed) fixedClock=~fixedClock; end
    end
    reg prepare_valid=0, fabricHeld_valid=0, fabricAllObligationsIdle=0;
    reg [7:0] prepare_bits=0, fabricHeld_bits=0;
    reg localIdle=0, linkReady=0;
    reg completion_valid=0, completion_canceled=0;
    reg [7:0] completion_epoch=0;
    reg terminalConsumedAtAon=0, terminalRetired=0;
    wire qualified_valid, retirementPermit, busy, fault;
    wire [7:0] qualified_bits;
    CommonFixedDomainEpochQualifier dut(
        .fabricClock(fabricClock), .fixedClock(fixedClock), .commonColdReset(commonColdReset),
        .prepare_valid(prepare_valid), .prepare_bits(prepare_bits),
        .fabricHeld_valid(fabricHeld_valid), .fabricHeld_bits(fabricHeld_bits),
        .fabricAllObligationsIdle(fabricAllObligationsIdle), .localIdle(localIdle), .linkReady(linkReady),
        .completion_valid(completion_valid), .completion_bits_epoch(completion_epoch),
        .completion_bits_canceled(completion_canceled), .terminalConsumedAtAon(terminalConsumedAtAon),
        .terminalRetired(terminalRetired), .qualified_valid(qualified_valid), .qualified_bits(qualified_bits),
        .retirementPermit(retirementPermit), .busy(busy), .fault(fault));

    integer fabric_edges=0, fixed_edges=0, epoch_fixed_start=0, receipt_fixed_start=0;
    integer eligible_samples=0, expected_epoch=0, qualified_checks=0, retirement_checks=0;
    integer prepare_count=0, retire_count=0, reset_count=0, blocked_checks=0;
    reg expected_owned=0, expected_canceled=0, expect_fault=0;
    // Mutate observations only. Ordinary ledger assertions remain unchanged.
    wire [7:0] observed_qualified_epoch = negative==1 ? qualified_bits^8'h01 : qualified_bits;
    wire observed_aon_receipt = negative==2 ? 1'b0 : terminalConsumedAtAon;
    always @(posedge fixedClock) begin
        fixed_edges=fixed_edges+1;
        if(!commonColdReset && expected_owned && fabricHeld_valid &&
            fabricHeld_bits==expected_epoch && fabricAllObligationsIdle && localIdle && linkReady)
            eligible_samples=eligible_samples+1;
    end
    always @(posedge fabricClock) begin
        fabric_edges=fabric_edges+1;
        if(!commonColdReset) begin
            if(fault&&!expect_fault) $fatal(1,"FIXED_ORACLE_UNEXPECTED_FAULT");
            if(qualified_valid) begin
                if(!expected_owned || observed_qualified_epoch!==expected_epoch[7:0])
                    $fatal(1,"FIXED_ORACLE_EPOCH observed=%0d expected=%0d",observed_qualified_epoch,expected_epoch);
                if(!fabricHeld_valid || fabricHeld_bits!==expected_epoch[7:0] ||
                    !fabricAllObligationsIdle || eligible_samples==0 || fixed_edges<=epoch_fixed_start)
                    $fatal(1,"FIXED_ORACLE_QUALIFY_WITHOUT_REAL_FIXED_SAMPLE");
                qualified_checks=qualified_checks+1;
            end
            if(retirementPermit) begin
                if(!expected_owned || !completion_valid || completion_epoch!==expected_epoch[7:0] ||
                    completion_canceled!==expected_canceled)
                    $fatal(1,"FIXED_ORACLE_RETIRE_TAG");
                if(!observed_aon_receipt || fixed_edges<=receipt_fixed_start)
                    $fatal(1,"FIXED_ORACLE_RECEIPT");
                retirement_checks=retirement_checks+1;
            end
            if(terminalRetired) begin
                if(!retirementPermit) $fatal(1,"FIXED_ORACLE_PREMATURE_RETIRE");
                retire_count=retire_count+1;
            end
        end
    end
    task ticks(input integer count); begin repeat(count) @(negedge fabricClock); end endtask
    task reset_all;
        begin
            @(negedge fabricClock); pause_fixed=0; commonColdReset=1;
            prepare_valid=0; fabricHeld_valid=0; fabricAllObligationsIdle=0;
            localIdle=0; linkReady=0; completion_valid=0; terminalConsumedAtAon=0; terminalRetired=0;
            expected_owned=0; expect_fault=0; eligible_samples=0;
            repeat(8) @(negedge fixedClock); ticks(8); commonColdReset=0;
            repeat(8) @(negedge fixedClock); ticks(8); reset_count=reset_count+1;
            if(busy||qualified_valid||retirementPermit||fault) $fatal(1,"FIXED_ORACLE_RESET_NOT_EMPTY");
        end
    endtask
    task start_epoch(input integer ep);
        begin
            @(negedge fabricClock);
            expected_epoch=ep; expected_owned=1; expected_canceled=0; eligible_samples=0;
            epoch_fixed_start=fixed_edges; receipt_fixed_start=fixed_edges;
            prepare_bits=ep; prepare_valid=1;
            @(negedge fabricClock); prepare_valid=0; prepare_count=prepare_count+1;
            ticks(2); if(!busy) $fatal(1,"FIXED_ORACLE_PREPARE_NOT_OWNED");
            $display("FIXED_PREPARE epoch=%0d",ep);
        end
    endtask
    task block_proof(input integer count);
        begin
            repeat(count) begin
                @(negedge fabricClock); blocked_checks=blocked_checks+1;
                if(qualified_valid||retirementPermit||!busy) $fatal(1,"FIXED_ORACLE_BLOCKED_QUALIFIED");
            end
        end
    endtask
    task wait_proof;
        integer n;
        begin
            n=0; while(!qualified_valid&&n<2500)begin ticks(1);n=n+1;end
            if(!qualified_valid) $fatal(1,"FIXED_ORACLE_PROOF_TIMEOUT");
            $display("FIXED_PROOF epoch=%0d fixed_edges=%0d",qualified_bits,fixed_edges);
        end
    endtask
    task wait_revoked;
        integer n;
        begin
            n=0; while(qualified_valid&&n<2500)begin ticks(1);n=n+1;end
            if(qualified_valid) $fatal(1,"FIXED_ORACLE_FALSE_OBSERVATION_LOST");
        end
    endtask
    task set_completion(input integer ep,input integer cancel_value);
        begin
            @(negedge fabricClock); completion_valid=1; completion_epoch=ep;
            completion_canceled=cancel_value; expected_canceled=cancel_value;
            terminalConsumedAtAon=0;
        end
    endtask
    task aon_receipt;
        begin
            @(negedge fabricClock); receipt_fixed_start=fixed_edges; terminalConsumedAtAon=1;
        end
    endtask
    task wait_permit;
        integer n;
        begin
            n=0; while(!retirementPermit&&n<2500)begin ticks(1);n=n+1;end
            if(!retirementPermit) $fatal(1,"FIXED_ORACLE_RETIREMENT_TIMEOUT");
            $display("FIXED_RECEIPT epoch=%0d canceled=%0d",completion_epoch,completion_canceled);
        end
    endtask
    task retire_epoch;
        begin
            wait_permit();
            repeat(30) begin
                ticks(1);
                if(!busy||!retirementPermit) $fatal(1,"FIXED_ORACLE_LOST_BACKPRESSURED_RECEIPT");
            end
            terminalRetired=1; @(negedge fabricClock);
            terminalRetired=0; completion_valid=0; terminalConsumedAtAon=0;
            fabricHeld_valid=0; fabricAllObligationsIdle=0; expected_owned=0;
            ticks(5);
            if(busy||retirementPermit||qualified_valid||fault) $fatal(1,"FIXED_ORACLE_OWNER_NOT_RETIRED");
        end
    endtask
    task give_real_hold;
        begin
            @(negedge fabricClock); fabricHeld_bits=expected_epoch; fabricHeld_valid=1;
            fabricAllObligationsIdle=1;
        end
    endtask
    task pause_clock;
        begin @(negedge fixedClock); pause_fixed=1; end
    endtask
    task finish_cancel;
        begin
            set_completion(expected_epoch,1); aon_receipt(); retire_epoch();
        end
    endtask
    integer n;
    initial begin
        if($value$plusargs("case=%d",selected_case))begin end
        if($value$plusargs("negative=%d",negative))begin end
        reset_all(); localIdle=1; linkReady=1;
        case(selected_case)
        0: begin
            start_epoch(1);
            // Idle and link alone, initial mailbox idle, wrong held epoch and
            // actual held without all obligations idle can never qualify.
            terminalConsumedAtAon=1; block_proof(35); terminalConsumedAtAon=0;
            fabricHeld_valid=1; fabricHeld_bits=8'h7f; fabricAllObligationsIdle=1; block_proof(35);
            fabricHeld_bits=1; fabricAllObligationsIdle=0; block_proof(35);
            localIdle=0; fabricAllObligationsIdle=1; block_proof(60);
            @(negedge fixedClock); localIdle=1; wait_proof();
            @(negedge fixedClock); localIdle=0; wait_revoked(); block_proof(50);
            @(negedge fixedClock); localIdle=1; wait_proof();
            @(negedge fixedClock); linkReady=0; wait_revoked(); block_proof(50);
            @(negedge fixedClock); linkReady=1; wait_proof();
            set_completion(1,0); ticks(50);
            if(retirementPermit||!busy) $fatal(1,"FIXED_ORACLE_INITIAL_IDLE_IS_NOT_ACK");
            aon_receipt(); retire_epoch();
            start_epoch(2); fabricHeld_valid=1; fabricHeld_bits=1; fabricAllObligationsIdle=1;
            block_proof(60); give_real_hold(); wait_proof();
            set_completion(2,0); aon_receipt(); retire_epoch();
        end
        1: begin
            // Early cancel never sent a qualification command. It still needs
            // a fixed-clock decision and link, not a synthesized ACK.
            start_epoch(1); localIdle=0; linkReady=0; set_completion(1,1); ticks(35);
            if(retirementPermit) $fatal(1,"FIXED_ORACLE_UNCONSUMED_CANCEL");
            aon_receipt(); block_proof(80);
            @(negedge fixedClock); linkReady=1; retire_epoch();
        end
        2: begin
            // Clock stopped before the qualification request reaches it.
            start_epoch(1); pause_clock(); give_real_hold(); block_proof(100);
            set_completion(1,1); aon_receipt(); block_proof(100);
            pause_fixed=0; retire_epoch();
        end
        3: begin
            // A proof does not convert initial sourceIdle into a retirement ACK.
            start_epoch(1); give_real_hold(); wait_proof(); pause_clock();
            set_completion(1,0); aon_receipt(); ticks(150);
            if(retirementPermit||!busy) $fatal(1,"FIXED_ORACLE_STOPPED_CLOCK_RETIRED");
            pause_fixed=0; retire_epoch();
        end
        4: begin
            // Coordinated cold reset discards active ownership and mailbox work.
            start_epoch(9); give_real_hold(); wait_proof(); set_completion(9,1); aon_receipt();
            ticks(2); reset_all(); localIdle=1; linkReady=1;
            start_epoch(1); block_proof(80); finish_cancel();
        end
        5: begin
            start_epoch(1); give_real_hold(); wait_proof(); set_completion(1,0); aon_receipt(); retire_epoch();
            start_epoch(2); expect_fault=1; set_completion(1,1); aon_receipt(); ticks(100);
            if(!fault||retirementPermit||qualified_valid||!busy) $fatal(1,"FIXED_ORACLE_STALE_COMPLETION_NOT_BLOCKED");
            $display("FIXED_STALE_COMPLETION_BLOCKED");
        end
        6: begin
            start_epoch(1); give_real_hold(); wait_proof();
            expect_fault=1; prepare_bits=2; prepare_valid=1; ticks(1); prepare_valid=0; ticks(80);
            if(!fault||retirementPermit||qualified_valid||!busy) $fatal(1,"FIXED_ORACLE_OWNER_OVERWRITE_NOT_BLOCKED");
            $display("FIXED_BUSY_PREPARE_BLOCKED");
        end
        7: begin
            // Request was sent, but its first snapshot is false. Cancellation
            // races a later true snapshot; late proof cannot choose normal result.
            start_epoch(1); localIdle=0; give_real_hold(); block_proof(70);
            set_completion(1,1); aon_receipt();
            @(negedge fixedClock); localIdle=1; retire_epoch();
            start_epoch(2); block_proof(80); finish_cancel();
        end
        8: begin
            start_epoch(1); give_real_hold(); wait_proof(); set_completion(1,0); aon_receipt();
            wait_permit(); expect_fault=1; completion_canceled=1; ticks(80);
            if(!fault||retirementPermit||qualified_valid||!busy) $fatal(1,"FIXED_ORACLE_CHANGED_TERMINAL_NOT_BLOCKED");
            $display("FIXED_CHANGED_COMPLETION_BLOCKED");
        end
        9: begin
            // The real runtime completion has already drained the old owners
            // and resumed the CPU. New traffic must not strand its control ACK.
            start_epoch(1); give_real_hold(); wait_proof();
            set_completion(1,0); @(negedge fixedClock); localIdle=0;
            wait_revoked(); ticks(70); aon_receipt(); retire_epoch();
            if(localIdle) $fatal(1,"FIXED_ORACLE_POST_RESUME_TRAFFIC_NOT_HELD");
            $display("FIXED_POST_RESUME_BUSY_RETIRED");
        end
        10: begin
            // Finite epoch equality does not authorize wrap or ancient replay.
            start_epoch(255); finish_cancel(); expect_fault=1;
            prepare_bits=1; prepare_valid=1; ticks(1); prepare_valid=0; ticks(80);
            if(!fault||busy||retirementPermit||qualified_valid)
                $fatal(1,"FIXED_ORACLE_WRAPPED_PREPARE_NOT_BLOCKED");
            $display("FIXED_WRAPPED_PREPARE_BLOCKED");
        end
        default: $fatal(1,"FIXED_UNKNOWN_CASE");
        endcase
        $display("FIXED_EPOCH_QUALIFIER_PASS case=%0d prepares=%0d retired=%0d proof_checks=%0d retirement_checks=%0d blocked_checks=%0d resets=%0d",
            selected_case,prepare_count,retire_count,qualified_checks,retirement_checks,blocked_checks,reset_count);
        $finish;
    end
    initial begin #5000000; $fatal(1,"FIXED_ORACLE_WATCHDOG"); end
endmodule
