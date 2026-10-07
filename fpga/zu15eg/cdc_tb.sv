`timescale 1ns/1ps
// Explicit user exception: only new CDC modules, no CPU xsim.
module cdc_tb;
  reg sourceClock=0, destinationClock=0, commonReset=1;
  real sourceHalf=5.0, destinationHalf=4.0;
  initial forever #(sourceHalf) sourceClock=~sourceClock;
  initial begin #1.375; forever #(destinationHalf) destinationClock=~destinationClock; end
  wire source_request_ready, source_response_valid;
  reg source_request_valid=0, source_response_ready=0;
  reg [63:0] source_request_bits_address=0, source_request_bits_data=0;
  reg source_request_bits_write=0;
  reg [2:0] source_request_bits_size=0;
  reg [7:0] source_request_bits_byteEnable=0;
  wire [63:0] source_response_bits_data;
  wire source_response_bits_error;
  reg destination_request_ready=0, destination_response_valid=0;
  wire destination_request_valid, destination_response_ready;
  wire [63:0] destination_request_bits_address, destination_request_bits_data;
  wire destination_request_bits_write;
  wire [2:0] destination_request_bits_size;
  wire [7:0] destination_request_bits_byteEnable;
  reg [63:0] destination_response_bits_data=0;
  reg destination_response_bits_error=0;
  reg streamIn_valid=0, streamOut_ready=0;
  wire streamIn_ready, streamOut_valid;
  reg [63:0] streamIn_bits_data=0;
  reg [7:0] streamIn_bits_keep=0;
  reg streamIn_bits_last=0, streamIn_bits_user=0;
  wire [63:0] streamOut_bits_data;
  wire [7:0] streamOut_bits_keep;
  wire streamOut_bits_last, streamOut_bits_user;
  reg irqIn=0;
  wire irqOut;
  ClockDomainCdcTop dut(.*);
  integer epoch=1, sourceCycles=0, destinationCycles=0;
  integer requests=0, replies=0, effects=0, streamSent=0, streamReceived=0;
  integer fullCycles=0, emptyCycles=0, requestStalls=0, responseStalls=0, packetEnds=0;
  integer delayCycles=0, responseIndex=0, irqHigh=0, irqLow=0;
  reg responsePending=0, streamHeld=0, replyHeld=0, requestHeld=0;
  reg [1:0] irqReference=0;
  reg [73:0] streamPrevious;
  reg [64:0] replyPrevious;
  reg [139:0] requestPrevious;
  bit inject;
  function automatic [63:0] addressOf(input integer n);
    addressOf=64'h10010000 + epoch*4096 + n;
  endfunction
  function automatic [63:0] dataOf(input integer n);
    dataOf=64'hfedcba9876543210 ^ (64'h0101010101010101*n) ^ (64'h100000000*epoch);
  endfunction
  function automatic [7:0] enableOf(input integer n);
    enableOf=8'hff >> (n%8);
  endfunction
  function automatic [63:0] replyOf(input integer n);
    replyOf=dataOf(n)^addressOf(n)^{52'b0,enableOf(n),3'(n%8),1'(n%2)};
  endfunction
  function automatic [7:0] keepOf(input integer n);
    keepOf=(n%11==10) ? ((1 << (n%7+1))-1) : 8'hff;
  endfunction
  // All stimuli change on falling edges; payload/valid persist until accepted.
  always @(negedge sourceClock) begin
    source_request_valid=!commonReset && requests<300;
    source_request_bits_address=addressOf(requests);
    source_request_bits_data=dataOf(requests);
    source_request_bits_write=requests%2;
    source_request_bits_size=requests%8;
    source_request_bits_byteEnable=enableOf(requests);
    source_response_ready=!commonReset && sourceCycles%127>=40 && sourceCycles%5!=0;
    streamIn_valid=!commonReset && streamSent<4096;
    streamIn_bits_data=dataOf(streamSent);
    streamIn_bits_keep=keepOf(streamSent);
    streamIn_bits_last=streamSent%11==10;
    streamIn_bits_user=streamSent%19==0;
  end
  always @(negedge destinationClock) begin
    destination_request_ready=!commonReset && destinationCycles%7>=2;
    destination_response_valid=!commonReset && responsePending && delayCycles==0;
    destination_response_bits_data=replyOf(responseIndex);
    destination_response_bits_error=responseIndex%13==0;
    streamOut_ready=!commonReset && destinationCycles>100 && destinationCycles%101>=25 && destinationCycles%5!=1;
    irqIn=!commonReset && destinationCycles%211>=70 && destinationCycles%211<170;
  end
  always @(posedge sourceClock or posedge commonReset) begin
    if (commonReset) begin
      sourceCycles=0; requests=0; replies=0; streamSent=0;
      fullCycles=0; responseStalls=0; replyHeld=0; irqHigh=0; irqLow=0;
      irqReference=0;
    end else begin
      sourceCycles++;
      if (sourceCycles>5 && irqOut!==irqReference[1]) $fatal(1,"CDC IRQ sampled-level mismatch");
      irqReference={irqReference[0],irqIn};
      if (replyHeld && (!source_response_valid || {source_response_bits_data,source_response_bits_error}!==replyPrevious))
        $fatal(1,"CDC reply changed under backpressure");
      replyHeld=source_response_valid && !source_response_ready;
      replyPrevious={source_response_bits_data,source_response_bits_error};
      if (source_request_valid && source_request_ready) requests++;
      if (source_response_valid && source_response_ready) begin
        if (replies>=requests || source_response_bits_data!==replyOf(replies) ||
            source_response_bits_error!==(replies%13==0)) $fatal(1,"CDC response order/payload mismatch");
        replies++;
      end
      if (streamIn_valid && streamIn_ready) streamSent++;
      if (streamIn_valid && !streamIn_ready) fullCycles++;
      if (source_response_valid && !source_response_ready) responseStalls++;
      if (irqOut) irqHigh++; else irqLow++;
    end
  end
  always @(posedge destinationClock or posedge commonReset) begin
    if (commonReset) begin
      destinationCycles=0; effects=0; streamReceived=0; emptyCycles=0;
      requestStalls=0; packetEnds=0; responsePending=0; delayCycles=0;
      streamHeld=0; requestHeld=0;
    end else begin
      destinationCycles++;
      if (streamHeld && (!streamOut_valid ||
          {streamOut_bits_data,streamOut_bits_keep,streamOut_bits_last,streamOut_bits_user}!==streamPrevious))
        $fatal(1,"CDC FIFO output changed under backpressure");
      streamHeld=streamOut_valid && !streamOut_ready;
      streamPrevious={streamOut_bits_data,streamOut_bits_keep,streamOut_bits_last,streamOut_bits_user};
      if (requestHeld && (!destination_request_valid ||
          {destination_request_bits_address,destination_request_bits_data,destination_request_bits_byteEnable,
           destination_request_bits_size,destination_request_bits_write}!==requestPrevious))
        $fatal(1,"CDC request changed under backpressure");
      requestHeld=destination_request_valid && !destination_request_ready;
      requestPrevious={destination_request_bits_address,destination_request_bits_data,
          destination_request_bits_byteEnable,destination_request_bits_size,destination_request_bits_write};
      if (delayCycles>0) delayCycles--;
      if (destination_response_valid && destination_response_ready) responsePending=0;
      if (destination_request_valid && destination_request_ready) begin
        if (responsePending || effects>=requests || destination_request_bits_address!==addressOf(effects) ||
            destination_request_bits_data!==dataOf(effects) || destination_request_bits_write!==(effects%2!=0) ||
            destination_request_bits_size!==3'(effects%8) || destination_request_bits_byteEnable!==enableOf(effects))
          $fatal(1,"CDC request order/payload/duplicate mismatch");
        responseIndex=effects; effects++; responsePending=1; delayCycles=effects%7;
      end
      if (streamOut_valid && streamOut_ready) begin
        if (streamReceived>=streamSent || streamOut_bits_data!==(dataOf(streamReceived)^
                ((inject && streamReceived==31) ? 64'h1 : 64'h0)) ||
            streamOut_bits_keep!==keepOf(streamReceived) || streamOut_bits_last!==(streamReceived%11==10) ||
            streamOut_bits_user!==(streamReceived%19==0)) $fatal(1,"CDC FIFO independent scoreboard mismatch");
        if (streamOut_bits_last) packetEnds++;
        streamReceived++;
      end
      if (!streamOut_valid) emptyCycles++;
      if (destination_request_valid && !destination_request_ready) requestStalls++;
    end
  end
  task automatic resetBoth(input integer newEpoch, input real sh, input real dh);
    commonReset=1; epoch=newEpoch; sourceHalf=sh; destinationHalf=dh;
    #(40*(sh+dh)+0.317); commonReset=0;
  endtask
  task automatic finishEpoch;
    wait(replies==300 && effects==300 && streamReceived==4096);
    repeat(30) @(posedge sourceClock);
    if (requests!=300 || streamSent!=4096 || fullCycles==0 || emptyCycles==0 ||
        requestStalls==0 || responseStalls==0 || packetEnds!=4096/11 || irqHigh==0 || irqLow==0)
      $fatal(1,"CDC coverage missing");
    $display("CDC_CASE_PASS epoch=%0d source_period=%0f destination_period=%0f requests=%0d replies=%0d beats=%0d full=%0d empty=%0d req_stall=%0d resp_stall=%0d packets=%0d",
        epoch,2*sourceHalf,2*destinationHalf,requests,replies,streamReceived,
        fullCycles,emptyCycles,requestStalls,responseStalls,packetEnds);
  endtask
  initial begin
    inject=$test$plusargs("inject");
    resetBoth(1,5.0,4.0);
    // Coordinated reset while traffic is in flight and FIFO is full; no stale
    // response or partial packet from epoch 1 may appear in the next epoch.
    wait(streamSent==16 && replies<requests); #0.271;
    $display("CDC_RESET_IN_FLIGHT requests=%0d replies=%0d fifo_sent=%0d",requests,replies,streamSent);
    resetBoth(2,7.0,11.0); finishEpoch();
    resetBoth(3,11.0,3.0); finishEpoch();
    resetBoth(4,4.0,9.0); finishEpoch();
    resetBoth(5,5.0,4.0); finishEpoch();
    $display("CDC_SHORT_PASS cases=4 requests=1200 beats=16384 coordinated_reset=1");
    $finish;
  end
  initial begin #2000000; $fatal(1,"CDC timeout"); end
endmodule
