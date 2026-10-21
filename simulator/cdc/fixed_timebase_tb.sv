`timescale 1ns/1ps
module fixed_timebase_tb;
  parameter integer FABRIC_HALF = 10;
  reg fabricClock = 0, timebaseClock = 0, commonColdReset = 1;
  reg runFabric = 1;
  always #2 timebaseClock = ~timebaseClock;
  always #(FABRIC_HALF) if (runFabric) fabricClock = ~fabricClock;
  reg registers_request_valid = 0, registers_request_bits_write = 0;
  reg [63:0] registers_request_bits_address = 0, registers_request_bits_data = 0;
  reg [2:0] registers_request_bits_size = 3;
  reg [7:0] registers_request_bits_byteEnable = 255;
  wire registers_request_ready, registers_response_valid, registers_response_bits_error, irq;
  wire [63:0] registers_response_bits_data, timeSnapshot;
  reg registers_response_ready = 0;
  FixedTimebaseBoundary dut (.*);
  task automatic access(input bit wr, input [63:0] addr, input [63:0] data,
                         input [2:0] size, input [7:0] mask,
                         input bit errorExpected, output reg [63:0] result);
    reg [63:0] held; reg err;
    begin
      @(negedge fabricClock);
      registers_request_valid = 1; registers_request_bits_write = wr;
      registers_request_bits_address = addr; registers_request_bits_data = data;
      registers_request_bits_size = size; registers_request_bits_byteEnable = mask;
      do @(posedge fabricClock); while (!registers_request_ready);
      @(negedge fabricClock); registers_request_valid = 0;
      do @(posedge fabricClock); while (!registers_response_valid);
      held = registers_response_bits_data; err = registers_response_bits_error;
      repeat (7) begin
        @(posedge fabricClock);
        if (!registers_response_valid || registers_response_bits_data !== held ||
            registers_response_bits_error !== err) $fatal(1, "MMIO response changed under stall");
      end
      if (err !== errorExpected) $fatal(1, "MMIO error mismatch");
      result = held;
      @(negedge fabricClock); registers_response_ready = 1;
      @(posedge fabricClock); @(negedge fabricClock); registers_response_ready = 0;
    end
  endtask
  reg [63:0] result, beforeTime, afterTime, previous;
  integer i;
  initial begin
    #37 commonColdReset = 0;
    repeat (30) @(posedge fabricClock);
    access(1, 64'h02004000, 64'h123456789abcdef0, 3, 255, 0, result);
    access(0, 64'h02004000, 0, 3, 255, 0, result);
    if (result !== 64'h123456789abcdef0) $fatal(1, "compare full write/read");
    access(1, 64'h02004004, 64'hfedcba98, 2, 15, 0, result);
    access(0, 64'h02004000, 0, 3, 255, 0, result);
    if (result !== 64'hfedcba989abcdef0) $fatal(1, "compare high write");
    access(0, 64'h02004008, 0, 3, 255, 1, result);
    access(1, 64'h02004000, 0, 3, 255, 0, result);
    repeat (8) @(posedge fabricClock);
    if (!irq) $fatal(1, "compare interrupt never asserted");
    access(1, 64'h02004000, 64'hffffffffffffffff, 3, 255, 0, result);
    repeat (8) @(posedge fabricClock);
    if (irq) $fatal(1, "compare interrupt never cleared");
    // Force carry through all 32 low bits. Torn samples would leave this window.
    access(1, 64'h0200bff8, 64'h12345678ffffff00, 3, 255, 0, result);
    repeat (20) @(posedge fabricClock);
    previous = timeSnapshot;
    for (i=0;i<100;i=i+1) begin
      @(negedge fabricClock);
      if (timeSnapshot < previous || timeSnapshot < 64'h12345678ffffff00 ||
          timeSnapshot > 64'h1234567900010000) $fatal(1, "torn or reordered time snapshot");
      previous = timeSnapshot;
    end
    beforeTime = timeSnapshot;
    @(negedge fabricClock); runFabric = 0;
    #4000;
    runFabric = 1;
    repeat (30) @(negedge fabricClock);
    afterTime = timeSnapshot;
    // Independent 250 MHz time persists while fabric stops. Include warmup latency.
    if (afterTime-beforeTime < 1000 || afterTime-beforeTime > 1400)
      $fatal(1, "timebase followed fabric or lost stopped-clock ticks: %0d", afterTime-beforeTime);
    commonColdReset = 1; #61; commonColdReset = 0;
    repeat (30) @(negedge fabricClock);
    if (timeSnapshot > 1000 || irq) $fatal(1, "cold reset epoch did not restart");
    $display("PASS FIXED_TIMEBASE independent_edges fabric_half=%0d", FABRIC_HALF);
    $finish;
  end
  initial begin #200000; $fatal(1, "fixed timebase timeout"); end
endmodule
