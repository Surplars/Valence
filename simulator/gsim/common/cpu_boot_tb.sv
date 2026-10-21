`timescale 1ps/1ps
// Native digital-only environment. Production emitted RTL is compiled unchanged.
// This test does not qualify metastability, clock gating, routed timing or FPGA boot.
module cpu_boot_tb;
  reg cpuClock=0,fabricClock=0,alwaysOnClock=0,rawUartClock=0,rawTxClock=0,rawRxClock=0;
  `ifdef COMMON_INDEPENDENT_FIXED_DOMAINS
  reg ddrClock=0,timebaseClock=0,debugClock=0;
  initial begin wait(domains_started); #557; forever #2000 ddrClock=~ddrClock; end
  initial begin wait(domains_started); #947; forever #2000 timebaseClock=~timebaseClock; end
  // Board debug input is the 250 MHz UI clock rate, not AON50.
  initial begin wait(domains_started); #1327; forever #2000 debugClock=~debugClock; end
`else
  wire ddrClock=fabricClock;
`endif
  reg commonColdReset=0;
  // Explicit physical cold-reset edge also reaches initially stopped gated domains.
  initial begin wait(configured); #1; commonColdReset=1; end
  integer cpu_half=1667,fabric_half=2000,phase_ps=731,maxcycles=1000000;
  integer domains_started=0,configured=0,firmware_mode=0,bad_drop_response=0,bad_drop_b=0,bad_uart=0;
  reg [2047:0] rom_hex;
  reg [63:0] pc_fail=0,pc_done=0,pc_fence_first=0,pc_fence_modified=0,pc_fence_final=0;
  initial begin
    if($value$plusargs("cpu_half=%d",cpu_half)) begin end
    if($value$plusargs("fabric_half=%d",fabric_half)) begin end
    if($value$plusargs("phase_ps=%d",phase_ps)) begin end
    if($value$plusargs("maxcycles=%d",maxcycles)) begin end
    if($value$plusargs("pc_fail=%h",pc_fail)) begin end
    if($value$plusargs("pc_done=%h",pc_done)) begin end
    if($value$plusargs("pc_fence_first=%h",pc_fence_first)) begin end
    if($value$plusargs("pc_fence_modified=%h",pc_fence_modified)) begin end
    if($value$plusargs("pc_fence_final=%h",pc_fence_final)) begin end
    firmware_mode=$test$plusargs("firmware_mode");
    bad_drop_response=$test$plusargs("bad_drop_response");
    bad_drop_b=$test$plusargs("bad_drop_b"); bad_uart=$test$plusargs("bad_uart");
    if(!$value$plusargs("rom_hex=%s",rom_hex)) $fatal(1,"COMMON_BOOT_ROM_INPUT_ORACLE");
    if(cpu_half<=0 || fabric_half<=0 || phase_ps<=0) $fatal(1,"COMMON_BOOT_INDEPENDENT_CLOCK_ORACLE");
    configured=1;
  end
  initial begin wait(configured && domains_started); forever #(cpu_half) cpuClock=~cpuClock; end
  initial begin wait(configured); #(phase_ps); forever #(fabric_half) fabricClock=~fabricClock; end
  initial begin wait(domains_started); forever #10000 alwaysOnClock=~alwaysOnClock; end
  initial begin wait(domains_started); #419; forever #10000 rawUartClock=~rawUartClock; end
  initial begin wait(domains_started); #1173; forever #4000 rawTxClock=~rawTxClock; end
  initial begin wait(domains_started); #2137; forever #4000 rawRxClock=~rawRxClock; end
  reg io_ddrReady=0,io_bootEnable=0,io_program_valid=0;
  reg [14:0] io_program_bits_index=0;
  reg [31:0] io_program_bits_data=0;
  wire io_uartTx,io_cpuLinkReady,io_fabricLinkReady,io_cpuTransportEmpty,io_fabricTransportEmpty;
  wire io_maintenancePending,io_homeDrained;
  wire [63:0] io_timeSnapshot,io_cpuCycles,io_instructions,io_fabricCycles;
  wire io_trap_valid; wire [63:0] io_trap_bits_pc,io_trap_bits_cause;
  wire io_retire_0_valid,io_retire_0_bits_writesRd;
  wire [63:0] io_retire_0_bits_pc,io_retire_0_bits_nextPc,io_retire_0_bits_data;
  wire [31:0] io_retire_0_bits_instruction; wire [4:0] io_retire_0_bits_rd;
  wire io_retire_1_valid,io_retire_1_bits_writesRd;
  wire [63:0] io_retire_1_bits_pc,io_retire_1_bits_nextPc,io_retire_1_bits_data;
  wire [31:0] io_retire_1_bits_instruction; wire [4:0] io_retire_1_bits_rd;
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
  CommonMachinePlatform dut(
    .cpuClock(cpuClock),
`ifdef COMMON_INDEPENDENT_FIXED_DOMAINS
    .ddrClock(ddrClock), .timebaseClock(timebaseClock), .debugClock(debugClock),
`endif
    .fabricClock(fabricClock),
    .alwaysOnClock(alwaysOnClock),
    .rawUartClock(rawUartClock),
    .rawTxClock(rawTxClock),
    .rawRxClock(rawRxClock),
    .commonColdReset(commonColdReset),
    .io_ddrReady(io_ddrReady),
    .io_bootEnable(io_bootEnable),
    .io_uartTx(io_uartTx),
    .io_cpuLinkReady(io_cpuLinkReady),
    .io_fabricLinkReady(io_fabricLinkReady),
    .io_cpuTransportEmpty(io_cpuTransportEmpty),
    .io_fabricTransportEmpty(io_fabricTransportEmpty),
    .io_maintenancePending(io_maintenancePending),
    .io_homeDrained(io_homeDrained),
    .io_timeSnapshot(io_timeSnapshot),
    .io_cpuCycles(io_cpuCycles),
    .io_instructions(io_instructions),
    .io_fabricCycles(io_fabricCycles),
    .io_trap_valid(io_trap_valid),
    .io_trap_bits_pc(io_trap_bits_pc),
    .io_trap_bits_cause(io_trap_bits_cause),
    .io_program_valid(io_program_valid),
    .io_program_bits_index(io_program_bits_index),
    .io_program_bits_data(io_program_bits_data),
    .io_ddrAxi_ar_valid(io_ddrAxi_ar_valid),
    .io_ddrAxi_aw_valid(io_ddrAxi_aw_valid),
    .io_ddrAxi_w_valid(io_ddrAxi_w_valid),
    .io_ddrAxi_r_ready(io_ddrAxi_r_ready),
    .io_ddrAxi_b_ready(io_ddrAxi_b_ready),
    .io_ddrAxi_ar_ready(io_ddrAxi_ar_ready),
    .io_ddrAxi_aw_ready(io_ddrAxi_aw_ready),
    .io_ddrAxi_w_ready(io_ddrAxi_w_ready),
    .io_ddrAxi_r_valid(io_ddrAxi_r_valid),
    .io_ddrAxi_b_valid(io_ddrAxi_b_valid),
    .io_ddrAxi_ar_bits_addr(io_ddrAxi_ar_bits_addr),
    .io_ddrAxi_aw_bits_addr(io_ddrAxi_aw_bits_addr),
    .io_ddrAxi_ar_bits_id(io_ddrAxi_ar_bits_id),
    .io_ddrAxi_aw_bits_id(io_ddrAxi_aw_bits_id),
    .io_ddrAxi_ar_bits_len(io_ddrAxi_ar_bits_len),
    .io_ddrAxi_aw_bits_len(io_ddrAxi_aw_bits_len),
    .io_ddrAxi_ar_bits_size(io_ddrAxi_ar_bits_size),
    .io_ddrAxi_aw_bits_size(io_ddrAxi_aw_bits_size),
    .io_ddrAxi_ar_bits_burst(io_ddrAxi_ar_bits_burst),
    .io_ddrAxi_aw_bits_burst(io_ddrAxi_aw_bits_burst),
    .io_ddrAxi_ar_bits_lock(io_ddrAxi_ar_bits_lock),
    .io_ddrAxi_aw_bits_lock(io_ddrAxi_aw_bits_lock),
    .io_ddrAxi_ar_bits_cache(io_ddrAxi_ar_bits_cache),
    .io_ddrAxi_aw_bits_cache(io_ddrAxi_aw_bits_cache),
    .io_ddrAxi_ar_bits_qos(io_ddrAxi_ar_bits_qos),
    .io_ddrAxi_aw_bits_qos(io_ddrAxi_aw_bits_qos),
    .io_ddrAxi_ar_bits_prot(io_ddrAxi_ar_bits_prot),
    .io_ddrAxi_aw_bits_prot(io_ddrAxi_aw_bits_prot),
    .io_ddrAxi_w_bits_data(io_ddrAxi_w_bits_data),
    .io_ddrAxi_w_bits_strb(io_ddrAxi_w_bits_strb),
    .io_ddrAxi_w_bits_last(io_ddrAxi_w_bits_last),
    .io_ddrAxi_r_bits_id(io_ddrAxi_r_bits_id),
    .io_ddrAxi_b_bits_id(io_ddrAxi_b_bits_id),
    .io_ddrAxi_r_bits_data(io_ddrAxi_r_bits_data),
    .io_ddrAxi_r_bits_resp(io_ddrAxi_r_bits_resp),
    .io_ddrAxi_b_bits_resp(io_ddrAxi_b_bits_resp),
    .io_ddrAxi_r_bits_last(io_ddrAxi_r_bits_last),
    .io_retire_0_valid(io_retire_0_valid),
    .io_retire_0_bits_pc(io_retire_0_bits_pc),
    .io_retire_0_bits_instruction(io_retire_0_bits_instruction),
    .io_retire_0_bits_nextPc(io_retire_0_bits_nextPc),
    .io_retire_0_bits_rd(io_retire_0_bits_rd),
    .io_retire_0_bits_writesRd(io_retire_0_bits_writesRd),
    .io_retire_0_bits_data(io_retire_0_bits_data),
    .io_retire_1_valid(io_retire_1_valid),
    .io_retire_1_bits_pc(io_retire_1_bits_pc),
    .io_retire_1_bits_instruction(io_retire_1_bits_instruction),
    .io_retire_1_bits_nextPc(io_retire_1_bits_nextPc),
    .io_retire_1_bits_rd(io_retire_1_bits_rd),
    .io_retire_1_bits_writesRd(io_retire_1_bits_writesRd),
    .io_retire_1_bits_data(io_retire_1_bits_data),
    .io_triSpeedRgmii_rxRise(5'b0),
    .io_triSpeedRgmii_rxFall(5'b0),
    .io_sources(31'b0),
    .io_uartRx(1'b1),
    .io_gmiiRxData(8'b0),
    .io_gmiiRxValid(1'b0),
    .io_gmiiRxError(1'b0),
    .io_linkUp(1'b0),
    .io_mdioIn(1'b1),
    .io_jtagLinkUp(1'b0),
    .io_jtagDmi_request_valid(1'b0),
    .io_jtagDmi_request_bits_op(2'b0),
    .io_jtagDmi_request_bits_address(7'b0),
    .io_jtagDmi_request_bits_data(32'b0),
    .io_jtagDmi_response_ready(1'b1),
    .io_maintenance_valid(1'b0),
    .io_maintenance_bits_epoch(8'b0),
    .io_maintenance_bits_invalidateInstructions(1'b0),
    .io_maintenance_bits_invalidateTranslations(1'b0)
  );

  // Two bounded backing windows represent sparse 2 GiB DDR; no model geometry override.
  reg [63:0] ram[0:32767]; reg [63:0] monitor_ram[0:4095];
  reg [31:0] rom[0:32767]; integer init_i;
  initial begin
    wait(configured);
    for(init_i=0;init_i<32768;init_i=init_i+1) ram[init_i]=0;
    for(init_i=0;init_i<4096;init_i=init_i+1) monitor_ram[init_i]=0;
    $readmemh(rom_hex,rom,0,32767);
    // The emitted SyncReadMem write port has no reset gating. Program all words
    // while common cold reset remains asserted; only the programming fabric
    // clock runs during this reset initialization. No live-domain clock stops.
    repeat(4) @(negedge fabricClock);
    for(init_i=0;init_i<32768;init_i=init_i+1) begin
      io_program_valid=1; io_program_bits_index=init_i; io_program_bits_data=rom[init_i];
      @(negedge fabricClock);
    end
    io_program_valid=0;
    domains_started=1;
    // Establish every real clock while still in common reset, then release once.
    repeat(12) @(negedge alwaysOnClock);
    @(negedge fabricClock); commonColdReset=0;
    repeat(20) @(negedge fabricClock);
    io_ddrReady=1; io_bootEnable=1;
  end
  function [63:0] memory_read(input [31:0] addr);
    begin
      if(addr<32'h40000) memory_read=ram[addr>>3];
      else if(addr>=32'h7fdf8000 && addr<32'h7fe00000) memory_read=monitor_ram[(addr-32'h7fdf8000)>>3];
      else begin $fatal(1,"COMMON_BOOT_RAM_RANGE_ORACLE addr=%h",addr); memory_read=0; end
    end
  endfunction
  task memory_write(input [31:0] addr,input [63:0] data,input [7:0] mask);
    reg [63:0] value; integer j;
    begin
      value=memory_read(addr);
      for(j=0;j<8;j=j+1) if(mask[j]) value[j*8+:8]=data[j*8+:8];
      if(addr<32'h40000) ram[addr>>3]=value;
      else monitor_ram[(addr-32'h7fdf8000)>>3]=value;
    end
  endtask
  task address_check(input [31:0] addr,input [7:0] len,input [2:0] size,input [1:0] burst);
    begin
      if(burst!==1 || size>3 || addr>=32'h80000000 || (addr&((1<<size)-1))!=0 ||
         ((addr&4095)+((len+1)<<size))>4096)
        $fatal(1,"COMMON_BOOT_AXI_GEOMETRY_ORACLE addr=%h len=%d size=%d burst=%d",addr,len,size,burst);
    end
  endtask
  // Host owners preserve all four DUT read slots and both write owners; IDs are never collapsed.
  reg rd_used[0:15]; reg wr_id_used[0:15]; reg [31:0] rd_addr[0:15];
  integer rd_due[0:15],rd_len[0:15],rd_size[0:15],rd_beat[0:15],rd_id[0:15],rd_ticket[0:15];
  reg [31:0] aw_addr[0:15]; integer aw_id[0:15],aw_len[0:15],aw_size[0:15];
  reg [63:0] w_data[0:127]; reg [7:0] w_mask[0:127]; reg w_last[0:127];
  integer b_id[0:15],b_due[0:15]; reg [31:0] b_addr[0:15]; reg b_error[0:15];
  integer aw_head=0,aw_tail=0,aw_count=0,w_head=0,w_tail=0,w_count=0,b_head=0,b_tail=0,b_count=0;
  integer sending=-1,ddr_edges=0,fabric_edges=0,cpu_edges=0,read_count=0,write_count=0,read_beats=0,write_beats=0;
  integer line_bursts=0,max_parallel_reads=0,overlap_cycles=0,ar_stalls=0,aw_stalls=0,w_stalls=0;
  integer ar_wait_edges=0;
  integer r_errors=0,b_errors=0,max_read_latency=0,read_latency_sum=0;
  integer b_completed=0,code_b_completed=0,max_pending_b=0;
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
  initial for(model_i=0;model_i<16;model_i=model_i+1) begin rd_used[model_i]=0; wr_id_used[model_i]=0; end

  always @(posedge fabricClock) fabric_edges=fabric_edges+1;
  always @(negedge ddrClock) begin
    if(commonColdReset) begin
      io_ddrAxi_ar_ready=0;io_ddrAxi_aw_ready=0;io_ddrAxi_w_ready=0;
      io_ddrAxi_r_valid=0;io_ddrAxi_b_valid=0;
    end else begin
      
      // Hold every AR for two observed DDR edges before the periodic mask.
      // Periodic masks alone can miss all requests after a CDC phase change.
      io_ddrAxi_ar_ready=(ar_wait_edges>=2 && ddr_edges%5!=1 && ddr_edges%5!=2);
      io_ddrAxi_aw_ready=(ddr_edges%7!=2 && ddr_edges%7!=3);
      io_ddrAxi_w_ready=(ddr_edges%4!=1);
      if(sending<0) begin
        best_ticket=-1;
        for(model_i=0;model_i<16;model_i=model_i+1)
          if(rd_used[model_i] && rd_due[model_i]<=ddr_edges && rd_ticket[model_i]>best_ticket &&
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
        io_ddrAxi_r_bits_resp=0;
      end
      io_ddrAxi_b_valid=(b_count>0 && b_due[b_head]<=ddr_edges);
      if(b_count>0) begin io_ddrAxi_b_bits_id=b_id[b_head]; io_ddrAxi_b_bits_resp=b_error[b_head]?2:0; end
    end
  end

  always @(posedge ddrClock) begin
    ddr_edges=ddr_edges+1;
    if(!commonColdReset) begin
      if(io_bootEnable && ddr_edges%50000==0) $display("COMMON_BOOT_PROGRESS ddr_edges=%0d cpu_edges=%0d retired=%0d rom_retired=%0d uart_bytes=%0d reads=%0d writes=%0d done=%0d",ddr_edges,cpu_edges,retired,rom_retired,uart_count,read_count,write_count,guest_done);
      if(!io_ddrReady && (io_ddrAxi_ar_valid || io_ddrAxi_aw_valid || io_ddrAxi_w_valid))
        $fatal(1,"COMMON_BOOT_CALIBRATION_ORACLE");
      if(ar_held && (!io_ddrAxi_ar_valid || ar_payload!==held_ar)) $fatal(1,"COMMON_BOOT_AR_HOLD_ORACLE");
      if(aw_held && (!io_ddrAxi_aw_valid || aw_payload!==held_aw)) $fatal(1,"COMMON_BOOT_AW_HOLD_ORACLE");
      if(w_held && (!io_ddrAxi_w_valid || w_payload!==held_w)) $fatal(1,"COMMON_BOOT_W_HOLD_ORACLE");
      if(io_ddrAxi_ar_valid && io_ddrAxi_ar_ready) ar_wait_edges=0;
      else if(io_ddrAxi_ar_valid) ar_wait_edges=ar_wait_edges+1;
      ar_held=io_ddrAxi_ar_valid && !io_ddrAxi_ar_ready; held_ar=ar_payload; ar_stalls=ar_stalls+ar_held;
      aw_held=io_ddrAxi_aw_valid && !io_ddrAxi_aw_ready; held_aw=aw_payload; aw_stalls=aw_stalls+aw_held;
      w_held=io_ddrAxi_w_valid && !io_ddrAxi_w_ready; held_w=w_payload; w_stalls=w_stalls+w_held;
      r_payload_held=io_ddrAxi_r_valid && !io_ddrAxi_r_ready;
      if(io_ddrAxi_r_valid && io_ddrAxi_r_ready) begin
        read_beats=read_beats+1; r_errors=r_errors+(io_ddrAxi_r_bits_resp!=0);
        if(rd_beat[sending]==rd_len[sending]) begin
          read_latency_sum=read_latency_sum+ddr_edges-rd_accepted[sending];
          if(ddr_edges-rd_accepted[sending]>max_read_latency) max_read_latency=ddr_edges-rd_accepted[sending];
          rd_used[sending]=0; sending=-1;
        end else rd_beat[sending]=rd_beat[sending]+1;
      end
      if(io_ddrAxi_b_valid && io_ddrAxi_b_ready) begin
        if(!wr_id_used[io_ddrAxi_b_bits_id]) $fatal(1,"COMMON_BOOT_B_OWNER_ID_ORACLE");
        wr_id_used[io_ddrAxi_b_bits_id]=0; b_completed=b_completed+1;
        if(b_addr[b_head]==32'h4000) code_b_completed=code_b_completed+1;
        b_errors=b_errors+(io_ddrAxi_b_bits_resp!=0); b_head=(b_head+1)%16; b_count=b_count-1;
      end
      if(io_ddrAxi_ar_valid) address_check(io_ddrAxi_ar_bits_addr,io_ddrAxi_ar_bits_len,
        io_ddrAxi_ar_bits_size,io_ddrAxi_ar_bits_burst);
      if(io_ddrAxi_aw_valid) address_check(io_ddrAxi_aw_bits_addr,io_ddrAxi_aw_bits_len,
        io_ddrAxi_aw_bits_size,io_ddrAxi_aw_bits_burst);
      if(io_ddrAxi_ar_valid && io_ddrAxi_ar_ready) begin
        slot=-1; for(model_i=0;model_i<16;model_i=model_i+1) if(!rd_used[model_i]) slot=model_i;
        if(slot<0) $fatal(1,"COMMON_BOOT_READ_OWNER_OVERFLOW");
        for(model_i=0;model_i<16;model_i=model_i+1)
          if(rd_used[model_i] && rd_id[model_i]==io_ddrAxi_ar_bits_id) $fatal(1,"COMMON_BOOT_READ_OWNER_REUSE_ORACLE");
        rd_used[slot]=1;rd_addr[slot]=io_ddrAxi_ar_bits_addr;rd_id[slot]=io_ddrAxi_ar_bits_id;
        rd_len[slot]=io_ddrAxi_ar_bits_len;rd_size[slot]=io_ddrAxi_ar_bits_size;rd_beat[slot]=0;
        rd_due[slot]=ddr_edges+3+(read_count*7)%13;rd_ticket[slot]=read_count;rd_accepted[slot]=ddr_edges;
        read_count=read_count+1;line_bursts=line_bursts+(io_ddrAxi_ar_bits_len!=0);
      end
      if(io_ddrAxi_aw_valid && io_ddrAxi_aw_ready) begin
        if(aw_count==16) $fatal(1,"COMMON_BOOT_AW_OWNER_OVERFLOW");
        if(wr_id_used[io_ddrAxi_aw_bits_id]) $fatal(1,"COMMON_BOOT_WRITE_OWNER_REUSE_ORACLE");
        wr_id_used[io_ddrAxi_aw_bits_id]=1;
        aw_addr[aw_tail]=io_ddrAxi_aw_bits_addr;aw_id[aw_tail]=io_ddrAxi_aw_bits_id;
        aw_len[aw_tail]=io_ddrAxi_aw_bits_len;aw_size[aw_tail]=io_ddrAxi_aw_bits_size;
        aw_tail=(aw_tail+1)%16;aw_count=aw_count+1;write_count=write_count+1;
      end
      if(io_ddrAxi_w_valid && io_ddrAxi_w_ready) begin
        if(w_count==128) $fatal(1,"COMMON_BOOT_W_OWNER_OVERFLOW");
        w_data[w_tail]=io_ddrAxi_w_bits_data;w_mask[w_tail]=io_ddrAxi_w_bits_strb;w_last[w_tail]=io_ddrAxi_w_bits_last;
        w_tail=(w_tail+1)%128;w_count=w_count+1;write_beats=write_beats+1;
      end
      if(aw_count>0 && w_count>=aw_len[aw_head]+1) begin
        if(b_count==16) $fatal(1,"COMMON_BOOT_B_OWNER_OVERFLOW");
        for(n=0;n<=aw_len[aw_head];n=n+1) begin
          if(w_last[w_head] !== (n==aw_len[aw_head])) $fatal(1,"COMMON_BOOT_WLAST_ORACLE");
          target_addr=(aw_addr[aw_head]+(n<<aw_size[aw_head]))&32'hfffffff8;
          memory_write(target_addr,w_data[w_head],w_mask[w_head]);
          w_head=(w_head+1)%128;w_count=w_count-1;
        end
        b_id[b_tail]=aw_id[aw_head];b_due[b_tail]=ddr_edges+23+(write_count*3)%31;
        b_error[b_tail]=0; b_addr[b_tail]=aw_addr[aw_head];
        if(bad_drop_b && aw_addr[aw_head]==32'h4000) b_due[b_tail]=2147483647;
        b_tail=(b_tail+1)%16;b_count=b_count+1;aw_head=(aw_head+1)%16;aw_count=aw_count-1;
      end
      if(b_count>max_pending_b) max_pending_b=b_count;
      owners=0; for(model_i=0;model_i<16;model_i=model_i+1) owners=owners+rd_used[model_i];
      if(owners>max_parallel_reads) max_parallel_reads=owners;
      if(owners>0 && (aw_count>0 || w_count>0 || b_count>0)) overlap_cycles=overlap_cycles+1;
    end
  end


  reg [63:0] trace_pc[0:15],trace_data[0:15]; reg [31:0] trace_insn[0:15];
  reg [4:0] trace_rd[0:15]; reg trace_writes[0:15]; integer trace_head=0,trace_count=0;
  task dump_trace;
    integer t,idx;
    begin
      for(t=0;t<trace_count;t=t+1) begin
        idx=(trace_head-trace_count+t+16)%16;
        $display("COMMON_BOOT_LAST_RETIRE pc=%h insn=%h writes=%0d rd=%0d data=%h",trace_pc[idx],trace_insn[idx],trace_writes[idx],trace_rd[idx],trace_data[idx]);
      end
      $display("COMMON_BOOT_OWNER_STATE maintenance=%0d home=%0d cpu_empty=%0d fabric_empty=%0d aw=%0d w=%0d b=%0d read_owners=%0d",io_maintenancePending,io_homeDrained,io_cpuTransportEmpty,io_fabricTransportEmpty,aw_count,w_count,b_count,owners);
    end
  endtask
  integer retired=0,rom_retired=0,guest_done=0,traps=0,mtip=0,meip=0;
  integer time_changes=0,fences=0,old_code_fetch=0,new_code_fetch=0;
  reg [63:0] last_time=0;
  task observe_retire(input valid,input [63:0] pc,input [31:0] insn,input writesRd,input [4:0] rd,input [63:0] data);
    begin
      if(valid===1) begin
        if(!io_bootEnable) $fatal(1,"COMMON_BOOT_COLD_START_ORACLE");
        trace_pc[trace_head]=pc; trace_insn[trace_head]=insn; trace_data[trace_head]=data;
        trace_rd[trace_head]=rd; trace_writes[trace_head]=writesRd;
        trace_head=(trace_head+1)%16; if(trace_count<16) trace_count=trace_count+1;
        retired=retired+1;
        if(pc>=64'h80000000 && pc<64'h80020000) rom_retired=rom_retired+1;
        else if(firmware_mode || pc<64'h80204000 || pc>=64'h80204008)
          $fatal(1,"COMMON_BOOT_RETIRE_RANGE_ORACLE pc=%h",pc);
        if(!firmware_mode) begin
          if(pc==pc_fail) begin dump_trace(); $fatal(1,"COMMON_BOOT_GUEST_FAILURE_ORACLE pc=%h",pc); end
          if(pc==pc_fence_first || pc==pc_fence_modified || pc==pc_fence_final) begin
            if(insn!==32'h0000100f) $fatal(1,"COMMON_BOOT_FENCE_INSTRUCTION_ORACLE");
            if(pc==pc_fence_first && (code_b_completed<1 || memory_read(32'h4000)!==64'h0000806700900513))
              $fatal(1,"COMMON_BOOT_FENCE_FIRST_REAL_COMPLETION_ORACLE b=%0d code=%h",code_b_completed,memory_read(32'h4000));
            if(pc==pc_fence_modified && (code_b_completed<2 || memory_read(32'h4000)!==64'h0000806702a00513))
              $fatal(1,"COMMON_BOOT_FENCE_MODIFIED_REAL_COMPLETION_ORACLE b=%0d code=%h",code_b_completed,memory_read(32'h4000));
            fences=fences+1;
          end
          if(pc==64'h80204000) begin
            if(old_code_fetch==0) begin
              if(insn!==32'h00900513 || data!==9 || !writesRd || rd!=10 || fences<1)
                $fatal(1,"COMMON_BOOT_ORIGINAL_FETCH_ORACLE insn=%h data=%h",insn,data);
              old_code_fetch=old_code_fetch+1;
            end else begin
              if(insn!==32'h02a00513 || data!==42 || !writesRd || rd!=10 || fences<2)
                $fatal(1,"COMMON_BOOT_MODIFIED_FETCH_ORACLE insn=%h data=%h",insn,data);
              new_code_fetch=new_code_fetch+1;
            end
          end
          if(pc==pc_done && !guest_done) begin
            if(fences!=3 || old_code_fetch!=1 || new_code_fetch!=1 || mtip!=1 || meip!=1 || traps!=2)
              $fatal(1,"COMMON_BOOT_GUEST_COVERAGE_ORACLE fences=%0d old=%0d new=%0d timer=%0d msi=%0d traps=%0d",fences,old_code_fetch,new_code_fetch,mtip,meip,traps);
            guest_done=1;
          end
        end
      end
    end
  endtask
  always @(posedge cpuClock) begin
    if(io_bootEnable) cpu_edges=cpu_edges+1;
    if(cpu_edges>maxcycles) begin dump_trace(); $fatal(1,"COMMON_BOOT_BOUNDED_COMPLETION_ORACLE cpu=%0d fabric=%0d retired=%0d uart=%0d reads=%0d writes=%0d b_completed=%0d code_b=%0d fences=%0d",cpu_edges,fabric_edges,retired,uart_count,read_count,write_count,b_completed,code_b_completed,fences); end
    if(!commonColdReset) begin
      if(io_cpuLinkReady===1) begin
        if(cpu_edges>50 && (^{io_fabricLinkReady,io_cpuTransportEmpty,io_fabricTransportEmpty,io_homeDrained,io_maintenancePending,io_uartTx,io_timeSnapshot})===1'bx)
          $fatal(1,"COMMON_BOOT_RESET_KNOWN_CONTROL_ORACLE");
        if(io_timeSnapshot<last_time) $fatal(1,"COMMON_BOOT_TIME_MONOTONIC_ORACLE");
        if(io_timeSnapshot>last_time) time_changes=time_changes+1;
        last_time=io_timeSnapshot;
      end
      if(io_trap_valid===1) begin
        traps=traps+1;
        case(io_trap_bits_cause)
          64'h8000000000000007: mtip=mtip+1;
          64'h800000000000000b: meip=meip+1;
          default: $fatal(1,"COMMON_BOOT_TRAP_ORACLE pc=%h cause=%h",io_trap_bits_pc,io_trap_bits_cause);
        endcase
        if(firmware_mode) $fatal(1,"COMMON_BOOT_FIRMWARE_TRAP_ORACLE pc=%h cause=%h",io_trap_bits_pc,io_trap_bits_cause);
      end
      observe_retire(io_retire_0_valid,io_retire_0_bits_pc,io_retire_0_bits_instruction,io_retire_0_bits_writesRd,io_retire_0_bits_rd,io_retire_0_bits_data);
      observe_retire(io_retire_1_valid,io_retire_1_bits_pc,io_retire_1_bits_instruction,io_retire_1_bits_writesRd,io_retire_1_bits_rd,io_retire_1_bits_data);
    end
  end
  localparam integer FIRMWARE_BANNER_BYTES=53;
  localparam [8*FIRMWARE_BANNER_BYTES-1:0] FIRMWARE_BANNER={"Valence Bootrom V0.2 | verified downloads auto-boot",8'h0d,8'h0a};
  localparam [63:0] GUEST_BANNER={"COMMON",8'h0d,8'h0a};
  real bit_ps=1000000000000.0/460800.0;
  reg [7:0] uart_byte,expected_byte; integer uart_count=0,uart_bit;
  initial begin
    wait(configured);
    forever begin
      @(negedge io_uartTx);
      if(!commonColdReset && io_bootEnable) begin
        #(bit_ps*1.5);
        for(uart_bit=0;uart_bit<8;uart_bit=uart_bit+1) begin
          uart_byte[uart_bit]=io_uartTx; #(bit_ps);
        end
        if(io_uartTx!==1) $fatal(1,"COMMON_BOOT_UART_STOP_ORACLE");
        if(firmware_mode) expected_byte=FIRMWARE_BANNER[(FIRMWARE_BANNER_BYTES-1-uart_count)*8+:8];
        else expected_byte=GUEST_BANNER[(7-uart_count)*8+:8];
        if(bad_uart && uart_count==0) expected_byte=expected_byte^8'h01;
        if(uart_byte!==expected_byte) $fatal(1,"COMMON_BOOT_UART_BANNER_ORACLE index=%0d got=%h expected=%h",uart_count,uart_byte,expected_byte);
        $display("COMMON_BOOT_UART index=%0d value=%h",uart_count,uart_byte);
        uart_count=uart_count+1;
        if(firmware_mode && uart_count==FIRMWARE_BANNER_BYTES) begin
          if(rom_retired==0 || read_count==0 || time_changes<10) $fatal(1,"COMMON_BOOT_FIRMWARE_COVERAGE_ORACLE");
          $display("COMMON_BOOT_FIRMWARE_BANNER_PASS cpu_edges=%0d fabric_edges=%0d retired=%0d uart_bytes=%0d",cpu_edges,fabric_edges,retired,uart_count);
          $finish;
        end
      end
    end
  end
  integer final_i;
  initial begin
    wait(guest_done && uart_count==8);
    @(negedge fabricClock);
    if(time_changes<10 || read_count==0 || write_count==0 || b_completed!=write_count || ar_stalls==0 || line_bursts==0)
      $fatal(1,"COMMON_BOOT_COVERAGE_ORACLE time=%0d reads=%0d writes=%0d b=%0d ar_stalls=%0d bursts=%0d",time_changes,read_count,write_count,b_completed,ar_stalls,line_bursts);
    if(memory_read(32'h10000)!==1 || memory_read(32'h10008)!==1 || memory_read(32'h10010)!==42 || memory_read(32'h10018)===0)
      $fatal(1,"COMMON_BOOT_FINAL_SIGNATURE_ORACLE");
    if(memory_read(32'h18000)!==64'h7c000000) $fatal(1,"COMMON_BOOT_BYTE_LANE_ORACLE");
    for(final_i=0;final_i<32;final_i=final_i+1)
      if(memory_read(32'h11000+8*final_i)!==64'h123456789abcdef0+final_i)
        $fatal(1,"COMMON_BOOT_DIRTY_DDR_DATA_ORACLE index=%0d",final_i);
    $display("COMMON_BOOT_METRICS cpu_edges=%0d fabric_edges=%0d retired=%0d rom_retired=%0d uart_bytes=%0d reads=%0d writes=%0d b_completed=%0d code_b_completed=%0d read_beats=%0d write_beats=%0d max_parallel_reads=%0d max_pending_b=%0d ar_stalls=%0d aw_stalls=%0d w_stalls=%0d fences=%0d timer=%0d msi=%0d old_fetch=%0d new_fetch=%0d time_changes=%0d",cpu_edges,fabric_edges,retired,rom_retired,uart_count,read_count,write_count,b_completed,code_b_completed,read_beats,write_beats,max_parallel_reads,max_pending_b,ar_stalls,aw_stalls,w_stalls,fences,mtip,meip,old_code_fetch,new_code_fetch,time_changes);
    $display("COMMON_CPU_BOOT_NATIVE_PASS cpu_half_ps=%0d fabric_half_ps=%0d phase_ps=%0d ddr_edges=%0d",cpu_half,fabric_half,phase_ps,ddr_edges);
    $finish;
  end
endmodule

// Bounded digital stand-in for the vendor primitive only. No clock-gating test or
// physical claim is made. Production ManagedClockBuffer/CdcLevel remain present.
module BUFGCE #(parameter CE_TYPE="SYNC")(input I,input CE,output O);
  reg ce_latched=0;
  always @(negedge I) ce_latched<=CE;
  assign O=I & ce_latched;
endmodule
