`timescale 1ns/1ps
// Uses actual installed UNISIM STARTUPE3/DCIRESET, never a fake vendor model.
module common_dci_startup_tb;
    reg cold_reset = 1'b0;
    wire ready;
    native_dci_startup dut(.cold_reset(cold_reset), .ready(ready));
    integer requests = 0;
    always @(posedge dut.reset_dci) begin
        if (dut.eos !== 1'b1) $fatal(1,"DCI reset before EOS");
        requests = requests + 1;
    end
    always @(posedge ready) begin
        if (dut.locked !== 1'b1 || !dut.reset_acknowledged || dut.reset_dci)
            $fatal(1,"DCI released without reset/LOCKED handshake");
    end
    initial begin
        wait (ready === 1'b1);
        if (requests != 1) $fatal(1,"missing single initial post-EOS request");
        #1000 cold_reset = 1'b1;
        #1 if (ready !== 1'b0) $fatal(1,"cold reset did not inhibit ready");
        #1000 cold_reset = 1'b0;
        wait (ready === 1'b1);
        if (requests != 2) $fatal(1,"cold reset did not repeat DCI sequence");
        $display("COMMON_DCI_STARTUP_PASS VENDOR_UNISIM=1 BOARD=0");
        $finish;
    end
    initial begin
        #20000000;
        $fatal(1,"DCI startup timeout: inspect actual UNISIM pulse/LOCKED semantics");
    end
endmodule
