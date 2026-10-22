`timescale 1ns/1ps
module i1_runtime_cdc_tb;
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

  CommonI1RuntimeCdcFixture dut(
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
    if (aonCycles > 140000) $fatal(1, "three-clock AON watchdog");
    if (reset) begin
      for (integer j = 0; j < 2; j = j + 1) begin
        requests[j] = 0; resumes[j] = 0; cancels[j] = 0; results[j] = 0; acceptedCycle[j] = 0;
      end
    end else begin
      if ((request_valid & request_ready) == 2'b11) $fatal(1, "shared epoch accepted both requesters");
      if (held_valid == 2'b11 || result_valid == 2'b11) $fatal(1, "shared epoch routed proof to both requesters");
      if (cleanupFault || epochExhausted) $fatal(1, "unexpected cleanup fault or epoch exhaustion");
      for (integer j = 0; j < 2; j = j + 1) begin
        if (request_valid[j] && request_ready[j]) begin requests[j] = requests[j] + 1; acceptedCycle[j] = aonCycles; end
        if (resume_valid[j] && resume_ready[j]) resumes[j] = resumes[j] + 1;
        if (cancel_valid[j] && cancel_ready[j]) cancels[j] = cancels[j] + 1;
        if (result_valid[j] && result_ready[j]) results[j] = results[j] + 1;
      end
    end
  end
  // Independent ledgers use physical input transitions and architectural PCs,
  // never DUT pending state or DUT-derived instruction expectations.
  always @(posedge cpuClock) begin
    cycles = cycles + 1;
    if (cycles > 220000) $fatal(1, "I1 three-clock CPU watchdog");
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
  task requestEpoch(input integer which, input [31:0] token);
    integer priorCount, fabricBefore;
    begin
      fabricBefore = fabricPrepares;
      @(negedge alwaysOnClock); priorCount = requests[which]; request_bits[which] = token; request_valid[which] = 1;
      while (requests[which] == priorCount) tick(); request_valid[which] = 0;
      allocatedEpoch[which] = activeEpoch;
      while (fabricPrepares == fabricBefore) tick();
    end
  endtask
  task waitHeld(input integer which, input [31:0] token, input [7:0] epoch);
    begin
      while (!held_valid[which]) tick();
      if (held_valid[1-which] || held_token[which] != token || held_epoch[which] != epoch ||
          !tileHeld_valid || !fabricHeld_valid || tileHeld_bits != epoch || fabricHeld_bits != epoch ||
          !fabricIdle || !cpuTransportEmpty || !fabricTransportEmpty || msiReplied != msiAccepted)
        $fatal(1, "AON held proof lacked matching real CPU/fabric/transport owner");
    end
  endtask
  task heldStable(input integer which, input [31:0] token, input [7:0] epoch, input integer duration);
    integer oldRetires, oldStores, oldAcquires, oldMsi, oldReplies, n;
    begin
      oldRetires = retires; oldStores = stores; oldAcquires = coherentAcquires;
      oldMsi = msiAccepted; oldReplies = msiReplied;
      for (n = 0; n < duration; n = n + 1) begin
        tick();
        if (!held_valid[which] || held_token[which] != token || held_epoch[which] != epoch ||
            !tileHeld_valid || !fabricHeld_valid || !fabricIdle)
          $fatal(1, "held epoch lost real source proofs");
        if (retires != oldRetires || stores != oldStores || coherentAcquires != oldAcquires)
          $fatal(1, "held epoch admitted architectural memory work");
        if (msiAccepted != oldMsi || msiReplied != oldReplies)
          $fatal(1, "new MSI owner while runtime epoch held");
      end
    end
  endtask
  task rejectControls(input integer which, input [31:0] token);
    integer oldResume, oldCancel, oldFabricResume, oldFabricCancel, n;
    begin
      @(negedge alwaysOnClock);
      oldResume = resumes[which]; oldCancel = cancels[which];
      oldFabricResume = fabricResumes; oldFabricCancel = fabricCancels;
      resume_bits[which] = token; cancel_bits[which] = token;
      resume_epoch[which] = activeEpoch; cancel_epoch[which] = activeEpoch;
      resume_valid[which] = 1; cancel_valid[which] = 1;
      for (n = 0; n < 5; n = n + 1) begin
        tick();
        if (resume_ready[which] || cancel_ready[which] || resumes[which] != oldResume || cancels[which] != oldCancel)
          $fatal(1, "invalid stale duplicate or wrong-lane control accepted");
      end
      resume_valid[which] = 0; cancel_valid[which] = 0;
      repeat (8) tick();
      if (fabricResumes != oldFabricResume || fabricCancels != oldFabricCancel)
        $fatal(1, "invalid AON token escaped into fabric");
    end
  endtask
  task rejectStaleEpoch(input integer which, input [31:0] token, input [7:0] staleEpoch);
    integer oldResume, oldCancel, n;
    begin
      @(negedge alwaysOnClock);
      oldResume = resumes[which]; oldCancel = cancels[which];
      resume_bits[which] = token; cancel_bits[which] = token;
      resume_epoch[which] = staleEpoch; cancel_epoch[which] = staleEpoch;
      resume_valid[which] = 1; cancel_valid[which] = 1;
      for (n = 0; n < 5; n = n + 1) begin
        tick();
        if (resume_ready[which] || cancel_ready[which] || resumes[which] != oldResume || cancels[which] != oldCancel)
          $fatal(1, "matching token with stale epoch was accepted");
      end
      resume_valid[which] = 0; cancel_valid[which] = 0;
    end
  endtask
  task resumeEpoch(input integer which, input [31:0] token);
    integer priorCount;
    begin
      @(negedge alwaysOnClock); priorCount = resumes[which]; resume_bits[which] = token; resume_epoch[which] = allocatedEpoch[which]; resume_valid[which] = 1;
      while (resumes[which] == priorCount) tick(); resume_valid[which] = 0;
    end
  endtask
  task cancelEpoch(input integer which, input [31:0] token);
    integer priorCount;
    begin
      @(negedge alwaysOnClock); priorCount = cancels[which]; cancel_bits[which] = token; cancel_epoch[which] = allocatedEpoch[which]; cancel_valid[which] = 1;
      while (cancels[which] == priorCount) tick(); cancel_valid[which] = 0;
    end
  endtask
  task cancelWins(input integer which, input [31:0] token);
    integer oldCancel, oldResume;
    begin
      @(negedge alwaysOnClock); oldCancel = cancels[which]; oldResume = resumes[which];
      cancel_bits[which] = token; resume_bits[which] = token;
      cancel_epoch[which] = allocatedEpoch[which]; resume_epoch[which] = allocatedEpoch[which];
      cancel_valid[which] = 1; resume_valid[which] = 1;
      while (cancels[which] == oldCancel) tick();
      cancel_valid[which] = 0; resume_valid[which] = 0;
      if (resumes[which] != oldResume) $fatal(1, "matching cancel lost priority to simultaneous resume");
    end
  endtask
  task terminal(input integer which, input [31:0] token, input [7:0] epoch,
                input bit canceled, input bit timedOut, input integer delivered);
    integer priorCount, fabricBefore, n;
    begin
      priorCount = results[which]; fabricBefore = fabricTerminals;
      while (!result_valid[which]) tick();
      for (n = 0; n < 24; n = n + 1) begin
        if (!result_valid[which] || result_valid[1-which] || result_token[which] != token ||
            result_epoch[which] != epoch || result_canceled[which] != canceled || result_timedOut[which] != timedOut ||
            !busy || request_ready != 0)
          $fatal(1, "AON terminal lost routed token epoch or cancellation under backpressure");
        if (tileHeld_valid || fabricHeld_valid) $fatal(1, "terminal preceded actual CPU epoch release");
        if (!fabricTerminalValid || fabricTerminalReady || fabricTerminals != fabricBefore)
          $fatal(1, "fabric terminal owner retired before AON consumer acceptance");
        if (msiAccepted != delivered || msiReplied != delivered)
          $fatal(1, "MSI reopened before AON terminal consumer acceptance");
        tick();
      end
      rejectControls(which, token);
      result_ready[which] = 1; while (results[which] == priorCount) tick(); result_ready[which] = 0;
      while (fabricTerminals == fabricBefore || busy) tick();
      if (results[which] != priorCount + 1 || fabricTerminals != fabricBefore + 1)
        $fatal(1, "duplicate or missing terminal acknowledgement roundtrip");
      $display("I1_RUNTIME_CDC_TERMINAL generation=%0d lane=%0d token=%h epoch=%0d canceled=%0d timed_out=%0d cpu_resumed=%0d fabric_terminals=%0d",
        resetGeneration, which, token, epoch, canceled, timedOut, cpuResumed, fabricTerminals);
      $fflush();
    end
  endtask
  task waitTimeout(input integer which);
    begin
      while (!timeoutSelected) tick();
      if (aonCycles - acceptedCycle[which] < 4095)
        $fatal(1, "timeout selected before actual AON timeout counter elapsed");
      if (result_valid != 0 || held_valid != 0)
        $fatal(1, "AON timeout fabricated terminal or held proof before drain");
      $display("I1_RUNTIME_CDC_TIMEOUT generation=%0d lane=%0d epoch=%0d elapsed_aon=%0d release_ack_blocked=%0d msi_reply_blocked=%0d completion_blocked=%0d",
        resetGeneration, which, activeEpoch, aonCycles - acceptedCycle[which], releaseAckBlocked, msiReplyBlocked, completionBlocked);
      $fflush();
      oldFabricCancels = fabricCancels;
      repeat (32) begin
        tick();
        if (result_valid != 0 || held_valid != 0) $fatal(1, "timeout revoked an outstanding real owner");
      end
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
      $display("I1_RUNTIME_CDC_LEDGER generation=%0d delivered=%0d replied=%0d id11=%0d id12=%0d id13=%0d pending=%h stores=%0d loads=%0d previous_loads=%0d loops=%0d",
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
      request_valid = 0; resume_valid = 0; cancel_valid = 0; result_ready = 0;
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
      $display("I1_RUNTIME_CDC_BOOT generation=%0d cpu_half=%0d fabric_half=%0d aon_half=%0d phase_ns=0,2,3", resetGeneration, cpuHalf, fabricHalf, aonHalf);
      $fflush();
    end
  endtask

  initial begin
    wrongData = $test$plusargs("wrong-data"); wrongStore = $test$plusargs("wrong-store"); wrongIrq = $test$plusargs("wrong-irq");
    if (!$value$plusargs("rom=%s", rom_path)) $fatal(1, "missing independently compiled guest image");
    $readmemh(rom_path, rom);
    for (i = 0; i < 2; i = i + 1) begin request_bits[i] = 0; resume_bits[i] = 0; cancel_bits[i] = 0; resume_epoch[i] = 0; cancel_epoch[i] = 0; allocatedEpoch[i] = 0; end
    boot(); rejectControls(0, 32'hffffffff); rejectControls(1, 32'hffffffff);

    // The first requester owns the sole epoch. Its competitor remains offered
    // through terminal backpressure, then owns the next epoch only after ACK.
    @(negedge fabricClock); holdMsiReply = 1; setSources(3'b001);
    while (msiAccepted != 1 || !msiReplyBlocked) tick();
    @(negedge cpuClock); holdCpuCompletion = 1;
    @(negedge alwaysOnClock); request_bits[0] = 32'hc0de0028; request_bits[1] = 32'hbabe0029; request_valid = 2'b11;
    while (requests[0] == 0) tick(); request_valid[0] = 0; allocatedEpoch[0] = activeEpoch;
    if (requests[1] != 0) $fatal(1, "two requester lanes owned one shared epoch");
    repeat (24) begin
      tick(); if (fabricHeld_valid || held_valid != 0 || result_valid != 0 || msiReplied != 0 || requests[1] != 0)
        $fatal(1, "pre-hold MSI reply owner discarded or competitor admitted");
    end
    @(negedge fabricClock); holdMsiReply = 0;
    while (!cpuCompletionBlocked || !fabricHeld_valid) tick();
    repeat (32) begin
      tick(); if (tileHeld_valid || held_valid != 0 || result_valid != 0 || !fabricHeld_valid)
        $fatal(1, "AON treated fabric-held or queued completion as CPU-held proof");
    end
    @(negedge cpuClock); holdCpuCompletion = 0;
    waitHeld(0, 32'hc0de0028, 8'd1);
    heldStable(0, 32'hc0de0028, 8'd1, 32);
    rejectControls(0, 32'hc0de0027); rejectControls(1, 32'hc0de0028); rejectStaleEpoch(0, 32'hc0de0028, 8'd0);
    oldCpuResumed = cpuResumed;
    @(negedge cpuClock); cpuPaused = 1;
    resumeEpoch(0, 32'hc0de0028);
    repeat (48) begin
      tick(); if (cpuResumed != oldCpuResumed || result_valid != 0 || fabricTerminalValid)
        $fatal(1, "resume completed without real CPU clock edges");
    end
    cpuPaused = 0;
    terminal(0, 32'hc0de0028, 8'd1, 0, 0, 1);
    while (requests[1] == 0) tick(); request_valid[1] = 0; allocatedEpoch[1] = activeEpoch;
    waitHeld(1, 32'hbabe0029, 8'd2); setSources(3'b111);
    rejectControls(0, 32'hc0de0028); rejectControls(0, 32'hbabe0029); rejectStaleEpoch(1, 32'hbabe0029, 8'd1);
    heldStable(1, 32'hbabe0029, 8'd2, 16);
    cancelWins(1, 32'hbabe0029);
    terminal(1, 32'hbabe0029, 8'd2, 1, 0, 1);
    exactLedger(1, 1, 1, 64'h3800);

    // AON's own counter expires while a real dirty ReleaseAck is retained.
    setSources(3'b000); advanceLoops(4);
    @(negedge fabricClock); holdReleaseAck = 1;
    requestEpoch(0, 32'hc0de002a); setSources(3'b111);
    while (!releaseAckBlocked) tick(); waitTimeout(0);
    if (!releaseAckBlocked || tileHeld_valid || fabricHeld_valid) $fatal(1, "timeout skipped dirty ReleaseAck");
    @(negedge fabricClock); holdReleaseAck = 0;
    terminal(0, 32'hc0de002a, 8'd3, 1, 1, 3);
    exactLedger(2, 2, 2, 64'h3800);

    // A timeout cannot revoke an accepted MSI response or admit queued sources.
    setSources(3'b000); advanceLoops(4);
    @(negedge fabricClock); holdMsiReply = 1; setSources(3'b001);
    while (msiAccepted != 7 || !msiReplyBlocked) tick();
    requestEpoch(1, 32'hbabe002b); setSources(3'b111); waitTimeout(1);
    if (msiAccepted != 7 || msiReplied != 6 || !msiReplyBlocked)
      $fatal(1, "timeout altered real MSI ownership ledger");
    @(negedge fabricClock); holdMsiReply = 0;
    terminal(1, 32'hbabe002b, 8'd4, 1, 1, 7);
    exactLedger(3, 3, 3, 64'h3800);

    // Cancellation after timeout still waits for the actual fabric completion
    // to enter, cross and leave the existing CPU boundary FIFO.
    @(negedge fabricClock); holdCompletion = 1;
    requestEpoch(0, 32'hc0de0028); // Deliberately reuse the first external token with a new epoch.
    while (!completionBlocked) tick(); rejectStaleEpoch(0, 32'hc0de0028, 8'd1); waitTimeout(0);
    if (tileHeld_valid || fabricHeld_valid || !completionBlocked)
      $fatal(1, "timeout manufactured queued drain completion");
    @(negedge fabricClock); holdCompletion = 0;
    terminal(0, 32'hc0de0028, 8'd5, 1, 1, 9);
    exactLedger(3, 3, 3, 64'h3800);
    if (requests[0] != 3 || requests[1] != 2 || results[0] != 3 || results[1] != 2 ||
        fabricPrepares != 5 || fabricResumes != 1 || fabricCancels != 4 || fabricTerminals != 5 || cpuResumed != 5)
      $fatal(1, "pre-reset exact shared epoch ledger mismatch");

    // Only coordinated reset of all three domains may abort accepted ownership.
    setSources(3'b000); advanceLoops(4);
    @(negedge fabricClock); holdMsiReply = 1; setSources(3'b001);
    while (msiAccepted != 10 || !msiReplyBlocked) tick();
    requestEpoch(1, 32'hbabe002d); setSources(3'b111);
    repeat (24) begin
      tick(); if (result_valid != 0 || fabricHeld_valid || msiAccepted != 10 || msiReplied != 9)
        $fatal(1, "coordinated reset test lost live pre-reset owner");
    end
    $display("I1_RUNTIME_CDC_RESET generation=0 prepares=6 terminal=5 reset_aborted=1 delivered=10 replied=9 queued_sources=2");
      $fflush();
    resetGeneration = 1; boot();
    requestEpoch(1, 32'hbabe002e); waitHeld(1, 32'hbabe002e, 8'd1);
    setSources(3'b111); heldStable(1, 32'hbabe002e, 8'd1, 24);
    rejectControls(1, 32'hbabe002d); resumeEpoch(1, 32'hbabe002e);
    terminal(1, 32'hbabe002e, 8'd1, 0, 0, 0); exactLedger(1, 1, 1, 64'h3800);
    advanceLoops(4); exactLedger(1, 1, 1, 64'h3800);
    if (requests[0] != 0 || requests[1] != 1 || results[0] != 0 || results[1] != 1 ||
        fabricPrepares != 1 || fabricResumes != 1 || fabricCancels != 0 || fabricTerminals != 1 || cpuResumed != 1)
      $fatal(1, "post-reset exact shared epoch ledger mismatch");
    $display("I1_RUNTIME_CDC_PASS cpu_half=%0d fabric_half=%0d aon_half=%0d cpu_phase=0 fabric_phase=2 aon_phase=3 normal=2 explicit_cancel=1 actual_aon_timeouts=3 terminal=6 coordinated_reset_aborts=1 cpu_cycles=%0d aon_cycles=%0d",
      cpuHalf, fabricHalf, aonHalf, cycles, aonCycles);
      $fflush();
    $finish;
  end
endmodule
