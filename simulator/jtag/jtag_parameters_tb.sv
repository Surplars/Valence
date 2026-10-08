`timescale 1ns/1ps
module jtag_parameters_tb #(parameter integer ABITS=1);
    reg tck=0,tms=1,tdi=0,trst_n=0,por_n=0,clk=0;
    wire tdo,oe;
    reg sample;
    reg [ABITS+33:0] scan_value,scan_result;
    reg [4:0] ir_capture;
    integer i;
    ValenceJtagDebugPort #(.ENABLE(1),.ABITS(ABITS),.IDCODE(32'h12345001),.IDLE_HINT(3)) dut (
        .tck(tck),.tms(tms),.tdi(tdi),.trst_n(trst_n),.debug_clk(clk),.debug_por_n(por_n),
        .tdo(tdo),.tdo_oe(oe),.dmi_reset_n(),.dmi_req_valid(),.dmi_req_ready(1'b0),
        .dmi_req_op(),.dmi_req_address(),.dmi_req_data(),.dmi_rsp_valid(1'b0),.dmi_rsp_ready(),
        .dmi_rsp_status(2'b00),.dmi_rsp_data(32'b0));
    always #7 clk=~clk;
    task tick(input bit tm,input bit td,output bit result);
        begin tms=tm;tdi=td;#19;result=tdo;tck=1;#19;tck=0;#1;end
    endtask
    task ir(input [4:0] value);
        integer k; begin
            tick(1,0,sample);tick(1,0,sample);tick(0,0,sample);tick(0,0,sample);
            for(k=0;k<5;k=k+1) tick(k==4,value[k],ir_capture[k]);
            tick(1,0,sample);tick(0,0,sample);
            if(ir_capture!==1)$fatal(1,"parameter IR capture");
        end
    endtask
    task scan(input integer n);
        integer k; begin
            scan_result=0;tick(1,0,sample);tick(0,0,sample);tick(0,0,sample);
            for(k=0;k<n;k=k+1)tick(k==n-1,scan_value[k],scan_result[k]);
            tick(1,0,sample);tick(0,0,sample);
        end
    endtask
    initial begin
        #2;por_n=1;trst_n=1;
        for(i=0;i<5;i=i+1)tick(1,0,sample);
        for(i=0;i<9;i=i+1)tick(0,0,sample);
        scan_value=0;scan(32);if(scan_result[31:0]!==32'h12345001)$fatal(1,"parameter IDCODE");
        ir(16);scan(32);
        if(scan_result[31:0] !== (32'h3001 | (ABITS<<4)))$fatal(1,"parameter DTMCS");
        ir(17);scan_value={{ABITS{1'b1}},32'h12345678,2'b01};scan(ABITS+34);
        for(i=0;i<30;i=i+1)tick(0,0,sample);
        scan_value=0;scan(ABITS+34);
        if(scan_result[1:0]!==2 || scan_result[ABITS+33:34]!=={ABITS{1'b1}})
            $fatal(1,"parameter DMI address/failure width");
        $display("PASS parameters ABITS=%0d DMI_WIDTH=%0d custom_test_IDCODE=12345001 idle=3",ABITS,ABITS+34);
        $finish;
    end
endmodule
