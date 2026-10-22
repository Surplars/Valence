`timescale 1ns/1ps
module i1_runtime_debug_tb;
  `include "guest_symbols.svh"
  integer cpuHalf = 5, fabricHalf = 7, aonHalf = 11;
  reg cpuClock = 0, fabricClock = 0, alwaysOnClock = 0, cpuPaused = 0;
  initial begin
    if ($value$plusargs("cpu-half=%d", cpuHalf)) begin end
    forever begin #(cpuHalf); if (!cpuPaused) cpuClock = ~cpuClock; end
  end
  initial begin
    if ($value$plusargs("fabric-half=%d", fabricHalf)) begin end
    #2; forever #(fabricHalf) fabricClock = ~fabricClock;
  end
  initial begin
    if ($value$plusargs("aon-half=%d", aonHalf)) begin end
    #3; forever #(aonHalf) alwaysOnClock = ~alwaysOnClock;
  end
  reg reset = 1, start = 0, program_valid = 0;
  reg [7:0] program_index = 0;
  reg [31:0] program_data = 0;
  reg [1:0] request_valid = 0, resume_valid = 0, cancel_valid = 0, result_ready = 0;
  reg [31:0] request_bits [0:1], resume_bits [0:1], cancel_bits [0:1];
  reg [7:0] resume_epoch [0:1], cancel_epoch [0:1], allocatedEpoch [0:1];
  wire [1:0] request_ready, resume_ready, cancel_ready, result_valid, result_canceled, result_timedOut, held_valid;
  wire [31:0] result_token [0:1], held_token [0:1];
  wire [7:0] result_epoch [0:1], held_epoch [0:1];
  reg holdReleaseAck = 0, holdCompletion = 0, holdCpuCompletion = 0;
  reg externalStop = 0, holdMsiReply = 0;
  reg [63:0] sources = 0;
  wire tileHeld_valid, fabricHeld_valid, retire_valid, trap, fabricIdle;
  wire [7:0] tileHeld_bits, fabricHeld_bits;
  wire releaseAckBlocked, completionBlocked, cpuCompletionBlocked, msiReplyBlocked;
  wire [31:0] releaseBeats, coherentAcquires, retire_instruction, cpuResumed;
  wire [31:0] msiAccepted, msiReplied, msiAccepted11, msiAccepted12, msiAccepted13;
  wire [31:0] fabricPrepares, fabricResumes, fabricCancels, fabricTerminals;
  wire fabricTerminalValid, fabricTerminalReady, cpuLinkReady, fabricLinkReady;
  wire cpuTransportEmpty, fabricTransportEmpty;
  wire busy, timeoutSelected, cleanupFault, epochExhausted, activeLane;
  wire [7:0] activeEpoch; wire [31:0] activeToken;
  wire [63:0] retire_pc, retire_data;
  wire [4:0] retire_rd; wire retire_writesRd;
  reg [31:0] rom [0:255]; reg [4095:0] rom_path;
  reg wrongData = 0;
  integer cycles = 0, aonCycles = 0, resetGeneration = 0;
  integer retires = 0, stores = 0, loads = 0, previousLoads = 0, loops = 0, pendingReads = 0, loopPhase = 0;
  integer requests [0:1], resumes [0:1], cancels [0:1], results [0:1], acceptedCycle [0:1];
  integer expected11 = 0, expected12 = 0, expected13 = 0;
  reg [63:0] expectedData = 0, eventMask = 0, lastPending = 0;
  integer i, lane, old, oldCpuResumed, oldFabricPrepares, oldFabricCancels;

  integer debugHalf = 13;
  reg debugClock = 0, debugLinkUp = 1;
  initial begin
    if ($value$plusargs("debug-half=%d", debugHalf)) begin end
    #4; forever #(debugHalf) debugClock = ~debugClock;
  end
  reg debug_request_valid = 0;
  wire debug_request_ready, debug_response_valid;
  reg [6:0] debug_request_address = 0;
  reg [31:0] debug_request_data = 0;
  reg [1:0] debug_request_op = 0;
  wire [31:0] debug_response_data;
  wire [1:0] debug_response_status;
  wire debugBusy, debugFault, debugHeld_valid;
  wire [7:0] debugHeld_bits;
  reg holdMemoryRequest = 0, holdMemoryResponse = 0, holdControlResponse = 0;
  wire memoryRequestBlocked, memoryResponseBlocked, controlResponseBlocked;
  wire memoryRequestFire, memoryRequestWrite, memoryResponseFire, memoryResponseError;
  wire [63:0] memoryRequestAddress, memoryRequestData, memoryResponseData;
  wire [2:0] memoryRequestSize; wire [7:0] memoryRequestByteEnable;
  wire controlRequestFire, controlRequestWrite, controlResponseFire, controlResponseError;
  wire [63:0] controlRequestAddress, controlRequestData;
  wire dmiOwnersIdle, controlOwnersIdle;
  integer sourceRequests = 0, sourceResponses = 0, plannedMemory = 0, memoryRequests = 0, memoryResponses = 0;
  integer controlRequests = 0, controlResponses = 0, controlWrites = 0, controlReads = 0;
  reg expectedMemoryWrite [0:255];
  reg [31:0] expectedMemoryData [0:255], expectedSourceReply [0:255];
  integer debugReads = 0, debugTerminals = 0, debugRetirementReceipts = 0;
  reg wrongDrain = 0, expectedFault = 0;
  localparam [31:0] DEBUG_ADDRESS = 32'h80202000;
  localparam [31:0] DEBUG_DATA = 32'h11223344;

  CommonI1RuntimeDebugFixture dut(
    .debugClock(debugClock), .debugLinkUp(debugLinkUp),
    .debug_request_valid(debug_request_valid), .debug_request_ready(debug_request_ready),
    .debug_request_bits_address(debug_request_address), .debug_request_bits_data(debug_request_data),
    .debug_request_bits_op(debug_request_op), .debug_response_valid(debug_response_valid),
    .debug_response_ready(1'b1), .debug_response_bits_data(debug_response_data), .debug_response_bits_status(debug_response_status),
    .debugBusy(debugBusy), .debugFault(debugFault), .debugHeld_valid(debugHeld_valid), .debugHeld_bits(debugHeld_bits),
    .observe_holdMemoryRequest(holdMemoryRequest), .observe_holdMemoryResponse(holdMemoryResponse),
    .observe_holdControlResponse(holdControlResponse), .observe_memoryRequestBlocked(memoryRequestBlocked),
    .observe_memoryResponseBlocked(memoryResponseBlocked), .observe_controlResponseBlocked(controlResponseBlocked),
    .observe_memoryRequestFire(memoryRequestFire), .observe_memoryRequestAddress(memoryRequestAddress),
    .observe_memoryRequestData(memoryRequestData), .observe_memoryRequestWrite(memoryRequestWrite),
    .observe_memoryRequestSize(memoryRequestSize), .observe_memoryRequestByteEnable(memoryRequestByteEnable),
    .observe_memoryResponseFire(memoryResponseFire), .observe_memoryResponseData(memoryResponseData),
    .observe_memoryResponseError(memoryResponseError), .observe_controlRequestFire(controlRequestFire),
    .observe_controlRequestAddress(controlRequestAddress), .observe_controlRequestData(controlRequestData),
    .observe_controlRequestWrite(controlRequestWrite), .observe_controlResponseFire(controlResponseFire),
    .observe_controlResponseError(controlResponseError), .observe_dmiOwnersIdle(dmiOwnersIdle),
    .observe_controlOwnersIdle(controlOwnersIdle),
    .cpuClock(cpuClock), .fabricClock(fabricClock), .alwaysOnClock(alwaysOnClock), .commonColdReset(reset),
    .io_start(start), .io_program_valid(program_valid), .io_program_bits_index(program_index), .io_program_bits_data(program_data),
    .io_requests_0_valid(request_valid[0]), .io_requests_0_bits(request_bits[0]), .io_requests_0_ready(request_ready[0]),
    .io_requests_1_valid(request_valid[1]), .io_requests_1_bits(request_bits[1]), .io_requests_1_ready(request_ready[1]),
    .io_resume_0_valid(resume_valid[0]), .io_resume_0_bits_token(resume_bits[0]), .io_resume_0_bits_epoch(resume_epoch[0]), .io_resume_0_ready(resume_ready[0]),
    .io_resume_1_valid(resume_valid[1]), .io_resume_1_bits_token(resume_bits[1]), .io_resume_1_bits_epoch(resume_epoch[1]), .io_resume_1_ready(resume_ready[1]),
    .io_cancel_0_valid(cancel_valid[0]), .io_cancel_0_bits_token(cancel_bits[0]), .io_cancel_0_bits_epoch(cancel_epoch[0]), .io_cancel_0_ready(cancel_ready[0]),
    .io_cancel_1_valid(cancel_valid[1]), .io_cancel_1_bits_token(cancel_bits[1]), .io_cancel_1_bits_epoch(cancel_epoch[1]), .io_cancel_1_ready(cancel_ready[1]),
    .io_held_0_valid(held_valid[0]), .io_held_0_bits_token(held_token[0]), .io_held_0_bits_epoch(held_epoch[0]),
    .io_held_1_valid(held_valid[1]), .io_held_1_bits_token(held_token[1]), .io_held_1_bits_epoch(held_epoch[1]),
    .io_result_0_valid(result_valid[0]), .io_result_0_ready(result_ready[0]), .io_result_0_bits_token(result_token[0]),
    .io_result_0_bits_epoch(result_epoch[0]), .io_result_0_bits_canceled(result_canceled[0]), .io_result_0_bits_timedOut(result_timedOut[0]),
    .io_result_1_valid(result_valid[1]), .io_result_1_ready(result_ready[1]), .io_result_1_bits_token(result_token[1]),
    .io_result_1_bits_epoch(result_epoch[1]), .io_result_1_bits_canceled(result_canceled[1]), .io_result_1_bits_timedOut(result_timedOut[1]),
    .io_busy(busy), .io_timeoutSelected(timeoutSelected), .io_cleanupFault(cleanupFault), .io_epochExhausted(epochExhausted),
    .io_activeLane(activeLane), .io_activeEpoch(activeEpoch), .io_activeToken(activeToken),
    .io_externalStop(externalStop), .io_holdReleaseAck(holdReleaseAck), .io_holdCompletion(holdCompletion),
    .io_holdCpuCompletion(holdCpuCompletion), .io_cpuCompletionBlocked(cpuCompletionBlocked),
    .io_releaseAckBlocked(releaseAckBlocked), .io_completionBlocked(completionBlocked),
    .io_sources(sources), .io_holdMsiReply(holdMsiReply), .io_msiReplyBlocked(msiReplyBlocked),
    .io_msiAccepted(msiAccepted), .io_msiReplied(msiReplied),
    .io_msiAccepted11(msiAccepted11), .io_msiAccepted12(msiAccepted12), .io_msiAccepted13(msiAccepted13),
    .io_tileHeld_valid(tileHeld_valid), .io_tileHeld_bits(tileHeld_bits),
    .io_fabricHeld_valid(fabricHeld_valid), .io_fabricHeld_bits(fabricHeld_bits),
    .io_retire_valid(retire_valid), .io_retire_bits_pc(retire_pc), .io_retire_bits_instruction(retire_instruction),
    .io_retire_bits_rd(retire_rd), .io_retire_bits_data(retire_data), .io_retire_bits_writesRd(retire_writesRd),
    .io_trap(trap), .io_releaseBeats(releaseBeats), .io_coherentAcquires(coherentAcquires), .io_fabricIdle(fabricIdle),
    .io_cpuResumed(cpuResumed), .io_fabricPrepares(fabricPrepares), .io_fabricResumes(fabricResumes),
    .io_fabricCancels(fabricCancels), .io_fabricTerminals(fabricTerminals),
    .io_fabricTerminalValid(fabricTerminalValid), .io_fabricTerminalReady(fabricTerminalReady),
    .io_cpuLinkReady(cpuLinkReady), .io_fabricLinkReady(fabricLinkReady),
    .io_cpuTransportEmpty(cpuTransportEmpty), .io_fabricTransportEmpty(fabricTransportEmpty));

  always @(posedge alwaysOnClock) begin
    aonCycles = aonCycles + 1;
    if (aonCycles > 150000) $fatal(1, "four-clock debug AON watchdog");
    if (reset) begin
      for (integer j = 0; j < 2; j = j + 1) begin
        requests[j] = 0; resumes[j] = 0; cancels[j] = 0; results[j] = 0; acceptedCycle[j] = 0;
      end
    end else begin
      if ((request_valid & request_ready) == 2'b11 || held_valid == 2'b11 || result_valid == 2'b11)
        $fatal(1, "shared runtime owner routed twice");
      if ((cleanupFault && !expectedFault) || epochExhausted) $fatal(1, "unexpected runtime cleanup fault");
      for (integer j = 0; j < 2; j = j + 1) begin
        if (request_valid[j] && request_ready[j]) begin requests[j] = requests[j] + 1; acceptedCycle[j] = aonCycles; end
        if (resume_valid[j] && resume_ready[j]) resumes[j] = resumes[j] + 1;
        if (cancel_valid[j] && cancel_ready[j]) cancels[j] = cancels[j] + 1;
        if (result_valid[j] && result_ready[j]) results[j] = results[j] + 1;
      end
    end
  end
  always @(posedge cpuClock) begin
    cycles = cycles + 1;
    if (cycles > 300000) $fatal(1, "real I1 debug CPU watchdog");
    if (reset) begin
      retires = 0; stores = 0; loads = 0; previousLoads = 0; loops = 0; pendingReads = 0; loopPhase = 0;
      expectedData = 0;
    end else begin
      if (start && trap) $fatal(1, "unexpected real I1 trap");
      if (start && retire_valid) begin
        retires = retires + 1;
        if (retire_pc == PC_GUEST_FAIL) $fatal(1, "guest memory comparison failed");
        if (retire_pc == PC_CONTROL_OPEN && retire_instruction !== 32'h0054b423)
          $fatal(1, "CPU loader open did not retire actual scalar store");
        if (retire_pc == PC_CONTROL_GENERATION && (!retire_writesRd || retire_rd != 19 || retire_data !== 1))
          $fatal(1, "CPU loader generation readback oracle");
        if (retire_pc == PC_LOOP_PREVIOUS) begin
          if (loopPhase != 0 || !retire_writesRd || retire_rd != 23 || retire_data !== expectedData)
            $fatal(1, "independent previous-store persistence oracle");
          loopPhase = 6; previousLoads = previousLoads + 1;
        end
        if (retire_pc == PC_LOOP_PREVIOUS_COMPARE) begin
          if (loopPhase != 6) $fatal(1, "independent previous-store comparison order");
          loopPhase = 7;
        end
        if (retire_pc == PC_LOOP_INCREMENT) begin
          if (loopPhase != 7) $fatal(1, "duplicate or skipped independent increment retirement");
          loopPhase = 1; expectedData = expectedData + 1;
          if (!retire_writesRd || retire_rd != 20 || retire_data !== expectedData)
            $fatal(1, "independent increment data oracle");
        end
        if (retire_pc == PC_LOOP_STORE) begin
          if (loopPhase != 1) $fatal(1, "duplicate or skipped independent store retirement");
          loopPhase = 2; stores = stores + 1;
        end
        if (retire_pc == PC_LOOP_LOAD) begin
          if (loopPhase != 2) $fatal(1, "duplicate or skipped independent load retirement");
          loopPhase = 3; loads = loads + 1;
          if (!retire_writesRd || retire_rd != 21 || retire_data !== expectedData)
            $fatal(1, "independent load data oracle");
        end
        if (retire_pc == PC_LOOP_COMPARE) begin
          if (loopPhase != 3) $fatal(1, "independent memory comparison order");
          loopPhase = 4;
        end
        if (retire_pc == PC_LOOP_CONTROL) begin
          if (loopPhase != 4 || !retire_writesRd || retire_rd != 22)
            $fatal(1, "real CPU control MMIO retirement missing");
          loopPhase = 5; pendingReads = pendingReads + 1;
        end
        if (retire_pc == PC_LOOP_JUMP) begin
          if (loopPhase != 5) $fatal(1, "independent loop jump retirement order");
          loopPhase = 0; loops = loops + 1;
        end
      end
    end
  end
  // Independent request ledger records only actual source acceptance; replies
  // are checked against requested register semantics, never DUT owner state.
  always @(posedge debugClock) begin
    if (reset) begin sourceRequests = 0; sourceResponses = 0; debugReads = 0; debugTerminals = 0; end
    else begin
      // Passive original-module port observations: no force, bind, or RTL edits.
      if (dut.sequencer.boundary.terminal_valid && dut.sequencer.boundary.terminal_ready) begin
        if (debugTerminals >= results[0] + results[1] || !dut.sequencer.terminalConsumedAtAon)
          $fatal(1, "debug original terminal retired before AON consumer receipt");
        debugTerminals = debugTerminals + 1;
      end
      if (debug_request_valid && debug_request_ready) begin
        if (sourceRequests >= 256) $fatal(1, "source request ledger overflow");
        if (debug_request_op == 2) expectedSourceReply[sourceRequests] = 0;
        else if (debug_request_op == 1 && debug_request_address == 7'h40)
          expectedSourceReply[sourceRequests] = 32'h564c0101;
        else if (debug_request_op == 1 && debug_request_address == 7'h3c) begin
          expectedSourceReply[sourceRequests] = DEBUG_DATA + (wrongData ? 1 : 0); debugReads = debugReads + 1;
        end else $fatal(1, "unplanned source DMI request");
        sourceRequests = sourceRequests + 1;
      end
      if (debug_response_valid) begin
        if (sourceResponses >= sourceRequests || debug_response_status !== 0 ||
            debug_response_data !== expectedSourceReply[sourceResponses])
          $fatal(1, "independent debug readback data oracle");
        sourceResponses = sourceResponses + 1;
      end
    end
  end
  // This edge is loader.memory before the real arbiter->Atomic->Home path.
  always @(posedge fabricClock) begin
    if (reset) begin
      memoryRequests = 0; memoryResponses = 0; controlRequests = 0; controlResponses = 0;
      controlWrites = 0; controlReads = 0; debugRetirementReceipts = 0;
    end else begin
      if (dut.sequencer.retirement.destination_valid && dut.sequencer.retirement.destination_ready) begin
        if (debugTerminals != debugRetirementReceipts + 1)
          $fatal(1, "debug retirement receipt preceded original debug terminal");
        debugRetirementReceipts = debugRetirementReceipts + 1;
      end
      if (fabricTerminalValid && fabricTerminalReady) begin
        if (!dut.sequencer.retirementPermit || !dut.sequencer.terminalConsumedAtAon ||
            debugRetirementReceipts != fabricTerminals + 1 || debugTerminals != fabricTerminals + 1)
          $fatal(1, "actual fabric retirement preceded actual debug retirement receipt");
      end
      if (memoryRequestFire) begin
        if (memoryRequests >= plannedMemory || memoryRequests != memoryResponses ||
            memoryRequestAddress !== {32'b0, DEBUG_ADDRESS} || memoryRequestSize !== 2 ||
            memoryRequestByteEnable !== 8'h0f || memoryRequestWrite !== expectedMemoryWrite[memoryRequests] ||
            (memoryRequestWrite && memoryRequestData !== {32'b0, expectedMemoryData[memoryRequests]}))
          $fatal(1, "independent actual loader memory request ledger");
        memoryRequests = memoryRequests + 1;
      end
      if (memoryResponseFire) begin
        if (memoryResponses >= memoryRequests || memoryResponseError ||
            (!expectedMemoryWrite[memoryResponses] && memoryResponseData[31:0] !== DEBUG_DATA))
          $fatal(1, "independent actual Home memory response ledger");
        memoryResponses = memoryResponses + 1;
      end
      if (controlRequestFire) begin
        if (controlRequestWrite) begin
          if (controlRequestAddress !== 64'h10003008 || controlRequestData !== 1 || controlWrites != 0)
            $fatal(1, "independent CPU loader arm store ledger");
          controlWrites = controlWrites + 1;
        end else begin
          if (controlRequestAddress !== 64'h10003000 && controlRequestAddress !== 64'h10003028)
            $fatal(1, "independent CPU loader MMIO read ledger");
          controlReads = controlReads + 1;
        end
        controlRequests = controlRequests + 1;
      end
      if (controlResponseFire) begin
        if (controlResponses >= controlRequests || controlResponseError)
          $fatal(1, "independent CPU loader control response ledger");
        controlResponses = controlResponses + 1;
      end
    end
  end

  task tick; begin @(posedge alwaysOnClock); #1; @(negedge alwaysOnClock); end endtask
  task cpuTick; begin @(posedge cpuClock); #1; @(negedge cpuClock); end endtask
  task fabricTick; begin @(posedge fabricClock); #1; @(negedge fabricClock); end endtask
  task debugTick; begin @(posedge debugClock); #1; @(negedge debugClock); end endtask
  task advanceLoops(input integer count);
    integer target;
    begin target = loops + count; while (loops < target || loopPhase != 0) cpuTick(); end
  endtask
  task boot;
    begin
      reset = 1; start = 0; expectedFault = 0; debugLinkUp = 1; debug_request_valid = 0;
      request_valid = 0; resume_valid = 0; cancel_valid = 0; result_ready = 0;
      holdMemoryRequest = 0; holdMemoryResponse = 0; holdControlResponse = 0;
      program_valid = 0; plannedMemory = 0;
      repeat (12) tick(); reset = 0; repeat (16) fabricTick();
      for (integer n = 0; n < 256; n = n + 1) begin
        program_valid = 1; program_index = n; program_data = rom[n]; fabricTick();
      end
      program_valid = 0; start = 1; advanceLoops(2);
      if (controlWrites != 1 || controlReads < 3) $fatal(1, "real CPU scalar loader boot missing");
      $display("I1_RUNTIME_DEBUG_BOOT cpu_control_writes=%0d reads=%0d loops=%0d", controlWrites, controlReads, loops);
    end
  endtask
  task dmi(input [1:0] op, input [6:0] address, input [31:0] data);
    integer beforeRequests, beforeResponses;
    begin
      @(negedge debugClock); beforeRequests = sourceRequests; beforeResponses = sourceResponses;
      debug_request_op = op; debug_request_address = address; debug_request_data = data; debug_request_valid = 1;
      while (sourceRequests == beforeRequests) debugTick(); debug_request_valid = 0;
      while (sourceResponses == beforeResponses) debugTick();
    end
  endtask
  task planMemory(input bit write);
    begin expectedMemoryWrite[plannedMemory] = write; expectedMemoryData[plannedMemory] = DEBUG_DATA;
      plannedMemory = plannedMemory + 1; end
  endtask
  task requestEpoch(input integer which, input [31:0] token);
    integer beforeCount;
    begin
      @(negedge alwaysOnClock); beforeCount = requests[which]; request_bits[which] = token; request_valid[which] = 1;
      while (requests[which] == beforeCount) tick(); request_valid[which] = 0; allocatedEpoch[which] = activeEpoch;
    end
  endtask
  task waitHeld(input integer which);
    begin
      while (!held_valid[which]) tick();
      if (!debugHeld_valid || debugHeld_bits != allocatedEpoch[which] || !tileHeld_valid || !fabricHeld_valid ||
          tileHeld_bits != allocatedEpoch[which] || fabricHeld_bits != allocatedEpoch[which] ||
          !fabricIdle || !dmiOwnersIdle || !controlOwnersIdle || memoryRequests != memoryResponses ||
          controlRequests != controlResponses || !cpuTransportEmpty || !fabricTransportEmpty)
        $fatal(1, "independent full-system held proof lacked real owners");
    end
  endtask
  task resumeEpoch(input integer which, input [31:0] token);
    integer beforeCount;
    begin
      @(negedge alwaysOnClock); beforeCount = resumes[which]; resume_bits[which] = token;
      resume_epoch[which] = allocatedEpoch[which]; resume_valid[which] = 1;
      while (resumes[which] == beforeCount) tick(); resume_valid[which] = 0;
    end
  endtask
  task cancelEpoch(input integer which, input [31:0] token);
    integer beforeCount;
    begin
      @(negedge alwaysOnClock); beforeCount = cancels[which]; cancel_bits[which] = token;
      cancel_epoch[which] = allocatedEpoch[which]; cancel_valid[which] = 1;
      while (cancels[which] == beforeCount) tick(); cancel_valid[which] = 0;
    end
  endtask
  task presentBlockedDmi;
    begin
      @(negedge debugClock); debug_request_op = 1; debug_request_address = 7'h40;
      debug_request_data = 0; debug_request_valid = 1;
    end
  endtask
  task terminal(input integer which, input [31:0] token, input bit canceled, input bit timedOut);
    integer beforeCount, fabricBefore, sourceBefore, n;
    begin
      beforeCount = results[which]; fabricBefore = fabricTerminals; sourceBefore = sourceRequests;
      while (!result_valid[which]) tick();
      for (n = 0; n < 40; n = n + 1) begin
        if (!result_valid[which] || result_valid[1-which] || result_token[which] != token ||
            result_epoch[which] != allocatedEpoch[which] || result_canceled[which] != canceled ||
            result_timedOut[which] != timedOut || !busy || request_ready != 0 ||
            !fabricTerminalValid || fabricTerminalReady || fabricTerminals != fabricBefore)
          $fatal(1, "terminal token/epoch/decision changed or retired before AON consumption");
        if (debug_request_ready || sourceRequests != sourceBefore)
          $fatal(1, "new DMI admitted before AON terminal consumption");
        tick();
      end
      result_ready[which] = 1;
      while (results[which] == beforeCount) tick(); result_ready[which] = 0;
      while (busy || debugBusy) tick();
      repeat (12) tick();
      if (results[which] != beforeCount + 1 || fabricTerminals != fabricBefore + 1 || result_valid != 0 ||
          debugTerminals != fabricTerminals || debugRetirementReceipts != fabricTerminals)
        $fatal(1, "runtime terminal was not consumed exactly once");
      $display("I1_RUNTIME_DEBUG_TERMINAL epoch=%0d aon=%0d debug=%0d receipt=%0d fabric=%0d busy=%0b",
          allocatedEpoch[which], results[0] + results[1], debugTerminals, debugRetirementReceipts, fabricTerminals, busy);
    end
  endtask
  task finishBlockedDmi(input integer oldRequests, input integer oldResponses);
    begin
      while (sourceRequests == oldRequests) debugTick(); debug_request_valid = 0;
      while (sourceResponses == oldResponses) debugTick(); repeat (8) debugTick();
      if (sourceRequests != oldRequests + 1 || sourceResponses != oldResponses + 1)
        $fatal(1, "held new DMI did not complete exactly once after reopening");
    end
  endtask
  task noFabricWhileOld(input integer prepareBefore, input integer duration);
    begin
      for (integer n = 0; n < duration; n = n + 1) begin
        tick();
        if (fabricPrepares != prepareBefore + (wrongDrain ? 1 : 0) || held_valid != 0 ||
            debugHeld_valid || result_valid != 0 || dmiOwnersIdle)
          $fatal(1, "independent debug drain oracle: early source reply is not RAM completion");
      end
    end
  endtask
  task readback;
    integer beforeResponses;
    begin
      dmi(2, 7'h38, 32'h00140000); // 32-bit access, read-on-address.
      beforeResponses = memoryResponses; planMemory(0); dmi(2, 7'h39, DEBUG_ADDRESS);
      while (memoryResponses == beforeResponses) fabricTick();
      dmi(1, 7'h3c, 0);
      if (sourceRequests != sourceResponses || memoryRequests != memoryResponses)
        $fatal(1, "independent debug readback left an owner");
    end
  endtask
  integer beforePrepares, beforeRequests, beforeResponses, beforeMemory, beforeCancel, beforeLoops;
  initial begin
    if (!$value$plusargs("rom=%s", rom_path)) $fatal(1, "guest ROM path required");
    $readmemh(rom_path, rom);
    wrongData = $test$plusargs("wrong-data"); wrongDrain = $test$plusargs("wrong-drain");
    for (i = 0; i < 2; i = i + 1) begin request_bits[i] = 0; resume_bits[i] = 0; cancel_bits[i] = 0;
      resume_epoch[i] = 0; cancel_epoch[i] = 0; allocatedEpoch[i] = 0; end
    boot();

    // An early source DMI write response is NOT a drained RAM owner. Preserve
    // both offered and accepted-but-unreturned states through a real AON timeout.
    dmi(2, 7'h39, DEBUG_ADDRESS); holdMemoryRequest = 1; planMemory(1); dmi(2, 7'h3c, DEBUG_DATA);
    while (!memoryRequestBlocked) fabricTick();
    if (sourceRequests != sourceResponses || memoryRequests != 0 || memoryResponses != 0)
      $fatal(1, "early DMI reply scenario did not retain genuine offered memory");
    beforePrepares = fabricPrepares; requestEpoch(0, 32'h51000001); noFabricWhileOld(beforePrepares, 80);
    holdMemoryResponse = 1; holdMemoryRequest = 0;
    while (!memoryResponseBlocked) fabricTick();
    if (memoryRequests != 1 || memoryResponses != 0) $fatal(1, "real RAM response was not retained");
    noFabricWhileOld(beforePrepares, 80);
    while (!timeoutSelected) begin noFabricWhileOld(beforePrepares, 1); end
    if (aonCycles - acceptedCycle[0] < 4096 || cancels[0] != 0 || fabricCancels != 0)
      $fatal(1, "actual 4096-AON timeout was replaced by test cancellation");
    noFabricWhileOld(beforePrepares, 20); holdMemoryResponse = 0;
    terminal(0, 32'h51000001, 1, 1);
    if (memoryResponses != 1 || fabricCancels != 1 || fabricPrepares != beforePrepares + 1)
      $fatal(1, "timeout did not finish real old owner then real fabric cancel");
    readback(); advanceLoops(2);
    $display("I1_RUNTIME_DEBUG_TIMEOUT source=%0d/%0d memory=%0d/%0d actual_aon_timeout=4096 fabric_cancels=%0d", sourceRequests, sourceResponses, memoryRequests, memoryResponses, fabricCancels);

    // Held and terminal backpressure both close admission. The queued new DMI
    // completes once only after the terminal consumer's receipt reaches debug.
    requestEpoch(1, 32'h51000002); waitHeld(1);
    beforeRequests = sourceRequests; beforeResponses = sourceResponses; beforeLoops = loops;
    presentBlockedDmi();
    repeat (40) begin tick();
      if (!held_valid[1] || sourceRequests != beforeRequests || debug_request_ready || loops != beforeLoops)
        $fatal(1, "held epoch admitted CPU or new source DMI work");
    end
    resumeEpoch(1, 32'h51000002);
    fork
      terminal(1, 32'h51000002, 0, 0);
      finishBlockedDmi(beforeRequests, beforeResponses);
    join
    advanceLoops(2);
    $display("I1_RUNTIME_DEBUG_NORMAL lane=1 exact_terminal=%0d new_dmi_once=1", results[1]);

    // Explicit cancellation is latched while debug is draining, but cannot
    // withdraw an offered memory owner or send CPU prepare ahead of debug-held.
    dmi(2, 7'h38, 32'h00040000); dmi(2, 7'h39, DEBUG_ADDRESS);
    holdMemoryRequest = 1; planMemory(1); dmi(2, 7'h3c, DEBUG_DATA);
    while (!memoryRequestBlocked) fabricTick(); beforePrepares = fabricPrepares;
    beforeCancel = fabricCancels; requestEpoch(0, 32'h51000003); cancelEpoch(0, 32'h51000003);
    noFabricWhileOld(beforePrepares, 80); holdMemoryRequest = 0;
    terminal(0, 32'h51000003, 1, 0);
    if (fabricCancels != beforeCancel + 1) $fatal(1, "explicit cancel missing real fabric terminal");
    readback(); advanceLoops(2);
    $display("I1_RUNTIME_DEBUG_CANCEL source=%0d/%0d memory=%0d/%0d", sourceRequests, sourceResponses, memoryRequests, memoryResponses);

    // Debug-only idle deliberately excludes CPU-control reply ownership; full
    // platform qualification must retain it until the actual scalar reply fires.
    holdControlResponse = 1; while (!controlResponseBlocked) fabricTick();
    beforePrepares = fabricPrepares; requestEpoch(1, 32'h51000004);
    while (!debugHeld_valid || fabricPrepares == beforePrepares) tick();
    repeat (80) begin tick();
      if (held_valid != 0 || fabricIdle || controlOwnersIdle || !controlResponseBlocked ||
          !debugHeld_valid || !dmiOwnersIdle || controlRequests == controlResponses)
        $fatal(1, "CPU control reply did not block final qualification while debug held");
    end
    holdControlResponse = 0; waitHeld(1); resumeEpoch(1, 32'h51000004); terminal(1, 32'h51000004, 0, 0);
    advanceLoops(2);
    $display("I1_RUNTIME_DEBUG_CPU_CONTROL request=%0d response=%0d actual_scalar_retire_reads=%0d", controlRequests, controlResponses, pendingReads);

    // A pulse entirely between debug edges must cause persistent fault during
    // an active barrier; the real old RAM response still completes, never aborts.
    dmi(2, 7'h38, 32'h00040000); dmi(2, 7'h39, DEBUG_ADDRESS);
    holdMemoryResponse = 1; planMemory(1); dmi(2, 7'h3c, DEBUG_DATA);
    while (!memoryResponseBlocked) fabricTick(); beforePrepares = fabricPrepares;
    requestEpoch(0, 32'h51000005); while (!debugBusy) tick();
    expectedFault = 1; @(negedge debugClock); #1; debugLinkUp = 0; #1; debugLinkUp = 1;
    while (!debugFault) tick(); holdMemoryResponse = 0;
    while (memoryRequests != memoryResponses) fabricTick();
    repeat (100) begin tick();
      if (!debugFault || held_valid != 0 || result_valid != 0 || fabricPrepares != beforePrepares || debug_request_ready)
        $fatal(1, "active link loss escaped conservative fault/reset contract");
    end
    $display("I1_RUNTIME_DEBUG_LINK_FAULT old_memory_completed=%0d terminal_absent=1", memoryResponses);
    boot(); requestEpoch(0, 32'h51000006); waitHeld(0); resumeEpoch(0, 32'h51000006);
    terminal(0, 32'h51000006, 0, 0); dmi(1, 7'h40, 0); advanceLoops(2);
    if (debugFault || sourceRequests != sourceResponses || fabricTerminals != 1 || controlWrites != 1)
      $fatal(1, "common reset did not recover all actual owners");
    // A late fault must not withdraw an already-offered Decoupled AON result.
    // Even after that copy is consumed, neither original owner may retire.
    requestEpoch(1, 32'h51000007); waitHeld(1); resumeEpoch(1, 32'h51000007);
    while (!result_valid[1]) tick(); beforePrepares = fabricTerminals;
    expectedFault = 1; @(negedge debugClock); #1; debugLinkUp = 0; #1; debugLinkUp = 1;
    while (!debugFault || !cleanupFault) tick();
    repeat (40) begin tick();
      if (!result_valid[1] || result_token[1] != 32'h51000007 ||
          result_epoch[1] != allocatedEpoch[1] || result_canceled[1] || result_timedOut[1] ||
          !busy || request_ready != 0 || held_valid != 0 || fabricTerminals != beforePrepares || debug_request_ready)
        $fatal(1, "late link fault withdrew offered result or retired actual owner");
    end
    beforeRequests = results[1]; result_ready[1] = 1;
    while (results[1] == beforeRequests) tick(); result_ready[1] = 0;
    repeat (80) begin tick();
      if (!debugFault || !cleanupFault || !busy || !debugBusy || request_ready != 0 ||
          held_valid != 0 || result_valid != 0 || fabricTerminals != beforePrepares || debug_request_ready)
        $fatal(1, "late fault consumed-copy escaped common-reset-only owner retention");
    end
    $display("I1_RUNTIME_DEBUG_LATE_FAULT offered_result_stable=1 consumed_copy=1 actual_retirement=0");
    boot(); requestEpoch(0, 32'h51000008); waitHeld(0); resumeEpoch(0, 32'h51000008);
    terminal(0, 32'h51000008, 0, 0); dmi(1, 7'h40, 0); advanceLoops(2);
    $display("I1_RUNTIME_DEBUG_PASS ratios=%0d/%0d/%0d/%0d loops=%0d control=%0d/%0d", cpuHalf, fabricHalf, aonHalf, debugHalf, loops, controlRequests, controlResponses);
    $finish;
  end
endmodule
