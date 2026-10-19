`timescale 1ns/1ps
module tb;
`include "signals.svh"
    integer cycles=0, a0=0, a1=0, e0=0, e1=0, simultaneous=0, stalls=0, resets=0;
    integer olda0, olda1, olde0, olde1, n;
    reg aHeld=0, eHeld=0, aHeldClient, eHeldClient;
    reg [63:0] aHeldBits;
    reg eHeldBits;
    reg af0,af1,ef0,ef1;

    task tick;
        begin
            clock=0; #2;
            af0=0;af1=0;ef0=0;ef1=0;
            if (!reset) begin
                if (io_aOut_valid !== 1'b0 && io_aOut_valid !== 1'b1)
                    $fatal(1,"four-state A valid is unknown");
                if (io_eOut_valid !== 1'b0 && io_eOut_valid !== 1'b1)
                    $fatal(1,"four-state E valid is unknown");
                if (io_aOut_valid) begin
                    if (io_aChosen !== 1'b0 && io_aChosen !== 1'b1) $fatal(1,"four-state A choice is unknown");
                    if (io_aChosen == 0) begin
                        if (io_a_0_ready !== io_aOut_ready) $fatal(1,"four-state A selected ready mismatch");
                        if (io_a_0_valid !== 1 || io_aOut_bits !== io_a_0_bits) $fatal(1,"A selected payload/valid mismatch");
                    end else begin
                        if (io_a_1_ready !== io_aOut_ready) $fatal(1,"four-state A selected ready mismatch");
                        if (io_a_1_valid !== 1 || io_aOut_bits !== io_a_1_bits) $fatal(1,"A selected payload/valid mismatch");
                    end
                end
                if (io_eOut_valid) begin
                    if (io_eChosen !== 1'b0 && io_eChosen !== 1'b1) $fatal(1,"four-state E choice is unknown");
                    if (io_eChosen == 0) begin
                        if (io_e_0_ready !== io_eOut_ready) $fatal(1,"four-state E selected ready mismatch");
                        if (io_e_0_valid !== 1 || io_eOut_bits !== io_e_0_bits) $fatal(1,"E selected sink/valid mismatch");
                    end else begin
                        if (io_e_1_ready !== io_eOut_ready) $fatal(1,"four-state E selected ready mismatch");
                        if (io_e_1_valid !== 1 || io_eOut_bits !== io_e_1_bits) $fatal(1,"E selected sink/valid mismatch");
                    end
                end
                if (aHeld && (io_aOut_valid !== 1 || io_aChosen !== aHeldClient || io_aOut_bits !== aHeldBits))
                    $fatal(1,"A source changed during long backpressure");
                if (eHeld && (io_eOut_valid !== 1 || io_eChosen !== eHeldClient || io_eOut_bits !== eHeldBits))
                    $fatal(1,"E sink/source changed during long backpressure");
                af0=io_a_0_valid && io_a_0_ready;af1=io_a_1_valid && io_a_1_ready;
                ef0=io_e_0_valid && io_e_0_ready;ef1=io_e_1_valid && io_e_1_ready;
                if ((af0+af1) !== (io_aOut_valid && io_aOut_ready)) $fatal(1,"A accepted owner accounting mismatch");
                if ((ef0+ef1) !== (io_eOut_valid && io_eOut_ready)) $fatal(1,"E accepted owner accounting mismatch");
                a0=a0+af0;a1=a1+af1;e0=e0+ef0;e1=e1+ef1;
                simultaneous=simultaneous+((af0||af1)&&(ef0||ef1));
                aHeld=io_aOut_valid && !io_aOut_ready;eHeld=io_eOut_valid && !io_eOut_ready;
                if(aHeld) begin aHeldClient=io_aChosen;aHeldBits=io_aOut_bits;end
                if(eHeld) begin eHeldClient=io_eChosen;eHeldBits=io_eOut_bits;end
                stalls=stalls+aHeld+eHeld;
            end else begin aHeld=0;eHeld=0;end
            clock=1;#2;clock=0;#2;
            if(af0)io_a_0_bits=io_a_0_bits+1;
            if(af1)io_a_1_bits=io_a_1_bits+1;
            cycles=cycles+1;
        end
    endtask
    task cold_reset;
        begin
            reset=1;io_a_0_valid=0;io_a_1_valid=0;io_e_0_valid=0;io_e_1_valid=0;
            io_aOut_ready=0;io_eOut_ready=0;
            repeat(3)tick();reset=0;tick();resets=resets+1;
        end
    endtask
    initial begin
`include "initialize.svh"
        io_a_0_bits=64'h1000000000000000;io_a_1_bits=64'h2000000000000000;
        io_e_0_bits=0;io_e_1_bits=1;
        cold_reset();
        // Captures the real boot direction: first post-reset request/E is client1.
        // No force/random-init/zero-init is applied to the legacy arbiter state.
        if($test$plusargs("first_e")) begin
            io_e_1_valid=1;io_eOut_ready=1;tick();io_e_1_valid=0;
        end else begin
            io_a_1_valid=1;io_aOut_ready=1;tick();io_a_1_valid=0;
        end
        io_a_1_valid=1;io_e_1_valid=1;io_aOut_ready=1;io_eOut_ready=1;tick();
        io_a_1_valid=0;io_e_1_valid=0;tick();
        // Lock client1, then introduce competing client0 while stalled.
        io_a_1_valid=1;io_e_1_valid=1;io_aOut_ready=0;io_eOut_ready=0;tick();
        io_a_0_valid=1;io_e_0_valid=1;repeat(64)tick();
        io_aOut_ready=1;io_eOut_ready=1;tick();
        // Both independent arbiters sustain II=1 with balanced round robin.
        olda0=a0;olda1=a1;olde0=e0;olde1=e1;
        repeat(96)tick();
        if(a0-olda0 != 48 || a1-olda1 != 48 || e0-olde0 != 48 || e1-olde1 != 48)
            $fatal(1,"round-robin fairness or II1 lost");
        io_aOut_ready=0;io_eOut_ready=0;tick();repeat(7)tick();
        // A common cold reset cancels both held channels in the same epoch.
        cold_reset();
        io_a_1_valid=1;io_e_1_valid=1;io_aOut_ready=1;io_eOut_ready=1;tick();
        io_a_1_valid=0;io_e_1_valid=0;repeat(4)tick();
        if(stalls<140 || resets!=2 || simultaneous<98) $fatal(1,"four-state coverage witnesses absent");
        $display("COMMON_HOME_ARBITER_4STATE_PASS cycles=%0d a=%0d/%0d e=%0d/%0d stalls=%0d resets=%0d simultaneous=%0d ii1=96",cycles,a0,a1,e0,e1,stalls,resets,simultaneous);
        $finish;
    end
endmodule
