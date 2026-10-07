`timescale 1ns/1ps
module managed_peripheral_cdc_tb;
    reg sourceClock=0, alwaysOnClock=0, slowClock=0, fastClock=0, commonReset=1;
    reg [1:0] stop=0, rawValid=0, statsReady=3, requestValid=0, responseReady=0;
    reg [7:0] rawData[2];
    reg [63:0] requestData[2];
    wire [1:0] managedClock, stopped, fault, capturedValid, statValid, requestReady, responseValid, responseError;
    wire [7:0] capturedData[2];
    wire [31:0] statCount[2], statSum[2];
    wire [63:0] responseData[2];
    wire [1:0] rawClocks={fastClock,slowClock};
    integer produced[2], consumed[2], byteSum[2], edges[2], heldEdges[2];
    integer countTotal[2], sumTotal[2];
    reg [7:0] expected[2][4096];
    reg held[2];
    reg [63:0] heldStats[2];
    realtime rawRise[2], rawFall[2], gateRise[2];
    reg risen[2];
`define LANE(P,N) \
    .P``_stop(stop[N]), .P``_rawData(rawData[N]), .P``_rawValid(rawValid[N]), \
    .P``_statsReady(statsReady[N]), .P``_managedClock(managedClock[N]), \
    .P``_stopped(stopped[N]), .P``_fault(fault[N]), \
    .P``_capturedData(capturedData[N]), .P``_capturedValid(capturedValid[N]), \
    .P``_statValid(statValid[N]), .P``_statCount(statCount[N]), .P``_statSum(statSum[N]), \
    .P``_registers_request_valid(requestValid[N]), .P``_registers_request_ready(requestReady[N]), \
    .P``_registers_request_bits_address(64'h10000000), .P``_registers_request_bits_write(1'b1), \
    .P``_registers_request_bits_size(3'd3), .P``_registers_request_bits_data(requestData[N]), \
    .P``_registers_request_bits_byteEnable(8'hff), .P``_registers_response_ready(responseReady[N]), \
    .P``_registers_response_valid(responseValid[N]), .P``_registers_response_bits_data(responseData[N]), \
    .P``_registers_response_bits_error(responseError[N])
    ManagedPeripheralCdcTop dut(.sourceClock(sourceClock), .alwaysOnClock(alwaysOnClock),
        .slowClock(slowClock), .fastClock(fastClock), .commonReset(commonReset), `LANE(slow,0), `LANE(fast,1));
