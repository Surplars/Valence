`timescale 1ns/1ps
// CDC-only test: real mailbox/barrier/FIFO, surrogate frame and status owners.
// Clock pausing is a TESTBENCH model, not an implementation of clock gating.
module rx_admission_stop_cdc_tb;
  reg controlRaw=0, rxRaw=0, commonReset=1;
  real controlHalf=5, rxHalf=4;
  reg controlPause=0, rxPause=0, controlGate=1, rxGate=1;
  wire controlClock=controlRaw && controlGate, rxClock=rxRaw && rxGate;
  initial forever #(controlHalf) controlRaw=~controlRaw;
  initial begin #1.125; forever #(rxHalf) rxRaw=~rxRaw; end
  always @(negedge controlRaw) controlGate<=!controlPause;
  always @(negedge rxRaw) rxGate<=!rxPause;

  reg requested=0, frameStart=0, rxIn_valid=0, rxOut_ready=0, statusReady=0;
  reg [31:0] rxIn_bits_data=0;
  reg [3:0] rxIn_bits_keep=0;
  reg rxIn_bits_last=0, rxIn_bits_bad=0;
  wire frameStartReady, nativeFrameActive, rxIn_ready, rxOut_valid;
  wire [31:0] rxOut_bits_data;
  wire [3:0] rxOut_bits_keep;
  wire rxOut_bits_last, rxOut_bits_bad;
  wire statusValid, rxFifoSourceIdle, cpuFifoIdle, stopNewFrames, settled, drained;
  GmacRxAdmissionStopCdcTop dut(.*);

  // This ledger is populated only by accepted external input, never DUT state.
  // Reset intentionally ends an epoch; stale words in the next epoch mismatch.
  reg [37:0] acceptedWords [0:4095];
  integer accepted=0, received=0, admittedFrames=0, acceptedFrames=0;
  integer receivedFrames=0, consumedStatuses=0, epoch=0;
  integer controlEdges=0, rxEdges=0, fifoFullCycles=0, heldOutputCycles=0;
  integer heldStatusCycles=0, preOutputCycles=0, drainChecks=0;
  integer caseNumber, frameNumber=0, pausedEdges, otherEdges;
  integer totalAccepted=0, totalReceived=0, resetDiscarded=0;
  longint unsigned inputChecksum=0, outputChecksum=0;
  reg expectedNativeActive=0, inputHeld=0, outputHeld=0;
  reg [37:0] previousInput, previousOutput, observedOutput;
  reg coalescingGuard=0, releaseRaceGuard=0, releaseSeen=0;
  reg observedDrain;
  string injection;

  always @(posedge rxClock or posedge commonReset) begin
    if (commonReset) begin
      accepted=0; admittedFrames=0; acceptedFrames=0; inputChecksum=0;
      expectedNativeActive=0; inputHeld=0; rxEdges=0; fifoFullCycles=0;
      releaseSeen=0;
    end else begin
      rxEdges++;
      if (nativeFrameActive !== expectedNativeActive)
        $fatal(1,"RX native frame ownership mismatch");
      if (inputHeld && (!rxIn_valid ||
          {rxIn_bits_data,rxIn_bits_keep,rxIn_bits_last,rxIn_bits_bad}!==previousInput))
        $fatal(1,"RX input stimulus changed under backpressure");
      inputHeld=rxIn_valid && !rxIn_ready;
      previousInput={rxIn_bits_data,rxIn_bits_keep,rxIn_bits_last,rxIn_bits_bad};
      if (frameStart && frameStartReady) begin
        if (stopNewFrames || expectedNativeActive)
          $fatal(1,"RX accepted a new frame while admission was closed");
        expectedNativeActive=1; admittedFrames++;
      end
      if (rxIn_valid && rxIn_ready) begin
        if (!expectedNativeActive || accepted>=4096)
          $fatal(1,"RX accepted unowned input or exhausted independent ledger");
        acceptedWords[accepted]=previousInput;
        inputChecksum+=64'(previousInput);
        accepted++; totalAccepted++;
        if (rxIn_bits_last) begin expectedNativeActive=0; acceptedFrames++; end
      end
      if (rxIn_valid && !rxIn_ready && nativeFrameActive) fifoFullCycles++;
      if (coalescingGuard && !stopNewFrames)
        $fatal(1,"RX unsent release must coalesce without opening admission");
      if (releaseRaceGuard && !stopNewFrames) releaseSeen=1;
    end
  end

  always @(posedge controlClock or posedge commonReset) begin
    if (commonReset) begin
      received=0; receivedFrames=0; consumedStatuses=0; outputChecksum=0;
      outputHeld=0; controlEdges=0; heldOutputCycles=0; heldStatusCycles=0;
      preOutputCycles=0; drainChecks=0;
    end else begin
      controlEdges++;
      observedOutput={rxOut_bits_data,rxOut_bits_keep,rxOut_bits_last,rxOut_bits_bad};
      if (outputHeld && (!rxOut_valid || observedOutput!==previousOutput))
        $fatal(1,"RX CDC output changed under backpressure");
      outputHeld=rxOut_valid && !rxOut_ready;
      previousOutput=observedOutput;
      if (outputHeld) heldOutputCycles++;
      if (statusValid && !statusReady) heldStatusCycles++;
      if (accepted>received && !cpuFifoIdle && !rxOut_valid && !statusValid) preOutputCycles++;
      if (rxOut_valid && rxOut_ready) begin
        // Negative control corrupts the observation, not RTL or the input oracle.
        if (injection=="payload" && received==7) observedOutput^=38'h1;
        if (received>=accepted || observedOutput!==acceptedWords[received])
          $fatal(1,"RX stop independent payload scoreboard mismatch");
        outputChecksum+=64'(observedOutput);
        received++; totalReceived++;
        if (rxOut_bits_last) receivedFrames++;
      end
      if (statusValid && statusReady) begin
        consumedStatuses++;
        if (consumedStatuses>receivedFrames) $fatal(1,"RX status completion duplicated");
      end
      observedDrain=drained || (injection=="drain" && requested &&
          nativeFrameActive && stopNewFrames);
      if (observedDrain) begin
        drainChecks++;
        if (!requested || !settled || !stopNewFrames || nativeFrameActive ||
            !rxFifoSourceIdle || !cpuFifoIdle || statusValid ||
            accepted!=received || inputChecksum!=outputChecksum ||
            admittedFrames!=acceptedFrames || acceptedFrames!=receivedFrames ||
            receivedFrames!=consumedStatuses || (releaseRaceGuard && !releaseSeen))
          $fatal(1,"RX stop independent drain scoreboard mismatch");
      end
    end
  end

  task automatic controlWait(input integer count);
    begin repeat(count) @(negedge controlClock); #0.001; end
  endtask
  task automatic resetEpoch;
    begin
      commonReset=1; controlPause=0; rxPause=0;
      requested=0; frameStart=0; rxIn_valid=0; rxOut_ready=0; statusReady=0;
      coalescingGuard=0; releaseRaceGuard=0; epoch++;
      #200; controlWait(1); commonReset=0; controlWait(20);
      if (nativeFrameActive || stopNewFrames || rxOut_valid || statusValid || drained || !settled)
        $fatal(1,"RX coordinated reset did not establish an empty released epoch");
    end
  endtask
  task automatic startFrame;
    integer budget;
    reg admitted;
    begin
      @(negedge rxClock); #0.001; frameStart=1; budget=0; admitted=0;
      while (!admitted) begin
        @(posedge rxClock); admitted=frameStartReady; budget++;
        if (budget>200) $fatal(1,"RX frame admission timeout");
      end
      @(negedge rxClock); #0.001; frameStart=0;
    end
  endtask
  task automatic sendBeats(input integer frameId, input integer offset,
      input integer count, input bit finishesFrame);
    integer k, budget;
    reg acceptedBeat;
    begin
      for (k=0;k<count;k++) begin
        @(negedge rxClock); #0.001;
        rxIn_valid=1;
        rxIn_bits_data=32'hc931a075 ^ (frameId*32'h01030507) ^
            ((offset+k)*32'h10200401) ^ (epoch*32'h31415161);
        rxIn_bits_last=finishesFrame && k==count-1;
        rxIn_bits_keep=rxIn_bits_last ? 4'((1 << (frameId%4+1))-1) : 4'hf;
        rxIn_bits_bad=rxIn_bits_last && frameId%3==1;
        budget=0; acceptedBeat=0;
        while (!acceptedBeat) begin
          @(posedge rxClock); acceptedBeat=rxIn_ready; budget++;
          if (budget>1000) $fatal(1,"RX accepted frame could not finish after stop");
        end
        @(negedge rxClock); #0.001; rxIn_valid=0;
      end
    end
  endtask
  task automatic waitStopVisible;
    integer budget;
    begin
      budget=0;
      while (!stopNewFrames) begin
        controlWait(1); budget++;
        if (budget>400) $fatal(1,"RX stop offer did not cross to media domain");
      end
    end
  endtask
  task automatic waitSettled;
    integer budget;
    begin
      budget=0;
      while (!settled) begin
        controlWait(1); budget++;
        if (budget>400) $fatal(1,"RX stop acknowledgement did not return");
      end
    end
  endtask
  task automatic waitDrained;
    integer budget;
    begin
      budget=0;
      while (!drained) begin
        controlWait(1); budget++;
        if (budget>2000) $fatal(1,"RX stop completion timeout");
      end
      controlWait(4);
      if (!stopNewFrames || !settled || nativeFrameActive || statusValid ||
          !rxFifoSourceIdle || !cpuFifoIdle || accepted!=received ||
          inputChecksum!=outputChecksum || admittedFrames!=acceptedFrames ||
          acceptedFrames!=receivedFrames || receivedFrames!=consumedStatuses)
        $fatal(1,"RX stop independent completion counter/checksum mismatch");
    end
  endtask
  task automatic releaseStop;
    integer budget;
    begin
      controlWait(1); requested=0; budget=0;
      // The extra edge prevents sampling the previous settled combinational value.
      controlWait(1);
      while (!settled || stopNewFrames) begin
        controlWait(1); budget++;
        if (budget>400) $fatal(1,"RX release did not reopen admission");
      end
      if (drained) $fatal(1,"RX release retained drained status");
    end
  endtask
  task automatic probeStoppedAdmission;
    integer beforeFrames;
    begin
      beforeFrames=admittedFrames;
      @(negedge rxClock); #0.001; frameStart=1;
      repeat(6) begin
        @(posedge rxClock);
        if (frameStartReady) $fatal(1,"RX stopped domain admitted another frame");
      end
      @(negedge rxClock); #0.001; frameStart=0;
      if (admittedFrames!=beforeFrames) $fatal(1,"RX stopped admission count changed");
    end
  endtask
  task automatic waitStatusTail;
    integer budget;
    begin
      budget=0;
      while (!statusValid || !cpuFifoIdle || !settled) begin
        controlWait(1); budget++;
        if (budget>2000) $fatal(1,"RX status-tail hold coverage timeout");
      end
      controlWait(12);
      if (drained || !statusValid || !cpuFifoIdle || !rxFifoSourceIdle)
        $fatal(1,"RX stop ignored held CPU adapter status");
      statusReady=1; waitDrained();
    end
  endtask
  task automatic pauseMedia;
    begin rxPause=1; @(negedge rxRaw); #0.001; end
  endtask
  task automatic resumeMedia;
    begin rxPause=0; @(negedge rxRaw); #0.001; end
  endtask

  task automatic activeFrameStop;
    integer budget;
    begin
      frameNumber++; startFrame();
      fork
        sendBeats(frameNumber,0,32,1);
        begin
          budget=0;
          while (!(rxIn_valid && !rxIn_ready && nativeFrameActive)) begin
            controlWait(1); budget++;
            if (budget>300) $fatal(1,"RX full-FIFO backpressure coverage missing");
          end
          requested=1; waitStopVisible(); controlWait(20);
          if (!nativeFrameActive || settled || drained || !fifoFullCycles)
            $fatal(1,"RX acknowledged stop before active frame/FIFO drain");
          // A release never accepted by the occupied mailbox may coalesce.
          coalescingGuard=1; requested=0; controlWait(2);
          if (settled || drained) $fatal(1,"RX pending stop falsely settled after cancellation");
          requested=1; controlWait(2);
          if (settled || drained) $fatal(1,"RX coalesced stop bypassed active frame");
          rxOut_ready=1;
        end
      join
      waitStatusTail(); coalescingGuard=0; probeStoppedAdmission();
    end
  endtask

  task automatic heldOutputStop;
    integer budget;
    begin
      releaseStop(); rxOut_ready=0; statusReady=0;
      frameNumber++; startFrame(); sendBeats(frameNumber,0,1,1);
      budget=0;
      while (!rxOut_valid || !rxFifoSourceIdle) begin
        controlWait(1); budget++;
        if (budget>400) $fatal(1,"RX held output did not release RAM pointer ownership");
      end
      if (cpuFifoIdle || nativeFrameActive)
        $fatal(1,"RX pointer-empty versus destination storage coverage missing");
      requested=1; controlWait(1); waitSettled(); controlWait(15);
      if (drained || !rxOut_valid || cpuFifoIdle || !rxFifoSourceIdle)
        $fatal(1,"RX stop ignored prefetched/held CPU FIFO output");
      rxOut_ready=1; waitStatusTail();
    end
  endtask

  task automatic acceptedReleaseRace;
    begin
      // Freeze RX before accepting RELEASE at the CPU mailbox. STOP then queues
      // behind that actual release, so its old stop ACK must never be reused.
      pauseMedia(); pausedEdges=rxEdges;
      controlWait(1); requested=0; releaseRaceGuard=1; releaseSeen=0;
      controlWait(3); requested=1; controlWait(20);
      if (settled || drained || rxEdges!=pausedEdges || !stopNewFrames)
        $fatal(1,"RX accepted release/re-stop reused stale acknowledgement");
      resumeMedia(); waitDrained();
      if (!releaseSeen) $fatal(1,"RX accepted release was not applied before re-stop");
      releaseRaceGuard=0; probeStoppedAdmission();
    end
  endtask

  task automatic pausedMediaStop;
    begin
      releaseStop(); rxOut_ready=1; statusReady=1;
      frameNumber++; startFrame(); sendBeats(frameNumber,0,2,0);
      pauseMedia(); pausedEdges=rxEdges;
      controlWait(1); requested=1; controlWait(30);
      if (settled || drained || rxEdges!=pausedEdges || !nativeFrameActive)
        $fatal(1,"RX pending stop completed while media/source clock was paused");
      resumeMedia(); waitStopVisible(); sendBeats(frameNumber,2,6,1); waitDrained();
    end
  endtask

  task automatic pausedControlStop;
    begin
      releaseStop(); rxOut_ready=0; statusReady=1;
      frameNumber++; startFrame(); sendBeats(frameNumber,0,2,0);
      controlWait(1); requested=1; controlWait(1);
      controlPause=1; @(negedge controlRaw); #0.001;
      pausedEdges=controlEdges; otherEdges=rxEdges;
      #(rxHalf*60);
      if (controlEdges!=pausedEdges || rxEdges<=otherEdges ||
          !stopNewFrames || settled || drained || !nativeFrameActive)
        $fatal(1,"RX request/ownership was not retained with command source clock paused");
      controlPause=0; @(negedge controlRaw); #0.001;
      controlWait(1); rxOut_ready=1;
      sendBeats(frameNumber,2,6,1); waitDrained();
    end
  endtask

  task automatic pendingStopReset;
    begin
      releaseStop(); rxOut_ready=0; statusReady=0;
      frameNumber++; startFrame(); sendBeats(frameNumber,0,2,0);
      controlWait(1); requested=1; waitStopVisible(); controlWait(20);
      if (!nativeFrameActive || settled || drained || accepted<=received)
        $fatal(1,"RX pending coordinated-reset coverage missing");
      resetDiscarded+=accepted-received;
      resetEpoch();
      // No pre-reset sender survives. Fresh payloads and independent ledgers
      // ensure old FIFO data, held status or mailbox ownership cannot leak.
      rxOut_ready=1; statusReady=1;
      frameNumber++; startFrame(); sendBeats(frameNumber,0,12,1);
      controlWait(1); requested=1; waitDrained(); probeStoppedAdmission();
    end
  endtask

  initial begin
    injection="";
    if ($test$plusargs("inject_payload")) injection="payload";
    if ($test$plusargs("inject_drain")) injection="drain";
    for (caseNumber=0;caseNumber<4;caseNumber++) begin
      case(caseNumber)
        0: begin controlHalf=5; rxHalf=4; end // 100 MHz / 125 MHz
        1: begin controlHalf=4; rxHalf=5; end // reversed clock ratio
        2: begin controlHalf=3; rxHalf=11; end // much slower media
        3: begin controlHalf=11; rxHalf=3; end // much faster media
      endcase
      resetEpoch();
      activeFrameStop(); heldOutputStop(); acceptedReleaseRace();
      pausedMediaStop(); pausedControlStop();
      if (!fifoFullCycles || !heldOutputCycles || !heldStatusCycles || !preOutputCycles || !drainChecks)
        $fatal(1,"RX independent-clock case missed required ownership/storage coverage");
      $display("RX_STOP_CASE_DATA case=%0d accepted=%0d received=%0d frames=%0d statuses=%0d checksum=%016h full=%0d held_output=%0d held_status=%0d pre_output=%0d",
          caseNumber,accepted,received,receivedFrames,consumedStatuses,outputChecksum,
          fifoFullCycles,heldOutputCycles,heldStatusCycles,preOutputCycles);
      pendingStopReset();
      $display("RX_STOP_CASE_PASS case=%0d clocks_ns=%0.3f/%0.3f reset_epoch=%0d accepted=%0d received=%0d checksum=%016h",
          caseNumber,2*controlHalf,2*rxHalf,epoch,accepted,received,outputChecksum);
    end
    if (totalAccepted!=totalReceived+resetDiscarded || resetDiscarded!=8)
      $fatal(1,"RX lifetime accepted/delivered/coordinated-reset ledger mismatch");
    $display("RX_ADMISSION_STOP_CDC_PASS clock_cases=4 active_frame=1 fifo_backpressure=1 held_output=1 status_tail=1 coalesced_release=1 accepted_release_restop=1 paused_media=1 paused_control=1 coordinated_reset=1 accepted=%0d received=%0d reset_discarded=%0d",
        totalAccepted,totalReceived,resetDiscarded);
    $finish;
  end
  initial begin #2000000; $fatal(1,"RX admission stop CDC global timeout"); end
endmodule
