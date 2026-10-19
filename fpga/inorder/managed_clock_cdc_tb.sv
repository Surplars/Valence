`timescale 1ns/1ps
module managed_clock_cdc_tb;
    reg alwaysOnClock=0, rawClock=0, commonReset=1;
    reg stop=0, wake=0, idle=1, clearFault=0, rawRunning=1;
    wire retainedClock, managedClock, enabled, quiesce, isolate, admission, stopped, fault, domainAck;
    reg mailboxIn_valid=0, mailboxOut_ready=0;
    reg [63:0] mailboxIn_bits=0;
    wire mailboxIn_ready, mailboxOut_valid;
    wire [63:0] mailboxOut_bits;
    integer sourceSequence=0, destinationSequence=0, receivedTotal=0, readyCycle=0;
    reg heldMailbox=0;
    reg [63:0] heldMailboxBits;
    function automatic [63:0] pattern(input integer n);
        pattern=64'hb19a_50c7_ee12_8943 ^ (64'h9e37_79b9_7f4a_7c15*n);
    endfunction
    always @(posedge retainedClock or posedge commonReset)
        if(commonReset) sourceSequence=0;
        else if(mailboxIn_valid && mailboxIn_ready) sourceSequence=sourceSequence+1;
    always @(negedge retainedClock) begin
        mailboxIn_valid=!commonReset;
        mailboxIn_bits=pattern(sourceSequence);
    end
    always @(negedge alwaysOnClock) begin
        readyCycle=readyCycle+1;
        mailboxOut_ready=!commonReset && readyCycle%11>=5;
    end
    always @(posedge alwaysOnClock or posedge commonReset) begin
        if(commonReset) begin destinationSequence=0; heldMailbox=0; end
        else begin
            if(heldMailbox && (!mailboxOut_valid || mailboxOut_bits!==heldMailboxBits))
                $fatal(1,"mailbox held payload changed under backpressure");
            heldMailbox=mailboxOut_valid && !mailboxOut_ready;
            heldMailboxBits=mailboxOut_bits;
            if(mailboxOut_valid && mailboxOut_ready) begin
                if(mailboxOut_bits!==(pattern(destinationSequence)^($test$plusargs("inject_mailbox")?64'd1:64'd0)))
                    $fatal(1,"independent mailbox data/order/epoch oracle mismatch");
                destinationSequence=destinationSequence+1;
                receivedTotal=receivedTotal+1;
            end
        end
    end
    real rawHalf=4.0;
    integer retainedEdges=0, heldRetained=0;
    integer edges=0, held, cases=0;
    realtime lastRise=0, rawRise=0, rawFall=0;
    reg seenRise=0;
    ManagedClockCdcTop dut(.*);
    always #10 alwaysOnClock=~alwaysOnClock;
    always begin
        #(rawHalf);
        if(rawRunning) rawClock=~rawClock;
        else rawClock=0;
    end
    always @(posedge rawClock) rawRise=$realtime;
    always @(negedge rawClock) rawFall=$realtime;
    always @(posedge retainedClock) begin
        if(rawClock!==1'b1) $fatal(1,"retained clock edge lost raw-source alignment");
        retainedEdges=retainedEdges+1;
    end
    always @(posedge managedClock or posedge commonReset) begin
        if(commonReset) edges=0;
        else begin
            if(rawClock!==1'b1) $fatal(1,"physical clock edge not aligned to raw source");
            edges=edges+1;
        end
    end
    always @(posedge managedClock) begin lastRise=$realtime; seenRise=1; end
    always @(negedge managedClock) begin
        // Compare against actual source edges, not the new period variable:
        // its assignment may run before the OLD falling edge propagates.
        if(seenRise && !commonReset &&
            (rawClock!==1'b0 || rawFall!=$realtime || lastRise!=rawRise))
            $fatal(1,"physical clock pulse-width independent oracle mismatch rise=%0t rawRise=%0t fall=%0t rawFall=%0t",
                lastRise,rawRise,$realtime,rawFall);
        seenRise=0;
    end
    task cycles(input integer n);
        repeat(n) @(negedge alwaysOnClock);
    endtask
    task running;
        integer n;
        begin
            n=0;
            while((!admission || isolate || !enabled) && n<100) begin cycles(1); n=n+1; end
            if(n>=100) $fatal(1,"clock restart did not observe destination progress");
        end
    endtask
    task stopping;
        integer n;
        begin
            n=0;
            while(!stopped && n<80) begin cycles(1); n=n+1; end
            if(n>=80 || enabled || !isolate || admission || !domainAck)
                $fatal(1,"clock stop handshake independent oracle mismatch");
            // Gate command/BUFG synchronizer latency is bounded but not zero.
            cycles(20); held=edges; heldRetained=retainedEdges; cycles(20);
            if(retainedEdges<=heldRetained) $fatal(1,"always-running companion clock stopped with gate");
            if(edges!=held+($test$plusargs("inject_clock")?1:0))
                $fatal(1,"physical stopped-clock independent oracle mismatch");
        end
    endtask
    task restart;
        begin
            wake=1; stop=0; cycles(2); running(); wake=0;
            held=edges; cycles(8);
            if(edges<=held || domainAck) $fatal(1,"wake resumed without actual managed edges");
        end
    endtask
    initial begin
        cycles(5); commonReset=0; cycles(40); running();
        for(integer c=0;c<3;c=c+1) begin
            // Change source period only while low; never use a logic clock AND.
            @(negedge rawClock); rawHalf=(c==0)?4.0:((c==1)?6.5:10.0);
            cycles(4); idle=0; stop=1; held=edges; cycles(18);
            if(!enabled || stopped || isolate || !quiesce || edges<=held)
                $fatal(1,"busy endpoint was prematurely clock-gated");
            idle=1; stopping(); restart();
            // Cancellation before drain completion must not close the clock.
            idle=0;stop=1;cycles(4);stop=0;cycles(5);running();
            // Unresponsive endpoint fails open and reports a sticky fault.
            stop=1;cycles(55);
            if(!fault || !enabled || stopped || isolate || quiesce)
                $fatal(1,"drain timeout did not keep physical clock open");
            stop=0;clearFault=1;cycles(2);clearFault=0;idle=1;cycles(4);
            if(fault) $fatal(1,"sticky timeout fault clear failed");
            // Common cold reset is the only reset allowed during stopped state.
            stop=1;stopping();commonReset=1;stop=0;cycles(5);commonReset=0;
            cycles(40);running();
            cases=cases+1;
        end
        // A missing ungated source (e.g. absent PHY RX clock) cannot be faked
        // as a completed wake: leave isolation closed while reporting timeout.
        stop=1;stopping();@(negedge rawClock);rawRunning=0;
        held=edges;wake=1;stop=0;cycles(55);
        if(!fault || !enabled || !isolate || admission || edges!=held)
            $fatal(1,"missing raw-clock wake released isolation");
        rawRunning=1;cycles(35);running();wake=0;clearFault=1;cycles(2);clearFault=0;
        if(receivedTotal<50) $fatal(1,"insufficient asynchronous mailbox transfer coverage");
        $display("MANAGED_CLOCK_CDC_PASS clock_cases=%0d actual_BUFGCE=2 raw_running=PASS pulse_width=PASS retention=PASS mailbox=%0d",
            cases,receivedTotal);
        $finish;
    end
    initial begin #300000; $fatal(1,"managed-clock CDC test timeout"); end
endmodule

