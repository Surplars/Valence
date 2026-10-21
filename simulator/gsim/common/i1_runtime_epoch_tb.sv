`timescale 1ns/1ps
module i1_runtime_epoch_tb;
  reg clock=0; always #5 clock=~clock;
  reg reset=1, start=0, program_valid=0, prepare_valid=0, resume_valid=0;
  reg [5:0] program_index=0; reg [31:0] program_data=0;
  reg [7:0] prepare_bits=0, resume_bits=0;
  wire prepare_ready,resume_ready,tileHeld_valid,fabricHeld_valid,retire_valid,trap,fabricIdle;
  wire [7:0] tileHeld_bits,fabricHeld_bits;
  wire [31:0] releaseBeats,coherentAcquires,retire_instruction;
  wire [63:0] retire_pc,retire_data; wire [4:0] retire_rd;wire retire_writesRd;
  integer cycles=0, retires=0,stores=0,loads=0,prepares=0,resumes=0,epoch,oldRetires,oldStores,oldReleases,oldAcquires,oldLoads,watchdog;
  reg [63:0] expected=0;reg wrongOracle=0;
  CommonI1RuntimeEpochFixture dut(.clock(clock),.reset(reset),.io_start(start),
    .io_program_valid(program_valid),.io_program_bits_index(program_index),.io_program_bits_data(program_data),
    .io_prepare_valid(prepare_valid),.io_prepare_bits(prepare_bits),.io_prepare_ready(prepare_ready),
    .io_resume_valid(resume_valid),.io_resume_bits(resume_bits),.io_resume_ready(resume_ready),
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
    if(start&&trap) $fatal(1,"unexpected real CPU trap");
    if(start&&retire_valid) begin
      retires=retires+1;
      if(retire_pc==64'h80000014) begin
        expected=expected+1;
        if(!retire_writesRd||retire_rd!=2||retire_data!=expected) $fatal(1,"independent increment oracle");
      end
      if(retire_pc==64'h80000018) stores=stores+1;
      if(retire_pc==64'h8000001c) begin
        loads=loads+1;
        if(!retire_writesRd||retire_rd!=3||retire_data!=(expected+(wrongOracle?1:0))) $fatal(1,"independent load data oracle");
      end
    end
  end
  task tick; begin @(posedge clock);#1;@(negedge clock);end endtask
  task programWord(input[5:0] index,input[31:0] word);begin
    program_valid=1;program_index=index;program_data=word;tick();program_valid=0;
  end endtask
  initial begin
    wrongOracle=$test$plusargs("wrong-oracle");
    repeat(4) tick();reset=0;tick();
    programWord(0,32'h802000b7);programWord(1,32'h02009093);programWord(2,32'h0200d093);
    programWord(3,32'h00000113);programWord(4,32'h0000100f);programWord(5,32'h00110113);
    programWord(6,32'h0020b023);programWord(7,32'h0000b183);programWord(8,32'h00311463);
    programWord(9,32'hff1ff06f);programWord(10,32'h00100073);
    start=1;
    for(epoch=19;epoch<23;epoch=epoch+1) begin
      oldLoads=loads;while(loads<oldLoads+3) tick();
      oldReleases=releaseBeats;prepare_bits=epoch;prepare_valid=1;
      watchdog=prepares;while(prepares==watchdog) tick();prepare_valid=0;
      while(!(tileHeld_valid&&fabricHeld_valid)) tick();
      if(tileHeld_bits!=epoch||fabricHeld_bits!=epoch||!fabricIdle) $fatal(1,"matching real drain epoch missing");
      if(releaseBeats<oldReleases+8) $fatal(1,"dirty cache line did not write back before held epoch");
      oldRetires=retires;oldStores=stores;oldAcquires=coherentAcquires;
      repeat(35) begin
        tick();
        if(!tileHeld_valid||!fabricHeld_valid||!fabricIdle||retires!=oldRetires||stores!=oldStores||coherentAcquires!=oldAcquires)
          $fatal(1,"held epoch admitted architectural work or lost barrier");
      end
      resume_bits=epoch;resume_valid=1;watchdog=resumes;
      while(resumes==watchdog) tick();resume_valid=0;
      while(tileHeld_valid||fabricHeld_valid) tick();
      oldLoads=loads;while(loads<oldLoads+3) tick();
    end
    $display("I1_RUNTIME_EPOCH_PASS epochs=4 holds=140 retires=%0d stores=%0d loads=%0d dirty_release_beats=%0d",retires,stores,loads,releaseBeats);
    $finish;
  end
endmodule
