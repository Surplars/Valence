// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
// Actual installed JTAG_SIME2/BSCANE2 plus a separate IEEE1149.1 DAP TAP.
// DAP model covers IDCODE/IR/BYPASS only, NOT ARM debugging or the FPGA TAP.
module i1_dap_bypass_tap(input wire tck, tms, tdi, output reg tdo=0);
    localparam [3:0] TLR=0, IDLE=1, SDR=2, CDR=3, SHDR=4, E1DR=5, PDR=6,
        E2DR=7, UDR=8, SIR=9, CIR=10, SHIR=11, E1IR=12, PIR=13, E2IR=14, UIR=15;
    reg [3:0] state=TLR, next_state, instruction=4'he, ir_shift=0;
    reg bypass=0;
    reg [31:0] id_shift=0;
    always @* case(state)
        TLR:next_state=tms?TLR:IDLE;
        IDLE:next_state=tms?SDR:IDLE;
        SDR:next_state=tms?SIR:CDR;
        CDR:next_state=tms?E1DR:SHDR;
        SHDR:next_state=tms?E1DR:SHDR;
        E1DR:next_state=tms?UDR:PDR;
        PDR:next_state=tms?E2DR:PDR;
        E2DR:next_state=tms?UDR:SHDR;
        UDR:next_state=tms?SDR:IDLE;
        SIR:next_state=tms?TLR:CIR;
        CIR:next_state=tms?E1IR:SHIR;
        SHIR:next_state=tms?E1IR:SHIR;
        E1IR:next_state=tms?UIR:PIR;
        PIR:next_state=tms?E2IR:PIR;
        E2IR:next_state=tms?UIR:SHIR;
        UIR:next_state=tms?SDR:IDLE;
        default:next_state=TLR;
    endcase
    always @(posedge tck) begin
        state<=next_state;
        case(state)
            TLR:instruction<=4'he;
            CIR:ir_shift<=4'b0001;
            SHIR:ir_shift<={tdi,ir_shift[3:1]};
            UIR:instruction<=ir_shift;
            CDR:begin bypass<=0;id_shift<=32'h5ba00477;end
            SHDR:if(instruction==4'hf)bypass<=tdi;
                  else id_shift<={tdi,id_shift[31:1]};
        endcase
    end
    always @(negedge tck)
        if(state==SHIR)tdo<=ir_shift[0];
        else if(state==SHDR)tdo<=instruction==4'hf ? bypass : id_shift[0];
        else tdo<=0;
endmodule

module i1_dual_tap_tb #(
    parameter integer WITH_DAP=1, DAP_UPSTREAM=1, DUT_SCAN_BITS=65,
    parameter integer LEGACY_DUT=0, BAD_EXPECTED=0,
    parameter integer SYS_HALF_PS=1667, START_PHASE_PS=333,
    parameter integer TCK_LOW=19, TCK_HIGH=23
);
    localparam integer FRAME_BITS=64+WITH_DAP;
    localparam integer OFFSET=WITH_DAP && !DAP_UPSTREAM ? 1 : 0;
    reg tck=0,tms=1,tdi=0,clk=0,por_n=0;
    wire fpga_tdo,dap_tdo,host_tdo,link,req_valid,req_ready,rsp_ready;
    wire [1:0] req_op;
    wire [6:0] req_address;
    wire [31:0] req_data;
    reg permit=1,pending=0,rsp_valid=0;
    reg [31:0] rsp_data=0,memory[0:127];
    reg [1:0] rsp_status=0;
    integer accepted=0,write_count=0,read_count=0,scans=0,rejected=0;
    wire [63:0] held_frame;
    wire [7:0] counted_bits;
    JTAG_SIME2 #(.PART_NAME("XCZU15EG")) fpga(
        .TCK(tck),.TMS(tms),.TDI(WITH_DAP && DAP_UPSTREAM?dap_tdo:tdi),.TDO(fpga_tdo));
    i1_dap_bypass_tap dap(.tck(tck),.tms(tms),
        .tdi(DAP_UPSTREAM?tdi:fpga_tdo),.tdo(dap_tdo));
    assign host_tdo=WITH_DAP && !DAP_UPSTREAM?dap_tdo:fpga_tdo;
    generate if(LEGACY_DUT) begin: legacy
        ValenceI1BscanDebugPort #(.ENABLE(1),.JTAG_CHAIN(2)) dut(
            .debug_clk(clk),.debug_por_n(por_n),.dmi_reset_n(link),
            .dmi_req_valid(req_valid),.dmi_req_ready(req_ready),.dmi_req_op(req_op),
            .dmi_req_address(req_address),.dmi_req_data(req_data),
            .dmi_rsp_valid(rsp_valid),.dmi_rsp_ready(rsp_ready),
            .dmi_rsp_status(rsp_status),.dmi_rsp_data(rsp_data));
        assign held_frame=dut.enabled.transport.update_frame;
        assign counted_bits=dut.enabled.transport.shift_count;
    end else begin: fixed_dut
        ValenceI1BscanDebugPort #(.ENABLE(1),.JTAG_CHAIN(2),.SCAN_BITS(DUT_SCAN_BITS)) dut(
            .debug_clk(clk),.debug_por_n(por_n),.dmi_reset_n(link),
            .dmi_req_valid(req_valid),.dmi_req_ready(req_ready),.dmi_req_op(req_op),
            .dmi_req_address(req_address),.dmi_req_data(req_data),
            .dmi_rsp_valid(rsp_valid),.dmi_rsp_ready(rsp_ready),
            .dmi_rsp_status(rsp_status),.dmi_rsp_data(rsp_data));
        assign held_frame=dut.enabled.transport.update_frame;
        assign counted_bits=dut.enabled.transport.shift_count;
    end endgenerate
    assign req_ready=permit && !pending && !rsp_valid;
    initial begin #(START_PHASE_PS*0.001);forever #(SYS_HALF_PS*0.001)clk=~clk;end
    always @(posedge clk or negedge link) begin
        if(!link)begin pending<=0;rsp_valid<=0;rsp_data<=0;rsp_status<=0;end
        else begin
            if(req_valid && req_ready)begin
                accepted=accepted+1;pending<=1;rsp_data<=memory[req_address];rsp_status<=0;
                if(req_op==2)begin memory[req_address]<=req_data;write_count=write_count+1;end
                else if(req_op==1)read_count=read_count+1;
                else $fatal(1,"CHAIN_DMI_OPCODE_ORACLE");
            end
            if(pending)begin pending<=0;rsp_valid<=1;end
            if(rsp_valid && rsp_ready)rsp_valid<=0;
        end
    end
    function [63:0] frame(input [1:0] op,input [6:0] address,input [31:0] value);
        frame={16'h5642,4'h1,3'b0,address,value,op};
    endfunction
    task tick(input logic ms,di,output logic sampled);
        begin tms=ms;tdi=di;#(TCK_LOW);sampled=host_tdo;tck=1;#(TCK_HIGH);tck=0;#2;end
    endtask
    logic ignored;
    task step(input logic ms);tick(ms,0,ignored);endtask
    task idle(input integer n);
        integer k;begin for(k=0;k<n;k=k+1)step(0);end
    endtask
    task ir;
        reg [15:0] bits;integer k,width;
        begin
            // Installed model opcode0x0e4 is simulation-only; physical BSDL
            // USER2 remains0x903. The DAP's four IR bits are shifted in series.
            width=12+(WITH_DAP?4:0);
            bits=!WITH_DAP?16'h0e4:DAP_UPSTREAM?16'hf0e4:16'h0e4f;
            step(1);step(1);step(0);step(0);
            for(k=0;k<width;k=k+1)tick(k==width-1,bits[k],ignored);
            step(1);step(0);idle(16);
            if(WITH_DAP && dap.instruction!==4'hf)$fatal(1,"CHAIN_DAP_IR_ORACLE");
            if(fpga.IRcontent_sig!==12'h0e4)$fatal(1,"CHAIN_FPGA_IR_ORACLE");
        end
    endtask
    task raw_scan(input [255:0] bits,input integer count,pause_at,output reg [255:0] reply);
        integer k;logic sampled;
        begin
            reply=0;scans=scans+1;step(1);step(0);
            if(count==0)begin step(1);step(1);step(0);end
            else begin
                step(0);
                for(k=0;k<count;k=k+1)begin
                    tick(k==count-1 || k==pause_at,bits[k],sampled);reply[k]=sampled;
                    if(k==pause_at && k!=count-1)begin
                        step(0);repeat(3)step(0);step(1);step(0);
                    end
                end
                step(1);step(0);
            end
        end
    endtask
    task scan(input [63:0] value,input integer count,pause_at,output reg [63:0] reply);
        reg [255:0] bits,rx;integer padding;
        begin
            // For malformed lengths >=65, preserve the exact final USER frame
            // too: rejection must be LENGTH-based, not accidental bad magic.
            padding=count-64-(WITH_DAP && DAP_UPSTREAM?1:0);
            bits={192'b0,value};
            if(padding>=0)bits=bits<<padding;
            raw_scan(bits,count,pause_at,rx);reply=rx>>OFFSET;
            if(count>=FRAME_BITS && held_frame!==value)
                $fatal(1,"CHAIN_INPUT_ALIGNMENT_ORACLE count=%0d held=%h wanted=%h",count,held_frame,value);
        end
    endtask
    task poll(output reg [63:0] rx);
        integer k;begin
            rx=0;
            for(k=0;k<100 && (!rx[41] || rx[42]);k=k+1)begin
                idle(8);scan(frame(0,0,0),FRAME_BITS,-1,rx);
                if(rx[63:48]!==16'h5642 || rx[47:44]!==1)$fatal(1,"CHAIN_REPLY_ALIGNMENT_ORACLE");
                if(rx[43])$fatal(1,"CHAIN_CAPABILITY_ORACLE protocol error at valid length=%0d",FRAME_BITS);
            end
            if(!rx[41] || rx[42])$fatal(1,"CHAIN_COMPLETION_ORACLE");
        end
    endtask
    task clear_error;
        reg [63:0] rx;begin
            idle(10);scan(frame(3,1,0),FRAME_BITS,-1,rx);idle(10);
            scan(frame(0,0,0),FRAME_BITS,-1,rx);
            if(rx[43:41]!==0)$fatal(1,"CHAIN_CLEAR_ERROR_ORACLE");
        end
    endtask
    reg [63:0] rx;
    reg [255:0] id_rx;
    reg [31:0] pattern;
    integer i,old_count,n;
    initial begin
        for(i=0;i<128;i=i+1)memory[i]=32'ha5000000+i;
        #1000;
        // Independently pinned installed-model identity. Never use this profile
        // to configure physical OpenOCD or relax physical expected-ID checks.
        if(fpga.IRLength!==12 || fpga.IDCODEval_sig!==32'h04a52093 ||
           (fpga.USER2_INSTR>>(fpga.IRLengthMax-fpga.IRLength))!==12'h0e4)
            $fatal(1,"CHAIN_INSTALLED_MODEL_PROFILE_ORACLE");
        por_n=1;repeat(6)step(1);idle(20);
        raw_scan(0,WITH_DAP?64:32,-1,id_rx);
        if(!WITH_DAP && id_rx[31:0]!==32'h04a52093)$fatal(1,"CHAIN_IDCODE_ORACLE");
        if(WITH_DAP && DAP_UPSTREAM &&
            id_rx[63:0]!==64'h5ba0047704a52093)$fatal(1,"CHAIN_IDCODE_ORACLE upstream %h",id_rx);
        if(WITH_DAP && !DAP_UPSTREAM &&
            id_rx[63:0]!==64'h04a520935ba00477)$fatal(1,"CHAIN_IDCODE_ORACLE downstream %h",id_rx);
        ir;
        scan(frame(3,0,0),FRAME_BITS,-1,rx);poll(rx);
        if(rx[33:2]!==32'h701 || accepted!=0)$fatal(1,"CHAIN_CAPABILITY_ORACLE bad value");
        for(i=0;i<24;i=i+1)begin
            pattern=32'h9e3779b9*(i+1) ^ (32'h1<<(i%32));
            scan(frame(2,7'h20+i,pattern),FRAME_BITS,i==0?17:-1,rx);poll(rx);
            scan(frame(1,7'h20+i,0),FRAME_BITS,-1,rx);poll(rx);
            if(rx[33:2] !== (pattern ^ BAD_EXPECTED) || rx[40:34]!==7'h20+i || rx[1:0]!==0)
                $fatal(1,"CHAIN_READBACK_ORACLE");
        end
        if(accepted!=48 || write_count!=24 || read_count!=24)$fatal(1,"CHAIN_EXACT_ONCE_ORACLE");
        clear_error;permit=0;old_count=accepted;
        scan(frame(1,7'h20,0),FRAME_BITS,-1,rx);idle(12);
        scan(frame(0,0,0),FRAME_BITS,-1,rx);
        if(!rx[42] || rx[43] || accepted!=old_count || !req_valid)
            $fatal(1,"CHAIN_BACKPRESSURE_ORACLE");
        permit=1;poll(rx);
        if(accepted!=old_count+1)$fatal(1,"CHAIN_BACKPRESSURE_REPLAY_ORACLE");
        for(i=0;i<10;i=i+1)begin
            case(i)0:n=0;1:n=1;2:n=63;3:n=64;4:n=65;5:n=66;
                6:n=67;7:n=127;8:n=128;9:n=255;endcase
            if(n!=FRAME_BITS)begin
                clear_error;old_count=accepted;
                scan(frame(2,7'h10,32'hdeadbeef),n,-1,rx);idle(12);
                if(n>DUT_SCAN_BITS && counted_bits!==DUT_SCAN_BITS+1)
                    $fatal(1,"CHAIN_COUNT_SATURATION_ORACLE");
                scan(frame(0,0,0),FRAME_BITS,-1,rx);
                if(!rx[43] || accepted!=old_count || memory[7'h10]!==32'ha5000010)
                    $fatal(1,"CHAIN_LONG_REJECTION_ORACLE count=%0d",n);
                rejected=rejected+1;
            end
        end
        clear_error;
        // Valid length is insufficient: signature/version/reserved bits remain mandatory.
        for(i=0;i<3;i=i+1)begin
            old_count=accepted;
            scan(frame(2,7'h10,1) ^ (64'h1<<(i==0?48:i==1?44:41)),FRAME_BITS,-1,rx);
            idle(10);scan(frame(0,0,0),FRAME_BITS,-1,rx);
            if(!rx[43] || accepted!=old_count)$fatal(1,"CHAIN_HEADER_REJECTION_ORACLE");
            clear_error;
        end
        // Stopped destination/transport reset cancels an unaccepted request.
        permit=0;old_count=accepted;scan(frame(1,7'h20,0),FRAME_BITS,-1,rx);idle(8);
        por_n=0;#100;
        if(link || req_valid)$fatal(1,"CHAIN_RESET_ISOLATION_ORACLE");
        por_n=1;permit=1;idle(20);
        scan(frame(3,0,0),FRAME_BITS,-1,rx);poll(rx);
        if(accepted!=old_count)$fatal(1,"CHAIN_RESET_REPLAY_ORACLE");
        if(rejected!=9)$fatal(1,"CHAIN_COVERAGE_ORACLE rejected=%0d",rejected);
        $display("PASS I1_DUAL_TAP actual_rtl=1 vendor_fpga=1 dap=%0d upstream=%0d accepted_bits=%0d rejected66=%0d rejected_total=%0d reads=%0d writes=%0d scans=%0d",
            WITH_DAP,DAP_UPSTREAM,DUT_SCAN_BITS,FRAME_BITS!=66,rejected,read_count,write_count,scans);
        $finish;
    end
    initial begin #10000000;$fatal(1,"CHAIN_WATCHDOG");end
endmodule

