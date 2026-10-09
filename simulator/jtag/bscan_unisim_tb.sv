`timescale 1ns/1ps
// Real installed JTAG_SIME2 + BSCANE2 models. No behavioral vendor replacements.
// MODEL_* are SIMULATION encodings, explicitly profiled from this installation.
// They must never overwrite the physical BSDL/SMT2 IR12/USER2=0x903 profile.
module bscan_unisim_tb #(
    parameter integer MODEL_IR_LENGTH=0, MODEL_USER1=0, MODEL_USER2=0,
    parameter integer SYS_HALF=7, TCK_LOW=19, TCK_HIGH=23, START_PHASE=3,
    parameter integer BAD_EXPECTED=0
);
    reg tck=0, tms=1, tdi=0, clk=0, por_n=0;
    wire tdo, link, req_valid, req_ready, rsp_ready;
    wire [1:0] req_op;
    wire [6:0] req_address;
    wire [31:0] req_data;
    reg rsp_valid=0;
    reg [31:0] rsp_data=0;
    reg [1:0] rsp_status=0;
    reg permit=1, complete=1, pending=0;
    integer accepted=0, updates=0, captures=0, shifted=0;
    reg [31:0] memory[0:127];
    wire other_sel;
    JTAG_SIME2 #(.PART_NAME("XCZU15EG")) tap(.TCK(tck),.TMS(tms),.TDI(tdi),.TDO(tdo));
    // Represents a separate USER1 consumer, NOT an emulation of dbg_hub itself.
    BSCANE2 #(.JTAG_CHAIN(1)) other_user(.CAPTURE(),.DRCK(),.RESET(),.RUNTEST(),
        .SEL(other_sel),.SHIFT(),.TCK(),.TDI(),.TMS(),.UPDATE(),.TDO(1'b1));
    ValenceBscanDebugPort #(.ENABLE(1),.JTAG_CHAIN(2)) dut(
        .debug_clk(clk),.debug_por_n(por_n),.dmi_reset_n(link),
        .dmi_req_valid(req_valid),.dmi_req_ready(req_ready),.dmi_req_op(req_op),
        .dmi_req_address(req_address),.dmi_req_data(req_data),
        .dmi_rsp_valid(rsp_valid),.dmi_rsp_ready(rsp_ready),
        .dmi_rsp_status(rsp_status),.dmi_rsp_data(rsp_data));
    assign req_ready=permit && !pending && !rsp_valid;
    initial begin #(START_PHASE); forever #(SYS_HALF) clk=~clk; end
    // Explicitly a transport endpoint model. Real bus-owner drain is a separate
    // loader_cdc_drain_tb with the generated production endpoint RTL.
    always @(posedge clk or negedge link) begin
        if(!link) begin pending<=0; rsp_valid<=0; rsp_status<=0; rsp_data<=0; end
        else begin
            if(req_valid && req_ready) begin
                accepted=accepted+1;
                pending<=1;
                rsp_status<=req_address==7'h7f ? 2 : 0;
                rsp_data<=memory[req_address];
                if(req_op==2 && req_address!=7'h7f) memory[req_address]<=req_data;
            end
            if(pending && complete) begin pending<=0; rsp_valid<=1; end
            if(rsp_valid && rsp_ready) rsp_valid<=0;
        end
    end
    reg monitor_on=0;
    integer expected_count=0;
    reg [63:0] expected_frame=0;
    always @(posedge dut.enabled.drck) if(monitor_on && dut.enabled.sel) begin
        if(dut.enabled.capture) captures=captures+1;
        if(dut.enabled.shift) shifted=shifted+1;
    end
    always @(posedge dut.enabled.update) if(monitor_on && dut.enabled.sel) begin
        updates=updates+1;
        #0.050;
        if(dut.enabled.transport.shift_count !== (expected_count>65 ? 65 : expected_count))
            $fatal(1,"UNISIM_DRCK_UPDATE_PHASE_ORACLE count");
        if(expected_count==64 && dut.enabled.transport.update_frame !== expected_frame)
            $fatal(1,"UNISIM_DRCK_UPDATE_PHASE_ORACLE held frame");
    end
    function [63:0] frame(input [1:0] op,input [6:0] address,input [31:0] data);
        frame={16'h5642,4'h1,3'b0,address,data,op};
    endfunction
    task tick(input logic ms,input logic di,output logic sampled);
        begin tms=ms;tdi=di;#(TCK_LOW);sampled=tdo;tck=1;#(TCK_HIGH);tck=0;#2;end
    endtask
    logic ignored;
    task step(input logic ms); tick(ms,0,ignored); endtask
    task idle(input integer n);
        integer k; begin for(k=0;k<n;k=k+1)step(0); end
    endtask
    task ir(input integer opcode);
        integer k; begin
            monitor_on=0;
            step(1);step(1);step(0);step(0);
            for(k=0;k<MODEL_IR_LENGTH;k=k+1)tick(k==MODEL_IR_LENGTH-1,(opcode>>k)&1,ignored);
            step(1);step(0);idle(4);
            monitor_on=1;
        end
    endtask
    task scan(input [63:0] value,input integer count,input integer pause_at,output reg [63:0] result);
        integer k;logic sampled;
        begin
            expected_count=count;expected_frame=value;result=0;
            step(1);step(0);step(0);
            for(k=0;k<count;k=k+1)begin
                tick(k==count-1 || k==pause_at,value[k%64],sampled);
                if(k<64)result[k]=sampled;
                if(k==pause_at && k!=count-1)begin step(0);idle(3);step(1);step(0);end
            end
            step(1); // UPDATE event, deliberately no RTI wait.
        end
    endtask
    task poll(output reg [63:0] result);
        integer k; begin
            result=0;
            for(k=0;k<100 && (!result[41] || result[42]);k=k+1)begin
                idle(8);scan(frame(0,0,0),64,-1,result);
                if(result[63:48]!==16'h5642 || result[47:44]!==1)
                    $fatal(1,"UNISIM_USER2_SELECTION_ORACLE frame header");
            end
            if(!result[41] || result[42])$fatal(1,"UNISIM completion timeout");
        end
    endtask
    task clear_error;
        reg [63:0] value;begin
            idle(8);scan(frame(3,1,0),64,-1,value);idle(8);
            scan(frame(0,0,0),64,-1,value);
            if(value[43:41]!==0)$fatal(1,"UNISIM error clear failed");
        end
    endtask
    reg [63:0] rx;
    integer i,old_count;
    initial begin
        for(i=0;i<128;i=i+1)memory[i]=32'ha5000000+i;
        #1000;
        if(MODEL_IR_LENGTH<1 || MODEL_IR_LENGTH>32 || MODEL_IR_LENGTH!=tap.IRLength ||
           MODEL_USER1!=(tap.USER1_INSTR>>(tap.IRLengthMax-tap.IRLength)) ||
           MODEL_USER2!=(tap.USER2_INSTR>>(tap.IRLengthMax-tap.IRLength)))
            $fatal(1,"UNISIM_PROFILE_MISMATCH inspect installed model; do not modify physical BSDL config");
        if((tap.IDCODEval_sig & 32'h0fffffff)!==32'h04750093)$fatal(1,"UNISIM wrong part model");
        por_n=1;repeat(6)step(1);idle(12);ir(MODEL_USER2);idle(12);
        if(dut.enabled.sel!==1 || other_sel!==0)$fatal(1,"UNISIM_USER2_SELECTION_ORACLE SEL");
        scan(frame(3,0,0),64,-1,rx);poll(rx);
        if(rx[33:2]!==32'h701 || rx[1:0]!==0 || accepted!=0)$fatal(1,"UNISIM capability oracle");
        scan(frame(2,7'h25,32'h89abcdef),64,17,rx);
        scan(frame(0,0,0),64,-1,rx);
        if(!rx[42] && rx[41])$fatal(1,"UNISIM stale DONE on immediate capture");
        poll(rx);scan(frame(1,7'h25,0),64,-1,rx);poll(rx);
        if(rx[33:2] !== (32'h89abcdef ^ BAD_EXPECTED) || rx[1:0]!==0 || accepted!=2)
            $fatal(1,"UNISIM_READBACK_ORACLE");
        old_count=accepted;ir(MODEL_USER1);
        if(other_sel!==1 || dut.enabled.sel!==0)$fatal(1,"UNISIM USER1 selection");
        scan(frame(2,7'h26,32'hffffffff),64,-1,rx);idle(12);
        if(accepted!=old_count || memory[7'h26]!==32'ha5000026)$fatal(1,"UNISIM USER isolation");
        ir(MODEL_USER2);
        old_count=accepted;scan(frame(1,7'h25,0),64,-1,rx);#1000;
        if(accepted!=old_count)$fatal(1,"UNISIM stopped TCK accepted early");
        poll(rx);if(accepted!=old_count+1)$fatal(1,"UNISIM stopped TCK replay");
        clear_error;permit=0;scan(frame(1,7'h12,0),64,-1,rx);idle(12);
        scan(frame(0,0,0),64,-1,rx);
        if(!rx[42] || rx[43] || !req_valid || req_address!==7'h12)$fatal(1,"UNISIM held request");
        permit=1;poll(rx);
        clear_error;scan(frame(2,7'h22,32'h1234),63,-1,rx);idle(8);
        scan(frame(0,0,0),64,-1,rx);if(!rx[43])$fatal(1,"UNISIM short scan accepted");
        clear_error;scan(frame(2,7'h22,32'h1234),65,-1,rx);idle(8);
        scan(frame(0,0,0),64,-1,rx);if(!rx[43])$fatal(1,"UNISIM long scan accepted");
        clear_error;scan(frame(1,7'h7f,0),64,-1,rx);poll(rx);
        if(rx[1:0]!==2 || rx[43])$fatal(1,"UNISIM endpoint failure");
        clear_error;permit=0;scan(frame(1,7'h11,0),64,-1,rx);idle(12);
        // Assert cold transport reset with TCK stopped, then prove no replay.
        por_n=0;#100;if(link || req_valid || rsp_ready)$fatal(1,"UNISIM stopped-TCK reset isolation");
        old_count=accepted;por_n=1;permit=1;idle(16);
        scan(frame(0,0,0),64,-1,rx);idle(12);
        if(rx[43:41]!==0 || accepted!=old_count)$fatal(1,"UNISIM reset replay");
        // TAP reset also cancels transport; it is not a fabric bus reset.
        monitor_on=0;repeat(6)step(1);idle(16);ir(MODEL_USER2);
        scan(frame(3,0,0),64,-1,rx);poll(rx);
        if(rx[33:2]!==32'h701 || updates<10 || captures<10 || shifted<640)
            $fatal(1,"UNISIM phase coverage incomplete");
        $display("BSCAN_UNISIM_PASS ir=%0d user2=%h requests=%0d updates=%0d captures=%0d shifts=%0d sys_half=%0d tck=%0d/%0d",
            MODEL_IR_LENGTH,MODEL_USER2,accepted,updates,captures,shifted,SYS_HALF,TCK_LOW,TCK_HIGH);
        $finish;
    end
    initial begin #10000000;$fatal(1,"UNISIM global watchdog");end
endmodule
