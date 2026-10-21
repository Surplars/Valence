`timescale 1ns/1ps
module jtag_loader_link_owner_tb;
  parameter integer FABRIC_HALF=10;
  reg sourceClock=0, fabricClock=0, commonColdReset=1, sourceLinkUp=0;
  always #2 sourceClock=~sourceClock;
  always #(FABRIC_HALF) fabricClock=~fabricClock;
  wire destinationLinkUp;
  reg source_request_valid=0, source_response_ready=0;
  reg [1:0] source_request_bits_op=0;
  reg [6:0] source_request_bits_address=0;
  reg [31:0] source_request_bits_data=0;
  wire source_request_ready, source_response_valid;
  wire [1:0] source_response_bits_status;
  wire [31:0] source_response_bits_data;
  reg control_request_valid=0, control_request_bits_write=0, control_response_ready=0;
  reg [63:0] control_request_bits_address=0, control_request_bits_data=0;
  reg [2:0] control_request_bits_size=3;
  reg [7:0] control_request_bits_byteEnable=255;
  wire control_request_ready, control_response_valid, control_response_bits_error;
  wire [63:0] control_response_bits_data;
  reg memory_request_ready=0, memory_response_valid=0, memory_response_bits_error=0;
  reg [63:0] memory_response_bits_data=0;
  wire memory_request_valid, memory_request_bits_write, memory_response_ready;
  wire [63:0] memory_request_bits_address, memory_request_bits_data;
  wire [2:0] memory_request_bits_size;
  wire [7:0] memory_request_bits_byteEnable;
  JtagLoaderLinkOwnerNative dut(.*);

  integer accepted=0, completed=0, expectedIndex=0;
  // Oracle uses test-selected literals, not DUT internal owner state.
  reg [63:0] expectedAddress=0, expectedData=0;
  reg expectWrite=1;
  always @(posedge fabricClock) if(!commonColdReset) begin
    if(memory_request_valid) begin
      if(memory_request_bits_address !== expectedAddress ||
         memory_request_bits_data !== expectedData || memory_request_bits_write !== expectWrite ||
         memory_request_bits_size !== 3'd2 || memory_request_bits_byteEnable !== 8'h0f)
        $fatal(1,"RAM request changed/corrupted during owner lifetime");
    end
    if(memory_request_valid && memory_request_ready) begin
      if(accepted != completed) $fatal(1,"duplicate or overlapping RAM acceptance");
      accepted=accepted+1;
    end
    if(memory_response_valid && memory_response_ready) begin
      if(completed >= accepted) $fatal(1,"RAM response without accepted owner");
      completed=completed+1;
    end
  end

  task automatic controlAccess(input bit wr, input [63:0] address, input [63:0] data,
                                input bit errorExpected, output reg [63:0] result);
    begin
      @(negedge fabricClock); control_request_valid=1;
      control_request_bits_write=wr; control_request_bits_address=address; control_request_bits_data=data;
      do @(posedge fabricClock); while(!control_request_ready);
      @(negedge fabricClock); control_request_valid=0;
      do @(negedge fabricClock); while(!control_response_valid);
      if(control_response_bits_error !== errorExpected) $fatal(1,"control error mismatch");
      result=control_response_bits_data;
      repeat(3) begin
        @(negedge fabricClock);
        if(!control_response_valid || control_response_bits_data !== result ||
            control_response_bits_error !== errorExpected) $fatal(1,"control backpressure corruption");
      end
      control_response_ready=1;
      @(posedge fabricClock); @(negedge fabricClock); control_response_ready=0;
    end
  endtask
  task automatic dmiSend(input [1:0] op, input [6:0] address, input [31:0] data);
    begin
      @(negedge sourceClock); source_request_valid=1;
      source_request_bits_op=op; source_request_bits_address=address; source_request_bits_data=data;
      do @(posedge sourceClock); while(!source_request_ready);
      @(negedge sourceClock); source_request_valid=0;
    end
  endtask
  task automatic dmiReceive(output reg [31:0] result);
    begin
      do @(negedge sourceClock); while(!source_response_valid);
      result=source_response_bits_data;
      repeat(7) begin
        @(negedge sourceClock);
        if(!source_response_valid || source_response_bits_status !== 0 || source_response_bits_data !== result)
          $fatal(1,"DMI response changed under host backpressure");
      end
      source_response_ready=1;
      @(posedge sourceClock); @(negedge sourceClock); source_response_ready=0;
    end
  endtask
  task automatic loseLink;
    begin
      @(negedge sourceClock); sourceLinkUp=0;
      repeat(12) @(negedge fabricClock);
      if(destinationLinkUp || source_response_valid) $fatal(1,"link reset failed");
    end
  endtask
  task automatic reconnect;
    begin
      @(negedge sourceClock); sourceLinkUp=1;
      repeat(12) @(negedge fabricClock);
      if(!destinationLinkUp || source_response_valid) $fatal(1,"stale DMI response on reconnect");
    end
  endtask
  task automatic completeRam(input bit error);
    begin
      @(negedge fabricClock); memory_response_bits_data=64'hfedcba9876543210;
      memory_response_bits_error=error; memory_response_valid=1;
      do @(posedge fabricClock); while(!memory_response_ready);
      @(negedge fabricClock); memory_response_valid=0;
      repeat(6) @(negedge fabricClock);
      if(memory_response_ready || memory_request_valid || accepted != completed)
        $fatal(1,"owner leaked or replayed after RAM response");
    end
  endtask
  reg [63:0] status;
  reg [31:0] reply;
  integer scenario;
  initial begin
    #37 commonColdReset=0; sourceLinkUp=1;
    repeat(20) @(negedge fabricClock);
    for(scenario=0;scenario<4;scenario=scenario+1) begin
      controlAccess(1,64'h10003008,1,0,status); // CPU opens a new generation.
      expectedAddress=64'h80200000 + scenario*4;
      expectedData=64'hcafe1000 + scenario;
      dmiSend(2,7'h39,expectedAddress[31:0]); dmiReceive(reply);
      dmiSend(2,7'h3c,expectedData[31:0]);
      do @(negedge fabricClock); while(!memory_request_valid);
      // DMI acknowledgement is not RAM completion. Keep it backpressured.
      do @(negedge sourceClock); while(!source_response_valid);
      repeat(9) @(negedge sourceClock);
      if(scenario==0) begin
        // Even an offered, not-yet-accepted request survives link loss unchanged.
        loseLink();
        if(!memory_request_valid || memory_response_ready) $fatal(1,"offered owner lost on link reset");
      end
      @(negedge fabricClock); memory_request_ready=1;
      @(posedge fabricClock); @(negedge fabricClock); memory_request_ready=0;
      if(!memory_response_ready || memory_request_valid) $fatal(1,"accepted owner not retained");
      if(scenario!=0) loseLink();
      repeat(17) begin
        @(negedge fabricClock);
        if(!memory_response_ready || memory_request_valid || accepted != completed+1)
          $fatal(1,"accepted RAM owner lost/replayed while link down");
      end
      if(scenario==1 || scenario==3) reconnect();
      // Re-open must fail while the old accepted RAM owner is still alive.
      controlAccess(1,64'h10003008,1,1,status);
      controlAccess(0,64'h10003000,0,0,status);
      if(!status[3] || status[0] || !status[2]) $fatal(1,"owner status incorrectly cleared by link loss");
      // Down-link completion, reconnect-before-completion, and bus error all drain once.
      completeRam(scenario==3);
      if(scenario==0 || scenario==2) reconnect();
      controlAccess(0,64'h10003000,0,0,status);
      if(status[3] || status[0] || !status[2] || status[4] !== (scenario==3))
        $fatal(1,"post-drain owner/status mismatch");
      dmiSend(1,7'h40,0); dmiReceive(reply);
      if(reply !== 32'h564c0101) $fatal(1,"new DMI response confused with old epoch");
    end
    // A new generation after all cancellations can complete normally. Stall its
    // DMI response while returning RAM response to prove independent ownership.
    controlAccess(1,64'h10003008,1,0,status);
    expectedAddress=64'h80200010; expectedData=64'hcafe2000;
    dmiSend(2,7'h39,expectedAddress[31:0]); dmiReceive(reply);
    dmiSend(2,7'h3c,expectedData[31:0]);
    do @(negedge fabricClock); while(!memory_request_valid);
    memory_request_ready=1; @(posedge fabricClock); @(negedge fabricClock); memory_request_ready=0;
    do @(negedge sourceClock); while(!source_response_valid);
    completeRam(0);
    if(!source_response_valid) $fatal(1,"RAM response incorrectly consumed host DMI response");
    dmiReceive(reply);
    controlAccess(0,64'h10003000,0,0,status);
    if(status[3] || !status[0] || status[4]) $fatal(1,"normal rearmed owner failed");
    repeat(50) @(negedge fabricClock);
    if(accepted != 5 || completed != 5 || memory_request_valid || memory_response_ready)
      $fatal(1,"final owner counts or leak");
    $display("PASS JTAG_LOADER_LINK_OWNER accepted=%0d completed=%0d fabric_half=%0d",accepted,completed,FABRIC_HALF);
    $finish;
  end
  initial begin #500000; $fatal(1,"loader owner timeout"); end
endmodule
