`timescale 1ns/1ps
// Directed completion-publication race checks, independent from the CDC model.
// Forced mailbox boundary controls place the response between the falling edge
// that publishes it and the next falling edge that latches DTM result registers.
module dtm_completion_tb;
    reg tck=0, reset_n=0;
    ValenceJtagDebugPort #(.ENABLE(1),.EXTERNAL_DMI(1)) dut (
        .tck(tck),.tms(0),.tdi(0),.trst_n(reset_n),.debug_clk(tck),.debug_por_n(reset_n),
        .tdo(),.tdo_oe(),.dmi_reset_n(),.dmi_req_valid(),.dmi_req_ready(0),
        .dmi_req_op(),.dmi_req_address(),.dmi_req_data(),.dmi_rsp_valid(0),
        .dmi_rsp_ready(),.dmi_rsp_status(0),.dmi_rsp_data(0));
    task edge_down; begin #5;tck=1;#5;tck=0;#1;end endtask
    initial begin
        #2;reset_n=1; repeat(12) edge_down();
        force dut.enabled.hard_reset=0;
        force dut.enabled.tap.state=3;
        force dut.enabled.instruction=5'h11;
        force dut.enabled.source_busy=1;
        force dut.enabled.response_valid=1;
        force dut.enabled.response_payload={32'hcafe1234,2'b00};
        dut.enabled.sticky_status=0;dut.enabled.result_data=32'hdeadbeef;
        #5;tck=1;#1;
        if(dut.enabled.tap.dr_shift[33:0] !== {32'hcafe1234,2'b00})
            $fatal(1,"published success used stale data");
        #4;tck=0;#1;
        force dut.enabled.response_payload={32'h98765432,2'b01};
        dut.enabled.sticky_status=0;dut.enabled.result_data=32'hdeadbeef;
        #5;tck=1;#1;
        if(dut.enabled.tap.dr_shift[33:0] !== {32'h98765432,2'b10})
            $fatal(1,"published reserved status not normalized with data");
        #4;tck=0;#1;
        force dut.enabled.tap.state=1;
        dut.enabled.sticky_status=3;
        force dut.enabled.response_payload={32'h12345678,2'b10};
        edge_down();
        force dut.enabled.response_valid=0;
        force dut.enabled.source_busy=0;
        force dut.enabled.instruction=5'h10;
        force dut.enabled.update_dr=1;
        force dut.enabled.dr_shift=41'h000010000;
        edge_down();
        if(dut.enabled.sticky_status!==2) $fatal(1,"busy recovery lost endpoint failure");
        edge_down();
        if(dut.enabled.sticky_status!==0) $fatal(1,"failure cannot be cleared after observation");
        $display("PASS DTM completion forwarding and busy-hidden failure");$finish;
    end
endmodule
