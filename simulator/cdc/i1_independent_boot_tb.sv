`timescale 1ns/1ps
// Test-only environment for unchanged emitted I1 RTL. No DUT force, clock rewrite,
// memory peeks, fake instruction response, or tohost-only shortcut is used.
module i1_independent_boot_tb;
  reg cpuClock=0, fabricClock=0, commonColdReset=1;
  integer cpu_half=5, fabric_half=10, phase_ps=3000, maxcycles=600000;
  integer image_words=0, image_bytes=0, ready_at=2147483647;
  integer bad_drop_response=0, single_mode=0, configured=0;
  reg [63:0] pc_mmio=0, pc_read=0, pc_write=0, pc_ecall=0, pc_success=0;
  reg [2047:0] image_hex;
  initial begin
    if ($value$plusargs("cpu_half=%d",cpu_half)) begin end
    if ($value$plusargs("fabric_half=%d",fabric_half)) begin end
    if ($value$plusargs("phase_ps=%d",phase_ps)) begin end
    if ($value$plusargs("maxcycles=%d",maxcycles)) begin end
    if ($value$plusargs("image_words=%d",image_words)) begin end
    if ($value$plusargs("image_bytes=%d",image_bytes)) begin end
    if ($value$plusargs("pc_mmio=%h",pc_mmio)) begin end
    if ($value$plusargs("pc_read=%h",pc_read)) begin end
    if ($value$plusargs("pc_write=%h",pc_write)) begin end
    if ($value$plusargs("pc_ecall=%h",pc_ecall)) begin end
    if ($value$plusargs("pc_success=%h",pc_success)) begin end
    bad_drop_response=$test$plusargs("bad_drop_response");
    single_mode=$test$plusargs("single_mode");
    if (!$value$plusargs("image_hex=%s",image_hex) || image_words<=0 || image_words>32768)
      $fatal(1,"I1_BOOT_INPUT_ORACLE");
    if (fabric_half!=10 || cpu_half<=0 || phase_ps<0 || (single_mode && (cpu_half!=10 || phase_ps!=0)))
      $fatal(1,"I1_BOOT_CLOCK_CONTRACT");
    configured=1;
  end
  initial begin wait(configured); forever #(cpu_half) cpuClock=~cpuClock; end
  initial begin wait(configured); #(phase_ps/1000.0); forever #(fabric_half) fabricClock=~fabricClock; end

  reg io_clockLocked=0, io_ddrReady=0, io_uartRx=1, io_externalIrq=0;
  wire io_uartTx,io_resetHeld,io_resetFault,io_cpuLinkReady,io_fabricLinkReady;
  wire io_cpuTransportEmpty,io_fabricTransportEmpty;
  wire [63:0] io_cycles,io_instructions,io_timeSnapshot;
  wire io_retire_valid,io_retire_bits_writesRd,io_retire_bits_trap,io_trapTaken;
  wire [63:0] io_retire_bits_pc,io_retire_bits_nextPc,io_retire_bits_data,io_retire_bits_cause,io_retire_bits_tval;
  wire [63:0] io_trapPc,io_trapCause;
  wire [31:0] io_retire_bits_instruction;
  wire [4:0] io_retire_bits_rd;
  wire io_ddrAxi_ar_valid,io_ddrAxi_aw_valid,io_ddrAxi_w_valid,io_ddrAxi_r_ready,io_ddrAxi_b_ready;
  reg io_ddrAxi_ar_ready=0,io_ddrAxi_aw_ready=0,io_ddrAxi_w_ready=0,io_ddrAxi_r_valid=0,io_ddrAxi_b_valid=0;
  wire [31:0] io_ddrAxi_ar_bits_addr,io_ddrAxi_aw_bits_addr;
  wire [3:0] io_ddrAxi_ar_bits_id,io_ddrAxi_aw_bits_id;
  wire [7:0] io_ddrAxi_ar_bits_len,io_ddrAxi_aw_bits_len;
  wire [2:0] io_ddrAxi_ar_bits_size,io_ddrAxi_aw_bits_size;
  wire [1:0] io_ddrAxi_ar_bits_burst,io_ddrAxi_aw_bits_burst;
  wire io_ddrAxi_ar_bits_lock,io_ddrAxi_aw_bits_lock;
  wire [3:0] io_ddrAxi_ar_bits_cache,io_ddrAxi_aw_bits_cache,io_ddrAxi_ar_bits_qos,io_ddrAxi_aw_bits_qos;
  wire [2:0] io_ddrAxi_ar_bits_prot,io_ddrAxi_aw_bits_prot;
  wire [63:0] io_ddrAxi_w_bits_data;
  wire [7:0] io_ddrAxi_w_bits_strb;
  wire io_ddrAxi_w_bits_last;
  reg [3:0] io_ddrAxi_r_bits_id=0,io_ddrAxi_b_bits_id=0;
  reg [63:0] io_ddrAxi_r_bits_data=0;
  reg [1:0] io_ddrAxi_r_bits_resp=0,io_ddrAxi_b_bits_resp=0;
  reg io_ddrAxi_r_bits_last=0;
  reg io_networkMemory_request_valid=0,io_networkMemory_response_ready=0;
  wire io_networkMemory_request_ready,io_networkMemory_response_valid,io_networkMemory_response_bits_error;
  reg [63:0] io_networkMemory_request_bits_address=0,io_networkMemory_request_bits_data=0;
  reg io_networkMemory_request_bits_write=0;
  reg [2:0] io_networkMemory_request_bits_size=3;
  reg [7:0] io_networkMemory_request_bits_byteEnable=255;
  wire [63:0] io_networkMemory_response_bits_data;
  I1IndependentClockHarness dut(
    .cpuClock(cpuClock),
    .fabricClock(fabricClock),
    .commonColdReset(commonColdReset),
    .io_clockLocked(io_clockLocked),
    .io_cpuLinkReady(io_cpuLinkReady),
    .io_cpuTransportEmpty(io_cpuTransportEmpty),
    .io_cycles(io_cycles),
    .io_ddrAxi_ar_bits_addr(io_ddrAxi_ar_bits_addr),
    .io_ddrAxi_ar_bits_burst(io_ddrAxi_ar_bits_burst),
    .io_ddrAxi_ar_bits_cache(io_ddrAxi_ar_bits_cache),
    .io_ddrAxi_ar_bits_id(io_ddrAxi_ar_bits_id),
    .io_ddrAxi_ar_bits_len(io_ddrAxi_ar_bits_len),
    .io_ddrAxi_ar_bits_lock(io_ddrAxi_ar_bits_lock),
    .io_ddrAxi_ar_bits_prot(io_ddrAxi_ar_bits_prot),
    .io_ddrAxi_ar_bits_qos(io_ddrAxi_ar_bits_qos),
    .io_ddrAxi_ar_bits_size(io_ddrAxi_ar_bits_size),
    .io_ddrAxi_ar_ready(io_ddrAxi_ar_ready),
    .io_ddrAxi_ar_valid(io_ddrAxi_ar_valid),
    .io_ddrAxi_aw_bits_addr(io_ddrAxi_aw_bits_addr),
    .io_ddrAxi_aw_bits_burst(io_ddrAxi_aw_bits_burst),
    .io_ddrAxi_aw_bits_cache(io_ddrAxi_aw_bits_cache),
    .io_ddrAxi_aw_bits_id(io_ddrAxi_aw_bits_id),
    .io_ddrAxi_aw_bits_len(io_ddrAxi_aw_bits_len),
    .io_ddrAxi_aw_bits_lock(io_ddrAxi_aw_bits_lock),
    .io_ddrAxi_aw_bits_prot(io_ddrAxi_aw_bits_prot),
    .io_ddrAxi_aw_bits_qos(io_ddrAxi_aw_bits_qos),
    .io_ddrAxi_aw_bits_size(io_ddrAxi_aw_bits_size),
    .io_ddrAxi_aw_ready(io_ddrAxi_aw_ready),
    .io_ddrAxi_aw_valid(io_ddrAxi_aw_valid),
    .io_ddrAxi_b_bits_id(io_ddrAxi_b_bits_id),
    .io_ddrAxi_b_bits_resp(io_ddrAxi_b_bits_resp),
    .io_ddrAxi_b_ready(io_ddrAxi_b_ready),
    .io_ddrAxi_b_valid(io_ddrAxi_b_valid),
    .io_ddrAxi_r_bits_data(io_ddrAxi_r_bits_data),
    .io_ddrAxi_r_bits_id(io_ddrAxi_r_bits_id),
    .io_ddrAxi_r_bits_last(io_ddrAxi_r_bits_last),
    .io_ddrAxi_r_bits_resp(io_ddrAxi_r_bits_resp),
    .io_ddrAxi_r_ready(io_ddrAxi_r_ready),
    .io_ddrAxi_r_valid(io_ddrAxi_r_valid),
    .io_ddrAxi_w_bits_data(io_ddrAxi_w_bits_data),
    .io_ddrAxi_w_bits_last(io_ddrAxi_w_bits_last),
    .io_ddrAxi_w_bits_strb(io_ddrAxi_w_bits_strb),
    .io_ddrAxi_w_ready(io_ddrAxi_w_ready),
    .io_ddrAxi_w_valid(io_ddrAxi_w_valid),
    .io_ddrReady(io_ddrReady),
    .io_externalIrq(io_externalIrq),
    .io_fabricLinkReady(io_fabricLinkReady),
    .io_fabricTransportEmpty(io_fabricTransportEmpty),
    .io_instructions(io_instructions),
    .io_networkMemory_request_bits_address(io_networkMemory_request_bits_address),
    .io_networkMemory_request_bits_byteEnable(io_networkMemory_request_bits_byteEnable),
    .io_networkMemory_request_bits_data(io_networkMemory_request_bits_data),
    .io_networkMemory_request_bits_size(io_networkMemory_request_bits_size),
    .io_networkMemory_request_bits_write(io_networkMemory_request_bits_write),
    .io_networkMemory_request_ready(io_networkMemory_request_ready),
    .io_networkMemory_request_valid(io_networkMemory_request_valid),
    .io_networkMemory_response_bits_data(io_networkMemory_response_bits_data),
    .io_networkMemory_response_bits_error(io_networkMemory_response_bits_error),
    .io_networkMemory_response_ready(io_networkMemory_response_ready),
    .io_networkMemory_response_valid(io_networkMemory_response_valid),
    .io_resetFault(io_resetFault),
    .io_resetHeld(io_resetHeld),
    .io_retire_bits_cause(io_retire_bits_cause),
    .io_retire_bits_data(io_retire_bits_data),
    .io_retire_bits_instruction(io_retire_bits_instruction),
    .io_retire_bits_nextPc(io_retire_bits_nextPc),
    .io_retire_bits_pc(io_retire_bits_pc),
    .io_retire_bits_rd(io_retire_bits_rd),
    .io_retire_bits_trap(io_retire_bits_trap),
    .io_retire_bits_tval(io_retire_bits_tval),
    .io_retire_bits_writesRd(io_retire_bits_writesRd),
    .io_retire_valid(io_retire_valid),
    .io_timeSnapshot(io_timeSnapshot),
    .io_trapCause(io_trapCause),
    .io_trapPc(io_trapPc),
    .io_trapTaken(io_trapTaken),
    .io_uartRx(io_uartRx),
    .io_uartTx(io_uartTx)
  );

  // Fixed bounded low RAM plus the final cache line in the 2 GiB aperture.
  // The final 64 bytes are required by real line fills, even for last-word tests.
  reg [63:0] ram[0:32767];
  reg [63:0] ram_last_line[0:7];
  integer init_i;
  initial begin
    wait(configured);
    for(init_i=0;init_i<32768;init_i=init_i+1) ram[init_i]=0;
    for(init_i=0;init_i<8;init_i=init_i+1) ram_last_line[init_i]=0;
    $readmemh(image_hex,ram,0,image_words-1);
  end
  function [63:0] memory_read(input [31:0] addr);
    begin
      if(addr<32'h40000) memory_read=ram[addr>>3];
      else if(addr>=32'h7fffffc0 && addr<=32'h7ffffff8) memory_read=ram_last_line[(addr-32'h7fffffc0)>>3];
      else begin $fatal(1,"I1_BOOT_RAM_RANGE_ORACLE addr=%h",addr); memory_read=0; end
    end
  endfunction
  task memory_write(input [31:0] addr,input [63:0] data,input [7:0] mask);
    reg [63:0] value; integer j;
    begin
      value=memory_read(addr);
      for(j=0;j<8;j=j+1) if(mask[j]) value[j*8+:8]=data[j*8+:8];
      if(addr<32'h40000) ram[addr>>3]=value;
      else ram_last_line[(addr-32'h7fffffc0)>>3]=value;
    end
  endtask
  task address_check(input [31:0] addr,input [7:0] len,input [2:0] size,input [1:0] burst);
    begin
      if(burst!==1 || size>3 || addr>=32'h80000000 || (addr&((1<<size)-1))!=0 ||
         ((addr&4095)+((len+1)<<size))>4096)
        $fatal(1,"I1_BOOT_AXI_GEOMETRY_ORACLE addr=%h len=%d size=%d burst=%d",addr,len,size,burst);
    end
  endtask
  // Host owners are independently bounded. They do not limit the DUT's two DDR slots.
  reg rd_used[0:15]; reg [31:0] rd_addr[0:15];
  integer rd_due[0:15],rd_len[0:15],rd_size[0:15],rd_beat[0:15],rd_id[0:15],rd_ticket[0:15];
  reg [31:0] aw_addr[0:15]; integer aw_id[0:15],aw_len[0:15],aw_size[0:15];
  reg [63:0] w_data[0:127]; reg [7:0] w_mask[0:127]; reg w_last[0:127];
  integer b_id[0:15],b_due[0:15]; reg b_error[0:15];
  integer aw_head=0,aw_tail=0,aw_count=0,w_head=0,w_tail=0,w_count=0,b_head=0,b_tail=0,b_count=0;
  integer sending=-1,fabric_edges=0,cpu_edges=0,read_count=0,write_count=0,read_beats=0,write_beats=0;
  integer line_bursts=0,max_parallel_reads=0,overlap_cycles=0,ar_stalls=0,aw_stalls=0,w_stalls=0;
  integer r_errors=0,b_errors=0,max_read_latency=0,read_latency_sum=0;
  integer rd_accepted[0:15];
  integer model_i,slot,owners,n,j,best_ticket,beat_index;
  reg [31:0] target_addr;
  reg ar_held=0,aw_held=0,w_held=0,r_payload_held=0;
  reg [60:0] held_ar,held_aw;
  reg [72:0] held_w;
  wire [60:0] ar_payload={io_ddrAxi_ar_bits_addr,io_ddrAxi_ar_bits_id,io_ddrAxi_ar_bits_len,
    io_ddrAxi_ar_bits_size,io_ddrAxi_ar_bits_burst,io_ddrAxi_ar_bits_lock,io_ddrAxi_ar_bits_cache,
    io_ddrAxi_ar_bits_prot,io_ddrAxi_ar_bits_qos};
  wire [60:0] aw_payload={io_ddrAxi_aw_bits_addr,io_ddrAxi_aw_bits_id,io_ddrAxi_aw_bits_len,
    io_ddrAxi_aw_bits_size,io_ddrAxi_aw_bits_burst,io_ddrAxi_aw_bits_lock,io_ddrAxi_aw_bits_cache,
    io_ddrAxi_aw_bits_prot,io_ddrAxi_aw_bits_qos};
  wire [72:0] w_payload={io_ddrAxi_w_bits_data,io_ddrAxi_w_bits_strb,io_ddrAxi_w_bits_last};
  initial for(model_i=0;model_i<16;model_i=model_i+1) rd_used[model_i]=0;

  always @(negedge fabricClock) begin
    if(commonColdReset) begin
      io_ddrAxi_ar_ready=0;io_ddrAxi_aw_ready=0;io_ddrAxi_w_ready=0;
      io_ddrAxi_r_valid=0;io_ddrAxi_b_valid=0;
    end else begin
      io_clockLocked=(fabric_edges>=17); io_ddrReady=(fabric_edges>=ready_at);
      // Different independent periodic masks guarantee deterministic backpressure.
      io_ddrAxi_ar_ready=(fabric_edges%5!=1 && fabric_edges%5!=2);
      io_ddrAxi_aw_ready=(fabric_edges%7!=2 && fabric_edges%7!=3);
      io_ddrAxi_w_ready=(fabric_edges%4!=1);
      if(sending<0) begin
        best_ticket=-1;
        for(model_i=0;model_i<16;model_i=model_i+1)
          if(rd_used[model_i] && rd_due[model_i]<=fabric_edges && rd_ticket[model_i]>best_ticket &&
             !(bad_drop_response && rd_ticket[model_i]==0)) begin
            sending=model_i; best_ticket=rd_ticket[model_i];
          end
      end
      io_ddrAxi_r_valid=(sending>=0);
      if(sending>=0 && !r_payload_held) begin
        target_addr=(rd_addr[sending]+(rd_beat[sending]<<rd_size[sending]))&32'hfffffff8;
        io_ddrAxi_r_bits_data=memory_read(target_addr);
        io_ddrAxi_r_bits_id=rd_id[sending];
        io_ddrAxi_r_bits_last=(rd_beat[sending]==rd_len[sending]);
        io_ddrAxi_r_bits_resp=(rd_addr[sending]==32'h18000 && io_ddrAxi_r_bits_last)?2:0;
      end
      io_ddrAxi_b_valid=(b_count>0 && b_due[b_head]<=fabric_edges);
      if(b_count>0) begin io_ddrAxi_b_bits_id=b_id[b_head]; io_ddrAxi_b_bits_resp=b_error[b_head]?2:0; end
    end
  end

  always @(posedge fabricClock) begin
    fabric_edges=fabric_edges+1;
    if(!commonColdReset) begin
      if(fabric_edges%10000==0) $display("I1_BOOT_PROGRESS fabric_edges=%0d cpu_edges=%0d retired=%0d rom_retired=%0d uart_bytes=%0d reads=%0d writes=%0d done=%0d",fabric_edges,cpu_edges,retired,rom_retired,uart_count,read_count,write_count,guest_done);
      if(io_resetFault===1) $fatal(1,"I1_BOOT_RESET_FAULT_ORACLE");
      if(!io_ddrReady && (io_ddrAxi_ar_valid || io_ddrAxi_aw_valid || io_ddrAxi_w_valid))
        $fatal(1,"I1_BOOT_CALIBRATION_ORACLE");
      if(ar_held && (!io_ddrAxi_ar_valid || ar_payload!==held_ar)) $fatal(1,"I1_BOOT_AR_HOLD_ORACLE");
      if(aw_held && (!io_ddrAxi_aw_valid || aw_payload!==held_aw)) $fatal(1,"I1_BOOT_AW_HOLD_ORACLE");
      if(w_held && (!io_ddrAxi_w_valid || w_payload!==held_w)) $fatal(1,"I1_BOOT_W_HOLD_ORACLE");
      ar_held=io_ddrAxi_ar_valid && !io_ddrAxi_ar_ready; held_ar=ar_payload; ar_stalls=ar_stalls+ar_held;
      aw_held=io_ddrAxi_aw_valid && !io_ddrAxi_aw_ready; held_aw=aw_payload; aw_stalls=aw_stalls+aw_held;
      w_held=io_ddrAxi_w_valid && !io_ddrAxi_w_ready; held_w=w_payload; w_stalls=w_stalls+w_held;
      r_payload_held=io_ddrAxi_r_valid && !io_ddrAxi_r_ready;
      if(io_ddrAxi_r_valid && io_ddrAxi_r_ready) begin
        read_beats=read_beats+1; r_errors=r_errors+(io_ddrAxi_r_bits_resp!=0);
        if(rd_beat[sending]==rd_len[sending]) begin
          read_latency_sum=read_latency_sum+fabric_edges-rd_accepted[sending];
          if(fabric_edges-rd_accepted[sending]>max_read_latency) max_read_latency=fabric_edges-rd_accepted[sending];
          rd_used[sending]=0; sending=-1;
        end else rd_beat[sending]=rd_beat[sending]+1;
      end
      if(io_ddrAxi_b_valid && io_ddrAxi_b_ready) begin
        b_errors=b_errors+(io_ddrAxi_b_bits_resp!=0); b_head=(b_head+1)%16; b_count=b_count-1;
      end
      if(io_ddrAxi_ar_valid) address_check(io_ddrAxi_ar_bits_addr,io_ddrAxi_ar_bits_len,
        io_ddrAxi_ar_bits_size,io_ddrAxi_ar_bits_burst);
      if(io_ddrAxi_aw_valid) address_check(io_ddrAxi_aw_bits_addr,io_ddrAxi_aw_bits_len,
        io_ddrAxi_aw_bits_size,io_ddrAxi_aw_bits_burst);
      if(io_ddrAxi_ar_valid && io_ddrAxi_ar_ready) begin
        slot=-1; for(model_i=0;model_i<16;model_i=model_i+1) if(!rd_used[model_i]) slot=model_i;
        if(slot<0) $fatal(1,"I1_BOOT_READ_OWNER_OVERFLOW");
        rd_used[slot]=1;rd_addr[slot]=io_ddrAxi_ar_bits_addr;rd_id[slot]=io_ddrAxi_ar_bits_id;
        rd_len[slot]=io_ddrAxi_ar_bits_len;rd_size[slot]=io_ddrAxi_ar_bits_size;rd_beat[slot]=0;
        rd_due[slot]=fabric_edges+3+(read_count*7)%13;rd_ticket[slot]=read_count;rd_accepted[slot]=fabric_edges;
        read_count=read_count+1;line_bursts=line_bursts+(io_ddrAxi_ar_bits_len!=0);
      end
      if(io_ddrAxi_aw_valid && io_ddrAxi_aw_ready) begin
        if(aw_count==16) $fatal(1,"I1_BOOT_AW_OWNER_OVERFLOW");
        aw_addr[aw_tail]=io_ddrAxi_aw_bits_addr;aw_id[aw_tail]=io_ddrAxi_aw_bits_id;
        aw_len[aw_tail]=io_ddrAxi_aw_bits_len;aw_size[aw_tail]=io_ddrAxi_aw_bits_size;
        aw_tail=(aw_tail+1)%16;aw_count=aw_count+1;write_count=write_count+1;
      end
      if(io_ddrAxi_w_valid && io_ddrAxi_w_ready) begin
        if(w_count==128) $fatal(1,"I1_BOOT_W_OWNER_OVERFLOW");
        w_data[w_tail]=io_ddrAxi_w_bits_data;w_mask[w_tail]=io_ddrAxi_w_bits_strb;w_last[w_tail]=io_ddrAxi_w_bits_last;
        w_tail=(w_tail+1)%128;w_count=w_count+1;write_beats=write_beats+1;
      end
      if(aw_count>0 && w_count>=aw_len[aw_head]+1) begin
        if(b_count==16) $fatal(1,"I1_BOOT_B_OWNER_OVERFLOW");
        for(n=0;n<=aw_len[aw_head];n=n+1) begin
          if(w_last[w_head] !== (n==aw_len[aw_head])) $fatal(1,"I1_BOOT_WLAST_ORACLE");
          target_addr=(aw_addr[aw_head]+(n<<aw_size[aw_head]))&32'hfffffff8;
          memory_write(target_addr,w_data[w_head],w_mask[w_head]);
          w_head=(w_head+1)%128;w_count=w_count-1;
        end
        b_id[b_tail]=aw_id[aw_head];b_due[b_tail]=fabric_edges+2+(write_count*3)%11;
        b_error[b_tail]=(aw_addr[aw_head]==32'h18008);
        b_tail=(b_tail+1)%16;b_count=b_count+1;aw_head=(aw_head+1)%16;aw_count=aw_count-1;
      end
      owners=0; for(model_i=0;model_i<16;model_i=model_i+1) owners=owners+rd_used[model_i];
      if(owners>max_parallel_reads) max_parallel_reads=owners;
      if(owners>0 && (aw_count>0 || w_count>0 || b_count>0)) overlap_cycles=overlap_cycles+1;
    end
  end

  integer retired=0,rom_retired=0,traps=0,msip=0,mtip=0,meip=0,load_faults=0,store_faults=0,ecalls=0;
  integer guest_done=0,boot_cpu_edges=0,boot_fabric_edges=0,first_ram_fabric=0;
  integer time_changes=0;
  reg [63:0] last_a0=64'hffffffffffffffff,last_time=0;
  always @(posedge cpuClock) begin
    cpu_edges=cpu_edges+1;
    if(cpu_edges>maxcycles) $fatal(1,"I1_BOOT_BOUNDED_COMPLETION_ORACLE cpu_edges=%0d fabric_edges=%0d retired=%0d rom_retired=%0d reads=%0d bad_drop=%0d",
      cpu_edges,fabric_edges,retired,rom_retired,read_count,bad_drop_response);
    if(!commonColdReset) begin
      if(!io_clockLocked && io_retire_valid===1) $fatal(1,"I1_BOOT_LOCK_ORACLE");
      if(!single_mode && io_cpuLinkReady===1 && !io_resetHeld) begin
        if(io_timeSnapshot<last_time) $fatal(1,"I1_BOOT_TIME_MONOTONIC_ORACLE");
        if(io_timeSnapshot>last_time) time_changes=time_changes+1;
        last_time=io_timeSnapshot;
      end
      if(!guest_done && io_trapTaken===1 && io_trapCause!=3) begin
        traps=traps+1;
        case(io_trapCause)
          64'h8000000000000003: msip=msip+1;
          64'h8000000000000007: mtip=mtip+1;
          64'h800000000000000b: meip=meip+1;
          5: begin
            load_faults=load_faults+1;
            if(io_trapPc!==pc_mmio && io_trapPc!==pc_read) $fatal(1,"I1_BOOT_LOAD_FAULT_PC_ORACLE pc=%h",io_trapPc);
          end
          7: begin
            store_faults=store_faults+1;
            if(io_trapPc!==pc_write) $fatal(1,"I1_BOOT_STORE_FAULT_PC_ORACLE pc=%h",io_trapPc);
          end
          11: begin
            ecalls=ecalls+1;
            if(io_trapPc!==pc_ecall) $fatal(1,"I1_BOOT_ECALL_PC_ORACLE pc=%h",io_trapPc);
          end
          default: $fatal(1,"I1_BOOT_TRAP_ORACLE cause=%h pc=%h",io_trapCause,io_trapPc);
        endcase
      end
      if(!guest_done && io_retire_valid===1) begin
        if(io_retire_bits_pc>=64'h10000 && io_retire_bits_pc<64'h11000) begin
          rom_retired=rom_retired+1;
          if(io_retire_bits_trap) $fatal(1,"I1_BOOT_ROM_TRAP_ORACLE");
        end else begin
          retired=retired+1;
          if(io_retire_bits_pc<64'h80200000 || io_retire_bits_pc>=64'h80200000+image_bytes)
            $fatal(1,"I1_BOOT_RETIRE_RANGE_ORACLE pc=%h",io_retire_bits_pc);
          if(first_ram_fabric==0) first_ram_fabric=fabric_edges;
          if(io_retire_bits_writesRd && io_retire_bits_rd==10) begin
            last_a0=io_retire_bits_data;
            if(last_a0!=0) $fatal(1,"I1_BOOT_GUEST_FAILURE_ORACLE pc=%h a0=%h",io_retire_bits_pc,last_a0);
          end
          if(io_retire_bits_trap && io_retire_bits_cause==3) begin
            if(io_retire_bits_instruction!==32'h00100073 || io_retire_bits_pc!==pc_success || last_a0!==0)
              $fatal(1,"I1_BOOT_SUCCESS_BREAK_ORACLE pc=%h expected=%h a0=%h",io_retire_bits_pc,pc_success,last_a0);
            if(traps!=7 || msip!=1 || mtip!=1 || meip!=1 || load_faults!=2 || store_faults!=1 || ecalls!=1)
              $fatal(1,"I1_BOOT_TRAP_COUNT_ORACLE traps=%0d msip=%0d mtip=%0d meip=%0d ld=%0d st=%0d ecall=%0d",
                traps,msip,mtip,meip,load_faults,store_faults,ecalls);
            if(rom_retired==0 || first_ram_fabric<ready_at) $fatal(1,"I1_BOOT_ROM_TO_RAM_ORACLE");
            guest_done=1;boot_cpu_edges=cpu_edges;boot_fabric_edges=fabric_edges;
            $display("I1_BOOT_GUEST_DONE cpu_edges=%0d fabric_edges=%0d retired=%0d rom_retired=%0d traps=%0d",cpu_edges,fabric_edges,retired,rom_retired,traps);
          end
        end
      end
    end
  end

  // Observe the actual serialized BootROM banner at the declared fabric timebase.
  localparam integer BANNER_BYTES=33;
  localparam [8*BANNER_BYTES-1:0] BANNER={"Valence Orbital-I1 BootROM V0.1",8'h0d,8'h0a};
  real bit_ns=1000000000.0/460800.0;
  reg [7:0] uart_byte;
  integer uart_count=0,uart_bit;
  initial begin
    wait(uart_count==BANNER_BYTES);
    @(negedge fabricClock);
    // Ensure the checked ROM actually waits for DDR, rather than releasing it
    // while the long serial banner is still being sent.
    ready_at=fabric_edges+2000;
  end
  initial begin
    wait(configured);
    forever begin
      @(negedge io_uartTx);
      if(!commonColdReset) begin
        #(bit_ns*1.5);
        for(uart_bit=0;uart_bit<8;uart_bit=uart_bit+1) begin
          uart_byte[uart_bit]=io_uartTx;
          #(bit_ns);
        end
        if(io_uartTx!==1) $fatal(1,"I1_BOOT_UART_STOP_ORACLE");
        if(uart_count>=BANNER_BYTES || uart_byte!==BANNER[(BANNER_BYTES-1-uart_count)*8+:8])
          $fatal(1,"I1_BOOT_UART_BANNER_ORACLE index=%0d value=%h",uart_count,uart_byte);
        uart_count=uart_count+1;
      end
    end
  end

  // Read actual dirty CPU state through the coherent networkMemory client. This
  // exercises real B/C/E probes and the Home; no backing-memory peek can pass it.
  integer coherent_reads=0,coherent_wait_cycles=0;
  task coherent_check(input [63:0] address,input [63:0] expected,input integer nonzero);
    integer accepted,received,waits; reg [63:0] observed;
    begin
      accepted=0;received=0;waits=0;
      @(negedge fabricClock);
      io_networkMemory_request_bits_address=address;
      io_networkMemory_request_valid=1;
      io_networkMemory_response_ready=1;
      while(!received && waits<20000) begin
        @(posedge fabricClock);
        if(io_networkMemory_request_valid && io_networkMemory_request_ready) accepted=1;
        if(io_networkMemory_response_valid && io_networkMemory_response_ready) begin
          if(!accepted || io_networkMemory_response_bits_error) $fatal(1,"I1_BOOT_COHERENT_RESPONSE_ORACLE address=%h",address);
          observed=io_networkMemory_response_bits_data;received=1;
        end
        @(negedge fabricClock);
        if(accepted) io_networkMemory_request_valid=0;
        waits=waits+1;
      end
      if(!received) $fatal(1,"I1_BOOT_COHERENT_TIMEOUT_ORACLE address=%h",address);
      if((!nonzero && observed!==expected) || (nonzero && (observed===0 || ^observed===1'bx)))
        $fatal(1,"I1_BOOT_COHERENT_DATA_ORACLE address=%h observed=%h expected=%h",address,observed,expected);
      coherent_reads=coherent_reads+1;coherent_wait_cycles=coherent_wait_cycles+waits;
      io_networkMemory_response_ready=0;
    end
  endtask
  // Read-only production port monitors, compiled only for the independent top.
`ifdef I1_OBSERVE_CDC
  integer cdc_a=0,cdc_b=0,cdc_c=0,cdc_d=0,cdc_e=0,i_uncached_requests=0,d_uncached_requests=0,i_uncached_responses=0,d_uncached_responses=0,i_line_grants=0,d_line_grants=0,reservation_clears=0;
  always @(posedge cpuClock) if(!commonColdReset) begin
    if(dut.dut.coherent_0.cpu_a_valid && dut.dut.coherent_0.cpu_a_ready) cdc_a=cdc_a+1;
    if(dut.dut.coherent_0.cpu_b_valid && dut.dut.coherent_0.cpu_b_ready) cdc_b=cdc_b+1;
    if(dut.dut.coherent_0.cpu_c_valid && dut.dut.coherent_0.cpu_c_ready) cdc_c=cdc_c+1;
    if(dut.dut.coherent_0.cpu_d_valid && dut.dut.coherent_0.cpu_d_ready) cdc_d=cdc_d+1;
    if(dut.dut.coherent_0.cpu_e_valid && dut.dut.coherent_0.cpu_e_ready) cdc_e=cdc_e+1;
    if(dut.dut.uncached_0.cpu_request_valid && dut.dut.uncached_0.cpu_request_ready) i_uncached_requests=i_uncached_requests+1;
    if(dut.dut.uncached_0.cpu_response_valid && dut.dut.uncached_0.cpu_response_ready) i_uncached_responses=i_uncached_responses+1;
    if(dut.dut.grants_0.destination_valid && dut.dut.grants_0.destination_ready) i_line_grants=i_line_grants+1;
    if(dut.dut.coherent_1.cpu_a_valid && dut.dut.coherent_1.cpu_a_ready) cdc_a=cdc_a+1;
    if(dut.dut.coherent_1.cpu_b_valid && dut.dut.coherent_1.cpu_b_ready) cdc_b=cdc_b+1;
    if(dut.dut.coherent_1.cpu_c_valid && dut.dut.coherent_1.cpu_c_ready) cdc_c=cdc_c+1;
    if(dut.dut.coherent_1.cpu_d_valid && dut.dut.coherent_1.cpu_d_ready) cdc_d=cdc_d+1;
    if(dut.dut.coherent_1.cpu_e_valid && dut.dut.coherent_1.cpu_e_ready) cdc_e=cdc_e+1;
    if(dut.dut.uncached_1.cpu_request_valid && dut.dut.uncached_1.cpu_request_ready) d_uncached_requests=d_uncached_requests+1;
    if(dut.dut.uncached_1.cpu_response_valid && dut.dut.uncached_1.cpu_response_ready) d_uncached_responses=d_uncached_responses+1;
    if(dut.dut.grants_1.destination_valid && dut.dut.grants_1.destination_ready) d_line_grants=d_line_grants+1;
  end
  always @(posedge fabricClock) if(!commonColdReset && dut.dut.uncached_1.fabricClearReservation) reservation_clears=reservation_clears+1;
