`timescale 1ns/1ps
module telemetry_event_pipeline_tb;
  reg sourceClock=0, destinationClock=0, commonReset=0;
  reg [6:0] events=0;
  wire [9:0] totals[0:7];
  TelemetryGrayCounterBank dut(.sourceClock(sourceClock), .destinationClock(destinationClock),
    .commonReset(commonReset), .events(events),
    .totals_0(totals[0]),.totals_1(totals[1]),.totals_2(totals[2]),.totals_3(totals[3]),
    .totals_4(totals[4]),.totals_5(totals[5]),.totals_6(totals[6]),.totals_7(totals[7]));
  always #7 destinationClock=~destinationClock;
  wire [9:0] sourceGray[0:7];
  assign sourceGray[0]=dut.gray_0; assign sourceGray[1]=dut.gray_1;
  assign sourceGray[2]=dut.gray_2; assign sourceGray[3]=dut.gray_3;
  assign sourceGray[4]=dut.gray_4; assign sourceGray[5]=dut.gray_5;
  assign sourceGray[6]=dut.gray_6; assign sourceGray[7]=dut.gray_7;
  reg [9:0] previousGray[0:7];
  reg grayCheck=0;
  integer n;
  reg [9:0] changed;
  task edge_step(input [6:0] mask);
    begin
      events=mask; #3; sourceClock=1; #1;
      for(integer g=0;g<8;g=g+1) begin
        changed=sourceGray[g]^previousGray[g];
        if(grayCheck && (changed & (changed-10'd1))!=0) $fatal(1,"non-unit source Gray transition counter=%0d",g);
        previousGray[g]=sourceGray[g];
      end
      #4; sourceClock=0; #4;
    end
  endtask
  integer initialEdges, expected[0:7], i;
  reg [6:0] pending=0, mask;
  initial begin
    #1; commonReset=1; #20; commonReset=0;
    repeat(8) edge_step(0);
    #100; grayCheck=1; initialEdges=totals[0];
    for(n=1;n<8;n=n+1) if(totals[n]!=0) $fatal(1,"reset event count nonzero");
    // Capture one real event, then stop BEFORE the next source edge.
    edge_step(7'b1); #100;
    if(totals[1]!=0) $fatal(1,"event bypassed required source sampling register");
    if(totals[0]!=(initialEdges+1)%1024) $fatal(1,"actual edge counter was incorrectly staged");
    // Resuming exactly one edge must drain the retained event exactly once.
    edge_step(0); #100;
    if(totals[1]!=1 || totals[0]!=(initialEdges+2)%1024) $fatal(1,"pending event lost or wrong edge count");
    edge_step(0); #100;
    if(totals[1]!=1) $fatal(1,"pending event duplicated after resume");
    for(n=0;n<8;n=n+1) expected[n]=totals[n];
    // Every slot receives an independent deterministic pattern, with natural
    // wraps in edge count and populated event counters. No expected count is
    // derived from any DUT register, except the pre-test baseline.
    for(i=0;i<2400;i=i+1) begin
      mask=((i*37)^(i>>2))&127;
      expected[0]=(expected[0]+1)%1024;
      for(n=1;n<8;n=n+1) expected[n]=(expected[n]+pending[n-1])%1024;
      edge_step(mask); pending=mask;
    end
    expected[0]=(expected[0]+1)%1024;
    for(n=1;n<8;n=n+1) expected[n]=(expected[n]+pending[n-1])%1024;
    edge_step(0); #100;
    for(n=0;n<8;n=n+1)
      if(totals[n]!==expected[n]) $fatal(1,"pulse accounting mismatch counter=%0d got=%0d expected=%0d",n,totals[n],expected[n]);
    // Reset a stopped source with a pending event: no pre-reset event may
    // reappear when the source resumes, and all Gray/cumulative state clears.
    edge_step(7'h7f); grayCheck=0; commonReset=1; #100;
    for(n=0;n<8;n=n+1) if(totals[n]!=0) $fatal(1,"cold reset failed while source stopped");
    commonReset=0; events=0; repeat(8) edge_step(0); #100;
    for(n=1;n<8;n=n+1) if(totals[n]!=0) $fatal(1,"pre-reset pending event leaked");
    $display("TELEMETRY_EVENT_PIPELINE_PASS one_edge_latency pending_stop_resume cold_reset pulse_conservation natural_wrap source_gray_unit frequency_unstaged");
    $finish;
  end
  initial begin #100000; $fatal(1,"timeout"); end
endmodule
