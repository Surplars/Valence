`timescale 1ns/1ps
// Actual exported default (1ms@100MHz) watchdog, independent recovered clocks.
// Edge-count/timeout semantics only; this cannot prove analog metastability.
module rx_clock_watchdog_tb;
    reg source_clock=0,monitor_clock=0,source_run=1,reset=1;
    real source_half=4.0;
    always begin #(source_half);if(source_run)source_clock=~source_clock;else source_clock=0;end
    initial begin #1.3;forever #5 monitor_clock=~monitor_clock;end
    wire present;
    EthernetRxClockWatchdog dut(.sourceClock(source_clock),.monitorClock(monitor_clock),
        .commonReset(reset),.present(present));
    integer cases=0,restarts=0;
    task automatic observe_rate(input real half_period);
        integer wait_cycles;begin
            @(negedge source_clock);source_half=half_period;
            wait_cycles=0;
            while(!present)begin @(posedge monitor_clock);wait_cycles=wait_cycles+1;
                if(wait_cycles>2000)$fatal(1,"WATCHDOG_RESTART_TIMEOUT");end
            repeat(3000)begin @(posedge monitor_clock);#0.01;
                if(!present)$fatal(1,"WATCHDOG_LOST_LEGAL_RATE");end
            @(negedge source_clock);source_run=0;
            repeat(90000)begin @(posedge monitor_clock);#0.01;
                if(!present)$fatal(1,"WATCHDOG_FALSE_EARLY_TIMEOUT");end
            repeat($test$plusargs("bad_timeout")?0:11000)@(posedge monitor_clock);#0.01;
            if(present)$fatal(1,"WATCHDOG_INDEPENDENT_TIMEOUT_ORACLE");
            source_run=1;wait_cycles=0;
            while(!present)begin @(posedge monitor_clock);wait_cycles=wait_cycles+1;
                if(wait_cycles>2000)$fatal(1,"WATCHDOG_RESTART_TIMEOUT");end
            restarts=restarts+1;cases=cases+1;
        end
    endtask
    initial begin
        #37.71;reset=0;
        observe_rate(4.0);observe_rate(20.0);observe_rate(200.0);
        @(negedge source_clock);source_run=0;#1.1;reset=1;#0.1;
        if(present)$fatal(1,"WATCHDOG_ASYNC_RESET");
        repeat(4)@(posedge monitor_clock);#0.27;reset=0;
        repeat(1200)@(posedge monitor_clock);#0.01;
        if(present)$fatal(1,"WATCHDOG_INVENTED_SOURCE_EDGES");
        source_run=1;wait(present);restarts=restarts+1;
        $display("RX_CLOCK_WATCHDOG_NATIVE_PASS rates=%0d restarts=%0d timeout_cycles=100000 stopped_reset=1 metastability_proof=0",cases,restarts);
        $finish;
    end
    initial begin #5000000;$fatal(1,"Watchdog native test timeout");end
endmodule