`endif

  integer final_i;
  initial begin
    wait(configured);
    repeat(12) @(negedge fabricClock);
    commonColdReset=0;
    wait(guest_done);
    // Keep both clocks and the parked CPU running during coherent verification.
    for(final_i=0;final_i<6;final_i=final_i+1)
      coherent_check(64'h80210000+8*final_i,(final_i==3)?2:1,0);
    coherent_check(64'h80210030,64'h55aa,0);
    coherent_check(64'h80210038,3,0);
    coherent_check(64'h80210040,0,1);
    coherent_check(64'h80214000,64'h55aa,0);
    coherent_check(64'h1001ffff8,64'h7c00005a,0);
    for(final_i=0;final_i<128;final_i=final_i+1)
      coherent_check(64'h80211000+8*final_i,64'h123456789abcdef0+final_i,0);
    if(!single_mode && time_changes<10) $fatal(1,"I1_BOOT_TIME_PROGRESS_ORACLE changes=%0d",time_changes);
    if(uart_count!=BANNER_BYTES) $fatal(1,"I1_BOOT_UART_COUNT_ORACLE got=%0d",uart_count);
    if(r_errors!=1 || b_errors!=1 || line_bursts==0 || ar_stalls==0 || w_stalls==0)
      $fatal(1,"I1_BOOT_COVERAGE_ORACLE r_errors=%0d b_errors=%0d bursts=%0d ar_stalls=%0d w_stalls=%0d",
        r_errors,b_errors,line_bursts,ar_stalls,w_stalls);
`ifdef I1_OBSERVE_CDC
    if(cdc_a==0 || cdc_b==0 || cdc_c==0 || cdc_d==0 || cdc_e==0 ||
       i_uncached_requests==0 || d_uncached_requests==0 || i_uncached_responses==0 || d_uncached_responses==0 ||
       i_line_grants==0 || d_line_grants==0 || reservation_clears==0)
      $fatal(1,"I1_BOOT_CDC_PATH_COVERAGE_ORACLE a=%0d b=%0d c=%0d d=%0d e=%0d",cdc_a,cdc_b,cdc_c,cdc_d,cdc_e);
    $display("I1_BOOT_CDC a=%0d b=%0d c=%0d d=%0d e=%0d i_uncached_requests=%0d d_uncached_requests=%0d i_uncached_responses=%0d d_uncached_responses=%0d i_line_grants=%0d d_line_grants=%0d reservation_clears=%0d",cdc_a,cdc_b,cdc_c,cdc_d,cdc_e,i_uncached_requests,d_uncached_requests,i_uncached_responses,d_uncached_responses,i_line_grants,d_line_grants,reservation_clears);
