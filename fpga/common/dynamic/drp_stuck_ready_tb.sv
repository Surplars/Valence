`timescale 1ns/1ps
`default_nettype none
module drp_stuck_ready_tb;
    reg aon=0,cold=1,valid=0,drdy=0;
    always #10 aon=~aon;
    wire ready,rvalid,error,reset_mmcm,fatal,den,dwe,busy,outstanding;
    wire [6:0] address;wire [15:0] data;wire [31:0] rhz,rtoken;
    native_clock_drp #(.TIMEOUT_CYCLES(12),.DRAIN_CYCLES(24)) dut(
        .aon_clock(aon),.cold_reset(cold),.gate_closed(1'b1),.isolated(1'b1),.clock_enable(1'b0),
        .program_valid(valid),.program_ready(ready),.program_hz(32'd50000000),.program_token(32'd77),
        .program_fallback(1'b1),.result_valid(rvalid),.result_ready(1'b1),
        .result_hz(rhz),.result_token(rtoken),.result_error(error),.mmcm_reset(reset_mmcm),.fatal(fatal),
        .drp_address(address),.drp_data(data),.drp_enable(den),.drp_write(dwe),
        .drp_read_data(16'h0000),.drp_ready(drdy),.busy(busy),.drp_outstanding(outstanding));
    integer accepted=0,mark=0,errors=0;
    always @(posedge aon)begin
        if(den)begin
            if(drdy)$fatal(1,"DEN_OVERLAPPED_STALE_DRDY");
            accepted=accepted+1;
        end
        if(rvalid && error)errors=errors+1;
    end
    task pending;
        begin
            while(ready!==1'b1)@(negedge aon);
            valid=1;@(negedge aon);valid=0;
            while(outstanding!==1'b1)@(negedge aon);
        end
    endtask
    initial begin
        #25;cold=0;pending();mark=accepted;drdy=1;
        repeat(5)@(negedge aon);
        if(accepted!=mark || fatal!==1'b0)$fatal(1,"STRETCHED_DRDY_REISSUED");
        drdy=0;while(accepted==mark)@(negedge aon);
        // Clear the new pending write as an old completion under common reset.
        cold=1;drdy=1;repeat(2)@(negedge aon);cold=0;drdy=0;
        pending();mark=accepted;drdy=1;
        repeat(42)@(negedge aon);
        if(accepted!=mark || fatal!==1'b1 || reset_mmcm!==1'b1 || ready!==1'b0 || errors<1)
            $fatal(1,"STUCK_DRDY_NOT_FAIL_CLOSED");
        $display("DRP_READY_FAULT_BEHAVIORAL_PASS stretched_and_stuck cases=2");$finish;
    end
    initial begin #100000;$fatal(1,"DRP_READY_TEST_TIMEOUT");end
endmodule
`default_nettype wire
