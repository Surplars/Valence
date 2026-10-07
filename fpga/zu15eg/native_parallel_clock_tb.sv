`timescale 1ns/1ps
// Compare actual exported gate before/after the audited input-net lowering.
// Independent oracle also checks each pulse against the ungated source.
module native_parallel_clock_tb;
    reg source=0, commonReset=0, enable=0;
    real half_period=4.0;
    wire rawClock, oldClock, parallelClock;
    BUFG raw_buffer(.I(source),.O(rawClock));
    ManagedClockBuffer old_gate(.rawClock(rawClock),.commonReset(commonReset),
        .enable(enable),.managedClock(oldClock));
    ParallelManagedClockBuffer new_gate(.rawClock(rawClock),
        .bufferSource($test$plusargs("invert_source") ? !source : source),
        .commonReset(commonReset),.enable(enable),.managedClock(parallelClock));
    always begin #(half_period); source=~source; end
    integer rises=0, falls=0, held;
    realtime last_rise=0;
    always @(posedge parallelClock) begin
        if($realtime>150) begin
            if(source!==1'b1) $fatal(1,"Parallel source edge independent oracle");
            rises=rises+1; last_rise=$realtime;
        end
    end
    always @(negedge parallelClock) begin
        if($realtime>150 && last_rise>0) begin
            if(source!==1'b0 || $realtime-last_rise < 3.999)
                $fatal(1,"Parallel pulse-width independent oracle");
            falls=falls+1;
        end
    end
    always @(oldClock or parallelClock) begin
        #0.001;
        if($realtime>150 && oldClock !== parallelClock)
            $fatal(1,"Parallel/cascaded zero-delay logical equivalence oracle");
    end
    initial begin
        #1.713; commonReset=1;
        #159.331; commonReset=0;
        for(integer frequency_case=0;frequency_case<3;frequency_case=frequency_case+1) begin
            @(negedge source);
            half_period=frequency_case==0 ? 4.0 : (frequency_case==1 ? 6.5 : 10.0);
            for(integer epoch=0;epoch<4;epoch=epoch+1) begin
                #1.117; enable=1;
                repeat(20) @(negedge source);
                held=rises; repeat(16) @(negedge source);
                if(rises-held!=16) $fatal(1,"Parallel running-clock count independent oracle");
                #1.337; enable=0;
                repeat(20) @(negedge source);
                held=rises; repeat(16) @(negedge source);
                if(rises!=held) $fatal(1,"Parallel stopped-clock independent oracle");
                // Common reset while stopped must restart cleanly when enabled.
                #1.713; commonReset=1; enable=1;
                repeat(9) @(negedge source);
                #1.119; commonReset=0;
                repeat(20) @(negedge source);
                held=rises; repeat(12) @(negedge source);
                if(rises-held!=12) $fatal(1,"Parallel cold-reset restart independent oracle");
            end
        end
        $display("PASS_NATIVE_PARALLEL_CLOCK cases=3 epochs=12 pulse_width=PASS logical_equivalence=PASS");
        $finish;
    end
    initial begin #100000; $fatal(1,"Parallel clock test timeout"); end
endmodule
