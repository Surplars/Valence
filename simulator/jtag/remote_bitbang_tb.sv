`timescale 1ns/1ps
// Local simulation command stream only. The default endpoint always returns failure.
module remote_bitbang_tb;
    reg tck=0,tms=1,tdi=0,trst_n=0,debug_por_n=0,debug_clk=0;
    wire tdo,tdo_oe;
    integer command,value,read_count;
    ValenceJtagDebugPort #(.ENABLE(1)) dut (
        .tck(tck),.tms(tms),.tdi(tdi),.trst_n(trst_n),.debug_clk(debug_clk),.debug_por_n(debug_por_n),
        .tdo(tdo),.tdo_oe(tdo_oe),.dmi_reset_n(),.dmi_req_valid(),.dmi_req_ready(1'b0),
        .dmi_req_op(),.dmi_req_address(),.dmi_req_data(),.dmi_rsp_valid(1'b0),.dmi_rsp_ready(),
        .dmi_rsp_status(2'b00),.dmi_rsp_data(32'b0));
    always #5 debug_clk=~debug_clk;
    initial begin
        #10;debug_por_n=1;trst_n=1;
        forever begin
            read_count=$fscanf(32'h80000000,"%d %d\n",command,value);
            if(read_count!=2) $finish;
            case(command)
                0: begin tms=value[1];tdi=value[0];#2;tck=value[2];#10;end
                1: begin trst_n=!value[1];#10;end // SRST has no CPU to reset in this harness.
                2: #1;
                3: #(value);
                4: $finish;
                default: $fatal(1,"bad local harness command");
            endcase
            $display("S %0d %0d",tdo,tdo_oe);$fflush();
        end
    end
endmodule
