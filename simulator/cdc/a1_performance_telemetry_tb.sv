`timescale 1ns/1ps
module a1_performance_telemetry_tb;
  reg sourceClock=0, alwaysOnClock=0, cpuClock=0, fabricClock=0, reset=1;
  integer cpuHalf=5;
  reg cpuRun=1;
  reg lane1=1;
  wire secondLane=$test$plusargs("wrong-lane") ? events0[0] : lane1;
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
    .secondRetire(secondLane), .events_0(events0), .events_1(events1), .invalidate_0(invalid0), .invalidate_1(invalid1),
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
  integer tries,k,eventExpected;
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
        eventExpected = (base == 'h10080900 && k == 0) ? 2*expected : expected;
        if(mask[k]) begin
          if(other+4<eventExpected || other>eventExpected+4) $fatal(1,"real event delta mismatch slot=%d got=%d",k,other);
        end else if(other!=0) $fatal(1,"inactive event fabricated slot=%d",k);
      end
    end
  endtask
  task independent_lanes(input integer mode,input integer pulses);
    reg [63:0] beforeTotal,afterTotal;
    integer j,expectedSum;
    reg a,b;
    begin
      @(negedge cpuClock);events0[0]=0;lane1=0;
      repeat(4) @(posedge cpuClock);
      @(negedge cpuClock);cpuRun=0;
      repeat(400) @(posedge alwaysOnClock);
      access('h10080988,0,0,beforeTotal);
      expectedSum=0;cpuRun=1;
      for(j=0;j<pulses;j=j+1) begin
        @(negedge cpuClock);
        a=(mode==0 || mode==3 || (mode==2 && j%3==0));
        b=(mode==1 || mode==3 || (mode==2 && j%5<2));
        events0[0]=a;lane1=b;expectedSum=expectedSum+a+b;
        @(posedge cpuClock);
      end
      @(negedge cpuClock);events0[0]=0;lane1=0;
      repeat(4) @(posedge cpuClock);
      @(negedge cpuClock);cpuRun=0;
      repeat(400) @(posedge alwaysOnClock);
      access('h10080988,0,0,afterTotal);
      if(((afterTotal-beforeTotal)&1023)!=(expectedSum&1023))
        $fatal(1,"independent lane sum oracle mode=%0d expected=%0d before=%0d after=%0d",mode,expectedSum,beforeTotal,afterTotal);
      $display("A1_TELEMETRY_LANES mode=%0d pulses=%0d expected=%0d modulo1024=%0d",mode,pulses,expectedSum,expectedSum&1023);
      cpuRun=1;
    end
  endtask
  initial begin
    #103; reset=0;
    access('h10080928,0,0,value);
    if(value != 64'h544d000a00000002) $fatal(1,"A1 CPU meter ABI2 descriptor missing");
    access('h10080a28,0,0,value);
    if(value != 64'h544d000a00000001) $fatal(1,"fabric meter ABI1 changed");
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
    independent_lanes(0,37);
    independent_lanes(1,53);
    independent_lanes(2,61);
    independent_lanes(3,600); // 1200 retirements cross the actual 10-bit sum wrap.
    $display("A1_PERFORMANCE_TELEMETRY_PASS actual50_100 stopped wrap transition reset events readonly coherence backpressure");
    $finish;
  end
  initial begin #500000; $fatal(1,"global timeout"); end
endmodule
