`timescale 1ns/1ps
// Uses actual installed UNISIM STARTUPE3/DCIRESET, never a fake vendor model.
module common_dci_startup_tb;
    reg cold_reset = 1'b0;
    wire ready;
    native_dci_startup dut(.cold_reset(cold_reset), .ready(ready));
    integer requests = 0;
    realtime last_rise = 0;
    realtime last_fall = 0;
    always @(negedge dut.reset_dci) begin
        if (last_rise > 0 && $realtime-last_rise < 100.0) $fatal(1,"DCI high pulse under100ns");
        last_fall = $realtime;
    end
    always @(posedge dut.reset_dci) begin
        if (dut.eos !== 1'b1) $fatal(1,"DCI reset before EOS");
        if ($realtime-last_fall < 100.0) $fatal(1,"DCI low pulse under100ns");
        last_rise = $realtime;
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
        // Re-trigger DURING the high pulse; the pulse must not be truncated.
        #1000 cold_reset = 1'b1;
        #1000 cold_reset = 1'b0;
        @(posedge dut.reset_dci);
        #5 cold_reset = 1'b1;
        #40 cold_reset = 1'b0;
        wait (requests == 4);
        wait (ready === 1'b1);
        // Re-trigger during the low guard after a completed high pulse.
        #1000 cold_reset = 1'b1;
        #1000 cold_reset = 1'b0;
        @(posedge dut.reset_dci);
        @(negedge dut.reset_dci);
        #5 cold_reset = 1'b1;
        #40 cold_reset = 1'b0;
        wait (requests == 6);
        wait (ready === 1'b1);
        // ready rises from a posedge CFGMCLK NBA update. Injecting a force in
        // that same active region races the unmodified posedge-ready checker.
        // Drive at the opposite edge instead, AFTER verifying the genuine
        // pre-injection state. The asynchronous inhibit deadline stays 1 ns.
        @(negedge dut.cfg_clock);
        if (ready !== 1'b1 || dut.locked !== 1'b1 || dut.inhibit !== 1'b0)
            $fatal(1,"DCI pre-injection ready/LOCKED state invalid");
        // Inject loss only at the DUT status net, not a replacement primitive.
        force dut.locked = 1'b0;
        #1 if (ready !== 1'b0) $fatal(1,"LOCKED loss did not inhibit ready");
        #100 release dut.locked;
        wait (ready === 1'b1);
        @(negedge dut.cfg_clock);
        if (ready !== 1'b1 || dut.locked !== 1'b1 || dut.inhibit !== 1'b0)
            $fatal(1,"DCI failed stable recovery after LOCKED loss");
        $display("COMMON_DCI_STARTUP_PASS VENDOR_UNISIM=1 BOARD=0");
        $finish;
    end
    initial begin
        #20000000;
        $fatal(1,"DCI startup timeout: inspect actual UNISIM pulse/LOCKED semantics");
    end
endmodule

// Negative control: actual vendor primitive must report a pulse violation.
module common_dci_short_pulse_tb;
    reg rst = 1'b0;
    wire locked;
    DCIRESET bad(.RST(rst), .LOCKED(locked));
    initial begin
        #500 rst = 1'b1;
        #25 rst = 1'b0;
        #25 rst = 1'b1;
        #200 rst = 1'b0;
        #500 $finish;
    end
endmodule
