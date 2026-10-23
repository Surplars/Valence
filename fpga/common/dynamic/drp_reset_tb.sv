`timescale 1ns/1ps
`default_nettype none
// Pure transaction/reset corner test. gate_closed/isolate here are test inputs,
// not physical evidence; physical witnesses are separately checked.
module drp_reset_tb;
    reg aon=0,cold=1,valid=0,drdy=0;
    always #10 aon=~aon;
    wire ready,rvalid,error,reset_mmcm,fatal,den,dwe,busy,outstanding;
    wire [6:0] address;wire [15:0] data;wire [31:0] rhz,rtoken;
    native_clock_drp #(.TIMEOUT_CYCLES(12),.DRAIN_CYCLES(24)) dut(
        .aon_clock(aon),.cold_reset(cold),.gate_closed(1'b1),.isolated(1'b1),.clock_enable(1'b0),
        .program_valid(valid),.program_ready(ready),.program_hz(32'd100000000),.program_token(32'd42),
        .program_parameters(24'h0a280a),.program_fallback(1'b0),.result_valid(rvalid),.result_ready(1'b1),
        .result_hz(rhz),.result_token(rtoken),.result_error(error),.mmcm_reset(reset_mmcm),.fatal(fatal),
        .drp_address(address),.drp_data(data),.drp_enable(den),.drp_write(dwe),
        .drp_read_data(16'h0000),.drp_ready(drdy),.busy(busy),.drp_outstanding(outstanding));
    integer accepted=0,mark=0,cases=0;
    always @(posedge aon)if(den)accepted=accepted+1;
    task wait_ready;
        integer n;
        begin
            n=0;while(ready!==1'b1 && n<60)begin @(negedge aon);n=n+1;end
            if(ready!==1'b1 || fatal!==1'b0)$fatal(1,"RESET_GUARD_DID_NOT_DRAIN");
        end
    endtask
    task launch;
        begin wait_ready();valid=1;@(negedge aon);valid=0;end
    endtask
    task pending;
        begin launch();while(outstanding!==1'b1)@(negedge aon);end
    endtask
    initial begin
        #25;cold=0;wait_ready();
        // DEN high but not yet accepted: async reset removes it without owner.
        launch();while(den!==1'b1)@(negedge aon);mark=accepted;cold=1;
        repeat(2)@(negedge aon);cold=0;wait_ready();
        if(outstanding!==1'b0 || accepted!=mark)$fatal(1,"UNSAMPLED_DEN_CREATED_OWNER");cases=cases+1;
        // Completion while reset is held must clear the persistent owner.
        pending();mark=accepted;cold=1;repeat(2)@(negedge aon);
        drdy=1;@(negedge aon);drdy=0;cold=0;wait_ready();
        if(outstanding!==1'b0 || accepted!=mark)$fatal(1,"RESET_HIGH_COMPLETION_LOST");cases=cases+1;
        // The sole old DRDY pulse coincides exactly with reset-exit guard.
        pending();mark=accepted;cold=1;repeat(2)@(negedge aon);
        cold=0;drdy=1;@(negedge aon);drdy=0;wait_ready();
        if(outstanding!==1'b0 || accepted!=mark)$fatal(1,"RESET_EXIT_COMPLETION_LOST");cases=cases+1;
        // Reset after a timeout still cannot discard the uncompleted transfer.
        pending();while(rvalid!==1'b1)@(negedge aon);mark=accepted;cold=1;
        repeat(2)@(negedge aon);cold=0;repeat(3)@(negedge aon);
        if(ready!==1'b0 || outstanding!==1'b1)$fatal(1,"TIMEOUT_OWNER_ERASED_BY_RESET");
        drdy=1;@(negedge aon);drdy=0;wait_ready();
        if(accepted!=mark)$fatal(1,"RESET_DRAIN_OVERLAPPED_NEW_DEN");cases=cases+1;
        // No completion after reset => fatal, never a replacement transaction.
        pending();mark=accepted;cold=1;repeat(2)@(negedge aon);cold=0;
        repeat(30)@(negedge aon);
        if(fatal!==1'b1 || ready!==1'b0 || outstanding!==1'b1 || accepted!=mark || reset_mmcm!==1'b1)
            $fatal(1,"RESET_LOST_DRP_NOT_FAIL_CLOSED");cases=cases+1;
        $display("DRP_RESET_BEHAVIORAL_PASS cases=%0d",cases);$finish;
    end
    initial begin #100000;$fatal(1,"DRP_RESET_TIMEOUT");end
endmodule
`default_nettype wire
