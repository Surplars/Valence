`timescale 1ns/1ps
module clock_performance_telemetry_tb;
  reg sourceClock=0, alwaysOnClock=0, cpuClock=0, fabricClock=0, reset=1;
  integer cpuHalf=5;
  reg cpuRun=1;
  always #10 sourceClock=~sourceClock;
  initial begin #3; forever #10 alwaysOnClock=~alwaysOnClock; end
  initial forever begin #(cpuHalf); if (cpuRun) cpuClock=~cpuClock; else cpuClock=0; end
  initial begin #7; forever #10 fabricClock=~fabricClock; end
  reg [6:0] events0=7'b1010101, events1=7'b0101010;
  reg invalid0=0, invalid1=0;
  reg reqValid=0, reqWrite=0;
  reg [63:0] address=0;
  wire reqReady, rspValid, rspError;
  wire [63:0] rspData;
  reg rspReady=1;
  ClockPerformanceTelemetry dut(
    .sourceClock(sourceClock), .alwaysOnClock(alwaysOnClock),
    .managedClocks_0(cpuClock), .managedClocks_1(fabricClock), .commonReset(reset),
    .events_0(events0), .events_1(events1), .invalidate_0(invalid0), .invalidate_1(invalid1),
    .registers_request_valid(reqValid), .registers_request_ready(reqReady),
    .registers_request_bits_address(address), .registers_request_bits_write(reqWrite),
    .registers_request_bits_size(3'd3), .registers_request_bits_data(64'd0),
    .registers_request_bits_byteEnable(8'hff),
    .registers_response_valid(rspValid), .registers_response_ready(rspReady),
    .registers_response_bits_data(rspData), .registers_response_bits_error(rspError),
    .sourceIdle(), .aonIdle());
  task access(input [63:0] a, input wr, input expectedError, output [63:0] value);
    integer timeout;
    begin
      @(negedge sourceClock); address=a; reqWrite=wr; reqValid=1;
      timeout=0;
      do begin @(posedge sourceClock); timeout=timeout+1; if(timeout>100) $fatal(1,"request timeout"); end while(!reqReady);
      @(negedge sourceClock); reqValid=0;
      timeout=0;
      do begin @(posedge sourceClock); timeout=timeout+1; if(timeout>100) $fatal(1,"reply timeout"); end while(!rspValid);
      value=rspData;
      if(rspError!==expectedError) $fatal(1,"MMIO error mismatch address=%h",a);
      @(negedge sourceClock);
    end
  endtask
  reg [63:0] seq0,seq1,flags,count,other,value;
  integer tries,k;
  task sample(input [63:0] base, input integer expected, input [6:0] mask);
    begin
      tries=0;
      do begin
        access(base,0,0,seq0); access(base+8,0,0,flags);
        access(base+64,0,0,count);
        access(base,0,0,seq1); tries=tries+1;
        if(tries>40) $fatal(1,"snapshot failed to converge");
      end while(seq0!=seq1);
      if((flags&5)!=1) $fatal(1,"stable sample invalid flags=%h",flags);
      if(count+2<expected || count>expected+2) $fatal(1,"frequency delta expected=%d got=%d",expected,count);
      for(k=0;k<7;k=k+1) begin
        access(base+72+8*k,0,0,other);
        if(mask[k]) begin
          if(other+2<expected || other>expected+2) $fatal(1,"real event delta mismatch slot=%d got=%d",k,other);
        end else if(other!=0) $fatal(1,"inactive event fabricated slot=%d",k);
      end
    end
  endtask
  initial begin
    #103; reset=0;
    repeat(700) @(posedge alwaysOnClock);
    sample('h10080900,256,events0); sample('h10080a00,128,events1);
    // More than1024 source edges have elapsed: width10 modulo wrap must work.
    repeat(520) @(posedge alwaysOnClock);
    sample('h10080900,256,events0);
    // A short transition finishing before publication must revoke the old
    // sample immediately; clearing live invalidate must not resurrect it.
    @(negedge alwaysOnClock); invalid0=1;
    repeat(4) @(posedge alwaysOnClock);
    @(negedge alwaysOnClock); invalid0=0;
    access('h10080908,0,0,flags);
    if(flags&1) $fatal(1,"old published sample resurrected after short transition");
    repeat(400) @(posedge alwaysOnClock);
    sample('h10080900,256,events0);
    // An interval overlapping a transition must not remain valid.
    @(negedge alwaysOnClock); invalid0=1; cpuHalf=10;
    repeat(150) @(posedge alwaysOnClock);
    access('h10080908,0,0,flags);
    if((flags&5)!=4) $fatal(1,"transition window falsely valid");
    @(negedge alwaysOnClock); invalid0=0;
    repeat(400) @(posedge alwaysOnClock);
    sample('h10080900,128,events0);
    // Stable stopped clock is still observable with no handshake dependency.
    @(negedge cpuClock); cpuRun=0;
    repeat(400) @(posedge alwaysOnClock);
    sample('h10080900,0,events0);
    sample('h10080a00,128,events1);
    access('h10080900,1,1,value); // no writable clear side effect
    access('h10080930,0,1,value); // hole
    access('h10080b00,0,1,value); // outside range
    // Backpressure must retain a response, including its exact snapshot data.
    @(negedge sourceClock); rspReady=0; reqValid=1; address='h10080a00; reqWrite=0;
    do @(posedge sourceClock); while(!reqReady);
    @(negedge sourceClock); reqValid=0;
    wait(rspValid); value=rspData;
    repeat(200) begin @(posedge sourceClock); if(!rspValid || rspData!==value) $fatal(1,"reply changed under backpressure"); end
    @(negedge sourceClock); rspReady=1;
    repeat(3) @(posedge sourceClock);
    reset=1; cpuRun=1; #103; reset=0;
    access('h10080900,0,0,value);
    if(value!=0) $fatal(1,"cold reset did not clear sequence");
    repeat(400) @(posedge alwaysOnClock);
    sample('h10080900,128,events0);
    $display("CLOCK_PERFORMANCE_TELEMETRY_PASS actual50_100 stopped wrap transition reset events readonly coherence backpressure");
    $finish;
  end
  initial begin #500000; $fatal(1,"global timeout"); end
endmodule
