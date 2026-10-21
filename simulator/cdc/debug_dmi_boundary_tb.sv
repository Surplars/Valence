`timescale 1ns/1ps
module debug_dmi_boundary_tb;
  parameter integer DEST_HALF = 10;
  reg sourceClock=0, destinationClock=0, commonColdReset=1, sourceLinkUp=0;
  always #2 sourceClock=~sourceClock;
  always #(DEST_HALF) destinationClock=~destinationClock;
  wire destinationLinkUp;
  reg source_request_valid=0, source_response_ready=0;
  reg [1:0] source_request_bits_op=0;
  reg [6:0] source_request_bits_address=0;
  reg [31:0] source_request_bits_data=0;
  wire source_request_ready, source_response_valid;
  wire [1:0] source_response_bits_status;
  wire [31:0] source_response_bits_data;
  wire destination_request_valid, destination_response_ready;
  wire [1:0] destination_request_bits_op;
  wire [6:0] destination_request_bits_address;
  wire [31:0] destination_request_bits_data;
  reg destination_request_ready=0, destination_response_valid=0;
  reg [1:0] destination_response_bits_status=0;
  reg [31:0] destination_response_bits_data=0;
  DebugDmiClockBoundary dut (.*);
  integer n, j, count=0;
  reg [31:0] expected;
  initial begin
    #37 commonColdReset=0; sourceLinkUp=1;
    repeat(8) @(negedge destinationClock);
    if(!destinationLinkUp) $fatal(1,"link failed to synchronize");
    for(n=0;n<40;n=n+1) begin
      expected=32'ha5320000 ^ (n*32'h01010101);
      @(negedge sourceClock);
      source_request_bits_op=(n%2)+1; source_request_bits_address=n;
      source_request_bits_data=expected; source_request_valid=1;
      do @(posedge sourceClock); while(!source_request_ready);
      @(negedge sourceClock); source_request_valid=0;
      do @(negedge destinationClock); while(!destination_request_valid);
      repeat(3) begin
        if(!destination_request_valid || destination_request_bits_op !== ((n%2)+1) ||
            destination_request_bits_address !== n || destination_request_bits_data !== expected)
          $fatal(1,"DMI request corruption/stall");
        @(negedge destinationClock);
      end
      destination_request_ready=1;
      @(posedge destinationClock); count=count+1;
      @(negedge destinationClock); destination_request_ready=0;
      repeat(n%4) @(negedge destinationClock);
      destination_response_valid=1; destination_response_bits_status=n%3;
      destination_response_bits_data=~expected;
      do @(posedge destinationClock); while(!destination_response_ready);
      @(negedge destinationClock); destination_response_valid=0;
      do @(negedge sourceClock); while(!source_response_valid);
      repeat(5) begin
        if(!source_response_valid || source_response_bits_status !== n%3 ||
            source_response_bits_data !== ~expected) $fatal(1,"DMI response corruption/stall");
        @(negedge sourceClock);
      end
      source_response_ready=1;
      @(posedge sourceClock); @(negedge sourceClock); source_response_ready=0;
    end
    // Cancel a request held against destination backpressure, then reconnect.
    @(negedge sourceClock); source_request_valid=1;
    do @(posedge sourceClock); while(!source_request_ready);
    @(negedge sourceClock); source_request_valid=0;
    do @(negedge destinationClock); while(!destination_request_valid);
    sourceLinkUp=0; #83;
    if(destinationLinkUp || destination_request_valid || source_response_valid)
      $fatal(1,"link loss failed to discard old DMI epoch");
    sourceLinkUp=1; repeat(20) @(negedge destinationClock);
    if(!destinationLinkUp || destination_request_valid || source_response_valid)
      $fatal(1,"stale DMI replay after reconnect");
    // A response already queued toward the host must also vanish on link reset.
    @(negedge destinationClock); destination_response_valid=1;
    destination_response_bits_data=32'hdeadbeef;
    do @(posedge destinationClock); while(!destination_response_ready);
    @(negedge destinationClock); destination_response_valid=0;
    do @(negedge sourceClock); while(!source_response_valid);
    sourceLinkUp=0; #83; sourceLinkUp=1;
    repeat(20) @(negedge sourceClock);
    if(source_response_valid) $fatal(1,"old response replay after reconnect");
    commonColdReset=1; #47; commonColdReset=0;
    repeat(20) @(negedge destinationClock);
    if(!destinationLinkUp || destination_request_valid || source_response_valid)
      $fatal(1,"cold reset did not clear DMI epoch");
    $display("PASS DEBUG_DMI_BOUNDARY requests=%0d independent_edges dest_half=%0d",count,DEST_HALF);
    $finish;
  end
  initial begin #200000; $fatal(1,"DMI boundary timeout"); end
endmodule