`undef LANE
    initial begin #1; forever #5 sourceClock=~sourceClock; end
    initial begin #3; forever #10 alwaysOnClock=~alwaysOnClock; end
    initial begin #7; forever #10 slowClock=~slowClock; end
    initial begin #2; forever #4 fastClock=~fastClock; end
    for(genvar i=0;i<2;i=i+1) begin
        always @(posedge rawClocks[i]) begin
            rawRise[i]=$realtime;
            if(!commonReset && rawValid[i]) begin
                expected[i][produced[i]]=rawData[i]; produced[i]=produced[i]+1; byteSum[i]=byteSum[i]+rawData[i];
            end
        end
        always @(negedge rawClocks[i]) rawFall[i]=$realtime;
        always @(posedge managedClock[i]) begin
            gateRise[i]=$realtime; risen[i]=1;
            if(!commonReset) begin
                if(rawClocks[i]!==1'b1) $fatal(1,"managed edge not aligned with raw source");
                edges[i]=edges[i]+1;
                if(capturedValid[i]) begin
                    if(consumed[i]>=produced[i] || capturedData[i] !==
                        (expected[i][consumed[i]] ^ (($test$plusargs("inject_data") && consumed[i]==0)?8'h1:8'h0)))
                        $fatal(1,"managed ingress independent byte oracle mismatch lane=%0d byte=%0d",i,consumed[i]);
                    consumed[i]=consumed[i]+1;
                end
            end
        end
        always @(negedge managedClock[i]) begin
            if(risen[i] && !commonReset && (rawClocks[i]!==1'b0 || rawFall[i]!=$realtime || gateRise[i]!=rawRise[i]))
                $fatal(1,"managed ingress full pulse oracle mismatch lane=%0d",i);
            risen[i]=0;
        end
        always @(posedge sourceClock) begin
            if(!commonReset && statValid[i]) begin
                if(held[i] && heldStats[i]!=={statCount[i],statSum[i]}) $fatal(1,"atomic delta changed while stalled");
                held[i]=!statsReady[i]; heldStats[i]={statCount[i],statSum[i]};
                if(statsReady[i]) begin countTotal[i]=countTotal[i]+statCount[i];sumTotal[i]=sumTotal[i]+statSum[i];end
            end else if(!commonReset && held[i]) $fatal(1,"atomic delta withdrawn while stalled");
        end
    end
    task cpuCycles(input integer n); repeat(n) @(negedge sourceClock); endtask
    task stopBoth;
        integer n;
        begin
            stop=3;n=0;
            // STOPPED can still be the OLD state just after raw ingress starts:
            // require the independent byte/statistic ledgers to drain as well.
            while((stopped!==2'b11 || consumed[0]!=produced[0] || consumed[1]!=produced[1] ||
                countTotal[0]!=produced[0] || countTotal[1]!=produced[1]) && n<3000)
                begin cpuCycles(1);n=n+1;end
            if(n>=3000 || fault) $fatal(1,"managed ingress drain/stop failed");
            cpuCycles(30);heldEdges[0]=edges[0];heldEdges[1]=edges[1];cpuCycles(30);
            if(edges[0]!=heldEdges[0] || edges[1]!=heldEdges[1]) $fatal(1,"stopped domain had physical clock edges");
        end
    endtask
    task automatic burst(input integer lane,input integer n,input integer seed);
        begin
            for(integer b=0;b<n;b=b+1) begin
                if(lane==0) @(negedge slowClock); else @(negedge fastClock);
                rawValid[lane]=1;rawData[lane]=(b*29+seed)&255;
            end
            if(lane==0) @(negedge slowClock); else @(negedge fastClock);
            rawValid[lane]=0;
        end
    endtask
    task compareStats;
        begin
            for(integer i=0;i<2;i=i+1)
                if(consumed[i]!=produced[i] || countTotal[i]!=produced[i] ||
                    sumTotal[i] != byteSum[i]+($test$plusargs("inject_counter")?1:0))
                    $fatal(1,"managed ingress independent counter oracle mismatch lane=%0d in=%0d out=%0d count=%0d sum=%0d expectedSum=%0d",
                        i,produced[i],consumed[i],countTotal[i],sumTotal[i],byteSum[i]);
        end
    endtask
    initial begin
        for(integer i=0;i<2;i=i+1) begin
            rawData[i]=0;requestData[i]=64'hfeed0001;produced[i]=0;consumed[i]=0;byteSum[i]=0;
            edges[i]=0;countTotal[i]=0;sumTotal[i]=0;held[i]=0;risen[i]=0;
        end
        #83; commonReset=0;cpuCycles(120);stopBoth();
        // Unrelated phases; burst begins with both actual clocks stopped.
        for(integer c=0;c<6;c=c+1) begin
            #(c*1.3+0.7);
            fork burst(0,(c==0)?1:73+c,17+c);burst(1,(c==0)?1:257+c,53+c);join
            stopBoth();compareStats();
        end
        // Held counter image prevents gating until consumed, including final bytes.
        statsReady=0;
        fork burst(0,9,4);burst(1,31,9);join
        cpuCycles(400);
        if(stopped || statValid!==2'b11)
            $fatal(1,"held statistic tail was prematurely clock-gated stopped=%b statValid=%b ready=%b bytes=%0d,%0d consumed=%0d,%0d",
                stopped,statValid,statsReady,produced[0],produced[1],consumed[0],consumed[1]);
        cpuCycles(60);statsReady=3;stopBoth();compareStats();
        // MMIO itself wakes the clock; complete source reply must be consumed before stop.
        requestValid[0]=1;
        begin : request
            integer n;n=0;
            // Sample ready AT the transfer edge, not after NBA has changed it.
            do begin @(posedge sourceClock);n=n+1;end while(!requestReady[0] && n<1500);
            if(n>=1500) $fatal(1,"MMIO did not wake the physical clock");
            @(negedge sourceClock);requestValid[0]=0;
            n=0;while(!responseValid[0] && n<1500) begin cpuCycles(1);n=n+1;end
            if(n>=1500 || responseError[0] || responseData[0]!=0) $fatal(1,"MMIO wake reply mismatch");
            cpuCycles(100);
            if(stopped[0] || !responseValid[0] || responseData[0]!=0) $fatal(1,"held MMIO reply gated or changed");
            responseReady[0]=1;cpuCycles(1);responseReady[0]=0;
        end
        stopBoth();compareStats();
        if(produced[0]!=390 || produced[1]!=1332) $fatal(1,"CDC stimulus did not exercise BOTH planned lanes");
        // Common asynchronous cold reset, asserted between all clock edges.
        #0.3;commonReset=1;stop=0;cpuCycles(10);commonReset=0;cpuCycles(100);
        if(stopped || fault) $fatal(1,"common cold reset did not restart clocks");
        $display("MANAGED_PERIPHERAL_CDC_PASS actual_BUFGCE=2 delays=64,128 clocks=100,50,125MHz first_wave=PASS replies=PASS atomic_stats=PASS");
        $finish;
    end
    initial begin #1000000;$fatal(1,"managed ingress CDC test timeout");end
endmodule
