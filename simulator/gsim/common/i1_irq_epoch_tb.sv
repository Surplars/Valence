`timescale 1ns/1ps
module i1_irq_epoch_tb;
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
  reg wrongData = 0, wrongStore = 0, wrongIrq = 0;
  integer cycles = 0, aonCycles = 0, resetGeneration = 0;
  integer retires = 0, stores = 0, loads = 0, previousLoads = 0, loops = 0, pendingReads = 0, loopPhase = 0;
  integer requests [0:1], resumes [0:1], cancels [0:1], results [0:1], acceptedCycle [0:1];
  integer expected11 = 0, expected12 = 0, expected13 = 0;
  reg [63:0] expectedData = 0, eventMask = 0, lastPending = 0;
  integer i, lane, old, oldCpuResumed, oldFabricPrepares, oldFabricCancels;

  wire [63:0] trapPc, trapCause;
  wire architecturalStopped;
  reg wrongEpc = 0, wrongClaim = 0, wrongService = 0;
  reg inHandler = 0;
  reg [63:0] expectedPc = 64'h80000000, savedEpc = 0;
  integer traps = 0, claims = 0, services = 0, serviceStores = 0, serviceLoads = 0, mrets = 0;
  integer handlerReads = 0, expectedIdentity = 0, episode = 0;
  CommonI1RuntimeArchitecturalFixture dut(
    .observe_trapPc(trapPc), .observe_trapCause(trapCause),
    .observe_architecturalStopped(architecturalStopped),
    .observe_holdAtomicRead(1'b0), .observe_holdAtomicWrite(1'b0),
    .observe_holdMemoryResponse(1'b0), .observe_holdAtomicResult(1'b0),
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
  // Expected PC comes only from immutable guest control flow, not retire.nextPc.
  // Every comparison is independently known not-taken; the only back-edge is LOOP_JUMP.
  always @(posedge cpuClock) begin
    cycles = cycles + 1;
    if (cycles > 220000) $fatal(1, "IRQ epoch CPU watchdog");
    if (reset) begin
      expectedPc = 64'h80000000; savedEpc = 0; inHandler = 0;
      traps = 0; claims = 0; services = 0; serviceStores = 0; serviceLoads = 0; mrets = 0; handlerReads = 0;
      retires = 0; loops = 0; loopPhase = 0; expectedData = 0; stores = 0; loads = 0; previousLoads = 0;
    end else if (start) begin
      if (msiAccepted !== msiAccepted11 + msiAccepted12 + msiAccepted13 ||
          msiAccepted11 > expected11 || msiAccepted12 > expected12 || msiAccepted13 > expected13)
        $fatal(1, "independent MSI source episode ledger");
      if ((architecturalStopped || tileHeld_valid) && (retire_valid || trap))
        $fatal(1, "architectural work while stopped or held");
      if (trap) begin
        if (retire_valid || inHandler || traps >= episode || trapCause !== 64'h800000000000000b)
          $fatal(1, "unexpected duplicate synchronous or nested IRQ trap");
        if (trapPc !== (expectedPc ^ (wrongEpc ? 64'h4 : 64'h0)))
          $fatal(1, "independent IRQ EPC oracle");
        savedEpc = expectedPc; expectedPc = PC_IRQ_HANDLER; inHandler = 1; traps = traps + 1;
      end
      if (retire_valid) begin
        retires = retires + 1;
        if (retire_pc !== expectedPc || retire_pc < 64'h80000000 || retire_pc >= 64'h80000400)
          $fatal(1, "independent IRQ next-PC oracle expected=%h actual=%h", expectedPc, retire_pc);
        if (retire_instruction !== rom[(retire_pc-64'h80000000)>>2])
          $fatal(1, "independent guest instruction oracle");
        if (retire_pc == PC_GUEST_FAIL) $fatal(1, "guest comparison failed");
        expectedPc = expectedPc + 4;
        if (retire_pc == PC_LOOP_PREVIOUS) begin
          if (inHandler || loopPhase != 0 || !retire_writesRd || retire_rd != 23 || retire_data !== expectedData)
            $fatal(1, "independent previous-store persistence oracle");
          loopPhase = 1; previousLoads = previousLoads + 1;
        end
        if (retire_pc == PC_LOOP_PREVIOUS_COMPARE) begin
          if (loopPhase != 1) $fatal(1, "memory compare order"); loopPhase = 2;
        end
        if (retire_pc == PC_LOOP_INCREMENT) begin
          if (loopPhase != 2 || !retire_writesRd || retire_rd != 20 || retire_data !== expectedData+1)
            $fatal(1, "independent increment oracle");
          expectedData = expectedData + 1; loopPhase = 3;
        end
        if (retire_pc == PC_LOOP_STORE) begin
          if (loopPhase != 3) $fatal(1, "memory store order"); loopPhase = 4; stores = stores + 1;
        end
        if (retire_pc == PC_LOOP_LOAD) begin
          if (loopPhase != 4 || !retire_writesRd || retire_rd != 21 || retire_data !== expectedData)
            $fatal(1, "independent load data oracle");
          loopPhase = 5; loads = loads + 1;
        end
        if (retire_pc == PC_LOOP_COMPARE) begin
          if (loopPhase != 5) $fatal(1, "memory compare order"); loopPhase = 6;
        end
        if (retire_pc == PC_LOOP_PENDING) begin
          if (loopPhase != 6 || !retire_writesRd || retire_rd != 22 || (retire_data & 8) != 8)
            $fatal(1, "mret failed to restore machine interrupt enable");
          loopPhase = 7;
        end
        if (retire_pc == PC_LOOP_JUMP) begin
          if (loopPhase != 7) $fatal(1, "memory loop order");
          expectedPc = PC_LOOP_PREVIOUS; loopPhase = 0; loops = loops + 1;
        end
        if (retire_pc == PC_IRQ_HANDLER) begin
          if (!inHandler || !retire_writesRd || retire_rd != 25 || retire_data !== 64'h800000000000000b)
            $fatal(1, "independent IRQ cause CSR oracle");
          handlerReads = handlerReads + 1;
        end
        if (retire_pc == PC_IRQ_EPC) begin
          if (!inHandler || !retire_writesRd || retire_rd != 26 || retire_data !== savedEpc)
            $fatal(1, "independent IRQ EPC oracle");
        end
        if (retire_pc == PC_IRQ_STATUS) begin
          if (!inHandler || !retire_writesRd || retire_rd != 27 || (retire_data & 64'h1888) !== 64'h1880)
            $fatal(1, "independent trap mstatus oracle");
        end
        if (retire_pc == PC_IRQ_CLAIM) begin
          if (!inHandler || claims != traps-1 || !retire_writesRd || retire_rd != 28 ||
              retire_instruction !== 32'h35c01e73 ||
              retire_data !== ((expectedIdentity << 16) | expectedIdentity) + (wrongClaim ? 1 : 0))
            $fatal(1, "independent IRQ claim oracle");
          claims = claims + 1;
        end
        if (retire_pc == PC_IRQ_INCREMENT) begin
          if (claims != traps || services != traps-1 || !retire_writesRd || retire_rd != 24 || retire_data !== services+1)
            $fatal(1, "independent IRQ service increment oracle");
          services = services + 1;
        end
        if (retire_pc == PC_IRQ_STORE) begin
          if (serviceStores != services-1) $fatal(1, "independent IRQ service store order");
          serviceStores = serviceStores + 1;
        end
        if (retire_pc == PC_IRQ_LOAD) begin
          if (serviceLoads != services-1 || serviceStores != services || !retire_writesRd || retire_rd != 29 ||
              retire_data !== services + (wrongService ? 1 : 0))
            $fatal(1, "independent IRQ service oracle");
          serviceLoads = serviceLoads + 1;
        end
        if (retire_pc == PC_IRQ_MRET) begin
          if (!inHandler || retire_instruction !== 32'h30200073 || serviceLoads != traps || mrets != traps-1)
            $fatal(1, "independent mret service ordering oracle");
          mrets = mrets + 1; inHandler = 0; expectedPc = savedEpc;
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
      for (i = 0; i < 256; i = i + 1) begin
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
  task beginEpisode(input integer identity);
    begin
      if (episode != mrets || inHandler) $fatal(1, "test attempted coalescing IRQ episode");
      expectedIdentity = identity; episode = episode + 1;
      case (identity)
        11: setSources(3'b001);
        12: setSources(3'b010);
        13: setSources(3'b100);
        default: $fatal(1, "invalid test IRQ identity");
      endcase
    end
  endtask
  task serviced(input integer count);
    begin
      while (mrets != count) cpuTick();
      setSources(3'b000);
      advanceLoops(3);
      if (traps != count || claims != count || services != count || serviceStores != count || serviceLoads != count || inHandler)
        $fatal(1, "exact IRQ trap claim service mret ledger mismatch");
      if (msiAccepted != count || msiReplied != count || msiAccepted11 != expected11 ||
          msiAccepted12 != expected12 || msiAccepted13 != expected13)
        $fatal(1, "exact physical-source MSI delivery/reply ledger mismatch");
      if (stores != loads || loads != expectedData || loops != loads || previousLoads != loops)
        $fatal(1, "interrupted memory-loop persistence ledger mismatch");
      $display("I1_IRQ_EPOCH_LEDGER episode=%0d traps=%0d claims=%0d services=%0d mrets=%0d delivered=%0d replied=%0d loops=%0d",
        count, traps, claims, services, mrets, msiAccepted, msiReplied, loops);
      $fflush();
    end
  endtask
  initial begin
    wrongEpc = $test$plusargs("wrong-epc"); wrongClaim = $test$plusargs("wrong-claim");
    wrongService = $test$plusargs("wrong-service");
    if (!$value$plusargs("rom=%s", rom_path)) $fatal(1, "missing independently compiled guest image");
    $readmemh(rom_path, rom);
    for (i = 0; i < 2; i = i + 1) begin
      request_bits[i] = 0; resume_bits[i] = 0; cancel_bits[i] = 0;
      resume_epoch[i] = 0; cancel_epoch[i] = 0; allocatedEpoch[i] = 0;
    end
    boot();
    // True interrupt, claim, observable service memory, and mret before prepare.
    beginEpisode(11); serviced(1);
    requestEpoch(0, 32'h1a130001); waitHeld(0, 32'h1a130001, allocatedEpoch[0]);
    heldStable(0, 32'h1a130001, allocatedEpoch[0], 24);
    resumeEpoch(0, 32'h1a130001);
    terminal(0, 32'h1a130001, allocatedEpoch[0], 0, 0, 1);
    advanceLoops(3);

    // Physical source assertion while held stays queued until terminal retirement.
    requestEpoch(1, 32'h1a130002); waitHeld(1, 32'h1a130002, allocatedEpoch[1]);
    beginEpisode(12); heldStable(1, 32'h1a130002, allocatedEpoch[1], 32);
    if (traps != 1 || claims != 1 || mrets != 1) $fatal(1, "held pending source entered handler");
    resumeEpoch(1, 32'h1a130002);
    terminal(1, 32'h1a130002, allocatedEpoch[1], 0, 0, 1);
    serviced(2);

    // Initiate the epoch from observed real handler retirement, not guessed cycles.
    // The linear NOP window is real guest work, not a CSR-response stall.
    beginEpisode(13);
    while (handlerReads != 3) cpuTick();
    if (!inHandler) $fatal(1, "handler-triggered epoch missed actual handler");
    requestEpoch(0, 32'h1a130003);
    waitHeld(0, 32'h1a130003, allocatedEpoch[0]);
    if (!inHandler || mrets != 2) $fatal(1, "handler epoch failed to stop before mret");
    heldStable(0, 32'h1a130003, allocatedEpoch[0], 24);
    resumeEpoch(0, 32'h1a130003);
    terminal(0, 32'h1a130003, allocatedEpoch[0], 0, 0, 3);
    serviced(3);

    // Cancellation cannot revoke a real accepted MSI reply, even after service.
    @(negedge fabricClock); holdMsiReply = 1;
    beginEpisode(11);
    while (msiAccepted != 4 || !msiReplyBlocked) tick();
    requestEpoch(1, 32'h1a130004);
    cancelEpoch(1, 32'h1a130004);
    repeat (32) begin
      tick();
      if (result_valid != 0 || fabricHeld_valid || held_valid != 0 || !msiReplyBlocked || msiReplied != 3)
        $fatal(1, "cancellation revoked accepted real MSI response owner");
    end
    @(negedge fabricClock); holdMsiReply = 0;
    terminal(1, 32'h1a130004, allocatedEpoch[1], 1, 0, 4);
    serviced(4);
    if (requests[0] != 2 || requests[1] != 2 || results[0] != 2 || results[1] != 2 ||
        fabricPrepares != 4 || fabricResumes != 3 || fabricCancels != 1 || fabricTerminals != 4 || cpuResumed != 4)
      $fatal(1, "exact IRQ epoch terminal retirement ledger mismatch");
    $display("I1_IRQ_EPOCH_PASS cpu_half=%0d fabric_half=%0d aon_half=%0d traps=%0d claims=%0d services=%0d mrets=%0d epochs=4 no_forced_csr_reply_stall=1", cpuHalf, fabricHalf, aonHalf, traps, claims, services, mrets);
    $fflush(); $finish;
  end
endmodule
