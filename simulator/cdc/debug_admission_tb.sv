`timescale 1ns/1ps
// External transaction oracle: no hierarchy references, forced state or fake ACKs.
module debug_admission_tb;
  integer sourceHalf=2, fabricHalf=7, fabricPhase=1;
  reg sourceClock=0, fabricClock=0, commonColdReset=1, sourceLinkUp=0;
  reg fabricRunning=1;
  initial begin
    if($value$plusargs("source-half=%d",sourceHalf)) begin end
    forever #(sourceHalf) sourceClock=~sourceClock;
  end
  initial begin
    if($value$plusargs("fabric-half=%d",fabricHalf)) begin end
    if($value$plusargs("fabric-phase=%d",fabricPhase)) begin end
    #(fabricPhase);
    forever begin #(fabricHalf); if(fabricRunning) fabricClock=~fabricClock; end
  end
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
  reg prepare_valid=0, cancel_valid=0, resume_valid=0, terminal_ready=0;
  reg [7:0] prepare_bits=0, cancel_bits=0, resume_bits=0;
  wire prepare_ready, cancel_ready, resume_ready, held_valid, terminal_valid;
  wire [7:0] held_bits, terminal_bits_epoch;
  wire terminal_bits_canceled, busy, fault;
  reg holdDestinationRequest=0, holdDestinationResponse=0;
  wire destinationRequestFire, destinationResponseFire, loaderOwnersIdle;
  JtagLoaderAdmissionNative dut(.*);

  integer sourceAccepted=0, sourceCompleted=0, destinationAccepted=0, destinationCompleted=0;
  integer ramAccepted=0, ramCompleted=0;
  reg [63:0] expectedAddress=0, expectedData=0;
  reg [31:0] expectedReply=0;
  reg [1:0] expectedStatus=0;
  reg admissionClosed=0;
  reg negativeData=0, negativeDrain=0;
  task automatic reject(input [255:0] reason);
    begin
      if((negativeData && reason == "DMI response payload mismatch") ||
         (negativeDrain && reason == "premature drain proof"))
        $display("NEGATIVE_ORACLE_REJECTED %0s",reason);
      $fatal(1,"external ownership/payload oracle: %0s",reason);
    end
  endtask
  always @(posedge sourceClock) begin
    if(commonColdReset) begin sourceAccepted=0; sourceCompleted=0; admissionClosed=0; end
    else begin
      if(source_request_valid && source_request_ready) begin
        if(admissionClosed || (prepare_valid && prepare_ready)) reject("admission opened during epoch");
        if(sourceAccepted!=sourceCompleted) reject("overlapping source requests");
        sourceAccepted=sourceAccepted+1;
      end
      if(source_response_valid && source_response_ready) begin
        if(sourceCompleted>=sourceAccepted) reject("duplicate source response");
        if(source_response_bits_status !== expectedStatus || source_response_bits_data !== expectedReply)
          reject("DMI response payload mismatch");
        sourceCompleted=sourceCompleted+1;
      end
      if(prepare_valid && prepare_ready) admissionClosed=1;
      if(terminal_valid && terminal_ready) admissionClosed=0;
    end
  end
  always @(posedge fabricClock) begin
    if(commonColdReset) begin
      destinationAccepted=0; destinationCompleted=0; ramAccepted=0; ramCompleted=0;
    end else begin
      if(destinationRequestFire) destinationAccepted=destinationAccepted+1;
      if(destinationResponseFire) begin
        if(destinationCompleted>=destinationAccepted) reject("unexpected destination response");
        destinationCompleted=destinationCompleted+1;
      end
      if(memory_request_valid) begin
        if(memory_request_bits_address !== expectedAddress || memory_request_bits_data !== expectedData ||
           memory_request_bits_write !== 1'b1 || memory_request_bits_size !== 3'd2 ||
           memory_request_bits_byteEnable !== 8'h0f) reject("RAM payload mismatch");
      end
      if(memory_request_valid && memory_request_ready) begin
        if(ramAccepted!=ramCompleted) reject("overlapping RAM owner");
        ramAccepted=ramAccepted+1;
      end
      if(memory_response_valid && memory_response_ready) begin
        if(ramCompleted>=ramAccepted) reject("duplicate RAM completion");
        ramCompleted=ramCompleted+1;
      end
    end
  end
  // This is an external outstanding-owner test, not the DUT's idle calculation.
  task automatic checkProof;
    begin
      if(sourceAccepted!=sourceCompleted || destinationAccepted!=destinationCompleted ||
         memory_request_valid || ramAccepted!=ramCompleted) reject("premature drain proof");
    end
  endtask
  always @(negedge sourceClock) if(!commonColdReset) begin
    if(held_valid || terminal_valid) checkProof();
    if(fault && (held_valid || terminal_valid || source_request_ready)) reject("fault reopened admission");
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
  task automatic dmiSend(input [1:0] op, input [6:0] address, input [31:0] data,
                         input [31:0] reply, input [1:0] status);
    begin
      @(negedge sourceClock); source_request_valid=1;
      source_request_bits_op=op; source_request_bits_address=address; source_request_bits_data=data;
      expectedReply=reply; expectedStatus=status;
      do @(posedge sourceClock); while(!source_request_ready);
      @(negedge sourceClock); source_request_valid=0;
    end
  endtask
  task automatic dmiReceive;
    reg [31:0] savedData; reg [1:0] savedStatus;
    begin
      do @(negedge sourceClock); while(!source_response_valid);
      savedData=source_response_bits_data; savedStatus=source_response_bits_status;
      repeat(7) begin
        @(negedge sourceClock);
        if(!source_response_valid || source_response_bits_data !== savedData || source_response_bits_status !== savedStatus)
          reject("response unstable when stalled");
      end
      source_response_ready=1;
      @(posedge sourceClock); @(negedge sourceClock); source_response_ready=0;
    end
  endtask
  task automatic prepareEpoch(input [7:0] epoch);
    begin
      @(negedge sourceClock); prepare_valid=1; prepare_bits=epoch;
      do @(posedge sourceClock); while(!prepare_ready);
      @(negedge sourceClock); prepare_valid=0;
    end
  endtask
  task automatic cancelEpoch(input [7:0] epoch);
    begin
      @(negedge sourceClock); cancel_valid=1; cancel_bits=epoch;
      do @(posedge sourceClock); while(!cancel_ready);
      @(negedge sourceClock); cancel_valid=0;
    end
  endtask
  task automatic waitHeld(input [7:0] epoch);
    begin
      do @(negedge sourceClock); while(!held_valid);
      if(held_bits !== epoch || !busy || fault) reject("held epoch identity");
      checkProof();
    end
  endtask
  task automatic noProof(input integer cycles);
    begin
      repeat(cycles) begin
        @(negedge sourceClock);
        if(held_valid || terminal_valid) reject("early held or terminal");
      end
    end
  endtask
  task automatic terminalTake(input [7:0] epoch, input bit canceled);
    begin
      do @(negedge sourceClock); while(!terminal_valid);
      repeat(13) begin
        @(negedge sourceClock);
        if(!terminal_valid || terminal_bits_epoch !== epoch || terminal_bits_canceled !== canceled ||
           source_request_ready || !busy) reject("terminal not retained/closed");
      end
      terminal_ready=1;
      @(posedge sourceClock); @(negedge sourceClock); terminal_ready=0;
    end
  endtask
  task automatic invalidEpochs(input [7:0] epoch);
    begin
      @(negedge sourceClock); prepare_valid=1; prepare_bits=epoch;
      cancel_valid=1; cancel_bits=epoch; resume_valid=1; resume_bits=epoch;
      repeat(6) begin
        @(negedge sourceClock);
        if(prepare_ready || cancel_ready || resume_ready) reject("stale epoch accepted");
      end
      prepare_valid=0; cancel_valid=0; resume_valid=0;
    end
  endtask
  task automatic acceptRam;
    begin
      do @(negedge fabricClock); while(!memory_request_valid);
      memory_request_ready=1;
      @(posedge fabricClock); @(negedge fabricClock); memory_request_ready=0;
      if(ramAccepted!=ramCompleted+1 || !memory_response_ready) reject("RAM not retained after acceptance");
    end
  endtask
  task automatic completeRam;
    begin
      @(negedge fabricClock); memory_response_bits_data=64'h123456789abcdef0;
      memory_response_valid=1;
      do @(posedge fabricClock); while(!memory_response_ready);
      @(negedge fabricClock); memory_response_valid=0;
    end
  endtask
  task automatic coldReset;
    begin
      @(negedge sourceClock); commonColdReset=1; sourceLinkUp=0;
      source_request_valid=0; source_response_ready=0;
      prepare_valid=0; cancel_valid=0; resume_valid=0; terminal_ready=0;
      control_request_valid=0; control_response_ready=0;
      memory_request_ready=0; memory_response_valid=0; memory_response_bits_error=0;
      holdDestinationRequest=0; holdDestinationResponse=0; fabricRunning=1;
      repeat(12) @(negedge fabricClock);
      @(negedge sourceClock); commonColdReset=0; sourceLinkUp=1;
      repeat(24) @(negedge fabricClock);
      if(!destinationLinkUp || busy || fault) reject("coordinated cold reset failed");
    end
  endtask
  reg [63:0] controlResult;
  integer baseline, scenario;
  initial begin
    negativeData=$test$plusargs("wrong-data"); negativeDrain=$test$plusargs("wrong-drain");
    coldReset();
    // This loader deliberately does not implement a hart Debug Module.
    dmiSend(1,7'h11,0,0,0); dmiReceive();
    dmiSend(2,7'h10,32'h80000001,0,2); dmiReceive();
    dmiSend(2,7'h10,32'h40000001,0,2); dmiReceive();
    dmiSend(1,7'h10,0,0,0); dmiReceive();

    // Early SBA DMI acknowledgment cannot discharge a real offered RAM owner.
    controlAccess(1,64'h10003008,1,0,controlResult);
    expectedAddress=64'h80200000; expectedData=64'hcafef00d;
    dmiSend(2,7'h39,expectedAddress[31:0],0,0); dmiReceive();
    dmiSend(2,7'h3c,expectedData[31:0],0,0); dmiReceive();
    if(sourceAccepted!=sourceCompleted || !memory_request_valid) reject("missing early SBA reply/owner");
    prepareEpoch(1);
    if(negativeDrain) checkProof(); // Deliberately claim drained at the known unsafe point.
    noProof(45);
    @(negedge sourceClock); resume_valid=1; resume_bits=1;
    repeat(9) begin @(negedge sourceClock); if(resume_ready) reject("resume accepted before held"); end
    resume_valid=0;
    acceptRam(); noProof(45);
    completeRam(); waitHeld(1);
    // Leave a new DMI request asserted across held, resume, and terminal stall.
    @(negedge sourceClock); source_request_valid=1; source_request_bits_op=1;
    source_request_bits_address=7'h40; source_request_bits_data=0;
    expectedReply=negativeData ? 32'h564c0100 : 32'h564c0101; expectedStatus=0;
    baseline=sourceAccepted;
    repeat(17) begin @(negedge sourceClock); if(source_request_ready) reject("request admitted while held"); end
    resume_valid=1; resume_bits=1;
    do @(posedge sourceClock); while(!resume_ready);
    @(negedge sourceClock); resume_valid=0;
    terminalTake(1,0);
    do @(posedge sourceClock); while(!source_request_ready);
    @(negedge sourceClock); source_request_valid=0;
    dmiReceive();
    if(sourceAccepted!=baseline+1 || sourceCompleted!=sourceAccepted) reject("held request not exactly once");
    invalidEpochs(1); invalidEpochs(0);

    // A request accepted into the real crossing still owns work, even though
    // the destination has not seen it. Cancellation is sticky, not a flush.
    @(negedge fabricClock); holdDestinationRequest=1;
    dmiSend(1,7'h40,0,32'h564c0101,0);
    prepareEpoch(2); cancelEpoch(2);
    noProof(35);
    // Duplicate cancellation and wrong-epoch resume/prepare cannot handshake.
    invalidEpochs(1); invalidEpochs(2); invalidEpochs(99);
    @(negedge sourceClock); cancel_valid=1; cancel_bits=2;
    repeat(5) begin @(negedge sourceClock); if(cancel_ready) reject("duplicate cancel accepted"); end
    cancel_valid=0;
    @(negedge fabricClock); holdDestinationResponse=1; holdDestinationRequest=0;
    repeat(20) @(negedge fabricClock);
    noProof(25);
    @(negedge fabricClock); holdDestinationResponse=0;
    do @(negedge sourceClock); while(!source_response_valid);
    noProof(30); dmiReceive(); terminalTake(2,1); invalidEpochs(2);

    // Same-edge priority: a prepare fire must beat a simultaneously valid DMI.
    @(negedge sourceClock); prepare_valid=1; prepare_bits=3;
    source_request_valid=1; source_request_bits_op=1; source_request_bits_address=7'h40;
    expectedReply=32'h564c0101; expectedStatus=0; baseline=sourceAccepted;
    do @(posedge sourceClock); while(!prepare_ready);
    if(source_request_ready) reject("same-edge prepare lost priority");
    @(negedge sourceClock); prepare_valid=0;
    // Stop fabric only for a bounded interval: source-cycle timers are not proof.
    @(negedge fabricClock); fabricRunning=0;
    noProof(70);
    fabricRunning=1;
    waitHeld(3);
    // Cancel wins when matching resume and cancel are presented together.
    @(negedge sourceClock); resume_valid=1; resume_bits=3; cancel_valid=1; cancel_bits=3;
    do @(posedge sourceClock); while(!cancel_ready);
    @(negedge sourceClock); resume_valid=0; cancel_valid=0;
    terminalTake(3,1);
    do @(posedge sourceClock); while(!source_request_ready);
    @(negedge sourceClock); source_request_valid=0;
    dmiReceive(); if(sourceAccepted!=baseline+1) reject("same-edge request count");
    invalidEpochs(3);

    // Active epoch link loss must fail closed; both offered and accepted real
    // RAM owners survive DTM-only reset and complete without replay.
    for(scenario=0;scenario<2;scenario=scenario+1) begin
      coldReset();
      controlAccess(1,64'h10003008,1,0,controlResult);
      expectedAddress=64'h80200020+scenario*4; expectedData=64'h10203040+scenario;
      dmiSend(2,7'h39,expectedAddress[31:0],0,0); dmiReceive();
      dmiSend(2,7'h3c,expectedData[31:0],0,0); dmiReceive();
      if(scenario==1) acceptRam();
      prepareEpoch(4);
      @(negedge sourceClock); sourceLinkUp=0;
      // The awaiting-owner case glitches entirely between source edges.
      // The transport's asynchronous reset/release must preserve that event.
      if(scenario==1) begin #1; sourceLinkUp=1; end
      repeat(20) @(negedge fabricClock);
      if(!fault || held_valid || terminal_valid || source_request_ready) reject("link loss not faulted");
      if(scenario==0) begin
        if(!memory_request_valid) reject("offered RAM lost on link reset");
        acceptRam();
      end
      if(ramAccepted!=1 || ramCompleted!=0 || !memory_response_ready) reject("RAM owner lost on link reset");
      @(negedge sourceClock); sourceLinkUp=1;
      repeat(20) @(negedge fabricClock);
      noProof(30); completeRam();
      repeat(30) @(negedge fabricClock);
      if(!fault || held_valid || terminal_valid || source_request_ready || ramAccepted!=1 || ramCompleted!=1)
        reject("link reconnect falsely recovered epoch");
      // Reset covers both DUT domains and every external model owner.
      coldReset(); dmiSend(1,7'h40,0,32'h564c0101,0); dmiReceive();
    end
    // A terminal already presented under backpressure must not retire an
    // admission epoch when link failure arrives as its consumer becomes ready.
    prepareEpoch(1); waitHeld(1); cancelEpoch(1);
    do @(negedge sourceClock); while(!terminal_valid);
    repeat(5) @(negedge sourceClock);
    sourceLinkUp=0; terminal_ready=1; #1; sourceLinkUp=1;
    repeat(10) @(negedge sourceClock);
    if(!busy || !fault || terminal_valid || held_valid || source_request_ready)
      reject("terminal link fault released epoch");
    terminal_ready=0;
    coldReset(); dmiSend(1,7'h40,0,32'h564c0101,0); dmiReceive();
    prepareEpoch(1); waitHeld(1); cancelEpoch(1); terminalTake(1,1);
    repeat(20) @(negedge sourceClock);
    checkProof();
    if(busy || fault) reject("final epoch did not release");
    $display("DEBUG_ADMISSION_PASS source_half=%0d fabric_half=%0d phase=%0d",sourceHalf,fabricHalf,fabricPhase);
    $finish;
  end
  initial begin #2000000; $fatal(1,"debug admission timeout"); end
endmodule
