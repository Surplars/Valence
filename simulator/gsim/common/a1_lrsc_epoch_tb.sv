`timescale 1ns/1ps
module a1_lrsc_epoch_tb;
  reg holdProbeResponse=1;
  wire probeBlocked,dmaActive,dmaIrq;
  wire [31:0] probes,dirtyProbeBeats,dmaRequests,dmaResponses;
  integer lrPlain=0, scPlain=0, lrPark=0, scPark=0, lrDma=0, scDma=0;
  reg [63:0] parkScResult=0;
  integer sourceChecks=0;
  integer dmaStarts=0, valueChecks=0,guardChecks=0,doneSeen=0;
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
  reg reset = 1, start = 0, program_valid = 0, timerTick = 0;
  wire [63:0] trapCause;
  integer timerTraps=0,externalTraps=0,timerHandlers=0,externalHandlers=0,returns=0,claims=0;
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
  wire tileHeld_valid, fabricHeld_valid, trap, fabricIdle;
  wire [7:0] tileHeld_bits, fabricHeld_bits;
  wire releaseAckBlocked, completionBlocked, cpuCompletionBlocked, msiReplyBlocked;
  wire [31:0] releaseBeats, coherentAcquires, cpuResumed;
  wire [31:0] msiAccepted, msiReplied, msiAccepted11, msiAccepted12, msiAccepted13;
  wire [31:0] fabricPrepares, fabricResumes, fabricCancels, fabricTerminals;
  wire fabricTerminalValid, fabricTerminalReady, cpuLinkReady, fabricLinkReady;
  wire cpuTransportEmpty, fabricTransportEmpty;
  wire busy, timeoutSelected, cleanupFault, epochExhausted, activeLane;
  wire [7:0] activeEpoch; wire [31:0] activeToken;
  reg retire_valid, retire_writesRd;
  reg [31:0] retire_instruction;
  reg [63:0] retire_pc, retire_data;
  reg [4:0] retire_rd;
  wire [1:0] rv, rw;
  wire [31:0] ri [0:1];
  wire [63:0] rp [0:1], rd [0:1];
  wire [4:0] rr [0:1];
  reg [31:0] rom [0:255]; reg [4095:0] rom_path;
  reg wrongData = 0, wrongStore = 0, wrongIrq = 0, arithmetic = 0;
  integer divisions=0, multiplications=0;
  integer cycles = 0, aonCycles = 0, resetGeneration = 0;
  integer retires = 0, stores = 0, loads = 0, previousLoads = 0, loops = 0, pendingReads = 0, loopPhase = 0;
  integer requests [0:1], resumes [0:1], cancels [0:1], results [0:1], acceptedCycle [0:1];
  integer expected11 = 0, expected12 = 0, expected13 = 0;
  reg [63:0] expectedData = 0, eventMask = 0, lastPending = 0;
  integer i, lane, old, oldCpuResumed, oldFabricPrepares, oldFabricCancels;

  CommonA1DmaProbeFixture dut(
    .holdProbeResponse(holdProbeResponse), .probeBlocked(probeBlocked), .probes(probes),
    .dirtyProbeBeats(dirtyProbeBeats), .dmaActive(dmaActive), .dmaIrq(dmaIrq),
    .dmaRequests(dmaRequests), .dmaResponses(dmaResponses),
    .cpuClock(cpuClock), .fabricClock(fabricClock), .alwaysOnClock(alwaysOnClock), .commonColdReset(reset),
    .io_start(start), .io_timerTick(timerTick), .trapCause(trapCause), .io_program_valid(program_valid), .io_program_bits_index(program_index), .io_program_bits_data(program_data),
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
    .io_retire_0_valid(rv[0]), .io_retire_0_bits_pc(rp[0]), .io_retire_0_bits_instruction(ri[0]),
    .io_retire_0_bits_rd(rr[0]), .io_retire_0_bits_data(rd[0]), .io_retire_0_bits_writesRd(rw[0]),
    .io_retire_1_valid(rv[1]), .io_retire_1_bits_pc(rp[1]), .io_retire_1_bits_instruction(ri[1]),
    .io_retire_1_bits_rd(rr[1]), .io_retire_1_bits_data(rd[1]), .io_retire_1_bits_writesRd(rw[1]),
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
  always @(posedge cpuClock) begin
    cycles = cycles + 1;
    if(cycles > 60000) $fatal(1,"LR/SC runtime watchdog");
    if(!reset && start) begin
      if(trap) begin
        if(trapCause==64'h8000000000000007) timerTraps=timerTraps+1;
        else if(trapCause==64'h800000000000000b) externalTraps=externalTraps+1;
        else $fatal(1,"unexpected actual trap cause %h",trapCause);
      end
      for(integer r=0;r<2;r=r+1) if(rv[r]) begin
        retires=retires+1;
        if(rp[r]==PC_GUEST_FAIL) $fatal(1,"LR/SC guest failed");
        if(rp[r]==PC_LR_PLAIN) begin
          lrPlain=lrPlain+1;
          if(!rw[r] || rd[r]!==64'd7) $fatal(1,"independent uncontended LR value");
        end
        if(rp[r]==PC_SC_PLAIN) begin
          scPlain=scPlain+1;
          if(!rw[r] || rd[r]!==($test$plusargs("wrong-sc") ? 64'd1 : 64'd0)) $fatal(1,"independent uncontended SC success");
        end
        if(rp[r]==PC_PLAIN_VALUE && (!rw[r] || rd[r]!==64'd9)) $fatal(1,"independent uncontended SC memory value");
        if(rp[r]==PC_LR_PARK) begin
          lrPark=lrPark+1;
          if(!rw[r] || rd[r]!==64'd9) $fatal(1,"independent park LR value");
        end
        if(rp[r]==PC_SC_PARK) begin
          scPark=scPark+1; parkScResult=rd[r];
          if(!rw[r] || $isunknown(rd[r]) || (cpuResumed!=1 || resumes[0]!=1 || tileHeld_valid)) $fatal(1,"SC did not cross released real park");
        end
        if(rp[r]==PC_PARK_VALUE && (!rw[r] || rd[r] !== (parkScResult==0 ? 64'd11 : 64'd9)))
          $fatal(1,"independent SC outcome and park memory consistency");
        if(rp[r]==PC_LR_DMA) begin
          lrDma=lrDma+1;
          if(!rw[r] || rd[r]!==64'hdeadbeef12345678) $fatal(1,"independent DMA LR original value");
        end
        if(rp[r]==PC_SC_DMA) begin
          scDma=scDma+1;
          if(!rw[r] || $isunknown(rd[r]) || ($test$plusargs("wrong-dma-sc") ? rd[r]!=0 : rd[r]==0) || externalTraps!=0 || dmaResponses!=2 || cpuResumed!=($test$plusargs("dma-no-park") ? 1 : 2) || resumes[0]!=($test$plusargs("dma-no-park") ? 1 : 2) || tileHeld_valid)
            $fatal(1,"independent DMA must invalidate SC before any trap rw=%b sc=%h traps=%0d responses=%0d terminals_consumed=%0d cpu_resumed=%0d",rw[r],rd[r],externalTraps,dmaResponses,results[0],cpuResumed);
        end
        if(rp[r]==PC_DMA_START) dmaStarts=dmaStarts+1;
        if(rp[r]==PC_DMA_SOURCE) begin
          sourceChecks=sourceChecks+1;
          if(!rw[r] || rr[r]!=23 || rd[r]!==64'h1122334455667788)
            $fatal(1,"independent DMA source preservation oracle");
        end
        if(rp[r]==PC_DMA_VALUE) begin
          valueChecks=valueChecks+1;
          if(!rw[r] || rr[r]!=21 || rd[r] !== (64'h1122334455667788 ^ ($test$plusargs("wrong-data") ? 64'd1 : 64'd0)))
            $fatal(1,"independent DMA coherent destination oracle");
        end
        if(rp[r]==PC_DMA_GUARD) begin
          guardChecks=guardChecks+1;
          if(!rw[r] || rr[r]!=22 || rd[r]!==64'ha5a5a5a5b6b6b6b6)
            $fatal(1,"independent dirty neighboring-word oracle");
        end
        if(rp[r]==PC_IRQ_COUNT) begin
          externalHandlers=externalHandlers+1;
          if(!rw[r] || rr[r]!=24 || rd[r]!==64'd1)
            $fatal(1,"independent DMA IRQ handler count oracle");
        end
        if(rp[r]==PC_GUEST_DONE) doneSeen=1;
        if(rp[r]==PC_IRQ_CLAIM) begin
          claims=claims+1;
          if(!rw[r] || rr[r]!=28 || rd[r]!==64'he000e) $fatal(1,"independent MSI claim identity oracle");
        end
        if(rp[r]==PC_IRQ_MRET) returns=returns+1;
      end
      if(tileHeld_valid && (rv || trap)) $fatal(1,"parked LR/SC core executed or trapped");
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
      $display("A1_RUNTIME_CDC_TERMINAL generation=%0d lane=%0d token=%h epoch=%0d canceled=%0d timed_out=%0d cpu_resumed=%0d fabric_terminals=%0d",
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
      $display("A1_RUNTIME_CDC_TIMEOUT generation=%0d lane=%0d epoch=%0d elapsed_aon=%0d release_ack_blocked=%0d msi_reply_blocked=%0d completion_blocked=%0d",
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
      $display("A1_RUNTIME_CDC_LEDGER generation=%0d delivered=%0d replied=%0d id11=%0d id12=%0d id13=%0d pending=%h stores=%0d loads=%0d previous_loads=%0d loops=%0d",
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
      for (i = 0; i < 256; i = i + 1) begin
        program_valid = 1; program_index = i; program_data = rom[i]; fabricTick();
      end
      program_valid = 0; start = 1;
      while (!cpuLinkReady || !fabricLinkReady) tick();
      if (msiAccepted != 0 || msiReplied != 0 || lastPending != 0 || busy || result_valid != 0 ||
          fabricPrepares != 0 || fabricTerminals != 0 || cpuResumed != 0)
        $fatal(1, "coordinated reset leaked old epoch MSI or architectural state");
      $display("A1_RUNTIME_CDC_BOOT generation=%0d cpu_half=%0d fabric_half=%0d aon_half=%0d phase_ns=0,2,3", resetGeneration, cpuHalf, fabricHalf, aonHalf);
      $fflush();
    end
  endtask

  initial begin
    if (!$value$plusargs("rom=%s", rom_path)) $fatal(1,"missing guest");
    $readmemh(rom_path,rom);
    for(i=0;i<2;i=i+1) begin request_bits[i]=0;resume_bits[i]=0;cancel_bits[i]=0;resume_epoch[i]=0;cancel_epoch[i]=0;allocatedEpoch[i]=0;end
    boot();
    while(lrPark!=1) cpuTick();
    requestEpoch(0,32'ha10000c1);
    waitHeld(0,32'ha10000c1,allocatedEpoch[0]);
    if(scPark || lrDma) $fatal(1,"park marker missed LR/SC boundary");
    heldStable(0,32'ha10000c1,allocatedEpoch[0],24);
    resumeEpoch(0,32'ha10000c1);
    terminal(0,32'ha10000c1,allocatedEpoch[0],0,0,0);
    while(!probeBlocked) cpuTick();
    if(probes<1 || dirtyProbeBeats!=0 || !dmaActive || dmaRequests!=1 || dmaResponses!=0)
      $fatal(1,"actual DMA dirty-probe interception missing");
    $display("A1_DMA_PROBE_BLOCKED probes=%0d requests=%0d responses=%0d",probes,dmaRequests,dmaResponses);$fflush();
    if(!$test$plusargs("dma-no-park")) begin
    requestEpoch(0,32'ha10000d1);
    repeat(64) begin
      tick();
      if(!probeBlocked || held_valid || result_valid || !dmaActive || dmaResponses!=0)
        $fatal(1,"DMA probe owner falsely drained during park request");
    end
    @(negedge cpuClock);holdProbeResponse=0;
    waitHeld(0,32'ha10000d1,allocatedEpoch[0]);
    if(dmaActive || dmaRequests!=2 || dmaResponses!=2 || dirtyProbeBeats<8)
      $fatal(1,"DMA/probe ownership incomplete at live held");
    heldStable(0,32'ha10000d1,allocatedEpoch[0],24);
    $display("A1_DMA_PROBE_DRAINED probes=%0d dirty_beats=%0d requests=%0d responses=%0d",probes,dirtyProbeBeats,dmaRequests,dmaResponses);$fflush();
    resumeEpoch(0,32'ha10000d1);
    terminal(0,32'ha10000d1,allocatedEpoch[0],0,0,0);
    end else begin
      repeat(64) begin
        tick();
        if(!probeBlocked || dmaResponses!=0 || held_valid || result_valid)
          $fatal(1,"DMA-only probe owner did not retain actual response");
      end
      @(negedge cpuClock); holdProbeResponse=0;
    end
    while(!doneSeen || returns<1)cpuTick();
    repeat(300)cpuTick();
    if(results[0]!=($test$plusargs("dma-no-park") ? 1 : 2) || fabricTerminals!=results[0])
      $fatal(1,"independent final park terminal count");
    if(lrPlain!=1 || scPlain!=1 || lrPark!=1 || scPark!=1 || lrDma!=1 || scDma!=1)
      $fatal(1,"independent LR/SC exact operation counts");
    if(sourceChecks!=1 || dmaStarts!=1 || valueChecks!=1 || guardChecks!=1 || externalTraps!=1 || externalHandlers!=1 ||
       claims!=($test$plusargs("wrong-irq") ? 2 : 1) || returns!=1 || msiAccepted!=1 || msiReplied!=1 || dmaIrq || timerTraps)
      $fatal(1,"independent DMA IRQ exact-once / CPU coherent read ledger");
    $display("A1_LRSC_PASS uncontended_success=1 park_consistent=1 DMA_invalidated_before_trap=1 DMA_value_guard=1 IRQ=1 terminals=%0d dma_park=%0d",results[0],!$test$plusargs("dma-no-park"));
    $finish;
  end
endmodule