`endif
    $display("I1_BOOT_METRICS cpu_edges=%0d fabric_edges=%0d boot_cpu_edges=%0d boot_fabric_edges=%0d retired=%0d rom_retired=%0d uart_bytes=%0d axi_reads=%0d axi_writes=%0d read_beats=%0d write_beats=%0d line_bursts=%0d max_parallel_reads=%0d overlap_cycles=%0d ar_stalls=%0d aw_stalls=%0d w_stalls=%0d r_errors=%0d b_errors=%0d max_read_latency=%0d read_latency_sum=%0d coherent_reads=%0d coherent_wait_cycles=%0d time_changes=%0d",
      cpu_edges,fabric_edges,boot_cpu_edges,boot_fabric_edges,retired,rom_retired,uart_count,read_count,write_count,read_beats,write_beats,line_bursts,max_parallel_reads,overlap_cycles,ar_stalls,aw_stalls,w_stalls,r_errors,b_errors,max_read_latency,read_latency_sum,coherent_reads,coherent_wait_cycles,time_changes);
    $display("I1_INDEPENDENT_BOOT_NATIVE_PASS cpu_half=%0d fabric_half=%0d phase_ps=%0d single=%0d",cpu_half,fabric_half,phase_ps,single_mode);
    $finish;
  end
endmodule
