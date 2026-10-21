`timescale 1ns/1ps
module i1_msi_epoch_tb;
  `include "guest_symbols.svh"
  reg clock = 0;
  always #5 clock = ~clock;
  reg reset = 1, start = 0, program_valid = 0;
  reg [5:0] program_index = 0;
  reg [31:0] program_data = 0;
  reg prepare_valid = 0, resume_valid = 0, cancel_valid = 0, complete_ready = 0;
  reg [7:0] prepare_bits = 0, resume_bits = 0, cancel_bits = 0;
  reg holdReleaseAck = 0, holdCompletion = 0, externalStop = 0, holdMsiReply = 0;
  reg [63:0] sources = 0;
  wire prepare_ready, resume_ready, cancel_ready, complete_valid, complete_canceled;
  wire [7:0] complete_epoch, tileHeld_bits, fabricHeld_bits;
  wire tileHeld_valid, fabricHeld_valid, retire_valid, trap, fabricIdle;
  wire releaseAckBlocked, completionBlocked, msiReplyBlocked;
  wire [31:0] releaseBeats, coherentAcquires, retire_instruction;
  wire [31:0] msiAccepted, msiReplied, msiAccepted11, msiAccepted12, msiAccepted13;
  wire [63:0] retire_pc, retire_data;
  wire [4:0] retire_rd;
  wire retire_writesRd;
  reg [31:0] rom [0:63];
  reg [4095:0] rom_path;
  reg wrongData = 0, wrongIrq = 0;
  integer cycles = 0, resetGeneration = 0;
  integer retires = 0, stores = 0, loads = 0, previousLoads = 0, loops = 0, pendingReads = 0, loopPhase = 0;
  integer prepares = 0, resumes = 0, cancels = 0, completions = 0;
  integer expected11 = 0, expected12 = 0, expected13 = 0;
  reg [63:0] expectedData = 0, eventMask = 0, lastPending = 0;
  integer i;

  CommonI1RuntimeEpochFixture dut(
    .clock(clock), .reset(reset), .io_start(start),
    .io_program_valid(program_valid), .io_program_bits_index(program_index), .io_program_bits_data(program_data),
    .io_prepare_valid(prepare_valid), .io_prepare_bits(prepare_bits), .io_prepare_ready(prepare_ready),
    .io_resume_valid(resume_valid), .io_resume_bits(resume_bits), .io_resume_ready(resume_ready),
    .io_cancel_valid(cancel_valid), .io_cancel_bits(cancel_bits), .io_cancel_ready(cancel_ready),
    .io_complete_valid(complete_valid), .io_complete_ready(complete_ready),
    .io_complete_bits_epoch(complete_epoch), .io_complete_bits_canceled(complete_canceled),
    .io_externalStop(externalStop), .io_holdReleaseAck(holdReleaseAck), .io_holdCompletion(holdCompletion),
    .io_releaseAckBlocked(releaseAckBlocked), .io_completionBlocked(completionBlocked),
    .io_sources(sources), .io_holdMsiReply(holdMsiReply), .io_msiReplyBlocked(msiReplyBlocked),
    .io_msiAccepted(msiAccepted), .io_msiReplied(msiReplied),
    .io_msiAccepted11(msiAccepted11), .io_msiAccepted12(msiAccepted12), .io_msiAccepted13(msiAccepted13),
    .io_tileHeld_valid(tileHeld_valid), .io_tileHeld_bits(tileHeld_bits),
    .io_fabricHeld_valid(fabricHeld_valid), .io_fabricHeld_bits(fabricHeld_bits),
    .io_retire_valid(retire_valid), .io_retire_bits_pc(retire_pc), .io_retire_bits_instruction(retire_instruction),
    .io_retire_bits_rd(retire_rd), .io_retire_bits_data(retire_data), .io_retire_bits_writesRd(retire_writesRd),
    .io_trap(trap), .io_releaseBeats(releaseBeats), .io_coherentAcquires(coherentAcquires), .io_fabricIdle(fabricIdle));

  // Independent ledgers use physical input transitions and architectural PCs,
  // never DUT pending state or DUT-derived instruction expectations.
  always @(posedge clock) begin
    cycles = cycles + 1;
    if (cycles > 160000) $fatal(1, "I1 MSI epoch watchdog");
    if (reset) begin
      retires = 0; stores = 0; loads = 0; previousLoads = 0; loops = 0; pendingReads = 0; loopPhase = 0;
      prepares = 0; resumes = 0; cancels = 0; completions = 0;
      expectedData = 0; lastPending = 0;
    end else begin
      if (prepare_valid && prepare_ready) prepares = prepares + 1;
      if (resume_valid && resume_ready) resumes = resumes + 1;
      if (cancel_valid && cancel_ready) cancels = cancels + 1;
      if (complete_valid && complete_ready) completions = completions + 1;
      if (msiAccepted !== msiAccepted11 + msiAccepted12 + msiAccepted13)
        $fatal(1, "MSI delivered an unrequested identity");
      if (msiAccepted11 > expected11 || msiAccepted12 > expected12 || msiAccepted13 > expected13)
        $fatal(1, "independent MSI event ledger: duplicate or unrequested delivery");
      if (msiReplied > msiAccepted) $fatal(1, "MSI returned response without delivered owner");
      if (start && trap) $fatal(1, "unexpected real I1 trap");
      if (start && retire_valid) begin
        retires = retires + 1;
        if (retire_pc == PC_GUEST_FAIL) $fatal(1, "guest memory comparison failed");
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

  task tick;
    begin @(posedge clock); #1; @(negedge clock); end
  endtask

  task setSources(input [2:0] value);
    reg [2:0] rising;
    begin
      rising = value & ~sources[2:0];
      if (rising[0]) begin expected11 = expected11 + 1; eventMask = eventMask | 64'h800; end
      if (rising[1]) begin expected12 = expected12 + 1; eventMask = eventMask | 64'h1000; end
      if (rising[2]) begin expected13 = expected13 + 1; eventMask = eventMask | 64'h2000; end
      sources = {61'b0, value};
    end
  endtask

  task advanceLoops(input integer count);
    integer target;
    begin target = loops + count; while (loops < target || loopPhase != 0) tick(); end
  endtask

  task prepareEpoch(input [7:0] tag);
    integer old;
    begin
      old = prepares; prepare_bits = tag; prepare_valid = 1;
      while (prepares == old) tick();
      prepare_valid = 0;
    end
  endtask

  task waitHeld(input [7:0] tag);
    begin
      while (!(tileHeld_valid && fabricHeld_valid)) tick();
      if (tileHeld_bits != tag || fabricHeld_bits != tag || !fabricIdle)
        $fatal(1, "matching real I1/fabric held epoch absent");
      if (msiReplied != msiAccepted) $fatal(1, "held proof dropped an accepted MSI response owner");
    end
  endtask

  task heldStable(input [7:0] tag, input integer duration);
    integer oldRetires, oldStores, oldAcquires, oldMsi, oldReplies, n;
    begin
      oldRetires = retires; oldStores = stores; oldAcquires = coherentAcquires;
      oldMsi = msiAccepted; oldReplies = msiReplied;
      for (n = 0; n < duration; n = n + 1) begin
        tick();
        if (!tileHeld_valid || !fabricHeld_valid || tileHeld_bits != tag || fabricHeld_bits != tag || !fabricIdle)
          $fatal(1, "pending physical interrupt lost held proof");
        if (retires != oldRetires || stores != oldStores || coherentAcquires != oldAcquires)
          $fatal(1, "held epoch admitted architectural memory work");
        if (msiAccepted != oldMsi || msiReplied != oldReplies)
          $fatal(1, "new MSI request handshake while held");
      end
    end
  endtask

  task rejectCancel(input [7:0] tag);
    integer old, n;
    begin
      old = cancels; cancel_bits = tag; cancel_valid = 1;
      for (n = 0; n < 3; n = n + 1) begin
        tick(); if (cancel_ready || cancels != old) $fatal(1, "stale or duplicate cancel accepted");
      end
      cancel_valid = 0;
    end
  endtask

  task cancelEpoch(input [7:0] tag);
    integer old;
    begin
      old = cancels; cancel_bits = tag; cancel_valid = 1;
      while (cancels == old) tick(); cancel_valid = 0;
    end
  endtask

  task resumeEpoch(input [7:0] tag);
    integer old;
    begin
      old = resumes; resume_bits = tag; resume_valid = 1;
      while (resumes == old) tick(); resume_valid = 0;
    end
  endtask

  task terminal(input [7:0] tag, input bit canceled, input integer deliveredBeforeRelease);
    integer old, n;
    begin
      old = completions;
      while (!complete_valid) tick();
      for (n = 0; n < 12; n = n + 1) begin
        if (!complete_valid || complete_epoch != tag || complete_canceled != canceled || prepare_ready)
          $fatal(1, "terminal result lost epoch/cancel data under backpressure");
        if (tileHeld_valid || fabricHeld_valid) $fatal(1, "terminal preceded actual epoch release");
        if (msiAccepted != deliveredBeforeRelease || msiReplied != deliveredBeforeRelease)
          $fatal(1, "MSI admission reopened before terminal completion acceptance");
        tick();
      end
      rejectCancel(tag);
      if (msiAccepted != deliveredBeforeRelease || msiReplied != deliveredBeforeRelease)
        $fatal(1, "MSI ledger changed while terminal response remained backpressured");
      complete_ready = 1; while (completions == old) tick(); complete_ready = 0;
      if (completions != old + 1) $fatal(1, "duplicate terminal handshake");
    end
  endtask

  task exactLedger(input integer a11, input integer a12, input integer a13, input [63:0] pending);
    reg [63:0] oracle;
    begin
      while (msiAccepted != a11 + a12 + a13 || msiReplied != a11 + a12 + a13) tick();
      advanceLoops(6);
      if (msiAccepted11 != a11 || msiAccepted12 != a12 || msiAccepted13 != a13 ||
          msiAccepted != a11 + a12 + a13 || msiReplied != a11 + a12 + a13)
        $fatal(1, "exact accepted/delivered MSI identity ledger mismatch");
      oracle = pending ^ (wrongIrq ? 64'h4000 : 64'h0);
      if (lastPending !== oracle) $fatal(1, "independent IMSIC pending oracle: eventual CSR bitmap mismatch");
      if (stores != loads || loads != expectedData || loops != loads || previousLoads != loops)
        $fatal(1, "independent memory retirement side-effect ledger mismatch");
      $display("I1_MSI_EPOCH_LEDGER generation=%0d delivered=%0d replied=%0d id11=%0d id12=%0d id13=%0d pending=%h stores=%0d loads=%0d previous_loads=%0d loops=%0d",
        resetGeneration, msiAccepted, msiReplied, msiAccepted11, msiAccepted12, msiAccepted13, lastPending, stores, loads, previousLoads, loops);
    end
  endtask

  task boot;
    begin
      start = 0; reset = 1; sources = 0;
      expected11 = 0; expected12 = 0; expected13 = 0; eventMask = 0;
      prepare_valid = 0; resume_valid = 0; cancel_valid = 0; complete_ready = 0;
      holdMsiReply = 0; holdReleaseAck = 0; holdCompletion = 0; externalStop = 0;
      repeat (5) tick(); reset = 0; tick();
      for (i = 0; i < 64; i = i + 1) begin
        program_valid = 1; program_index = i; program_data = rom[i]; tick();
      end
      program_valid = 0; start = 1; advanceLoops(3);
      if (msiAccepted != 0 || msiReplied != 0 || lastPending != 0)
        $fatal(1, "coordinated reset leaked old MSI owners or pending state");
    end
  endtask

  initial begin
    wrongData = $test$plusargs("wrong-data"); wrongIrq = $test$plusargs("wrong-irq");
    if (!$value$plusargs("rom=%s", rom_path)) $fatal(1, "missing independently compiled guest image");
    $readmemh(rom_path, rom);
    boot();
    rejectCancel(8'hff);

    // A real accepted MSI response is held before PREPARE. It must drain, not
    // disappear, before either the held proof or a terminal result can exist.
    holdMsiReply = 1; setSources(3'b001);
    while (msiAccepted != 1 || !msiReplyBlocked) tick();
    prepareEpoch(8'd40);
    repeat (24) begin
      tick(); if (fabricHeld_valid || complete_valid || msiReplied != 0)
        $fatal(1, "pre-hold MSI response owner was discarded");
    end
    holdMsiReply = 0; waitHeld(8'd40);
    if (msiAccepted != 1 || msiReplied != 1) $fatal(1, "pre-hold MSI owner failed to drain");
    setSources(3'b111); heldStable(8'd40, 48); rejectCancel(8'd39);
    resumeEpoch(8'd40); terminal(8'd40, 0, 1); exactLedger(1, 1, 1, 64'h3800);

    // Source 1 stays high throughout. Only fresh source 2/3 edges are owed.
    // Each previous APLIC event was already delivered before re-arming low;
    // IMSIC pending is intentionally a coalescing bitmap, not an event count.
    // CANCEL releases the actual held epoch but does not erase queued events.
    setSources(3'b001); advanceLoops(4); prepareEpoch(8'd41); waitHeld(8'd41);
    setSources(3'b111); heldStable(8'd41, 48);
    cancelEpoch(8'd41); terminal(8'd41, 1, 3); exactLedger(1, 2, 2, 64'h3800);

    // Cancellation before drain completion must retain a stalled real MSI
    // reply owner, while the other two source events remain unaccepted.
    setSources(3'b000); advanceLoops(4); holdMsiReply = 1; setSources(3'b001);
    while (msiAccepted != 6 || !msiReplyBlocked) tick();
    prepareEpoch(8'd42); setSources(3'b111); cancelEpoch(8'd42);
    repeat (32) begin
      tick(); if (fabricHeld_valid || complete_valid || msiAccepted != 6 || msiReplied != 5)
        $fatal(1, "cancel revoked live MSI owner or admitted pending MSI before release");
    end
    holdMsiReply = 0; terminal(8'd42, 1, 6); exactLedger(2, 3, 3, 64'h3800);
    if (prepares != 3 || resumes != 1 || cancels != 2 || completions != 3)
      $fatal(1, "normal/canceled epoch accepted-control ledger mismatch");

    // Only a coordinated reset of CPU, fabric, APLIC, IMSIC and the admission
    // ledger may discard this accepted response plus queued upstream events.
    setSources(3'b000); advanceLoops(4); holdMsiReply = 1; setSources(3'b001);
    while (msiAccepted != 9 || !msiReplyBlocked) tick();
    prepareEpoch(8'd43); setSources(3'b111);
    repeat (24) begin
      tick(); if (complete_valid || fabricHeld_valid || msiAccepted != 9 || msiReplied != 8)
        $fatal(1, "pre-reset MSI ownership was not live and blocked");
    end
    $display("I1_MSI_EPOCH_RESET generation=0 prepares=%0d completed=%0d reset_aborted=1 delivered=9 replied=8 pending_unaccepted=2",
      prepares, completions);
    resetGeneration = 1; boot();
    prepareEpoch(8'd44); waitHeld(8'd44); setSources(3'b111); heldStable(8'd44, 48);
    resumeEpoch(8'd44); terminal(8'd44, 0, 0); exactLedger(1, 1, 1, 64'h3800);
    advanceLoops(6); exactLedger(1, 1, 1, 64'h3800);
    if (prepares != 1 || resumes != 1 || cancels != 0 || completions != 1)
      $fatal(1, "post-reset epoch ledger mismatch");
    $display("I1_MSI_EPOCH_PASS normal_resumes=2 cancellations=2 completed=4 coordinated_reset_aborts=1 cycles=%0d", cycles);
    $finish;
  end
endmodule
