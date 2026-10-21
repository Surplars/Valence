`timescale 1ns/1ps
module i1_runtime_epoch_tb;
  reg clock=0; always #5 clock=~clock;
  reg reset=1, start=0, program_valid=0, prepare_valid=0, resume_valid=0;
  reg [5:0] program_index=0; reg [31:0] program_data=0;
  reg [7:0] prepare_bits=0, resume_bits=0, cancel_bits=0;
  reg cancel_valid=0,complete_ready=0,holdReleaseAck=0,holdCompletion=0,externalStop=0;
  wire cancel_ready,complete_valid,complete_canceled,releaseAckBlocked,completionBlocked;
  wire [7:0] complete_epoch;
  wire prepare_ready,resume_ready,tileHeld_valid,fabricHeld_valid,retire_valid,trap,fabricIdle;
  wire [7:0] tileHeld_bits,fabricHeld_bits;
  wire [31:0] releaseBeats,coherentAcquires,retire_instruction;
  wire [63:0] retire_pc,retire_data; wire [4:0] retire_rd;wire retire_writesRd;
  integer loopPhase=0;
  integer cycles=0, retires=0,stores=0,loads=0,prepares=0,resumes=0,epoch,oldRetires,oldStores,oldReleases,oldAcquires,oldLoads,watchdog,cancels=0,completions=0,oldCancels,oldCompletes,oldResumes;
  reg [63:0] expected=0;reg wrongOracle=0;
  CommonI1RuntimeEpochFixture dut(.clock(clock),.reset(reset),.io_start(start),
    .io_program_valid(program_valid),.io_program_bits_index(program_index),.io_program_bits_data(program_data),
    .io_prepare_valid(prepare_valid),.io_prepare_bits(prepare_bits),.io_prepare_ready(prepare_ready),
    .io_resume_valid(resume_valid),.io_resume_bits(resume_bits),.io_resume_ready(resume_ready),
    .io_cancel_valid(cancel_valid),.io_cancel_bits(cancel_bits),.io_cancel_ready(cancel_ready),
    .io_complete_valid(complete_valid),.io_complete_ready(complete_ready),
    .io_complete_bits_epoch(complete_epoch),.io_complete_bits_canceled(complete_canceled),
    .io_externalStop(externalStop),.io_holdReleaseAck(holdReleaseAck),.io_holdCompletion(holdCompletion),
    .io_releaseAckBlocked(releaseAckBlocked),.io_completionBlocked(completionBlocked),
    .io_tileHeld_valid(tileHeld_valid),.io_tileHeld_bits(tileHeld_bits),
    .io_fabricHeld_valid(fabricHeld_valid),.io_fabricHeld_bits(fabricHeld_bits),
    .io_retire_valid(retire_valid),.io_retire_bits_pc(retire_pc),.io_retire_bits_instruction(retire_instruction),
    .io_retire_bits_rd(retire_rd),.io_retire_bits_data(retire_data),.io_retire_bits_writesRd(retire_writesRd),
    .io_trap(trap),.io_releaseBeats(releaseBeats),.io_coherentAcquires(coherentAcquires),.io_fabricIdle(fabricIdle));
  always @(posedge clock) if(!reset) begin
    cycles=cycles+1;
    if(cycles>100000) $fatal(1,"runtime epoch watchdog");
    if(prepare_valid&&prepare_ready) prepares=prepares+1;
    if(resume_valid&&resume_ready) resumes=resumes+1;
    if(cancel_valid&&cancel_ready) cancels=cancels+1;
    if(complete_valid&&complete_ready) completions=completions+1;
    if(start&&trap) $fatal(1,"unexpected real CPU trap");
    if(start&&retire_valid) begin
      retires=retires+1;
      if(retire_pc==64'h80000014) begin
        if(loopPhase!=0) $fatal(1,"duplicate or skipped loop retirement before increment");
        loopPhase=1;expected=expected+1;
        if(!retire_writesRd||retire_rd!=2||retire_data!=expected) $fatal(1,"independent increment oracle");
      end
      if(retire_pc==64'h80000018) begin
        if(loopPhase!=1) $fatal(1,"duplicate or skipped store retirement");
        loopPhase=2;stores=stores+1;
      end
      if(retire_pc==64'h8000001c) begin
        if(loopPhase!=2) $fatal(1,"duplicate or skipped load retirement");
        loopPhase=3;loads=loads+1;
        if(!retire_writesRd||retire_rd!=3||retire_data!=(expected+(wrongOracle?1:0))) $fatal(1,"independent load data oracle");
      end
      if(retire_pc==64'h80000020) begin
        if(loopPhase!=3) $fatal(1,"branch retirement order lost");loopPhase=4;
      end
      if(retire_pc==64'h80000024) begin
        if(loopPhase!=4) $fatal(1,"jump retirement order lost");loopPhase=0;
      end
    end
  end
  task tick; begin @(posedge clock);#1;@(negedge clock);end endtask
  task programWord(input[5:0] index,input[31:0] word);begin
    program_valid=1;program_index=index;program_data=word;tick();program_valid=0;
  end endtask
  task rejectCancel(input[7:0] tag);begin
    oldCancels=cancels;cancel_bits=tag;cancel_valid=1;
    repeat(3) begin tick();if(cancel_ready||cancels!=oldCancels) $fatal(1,"invalid cancel accepted");end
    cancel_valid=0;
  end endtask
  task acceptCancel(input[7:0] tag);begin
    cancel_bits=tag;cancel_valid=1;watchdog=cancels;
    while(cancels==watchdog) tick();cancel_valid=0;
  end endtask
  initial begin
    wrongOracle=$test$plusargs("wrong-oracle");
    repeat(4) tick();reset=0;tick();
    programWord(0,32'h802000b7);programWord(1,32'h02009093);programWord(2,32'h0200d093);
    programWord(3,32'h00000113);programWord(4,32'h0000100f);programWord(5,32'h00110113);
    programWord(6,32'h0020b023);programWord(7,32'h0000b183);programWord(8,32'h00311463);
    programWord(9,32'hff1ff06f);programWord(10,32'h00100073);
    rejectCancel(8'hfe); // idle cancel is not an accepted transaction
    start=1;
    for(epoch=19;epoch<25;epoch=epoch+1) begin
      oldLoads=loads;while(loads<oldLoads+3) tick();
      oldReleases=releaseBeats;oldCompletes=completions;oldResumes=resumes;
      holdReleaseAck=(epoch==20);holdCompletion=(epoch==21);
      prepare_bits=epoch;prepare_valid=1;
      watchdog=prepares;while(prepares==watchdog) tick();prepare_valid=0;
      // Wrong/stale control never owns or cancels the current transaction.
      rejectCancel(epoch-1);
      if(epoch==19) begin
        acceptCancel(epoch); // timeout before private/fabric drain completes
        rejectCancel(epoch); // duplicate pending cancel
      end else if(epoch==20) begin
        while(!releaseAckBlocked) tick();
        acceptCancel(epoch);
        repeat(18) begin tick();if(complete_valid||tileHeld_valid) $fatal(1,"cancel discarded held ReleaseAck owner");end
        holdReleaseAck=0;
      end else if(epoch==21) begin
        while(!completionBlocked) tick();
        acceptCancel(epoch);
        repeat(18) begin tick();if(complete_valid||tileHeld_valid) $fatal(1,"cancel skipped queued drain completion");end
        holdCompletion=0;
      end else begin
        while(!(tileHeld_valid&&fabricHeld_valid)) tick();
        if(tileHeld_bits!=epoch||fabricHeld_bits!=epoch||!fabricIdle) $fatal(1,"matching real drain epoch missing");
        oldRetires=retires;oldStores=stores;oldAcquires=coherentAcquires;
        repeat(20) begin
          tick();
          if(!tileHeld_valid||!fabricHeld_valid||!fabricIdle||retires!=oldRetires||stores!=oldStores||coherentAcquires!=oldAcquires)
            $fatal(1,"held epoch admitted architectural work or lost barrier");
        end
        if(epoch==23) begin
          externalStop=1;
          oldCancels=cancels;cancel_bits=epoch-1;cancel_valid=1;
          resume_bits=epoch;resume_valid=1;watchdog=resumes;
          while(resumes==watchdog) tick();resume_valid=0;cancel_valid=0;
          if(cancels!=oldCancels) $fatal(1,"wrong cancel altered valid normal resume");
          repeat(18) begin tick();if(complete_valid) $fatal(1,"release proof ignored aggregate external stop");end
          externalStop=0;
          repeat(2) begin tick();if(complete_valid) $fatal(1,"terminal bypassed real CPU release edges");end
        end else if(epoch==22) begin
          resume_bits=epoch;resume_valid=1;
          acceptCancel(epoch);resume_valid=0;
          if(resumes!=oldResumes) $fatal(1,"normal resume beat simultaneous matching cancel");
        end else acceptCancel(epoch);
      end
      while(!complete_valid) tick();
      if(complete_epoch!=epoch||complete_canceled!=(epoch!=23)) $fatal(1,"terminal epoch/cancel accounting mismatch");
      if(tileHeld_valid||fabricHeld_valid) $fatal(1,"terminal result preceded actual release");
      if(releaseBeats<oldReleases+8) $fatal(1,"dirty cache line did not write back before terminal");
      prepare_bits=epoch+1;
      repeat(16) begin
        tick();
        if(!complete_valid||complete_epoch!=epoch||complete_canceled!=(epoch!=23)||prepare_ready)
          $fatal(1,"terminal backpressure lost result or external owner");
      end
      rejectCancel(epoch); // late/duplicate cancel cannot alter held terminal
      complete_ready=1;while(completions==oldCompletes) tick();complete_ready=0;
      rejectCancel(epoch); // retired duplicate
      oldLoads=loads;while(loads<oldLoads+3) tick();
      if(completions!=oldCompletes+1) $fatal(1,"duplicate terminal result");
    end
    if(stores!=loads||loads!=expected||releaseBeats!=48) $fatal(1,"retired side effect or dirty release ledger mismatch");
    if(prepares!=6||cancels!=5||resumes!=1||completions!=6) $fatal(1,"accepted epoch ledger mismatch");
    $display("I1_RUNTIME_EPOCH_PASS epochs=6 cancels=5 normal_resumes=1 terminal=6 retires=%0d stores=%0d loads=%0d dirty_release_beats=%0d",retires,stores,loads,releaseBeats);
    $finish;
  end
endmodule
