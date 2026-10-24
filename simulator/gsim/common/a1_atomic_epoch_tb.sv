`timescale 1ns/1ps
module a1_atomic_epoch_tb;
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
  wire tileHeld_valid, fabricHeld_valid, trap, fabricIdle; reg retire_valid;
  wire [7:0] tileHeld_bits, fabricHeld_bits;
  wire releaseAckBlocked, completionBlocked, cpuCompletionBlocked, msiReplyBlocked;
  wire [31:0] releaseBeats, coherentAcquires, cpuResumed; reg [31:0] retire_instruction;
  wire [31:0] msiAccepted, msiReplied, msiAccepted11, msiAccepted12, msiAccepted13;
  wire [31:0] fabricPrepares, fabricResumes, fabricCancels, fabricTerminals;
  wire fabricTerminalValid, fabricTerminalReady, cpuLinkReady, fabricLinkReady;
  wire cpuTransportEmpty, fabricTransportEmpty;
  wire busy, timeoutSelected, cleanupFault, epochExhausted, activeLane;
  wire [7:0] activeEpoch; wire [31:0] activeToken;
  reg [63:0] retire_pc, retire_data;
  reg [4:0] retire_rd; reg retire_writesRd;
  wire [1:0] rv, rw;
  wire [31:0] ri[0:1]; wire [63:0] rp[0:1],rd[0:1]; wire [4:0] rr[0:1];
  reg [31:0] rom [0:255]; reg [4095:0] rom_path;
  reg wrongData = 0, wrongStore = 0, wrongIrq = 0;
  integer cycles = 0, aonCycles = 0, resetGeneration = 0;
  integer retires = 0, stores = 0, loads = 0, previousLoads = 0, loops = 0, pendingReads = 0, loopPhase = 0;
  integer requests [0:1], resumes [0:1], cancels [0:1], results [0:1], acceptedCycle [0:1];
  integer expected11 = 0, expected12 = 0, expected13 = 0;
  reg [63:0] expectedData = 0, eventMask = 0, lastPending = 0;
  integer i, lane, old, oldCpuResumed, oldFabricPrepares, oldFabricCancels;

  reg holdAtomicRead=0, holdAtomicWrite=0, holdMemoryResponse=0, holdAtomicResult=0;
  wire atomicRequestFire, atomicResponseFire, memoryRequestFire, memoryRequestWrite, memoryResponseFire;
  wire atomicActive, reservationClear, atomicReadBlocked, atomicWriteBlocked, memoryResponseBlocked, atomicResultBlocked;
  wire [4:0] atomicOperation;
  wire [63:0] atomicAddress, atomicData, atomicResponseData, memoryRequestData, memoryRequestAddress, memoryResponseData;
  wire [63:0] trapPc, trapCause;
  wire architecturalStopped;
  integer atomicRequests=0, atomicResponses=0, physicalReads=0, physicalWrites=0, clears=0;
  integer amoRetires=0, lrRetires=0, scRetires=0, doneSeen=0, valueChecks=0;
  integer scenario, beforeClears, blockedRetires;
  reg wrongOld=0, wrongFinal=0, wrongSc=0;
  reg [4:0] ownedOperation;
  reg [63:0] ownedAddress;
  integer ownedReads=0, ownedWrites=0, ownedMemoryResponses=0;
  CommonA1AtomicRuntimeFixture dut(
    .observe_holdAtomicRead(holdAtomicRead), .observe_holdAtomicWrite(holdAtomicWrite),
    .observe_holdMemoryResponse(holdMemoryResponse), .observe_holdAtomicResult(holdAtomicResult),
    .observe_atomicRequestFire(atomicRequestFire), .observe_atomicOperation(atomicOperation),
    .observe_atomicAddress(atomicAddress), .observe_atomicData(atomicData),
    .observe_atomicResponseFire(atomicResponseFire), .observe_atomicResponseData(atomicResponseData),
    .observe_memoryRequestFire(memoryRequestFire), .observe_memoryWrite(memoryRequestWrite),
    .observe_memoryData(memoryRequestData), .observe_memoryAddress(memoryRequestAddress),
    .observe_memoryResponseFire(memoryResponseFire), .observe_memoryResponseData(memoryResponseData),
    .observe_atomicActive(atomicActive), .observe_reservationClear(reservationClear),
    .observe_atomicReadBlocked(atomicReadBlocked), .observe_atomicWriteBlocked(atomicWriteBlocked),
    .observe_memoryResponseBlocked(memoryResponseBlocked), .observe_atomicResultBlocked(atomicResultBlocked),
    .observe_trapPc(trapPc), .observe_trapCause(trapCause), .observe_architecturalStopped(architecturalStopped),
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

  task tick; begin @(negedge alwaysOnClock); end endtask
  task fabricTick; begin @(negedge fabricClock); end endtask
  always @(posedge alwaysOnClock) begin
    aonCycles = aonCycles + 1;
    if (aonCycles > 160000) $fatal(1,"atomic epoch AON watchdog");
    if (!reset && (cleanupFault || epochExhausted || timeoutSelected))
      $fatal(1,"unexpected atomic epoch timeout/fault");
  end
  always @(posedge fabricClock) begin
    if (reset) begin
      atomicRequests=0; atomicResponses=0; physicalReads=0; physicalWrites=0; clears=0;
      ownedReads=0; ownedWrites=0; ownedMemoryResponses=0;
    end else begin
      if (reservationClear) clears=clears+1;
      if (atomicRequestFire) begin
        if (atomicRequests != atomicResponses) $fatal(1,"overlapping atomic owners");
        atomicRequests=atomicRequests+1; ownedOperation=atomicOperation; ownedAddress=atomicAddress;
        ownedReads=0; ownedWrites=0; ownedMemoryResponses=0;
        case (atomicRequests)
          1: if (atomicOperation!=0 || atomicAddress!=64'h80200000 || atomicData!=5) $fatal(1,"AMO.D input ledger");
          default: $fatal(1,"unexpected duplicate atomic request");
        endcase
      end
      if (atomicActive && memoryRequestFire) begin
        if (memoryRequestAddress!=ownedAddress) $fatal(1,"physical atomic address changed");
        if (memoryRequestWrite) begin
          physicalWrites=physicalWrites+1; ownedWrites=ownedWrites+1;
          if (ownedOperation==3) $fatal(1,"post-epoch failed SC performed a physical write");
          if (ownedAddress==64'h80200000 && memoryRequestData!=12) $fatal(1,"AMO.D physical new-value ledger");
          if (ownedAddress==64'h8020000c && memoryRequestData!=64'h8000000300000000)
            $fatal(1,"AMO.W physical upper-lane new-value ledger");
        end else begin physicalReads=physicalReads+1; ownedReads=ownedReads+1; end
      end
      if (memoryResponseFire) ownedMemoryResponses=ownedMemoryResponses+1;
      if (atomicResponseFire) begin
        if (ownedMemoryResponses!=ownedReads+ownedWrites) $fatal(1,"atomic completed before all real physical responses");
        atomicResponses=atomicResponses+1;
        case (atomicResponses)
          1: if (atomicResponseData!=7 || ownedReads!=1 || ownedWrites!=1) $fatal(1,"AMO.D owner result ledger");
          default: $fatal(1,"duplicate atomic result");
        endcase
      end
    end
  end
  always @(posedge cpuClock) begin
    if (reset) begin amoRetires=0; lrRetires=0; scRetires=0; valueChecks=0; doneSeen=0; retires=0; end
    else begin
      if (start && trap) $fatal(1,"atomic guest trap pc=%h cause=%h",trapPc,trapCause);
      for (lane=0;lane<2;lane=lane+1) begin
      retire_valid=rv[lane]; retire_pc=rp[lane]; retire_instruction=ri[lane];
      retire_rd=rr[lane]; retire_data=rd[lane]; retire_writesRd=rw[lane];
      if (start && retire_valid) begin
        retires=retires+1;
        if (retire_pc==PC_GUEST_FAIL) $fatal(1,"atomic guest comparison failed");
        if (retire_pc==PC_AMO_D) begin
          amoRetires=amoRetires+1;
          if (amoRetires!=1 || !retire_writesRd || retire_rd!=23 || retire_instruction!=32'h01443baf || retire_data !== 64'd7+(wrongOld?1:0))
            $fatal(1,"independent atomic old-value oracle");
        end
        if (retire_pc==PC_CHECK_D) begin
          valueChecks=valueChecks+1;
          if (!retire_writesRd || retire_rd!=21 || retire_data !== 64'd12+(wrongFinal?1:0))
            $fatal(1,"independent atomic final-value oracle");
        end
        if (retire_pc==PC_GUEST_DONE) doneSeen=1;
      end
      end
    end
  end
  task requestEpoch(input [31:0] token);
    begin
      tick(); request_bits[0]=token; request_valid[0]=1;
      @(posedge alwaysOnClock); while(!request_ready[0]) @(posedge alwaysOnClock);
      tick(); request_valid[0]=0;
      while (fabricPrepares==fabricTerminals) tick();
    end
  endtask
  task finishEpoch(input [31:0] token);
    integer terminalBefore, n, retiredBefore;
    begin
      while (!held_valid[0]) tick();
      if (!tileHeld_valid || !fabricHeld_valid || !architecturalStopped || !fabricIdle ||
          !cpuTransportEmpty || !fabricTransportEmpty || held_token[0]!=token || held_valid[1])
        $fatal(1,"atomic epoch held without real owner drain");
      allocatedEpoch[0]=held_epoch[0]; retiredBefore=retires;
      repeat (12) begin
        tick();
        if (!held_valid[0] || retires!=retiredBefore || atomicActive) $fatal(1,"atomic held proof unstable");
      end
      @(negedge cpuClock); externalStop=0;
      tick(); resume_bits[0]=token; resume_epoch[0]=allocatedEpoch[0]; resume_valid[0]=1;
      @(posedge alwaysOnClock); while(!resume_ready[0]) @(posedge alwaysOnClock);
      tick(); resume_valid[0]=0;
      while (!result_valid[0]) tick();
      terminalBefore=fabricTerminals;
      repeat(12) begin
        if (result_token[0]!=token || result_epoch[0]!=allocatedEpoch[0] || result_canceled[0] || result_timedOut[0] ||
            !busy || fabricTerminals!=terminalBefore) $fatal(1,"atomic terminal ownership");
        tick();
      end
      result_ready[0]=1;
      @(posedge alwaysOnClock); while(!result_valid[0]) @(posedge alwaysOnClock);
      tick(); result_ready[0]=0;
      while (busy || fabricTerminals==terminalBefore) tick();
      if (fabricTerminals!=terminalBefore+1) $fatal(1,"atomic terminal duplicated");
    end
  endtask
  initial begin
    wrongOld=$test$plusargs("wrong-old"); wrongFinal=$test$plusargs("wrong-final"); wrongSc=$test$plusargs("wrong-sc");
    if (!$value$plusargs("rom=%s",rom_path)) $fatal(1,"missing atomic guest ROM");
    $readmemh(rom_path,rom);
    for (i=0;i<2;i=i+1) begin request_bits[i]=0; resume_bits[i]=0; cancel_bits[i]=0; resume_epoch[i]=0; cancel_epoch[i]=0; end
    for (scenario=0;scenario<4;scenario=scenario+1) begin
      reset=1; start=0; externalStop=0; request_valid=0; resume_valid=0; result_ready=0;
      holdAtomicRead=(scenario==0 || scenario==3); holdAtomicWrite=(scenario==1); holdAtomicResult=(scenario==2); holdMemoryResponse=0;
      repeat(20) tick(); reset=0;
      repeat(20) fabricTick();
      for(i=0;i<256;i=i+1) begin program_valid=1; program_index=i; program_data=rom[i]; fabricTick(); end
      program_valid=0; start=1;
      if(scenario==0 || scenario==3) while(!atomicReadBlocked) fabricTick();
      if(scenario==1) while(!atomicWriteBlocked) fabricTick();
      if(scenario==2) while(!atomicResultBlocked) fabricTick();
      if(scenario==3) begin
        fabricTick(); holdMemoryResponse=1; holdAtomicRead=0;
        while(!memoryResponseBlocked) fabricTick();
      end
      requestEpoch(32'h4100+scenario);
      repeat(64) begin
        tick();
        if (!atomicActive || held_valid!=0 || tileHeld_valid || fabricHeld_valid || result_valid!=0 || amoRetires!=0)
          $fatal(1,"atomic outstanding owner was falsely drained");
      end
      fabricTick(); holdAtomicRead=0; holdAtomicWrite=0; holdAtomicResult=0; holdMemoryResponse=0;
      while(!held_valid[0]) tick();
      finishEpoch(32'h4100+scenario);
      while(!doneSeen) tick();
      repeat(12) tick();
      if(atomicRequests!=1 || atomicResponses!=1 || physicalReads!=1 || physicalWrites!=1 ||
          amoRetires!=1 || valueChecks!=1 || fabricTerminals!=1)
        $fatal(1,"exact atomic end-to-end ledger");
      $display("A1_ATOMIC_EPOCH_CASE scenario=%0d atomics=%0d responses=%0d reads=%0d writes=%0d clears=%0d terminals=%0d",scenario,atomicRequests,atomicResponses,physicalReads,physicalWrites,clears,fabricTerminals);
      $fflush();
    end
    $display("A1_ATOMIC_EPOCH_PASS"); $finish;
  end
endmodule
