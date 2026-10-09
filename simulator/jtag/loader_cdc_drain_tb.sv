`timescale 1ns/1ps
// Production endpoint RTL + real DMI mailbox, independent clocks. No CPU/DDR.
module loader_cdc_drain_tb #(
    parameter integer SYS_HALF=7, TCK_HALF=11, BAD_RESET_OWNER=0
);
    reg clk=0,tck=0,reset=1,por_n=0;
    always #(SYS_HALF)clk=~clk;
    always #(TCK_HALF)tck=~tck;
    reg source_valid=0,source_rsp_ready=0;
    reg [40:0] source_data=0;
    wire source_ready,source_rsp_valid,busy,link,req_valid,req_ready,rsp_valid,rsp_ready;
    wire [40:0] req_data;
    wire [33:0] source_rsp;
    wire [31:0] rsp_data;
    wire [1:0] rsp_status;
    ValenceDmiCdc bridge(.tck(tck),.debug_clk(clk),.reset_n(por_n),
        .s_req_valid(source_valid),.s_req_ready(source_ready),.s_req_payload(source_data),
        .s_rsp_valid(source_rsp_valid),.s_rsp_payload(source_rsp),.s_rsp_ready(source_rsp_ready),.s_busy(busy),
        .dmi_reset_n(link),.d_req_valid(req_valid),.d_req_ready(req_ready),.d_req_payload(req_data),
        .d_rsp_valid(rsp_valid),.d_rsp_ready(rsp_ready),.d_rsp_payload({rsp_data,rsp_status}));
    reg cv=0,cwrite=0,crready=0;
    reg [63:0] ca=0,cd=0;
    wire cqready,crvalid,crerror;
    wire [63:0] crdata;
    reg mqready=0,mrvalid=0,mrerror=0;
    wire mqvalid,mwrite,mrready;
    wire [63:0] ma,md;
    wire [2:0] msize;
    wire [7:0] mbytes;
    integer requests=0;
    always @(posedge clk)if(!reset && mqvalid && mqready)requests=requests+1;
    JtagRamLoader loader(.clock(clk),.reset(reset || (BAD_RESET_OWNER && !link)),
        .io_linkUp(link),.io_dmi_request_valid(req_valid),.io_dmi_request_ready(req_ready),
        .io_dmi_request_bits_op(req_data[1:0]),.io_dmi_request_bits_address(req_data[40:34]),
        .io_dmi_request_bits_data(req_data[33:2]),.io_dmi_response_valid(rsp_valid),
        .io_dmi_response_ready(rsp_ready),.io_dmi_response_bits_data(rsp_data),.io_dmi_response_bits_status(rsp_status),
        .io_control_request_valid(cv),.io_control_request_ready(cqready),.io_control_request_bits_address(ca),
        .io_control_request_bits_write(cwrite),.io_control_request_bits_size(3'd3),
        .io_control_request_bits_data(cd),.io_control_request_bits_byteEnable(8'hff),
        .io_control_response_valid(crvalid),.io_control_response_ready(crready),
        .io_control_response_bits_data(crdata),.io_control_response_bits_error(crerror),
        .io_memory_request_valid(mqvalid),.io_memory_request_ready(mqready),
        .io_memory_request_bits_address(ma),.io_memory_request_bits_write(mwrite),
        .io_memory_request_bits_size(msize),.io_memory_request_bits_data(md),.io_memory_request_bits_byteEnable(mbytes),
        .io_memory_response_valid(mrvalid),.io_memory_response_ready(mrready),
        .io_memory_response_bits_data(64'h12345678),.io_memory_response_bits_error(mrerror));
    task cpu(input integer offset,input logic write,input [63:0] value,input logic expected_error,
             output reg [63:0] response);
        begin
            @(negedge clk);ca=64'h10003000+offset;cwrite=write;cd=value;cv=1;
            while(!cqready)@(negedge clk);
            @(posedge clk);#1;@(negedge clk);cv=0;
            wait(crvalid);#1;
            if(crerror!==expected_error)$fatal(1,"CPU control error mismatch");
            response=crdata;crready=1;@(posedge clk);#1;@(negedge clk);crready=0;
        end
    endtask
    task dmi(input [1:0] op,input [6:0] address,input [31:0] value,output reg [31:0] response);
        begin
            @(posedge tck);while(!source_ready)@(posedge tck);
            source_data={address,value,op};source_valid=1;
            @(negedge tck);#1;@(posedge tck);source_valid=0;
            wait(source_rsp_valid);@(posedge tck);
            if(source_rsp[1:0]!==0)$fatal(1,"CDC DMI failure");
            response=source_rsp[33:2];source_rsp_ready=1;
            @(negedge tck);#1;@(posedge tck);source_rsp_ready=0;
        end
    endtask
    reg [31:0] ignored32;
    reg [63:0] status;
    task open_session(input logic error);
        cpu(8,1,1,error,status);
    endtask
    task start_write;
        begin dmi(2,7'h39,32'h80200004,ignored32);dmi(2,7'h3c,32'h89abcdef,ignored32);end
    endtask
    task drain(input logic error);
        begin
            @(negedge clk);mrerror=error;mrvalid=1;
            if(!mrready)$fatal(1,"DRAIN_OWNER_ORACLE late reply owner lost");
            @(posedge clk);#1;@(negedge clk);mrvalid=0;mrerror=0;
        end
    endtask
    integer i,old_requests;
    initial begin
        repeat(4)@(negedge clk);reset=0;por_n=1;wait(link);repeat(8)@(negedge tck);
        open_session(0);start_write;wait(mqvalid);
        // Offered-but-stalled ownership survives link reset, including payload.
        por_n=0;repeat(3)@(negedge clk);
        for(i=0;i<12;i=i+1)begin
            if(!mqvalid || ma!==64'h80200004 || md!==64'h89abcdef || !mwrite || msize!==2 || mbytes!==15)
                $fatal(1,"DRAIN_OWNER_ORACLE stalled request withdrawn/changed");
            @(negedge clk);
        end
        open_session(1);por_n=1;wait(link);open_session(1);
        @(negedge clk);mqready=1;@(posedge clk);#1;@(negedge clk);mqready=0;
        drain(0);cpu(0,0,0,0,status);
        if(status[3] || status[0] || requests!=1)$fatal(1,"late drain count/status");
        open_session(0);
        // Accepted timeout cannot release the owner or admit OPEN/new traffic.
        mqready=1;start_write;@(negedge clk);mqready=0;
        repeat(100)@(negedge clk);cpu(0,0,0,0,status);
        if(!status[3] || !status[4] || status[0])$fatal(1,"timeout did not retain BUSY/fault");
        open_session(1);old_requests=requests;por_n=0;repeat(12)@(negedge clk);
        if(!mrready || requests!=old_requests)$fatal(1,"DRAIN_OWNER_ORACLE accepted owner lost");
        por_n=1;wait(link);repeat(12)@(negedge tck);
        if(requests!=old_requests)$fatal(1,"stale CDC request replay");
        open_session(1);drain(0);open_session(0);
        mqready=1;start_write;@(negedge clk);mqready=0;drain(1);
        cpu(0,0,0,0,status);
        if(status[3] || !status[4] || status[0])$fatal(1,"bus error did not fail closed");
        open_session(0);old_requests=requests;
        dmi(2,7'h39,32'h10000000,ignored32);dmi(2,7'h3c,32'hdeadbeef,ignored32);
        dmi(1,7'h38,0,ignored32);
        if(ignored32[14:12]!==2 || requests!=old_requests)$fatal(1,"MMIO whitelist admission");
        $display("LOADER_CDC_DRAIN_PASS requests=%0d offered_reset accepted_timeout late_drain error mmio_reject sys_half=%0d tck_half=%0d",
            requests,SYS_HALF,TCK_HALF);
        $finish;
    end
    initial begin #1000000;$fatal(1,"loader CDC drain watchdog");end
endmodule
