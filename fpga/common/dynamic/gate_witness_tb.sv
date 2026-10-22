`timescale 1ns/1ps
`default_nettype none
module gate_witness_tb;
    reg aon=0,raw=0,cold=1,enable=0,raw_running=1,delivery=1;
    always #10 aon=~aon;
    always begin #5;if(raw_running)raw=~raw;end
    wire ce,managed,buffered,closed,opened,resumed;
    BUFGCE buffer(.I(raw),.CE(ce),.O(buffered));
    assign managed=buffered && delivery;
    native_clock_gate dut(.aon_clock(aon),.cold_reset(cold),.raw_clock(raw),.managed_clock(managed),
        .enable(enable),.gate_ce(ce),.gate_closed(closed),.gate_open(opened),.resumed(resumed));
    initial begin
        #101;cold=0;repeat(15)@(negedge aon);
        if(closed!==1'b1)$fatal(1,"INITIAL_CLOSE_NOT_PROVEN");
        enable=1;repeat(15)@(negedge aon);
        if(resumed!==1'b1)$fatal(1,"INITIAL_RESUME_NOT_PROVEN");
        // Stop raw while already low. Merely requesting close is insufficient.
        @(negedge raw);raw_running=0;@(negedge aon);enable=0;
        repeat(15)begin @(negedge aon);if(closed!==1'b0)$fatal(1,"NO_RAW_EDGES_FAKE_CLOSE");end
        raw_running=1;repeat(15)@(negedge aon);
        if(closed!==1'b1)$fatal(1,"RESUMED_RAW_CLOSE_NOT_PROVEN");
        // Even real source edges/CE opening cannot substitute destination edges.
        delivery=0;enable=1;repeat(15)@(negedge aon);
        if(opened!==1'b0 || resumed!==1'b0)$fatal(1,"NO_MANAGED_EDGES_FAKE_RESUME");
        @(negedge raw);delivery=1;repeat(15)@(negedge aon);
        if(opened!==1'b1 || resumed!==1'b1)$fatal(1,"MANAGED_RESUME_NOT_PROVEN");
        // One AON-cycle disable/re-enable must not publish stale open witnesses.
        enable=0;delivery=0;@(negedge aon);enable=1;
        #1;if(opened!==1'b0 || resumed!==1'b0)$fatal(1,"SHORT_DISABLE_STALE_OPEN");
        repeat(8)@(negedge aon);
        if(opened!==1'b0 || resumed!==1'b0)$fatal(1,"SHORT_DISABLE_NO_MANAGED_EDGES");
        @(negedge raw);delivery=1;repeat(15)@(negedge aon);
        if(resumed!==1'b1)$fatal(1,"SHORT_DISABLE_RECOVERY");
        // A fresh close cannot reuse an earlier close token.
        enable=0;#1;if(closed!==1'b0)$fatal(1,"STALE_CLOSE_TOKEN");
        repeat(15)@(negedge aon);
        if(closed!==1'b1)$fatal(1,"FRESH_CLOSE_TOKEN_NOT_PROVEN");
        $display("GATE_WITNESS_BEHAVIORAL_PASS missing_raw_missing_managed_fresh_tokens");$finish;
    end
    initial begin #100000;$fatal(1,"GATE_WITNESS_TIMEOUT");end
endmodule
`default_nettype wire
