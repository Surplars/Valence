`timescale 1ns/1ps
// Pin-event behavioral test, not AMD UNISIM or physical timing qualification.
module bscan_user_tb;
    localparam [3:0] TLR=0, IDLE=1, SELECT_DR=2, CAPTURE_DR=3, SHIFT_DR=4,
        EXIT1_DR=5, PAUSE_DR=6, EXIT2_DR=7, UPDATE_DR=8,
        SELECT_IR=9, CAPTURE_IR=10, SHIFT_IR=11, EXIT1_IR=12,
        PAUSE_IR=13, EXIT2_IR=14, UPDATE_IR=15;
    reg tck=0, tms=1, tdi=0, sel=1, por_n=0, clk=0;
    reg [3:0] state=TLR, next_state;
    wire capture=state==CAPTURE_DR, shift=state==SHIFT_DR;
    wire update=state==UPDATE_DR, reset=state==TLR;
    // DRCK can remain high outside Capture/Shift; no UPDATE clock is fabricated
    // from DRCK. This reproduces the primitive interface, not an FPGA TAP model.
    wire drck=sel && ((!capture && !shift) || tck);
    wire tdo;
    reg external_tdo=0;
    always #7 clk=~clk;
    always @(negedge tck) external_tdo <= tdo;
    always @* begin
        case(state)
            TLR:next_state=tms?TLR:IDLE;
            IDLE:next_state=tms?SELECT_DR:IDLE;
            SELECT_DR:next_state=tms?SELECT_IR:CAPTURE_DR;
            CAPTURE_DR:next_state=tms?EXIT1_DR:SHIFT_DR;
            SHIFT_DR:next_state=tms?EXIT1_DR:SHIFT_DR;
            EXIT1_DR:next_state=tms?UPDATE_DR:PAUSE_DR;
            PAUSE_DR:next_state=tms?EXIT2_DR:PAUSE_DR;
            EXIT2_DR:next_state=tms?UPDATE_DR:SHIFT_DR;
            UPDATE_DR:next_state=tms?SELECT_DR:IDLE;
            SELECT_IR:next_state=tms?TLR:CAPTURE_IR;
            CAPTURE_IR:next_state=tms?EXIT1_IR:SHIFT_IR;
            SHIFT_IR:next_state=tms?EXIT1_IR:SHIFT_IR;
            EXIT1_IR:next_state=tms?UPDATE_IR:PAUSE_IR;
            PAUSE_IR:next_state=tms?EXIT2_IR:PAUSE_IR;
            EXIT2_IR:next_state=tms?UPDATE_IR:SHIFT_IR;
            UPDATE_IR:next_state=tms?SELECT_DR:IDLE;
            default:next_state=TLR;
        endcase
    end
    always @(posedge tck) state<=next_state;

    wire req_valid, rsp_ready, dmi_reset_n;
    wire [1:0] req_op;
    wire [6:0] req_address;
    wire [31:0] req_data;
    reg req_ready=1, rsp_valid=0;
    reg [1:0] rsp_status=0;
    reg [31:0] rsp_data=0;
    reg pending=0, endpoint_enable=1;
    integer pending_delay=0, response_delay=0, request_count=0;
    reg [31:0] memory[0:127];
    ValenceBscanUserTransport dut(
        .bscan_tck(tck),.bscan_drck(drck),.bscan_capture(capture),.bscan_shift(shift),
        .bscan_update(update),.bscan_sel(sel),.bscan_reset(reset),.bscan_tdi(tdi),.bscan_tdo(tdo),
        .debug_clk(clk),.debug_por_n(por_n),.dmi_reset_n(dmi_reset_n),
        .dmi_req_valid(req_valid),.dmi_req_ready(req_ready),.dmi_req_op(req_op),
        .dmi_req_address(req_address),.dmi_req_data(req_data),
        .dmi_rsp_valid(rsp_valid),.dmi_rsp_ready(rsp_ready),
        .dmi_rsp_status(rsp_status),.dmi_rsp_data(rsp_data));
    always @(posedge clk or negedge dmi_reset_n) begin
        if (!dmi_reset_n) begin
            pending<=0; rsp_valid<=0; rsp_status<=0; rsp_data<=0; pending_delay<=0;
        end else begin
            if (req_valid && req_ready) begin
                if(pending || rsp_valid) $fatal(1,"overlapping downstream request");
                request_count=request_count+1;
                pending<=1; pending_delay<=response_delay;
                rsp_status<=req_address==7'h7f?2:0;
                rsp_data<=memory[req_address];
                if(req_op==2 && req_address!=7'h7f) memory[req_address]<=req_data;
            end
            if(pending && endpoint_enable) begin
                if(pending_delay!=0) pending_delay<=pending_delay-1;
                else begin pending<=0; rsp_valid<=1; end
            end
            if(rsp_valid && rsp_ready) rsp_valid<=0;
        end
    end

    function [63:0] frame(input [1:0] op,input [6:0] address,input [31:0] data);
        frame={16'h5642,4'h1,3'b0,address,data,op};
    endfunction
    task tick(input bit ms,input bit di,output bit dout);
        begin
            tms=ms;tdi=di;#4;dout=external_tdo;tck=1;#5;tck=0;#1;
        end
    endtask
    bit ignored;
    task step(input bit ms);
        tick(ms,0,ignored);
    endtask
    task idle(input integer clocks);
        integer n;
        begin for(n=0;n<clocks;n=n+1) step(0); end
    endtask
    task begin_scan;
        begin
            if(state==IDLE || state==UPDATE_DR) begin step(1);step(0);step(0); end
            else $fatal(1,"scan started from wrong state");
        end
    endtask
    task scan(input [63:0] tx,input integer count,input integer pause_after,output [63:0] rx);
        integer n;
        bit sampled;
        begin
            rx=0;begin_scan;
            for(n=0;n<count;n=n+1)begin
                tick(n==count-1 || n==pause_after, tx[n%64],sampled);
                if(n<64)rx[n]=sampled;
                if(n==pause_after && n!=count-1)begin
                    step(0);idle(4);step(1);step(0);
                end
            end
            if(count==0)$fatal(1,"zero-bit scan not implemented by this helper");
            step(1); // Exit1 -> Update; deliberately NO idle cycle here.
        end
    endtask
    task scan_empty;
        begin
            if(state!=IDLE && state!=UPDATE_DR)$fatal(1,"empty scan started from wrong state");
            step(1);step(0);step(1);step(1); // Select -> Capture -> Exit1 -> Update, no Shift.
        end
    endtask
    task poll_done(output [63:0] rx);
        integer tries;
        begin
            rx=0;tries=0;
            while(!rx[41] || rx[42])begin
                idle(8);scan(frame(0,0,0),64,-1,rx);tries=tries+1;
                if(tries>100)$fatal(1,"response timeout");
                if(rx[63:48]!=16'h5642 || rx[47:44]!=1)$fatal(1,"signature/bit order");
            end
        end
    endtask
    task clear_result;
        reg [63:0] rx;
        begin
            idle(8);scan(frame(3,1,0),64,-1,rx);idle(8);
            scan(frame(0,0,0),64,-1,rx);
            if(rx[43:41]!=0 || rx[1:0]!=0)$fatal(1,"clear did not recover idle");
        end
    endtask
    reg [63:0] rx,tx;
    integer n,before_count;
    initial begin
        for(n=0;n<128;n=n+1)memory[n]=32'hcafe0000+n;
        #2;por_n=1;step(0);idle(10);
        scan(frame(3,0,0),64,-1,rx);poll_done(rx);
        if(rx[33:2]!=32'h701 || rx[1:0]!=0 || request_count!=0)$fatal(1,"capability");

        // Zero-idle Update->Capture must never expose the prior DONE as a new
        // completed request; pause/resume preserves all 64 bits and last bit.
        scan(frame(2,7'h25,32'h89abcdef),64,17,rx);
        scan(frame(0,0,0),64,-1,rx);
        if(!rx[42] && rx[41])$fatal(1,"stale DONE visible on immediate capture");
        poll_done(rx);
        if(rx[1:0]!=0 || rx[40:34]!=7'h25 || memory[7'h25]!=32'h89abcdef)$fatal(1,"write");
        scan(frame(1,7'h25,0),64,-1,rx);poll_done(rx);
        if(rx[33:2]!=32'h89abcdef || rx[1:0]!=0 || request_count!=2)$fatal(1,"read/duplicates");

        // Deselected USER scans may not mutate transport state.
        before_count=request_count;sel=0;
        scan(frame(2,7'h26,32'hffffffff),64,-1,rx);idle(12);sel=1;
        scan(frame(0,0,0),64,-1,rx);
        if(request_count!=before_count || memory[7'h26]!=32'hcafe0026)$fatal(1,"deselected update");

        // Stopped TCK after UPDATE holds the event and data; no phantom request.
        before_count=request_count;
        scan(frame(1,7'h25,0),64,-1,rx);#500;
        if(request_count!=before_count)$fatal(1,"UPDATE bypassed TCK mailbox");
        poll_done(rx);if(request_count!=before_count+1)$fatal(1,"stopped TCK recovery");

        // Poll while request backpressured: no sticky error and stable payload.
        clear_result;req_ready=0;
        scan(frame(1,7'h12,0),64,-1,rx);idle(8);
        scan(frame(0,0,0),64,-1,rx);
        if(!rx[42] || rx[43])$fatal(1,"busy polling semantics");
        if(!req_valid || req_address!=7'h12 || req_op!=1)$fatal(1,"request backpressure");
        // Second operation while busy must fail closed, never duplicate.
        before_count=request_count;
        scan(frame(2,7'h33,32'h55555555),64,-1,rx);idle(8);
        req_ready=1;poll_done(rx);
        if(!rx[43] || rx[1:0]!=2 || request_count!=before_count+1 ||
           memory[7'h33]!=32'hcafe0033)$fatal(1,"overlapping command did not fail closed");
        clear_result;

        // Endpoint failure is a completed failure and may be cleared explicitly.
        scan(frame(1,7'h7f,0),64,-1,rx);poll_done(rx);
        if(rx[1:0]!=2 || rx[43])$fatal(1,"endpoint failure status");
        clear_result;

        // Short/overlong/invalid-signature/version/reserved frames do no DMI work.
        before_count=request_count;
        scan_empty;idle(8);scan(frame(0,0,0),64,-1,rx);
        if(!rx[43])$fatal(1,"zero-bit frame accepted");clear_result;
        scan(frame(2,7'h22,32'h11223344),63,-1,rx);idle(8);
        scan(frame(0,0,0),64,-1,rx);if(!rx[43])$fatal(1,"short frame accepted");clear_result;
        scan(frame(2,7'h22,32'h11223344),65,-1,rx);idle(8);
        scan(frame(0,0,0),64,-1,rx);if(!rx[43])$fatal(1,"long frame accepted");clear_result;
        // 192 ends with the same frame and would wrap a broken 7-bit count to64.
        scan(frame(2,7'h22,32'h11223344),192,-1,rx);idle(8);
        scan(frame(0,0,0),64,-1,rx);if(!rx[43])$fatal(1,"scan length counter wrapped");clear_result;
        tx=frame(2,7'h22,32'h11223344);tx[63]=~tx[63];
        scan(tx,64,-1,rx);idle(8);scan(frame(0,0,0),64,-1,rx);
        if(!rx[43])$fatal(1,"bad signature accepted");clear_result;
        tx=frame(2,7'h22,32'h11223344);tx[44]=0;
        scan(tx,64,-1,rx);idle(8);scan(frame(0,0,0),64,-1,rx);
        if(!rx[43])$fatal(1,"bad version accepted");clear_result;
        tx=frame(2,7'h22,32'h11223344);tx[41]=1;
        scan(tx,64,-1,rx);idle(8);scan(frame(0,0,0),64,-1,rx);
        if(!rx[43] || request_count!=before_count)$fatal(1,"malformed frame side effect");clear_result;

        // Soft reset clears both event domains; never replay the held frame.
        endpoint_enable=0;scan(frame(1,7'h11,0),64,-1,rx);idle(12);
        scan(frame(3,2,0),64,-1,rx);idle(12);endpoint_enable=1;
        before_count=request_count;scan(frame(0,0,0),64,-1,rx);idle(12);
        if(rx[43:41]!=0 || request_count!=before_count)$fatal(1,"soft reset replay");
        // External reset asserts with both BSCAN clocks stopped.
        req_ready=0;scan(frame(1,7'h11,0),64,-1,rx);idle(12);
        por_n=0;#2;
        if(req_valid || rsp_ready || dmi_reset_n)$fatal(1,"asynchronous reset isolation");
        por_n=1;req_ready=1;idle(12);before_count=request_count;
        scan(frame(0,0,0),64,-1,rx);idle(12);
        if(rx[43:41]!=0 || request_count!=before_count)$fatal(1,"POR replay");
        $display("PASS BSCAN_USER capability write read zero_idle pause deselect stopped_tck backpressure overlap malformed endpoint_error soft_reset por_no_replay");
        $finish;
    end
    initial begin #1000000;$fatal(1,"BSCAN test timeout");end
endmodule
