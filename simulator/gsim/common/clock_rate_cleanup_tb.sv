`timescale 1ns/1ps
module clock_rate_cleanup_tb;
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
  reg [5:0] program_index = 0;
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
  reg [31:0] rom [0:63]; reg [4095:0] rom_path;
  reg wrongData = 0, wrongStore = 0, wrongIrq = 0;
  integer cycles = 0, aonCycles = 0, resetGeneration = 0;
  integer retires = 0, stores = 0, loads = 0, previousLoads = 0, loops = 0, pendingReads = 0, loopPhase = 0;
  integer requests [0:1], resumes [0:1], cancels [0:1], results [0:1], acceptedCycle [0:1];
  integer expected11 = 0, expected12 = 0, expected13 = 0;
  reg [63:0] expectedData = 0, eventMask = 0, lastPending = 0;
  integer i, lane, old, oldCpuResumed, oldFabricPrepares, oldFabricCancels;

  reg [1:0] controlSubmit = 0, controlCommitted = 0, holdTerminal = 3;
  wire [1:0] controlBusy, controlQuiesce, controlClockEnable, controlSuccess;
  wire [1:0] requestFire, terminalFire, retired;
  wire [3:0] controlState [0:1];
  wire [31:0] controlCompleted [0:1], controlErrors [0:1], controlRequestError [0:1];
  wire deadline, proofObserved;
  integer terminalsConsumed [0:1], retirements [0:1];
  integer oldCompleted, oldTerminals, oldAccepted, n;
  CommonClockRateCleanupFixture dut(
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
    .io_cpuTransportEmpty(cpuTransportEmpty), .io_fabricTransportEmpty(fabricTransportEmpty),
    .control_submit_0_valid(controlSubmit[0]), .control_submit_0_bits(32'd55000000),
    .control_submit_1_valid(controlSubmit[1]), .control_submit_1_bits(32'd55000000),
    .control_responseCommitted(controlCommitted), .control_holdTerminal(holdTerminal),
    .control_busy(controlBusy), .control_quiesce(controlQuiesce), .control_clockEnable(controlClockEnable),
    .control_success(controlSuccess), .control_state_0(controlState[0]), .control_state_1(controlState[1]),
    .control_completed_0(controlCompleted[0]), .control_completed_1(controlCompleted[1]),
    .control_errors_0(controlErrors[0]), .control_errors_1(controlErrors[1]),
    .control_requestError_0(controlRequestError[0]), .control_requestError_1(controlRequestError[1]),
    .control_requestFire(requestFire), .control_terminalFire(terminalFire), .control_retired(retired),
    .control_deadline(deadline), .control_proofObserved(proofObserved));

  always @(posedge alwaysOnClock) begin
    aonCycles = aonCycles + 1;
    if (aonCycles > 180000) $fatal(1, "cleanup AON watchdog");
    if (reset) begin
      for (integer j = 0; j < 2; j = j + 1) begin
        requests[j] = 0; terminalsConsumed[j] = 0; retirements[j] = 0; acceptedCycle[j] = 0;
      end
    end else begin
      if (requestFire == 3) $fatal(1, "two controller leases accepted together");
      if (epochExhausted) $fatal(1, "unexpected epoch exhaustion");
      for (integer j = 0; j < 2; j = j + 1) begin
        if (requestFire[j]) begin requests[j] = requests[j] + 1; acceptedCycle[j] = aonCycles; end
        if (terminalFire[j]) terminalsConsumed[j] = terminalsConsumed[j] + 1;
        if (retired[j]) retirements[j] = retirements[j] + 1;
        if (controlCompleted[j] > retirements[j]) $fatal(1, "controller completed before actual fabric retirement");
        if (controlState[j] == 3 || controlState[j] == 4 || controlSuccess[j])
          $fatal(1, "timeout-only fixture entered rate change or claimed success");
      end
    end
  end
  // Independent ledgers use physical input transitions and architectural PCs,
  // never DUT pending state or DUT-derived instruction expectations.
  always @(posedge cpuClock) begin
    cycles = cycles + 1;
    if (cycles > 450000) $fatal(1, "I1 three-clock CPU watchdog");
    if (reset) begin
      retires = 0; stores = 0; loads = 0; previousLoads = 0; loops = 0; pendingReads = 0; loopPhase = 0;
      expectedData = 0; lastPending = 0;
    end else begin
      if (msiAccepted !== msiAccepted11 + msiAccepted12 + msiAccepted13)
        $fatal(1, "MSI delivered an unrequested identity");
      if (msiAccepted11 > expected11 || msiAccepted12 > expected12 || msiAccepted13 > expected13)
        $fatal(1, "independent MSI event ledger: duplicate or unrequested delivery");
      if (start && trap) $fatal(1, "unexpected real I1 trap");
      if (start && retire_valid) begin
        retires = retires + 1;
        if (retire_pc == PC_GUEST_FAIL) $fatal(1, "guest memory comparison failed");
        if (retire_pc == PC_LOOP_PREVIOUS) begin
          if (loopPhase != 0 || !retire_writesRd || retire_rd != 23 || retire_data !== expectedData + (wrongStore ? 1 : 0))
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
          if (!retire_writesRd || retire_rd != 21 || retire_data !== expectedData + (wrongData ? 1 : 0))
            $fatal(1, "independent load data oracle");
        end
        if (retire_pc == PC_LOOP_COMPARE) begin
          if (loopPhase != 3) $fatal(1, "independent memory comparison order");
          loopPhase = 4;
        end
        if (retire_pc == PC_LOOP_PENDING) begin
          if (loopPhase != 4 || !retire_writesRd || retire_rd != 22 || retire_instruction !== 32'h35102b73)
            $fatal(1, "real IMSIC pending CSR retirement missing");
          loopPhase = 5; pendingReads = pendingReads + 1;
          if ((retire_data & ~eventMask) !== 0 || (retire_data & lastPending) !== lastPending)
            $fatal(1, "independent IMSIC pending oracle: unexpected or lost pending identity");
          lastPending = retire_data;
        end
        if (retire_pc == PC_LOOP_JUMP) begin
          if (loopPhase != 5) $fatal(1, "independent loop jump retirement order");
          loopPhase = 0; loops = loops + 1;
        end
      end
    end
  end

  task tick; begin @(posedge alwaysOnClock); #1; @(negedge alwaysOnClock); end endtask
  task cpuTick; begin @(posedge cpuClock); #1; @(negedge cpuClock); end endtask
  task fabricTick; begin @(posedge fabricClock); #1; @(negedge fabricClock); end endtask

  task setSources(input [2:0] value);
    reg [2:0] rising;
    begin
      @(negedge fabricClock);
      rising = value & ~sources[2:0];
      if (rising[0]) begin expected11 = expected11 + 1; eventMask = eventMask | 64'h800; end
      if (rising[1]) begin expected12 = expected12 + 1; eventMask = eventMask | 64'h1000; end
      if (rising[2]) begin expected13 = expected13 + 1; eventMask = eventMask | 64'h2000; end
      sources = {61'b0, value};
    end
  endtask
  task advanceLoops(input integer count);
    integer target;
    begin target = loops + count; while (loops < target || loopPhase != 0) cpuTick(); end
  endtask
  task submitRates(input [1:0] lanes);
    begin
      @(negedge alwaysOnClock);
      for (integer j = 0; j < 2; j = j + 1)
        if (lanes[j] && controlState[j] != 0) $fatal(1, "submit to non-idle controller");
      controlSubmit = lanes; tick(); controlSubmit = 0;
      for (integer j = 0; j < 2; j = j + 1)
        if (lanes[j] && controlState[j] != 1) $fatal(1, "rate request not reserved until response receipt");
      controlCommitted = lanes; tick(); controlCommitted = 0;
    end
  endtask
  task waitTimeout(input integer which);
    begin
      while (!timeoutSelected || activeLane != which) tick();
      if (aonCycles - acceptedCycle[which] != 4096)
        $fatal(1, "real boundary timeout did not occur at exact allocated AON age");
      repeat (4) tick();
      if (!(controlErrors[which] & 32'h10) || !controlBusy[which] || !controlQuiesce[which] ||
          !controlClockEnable[which] || controlCompleted[which] != oldCompleted)
        $fatal(1, "actual AON timeout did not retain controller cleanup ownership");
      $display("CLOCK_RATE_CLEANUP_TIMEOUT lane=%0d epoch=%0d actual_aon_age=4096",which,activeEpoch); $fflush();
    end
  endtask
  task finishCleanup(input integer which);
    integer beforeConsumed, beforeRetired, beforeCompleted, beforeFabric;
    begin
      beforeConsumed = terminalsConsumed[which]; beforeRetired = retirements[which];
      beforeCompleted = controlCompleted[which]; beforeFabric = fabricTerminals;
      while (!result_valid[which]) tick();
      for (integer k = 0; k < 32; k = k + 1) begin
        if (!result_canceled[which] || !result_timedOut[which] || !busy ||
            !controlBusy[which] || !controlQuiesce[which] || !controlClockEnable[which] ||
            fabricTerminalReady || fabricTerminals != beforeFabric || controlCompleted[which] != beforeCompleted)
          $fatal(1, "terminal backpressure prematurely released controller or fabric owner");
        tick();
      end
      holdTerminal[which] = 0;
      while (terminalsConsumed[which] == beforeConsumed) tick();
      holdTerminal[which] = 1;
      if (controlCompleted[which] != beforeCompleted || !controlBusy[which])
        $fatal(1, "mailbox terminal consume impersonated fabric retirement");
      while (controlCompleted[which] == beforeCompleted) tick();
      if (controlCompleted[which] != beforeCompleted + 1 || controlBusy[which] ||
          retirements[which] != beforeRetired + 1 || fabricTerminals != beforeFabric + 1 ||
          terminalsConsumed[which] != beforeConsumed + 1 || controlSuccess[which])
        $fatal(1, "controller cleanup did not retire exactly once after real fabric receipt");
      $display("CLOCK_RATE_CLEANUP_TERMINAL lane=%0d completed=%0d fabric_terminals=%0d",which,controlCompleted[which],fabricTerminals); $fflush();
    end
  endtask
  task exactLedger(input integer a11, input integer a12, input integer a13, input [63:0] pending);
    reg [63:0] oracle;
    begin
      while (msiAccepted != a11 + a12 + a13 || msiReplied != a11 + a12 + a13) tick();
      advanceLoops(6);
      if (msiAccepted11 != a11 || msiAccepted12 != a12 || msiAccepted13 != a13 ||
          msiAccepted != a11 + a12 + a13 || msiReplied != a11 + a12 + a13)
        $fatal(1, "exact stable MSI event delivery and reply ledger mismatch");
      oracle = pending ^ (wrongIrq ? 64'h4000 : 64'h0);
      if (lastPending !== oracle) $fatal(1, "independent IMSIC pending oracle: eventual CSR bitmap mismatch");
      if (stores != loads || loads != expectedData || loops != loads || previousLoads != loops)
        $fatal(1, "independent memory retirement side-effect ledger mismatch");
      $display("CLOCK_RATE_CLEANUP_LEDGER generation=%0d delivered=%0d replied=%0d id11=%0d id12=%0d id13=%0d pending=%h stores=%0d loads=%0d previous_loads=%0d loops=%0d",
        resetGeneration, msiAccepted, msiReplied, msiAccepted11, msiAccepted12, msiAccepted13,
        lastPending, stores, loads, previousLoads, loops);
      $fflush();
    end
  endtask
  task boot;
    begin
      // Assert coordinated reset before removing boot enable. Keeping start
      // through two fabric edges avoids a delta-cycle race when unrelated
      // AON/fabric edges coincide; local reset release remains synchronized.
      #1; reset = 1; cpuPaused = 0; repeat (2) fabricTick();
      start = 0; sources = 0;
      expected11 = 0; expected12 = 0; expected13 = 0; eventMask = 0;
      request_valid = 0; resume_valid = 0; cancel_valid = 0; result_ready = 0; controlSubmit = 0; controlCommitted = 0; holdTerminal = 3;
      holdMsiReply = 0; holdReleaseAck = 0; holdCompletion = 0; holdCpuCompletion = 0; externalStop = 0;
      repeat (8) tick(); reset = 0; repeat (8) fabricTick();
      for (i = 0; i < 64; i = i + 1) begin
        program_valid = 1; program_index = i; program_data = rom[i]; fabricTick();
      end
      program_valid = 0; start = 1; advanceLoops(3);
      while (!cpuLinkReady || !fabricLinkReady) tick();
      if (msiAccepted != 0 || msiReplied != 0 || lastPending != 0 || busy || result_valid != 0 ||
          fabricPrepares != 0 || fabricTerminals != 0 || cpuResumed != 0)
        $fatal(1, "coordinated reset leaked old epoch MSI or architectural state");
      $display("CLOCK_RATE_CLEANUP_BOOT generation=%0d cpu_half=%0d fabric_half=%0d aon_half=%0d phase_ns=0,2,3", resetGeneration, cpuHalf, fabricHalf, aonHalf);
      $fflush();
    end
  endtask

  initial begin
    wrongData = $test$plusargs("wrong-data"); wrongStore = $test$plusargs("wrong-store"); wrongIrq = $test$plusargs("wrong-irq");
    if (!$value$plusargs("rom=%s", rom_path)) $fatal(1, "missing independently compiled guest image");
    $readmemh(rom_path, rom);
    for (i = 0; i < 2; i = i + 1) begin request_bits[i] = 0; resume_bits[i] = 0; cancel_bits[i] = 0; resume_epoch[i] = 0; cancel_epoch[i] = 0; allocatedEpoch[i] = 0; end
    boot();
    while (controlBusy != 0) tick();
    // Both real controllers submit; only the selected lease starts the AON timer.
    @(negedge fabricClock); holdReleaseAck = 1;
    submitRates(2'b11);
    while (requests[0] == 0 || !releaseAckBlocked) tick();
    if (requests[1] != 0) $fatal(1, "contender bypassed shared epoch owner");
    oldCompleted = 0; waitTimeout(0);
    // The real owner remains late beyond cleanup timeout. Fault reports but does
    // not release either the controller lease or accepted cache/transport owner.
    while (!cleanupFault) begin
      tick();
      if (!busy || !controlBusy[0] || !controlQuiesce[0] || result_valid != 0 ||
          requests[1] != 0 || controlCompleted[0] != 0 || controlErrors[1] != 0)
        $fatal(1, "late owner or queued contender falsely completed/timed out");
    end
    repeat (32) begin
      tick(); if (!controlBusy[0] || !controlQuiesce[0] || requests[1] != 0 ||
          controlCompleted[0] != 0 || !releaseAckBlocked) $fatal(1, "cleanup fault erased live owner");
    end
    $display("CLOCK_RATE_CLEANUP_FAULT retained_release_ack=1 queued_lane_age=%0d",aonCycles-acceptedCycle[0]); $fflush();
    @(negedge cpuClock); cpuPaused = 1; oldCpuResumed = cpuResumed;
    @(negedge fabricClock); holdReleaseAck = 0;
    repeat (48) begin
      tick(); if (cpuResumed != oldCpuResumed || result_valid != 0 || controlCompleted[0] != 0)
        $fatal(1, "cleanup completed without real CPU resumed edges");
    end
    cpuPaused = 0;
    while (!result_valid[0]) tick();
    // Block the next epoch only after the first has actually drained.
    @(negedge fabricClock); holdCompletion = 1;
    setSources(3'b111);
    finishCleanup(0);
    while (requests[1] == 0 || !completionBlocked) tick();
    if ((controlErrors[1] & ~32'h200) != 0) $fatal(1, "waiting contender inherited prior lease timeout");
    // R10 cleanupFault remains globally sticky: Fatal may be conservatively
    // reported after this new lease acquires; DrainTimeout must not be inherited.
    oldCompleted = 0; waitTimeout(1);
    @(negedge fabricClock); holdCompletion = 0;
    finishCleanup(1);
    exactLedger(1,1,1,64'h3800);

    // Another accepted real MSI reply cannot be canceled by AON timeout.
    setSources(3'b000); advanceLoops(4);
    @(negedge fabricClock); holdMsiReply = 1; setSources(3'b001);
    while (msiAccepted != 4 || !msiReplyBlocked) tick();
    oldCompleted = 1; submitRates(2'b01);
    while (requests[0] != 2) tick();
    setSources(3'b111); waitTimeout(0);
    if (msiAccepted != 4 || msiReplied != 3 || !msiReplyBlocked)
      $fatal(1, "controller timeout lost accepted MSI owner");
    @(negedge fabricClock); holdMsiReply = 0;
    finishCleanup(0); exactLedger(2,2,2,64'h3800);
    if (fabricPrepares != 3 || fabricCancels != 3 || fabricResumes != 0 || fabricTerminals != 3 ||
        controlCompleted[0] != 2 || controlCompleted[1] != 1 || cpuResumed != 3)
      $fatal(1, "exact controller epoch completion ledger mismatch");
    $display("CLOCK_RATE_CLEANUP_PASS actual_aon_timeouts=3 real_cleanup_fault=1 terminal=3 controller0=2 controller1=1 cpu_cycles=%0d aon_cycles=%0d",cycles,aonCycles); $fflush();
    $finish;
  end
endmodule
