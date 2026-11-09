  // DDR-resident observation only. Original DUT and AXI service host remain intact.
  integer retired=0,rom_retired=0,guest_done=0,uart_count=0;
  integer loader_fences=0,ddr_entered=0,ddr_retired=0;
  reg [63:0] loader_fence_pc,loader_fail_pc;
  integer code_ar=0,data_ar=0,code_r=0,data_r=0,code_aw=0,data_aw=0,code_b=0,data_b=0;
  integer code_read_complete=0,data_read_complete=0;
  integer start_code_ar,start_data_ar,start_code_r,start_data_r;
  integer start_code_aw,start_data_aw,start_code_b,start_data_b;
  integer rd_kind[0:15],wr_kind[0:15],ddr_i,ddr_index;
  integer data_owners=0,code_owners=0;
  initial begin
    if(!$value$plusargs("loader_fence=%h",loader_fence_pc) ||
       !$value$plusargs("loader_fail=%h",loader_fail_pc)) $fatal(1,"COMMON_DDR_LOADER_SYMBOL_ORACLE");
    for(ddr_i=0;ddr_i<16;ddr_i=ddr_i+1) begin rd_kind[ddr_i]=0;wr_kind[ddr_i]=0;end
  end
  // Independent AXI-ID scoreboard reads only public interface handshakes. R/B
  // retire owners before same-edge ID reuse. No dependence on host process order.
  function integer address_kind(input [31:0] addr);
    begin
      if(addr<32'h10000) address_kind=1;
      else if((addr>=32'h10000 && addr<32'h11000) ||
              (addr>=32'h20000 && addr<32'h21000) ||
              (addr>=32'h30000 && addr<32'h31000)) address_kind=2;
      else begin $fatal(1,"COMMON_DDR_ADDRESS_CLASS_ORACLE addr=%h",addr);address_kind=0;end
    end
  endfunction
  always @(posedge fabricClock) if(!commonColdReset) begin
    if(io_ddrAxi_r_valid && io_ddrAxi_r_ready) begin
      if(rd_kind[io_ddrAxi_r_bits_id]==1) code_r=code_r+1;
      else if(rd_kind[io_ddrAxi_r_bits_id]==2) data_r=data_r+1;
      else $fatal(1,"COMMON_DDR_R_CLASS_OWNER_ORACLE");
      if(io_ddrAxi_r_bits_last) begin
        if(rd_kind[io_ddrAxi_r_bits_id]==1) code_read_complete=code_read_complete+1;
        else data_read_complete=data_read_complete+1;
        rd_kind[io_ddrAxi_r_bits_id]=0;
      end
    end
    if(io_ddrAxi_b_valid && io_ddrAxi_b_ready) begin
      if(wr_kind[io_ddrAxi_b_bits_id]==1) code_b=code_b+1;
      else if(wr_kind[io_ddrAxi_b_bits_id]==2) data_b=data_b+1;
      else $fatal(1,"COMMON_DDR_B_CLASS_OWNER_ORACLE");
      wr_kind[io_ddrAxi_b_bits_id]=0;
    end
    if(io_ddrAxi_ar_valid && io_ddrAxi_ar_ready) begin
      if(rd_kind[io_ddrAxi_ar_bits_id]!=0) $fatal(1,"COMMON_DDR_AR_CLASS_REUSE_ORACLE");
      rd_kind[io_ddrAxi_ar_bits_id]=address_kind(io_ddrAxi_ar_bits_addr);
      if(address_kind(io_ddrAxi_ar_bits_addr)==1) code_ar=code_ar+1;else data_ar=data_ar+1;
    end
    if(io_ddrAxi_aw_valid && io_ddrAxi_aw_ready) begin
      if(wr_kind[io_ddrAxi_aw_bits_id]!=0) $fatal(1,"COMMON_DDR_AW_CLASS_REUSE_ORACLE");
      wr_kind[io_ddrAxi_aw_bits_id]=address_kind(io_ddrAxi_aw_bits_addr);
      if(address_kind(io_ddrAxi_aw_bits_addr)==1) code_aw=code_aw+1;else data_aw=data_aw+1;
    end
    data_owners=0;code_owners=0;
    for(ddr_i=0;ddr_i<16;ddr_i=ddr_i+1) begin
      data_owners=data_owners+(rd_kind[ddr_i]==2);
      code_owners=code_owners+(rd_kind[ddr_i]==1);
    end
  end
  task check_code_image;
    integer i;
    begin
      for(i=0;i<45;i=i+1)
        if(memory_read(8*i)!=={rom[1024+2*i+1],rom[1024+2*i]})
          $fatal(1,"COMMON_DDR_CODE_IMAGE_ORACLE index=%0d",i);
    end
  endtask
  task checkpoint(input integer which);
    begin
      $display("COMMON_DDR_CHECKPOINT stage=%0d cpu_edge=%0d fabric_edge=%0d retired=%0d code_ar=%0d data_ar=%0d code_r=%0d data_r=%0d code_aw=%0d data_aw=%0d code_b=%0d data_b=%0d r=%0d w=%0d code_owners=%0d data_owners=%0d",
        which,cpu_edges,fabric_edges,retired,code_ar,data_ar,code_r,data_r,code_aw,data_aw,code_b,data_b,read_beats,write_beats,code_owners,data_owners);
    end
  endtask
  integer window=-1,completed=0,fences=0;
  reg [63:0] pc_begin[0:3],pc_end[0:3];
  reg [63:0] start_cpu,start_retired,start_fabric,start_ps;
  integer starts_ar,starts_aw,starts_r,starts_w,starts_b;
  integer starts_ar_stall,starts_aw_stall,starts_w_stall;
  integer starts_r_stall,starts_b_stall,starts_overlap;
  integer starts_reads,starts_writes;
  integer r_stalls=0,b_stalls=0,write_owners=0,read_complete=0;
  integer perf_max_rd=0,perf_max_wr=0,perf_rd_sum=0,perf_wr_sum=0;
  integer perf_fabric=0,perf_loads=0,perf_stores=0,perf_retired=0;
  integer perf_dual=0,perf_cpu_active=0,perf_init;
  integer bad_pattern=0;
  reg [63:0] dep_b,dep_e,ind_b,ind_e,copy_b,copy_e,drain_b,drain_e;
  initial begin
    if(!$value$plusargs("dep_begin=%h",dep_b) || !$value$plusargs("dep_end=%h",dep_e) ||
       !$value$plusargs("ind_begin=%h",ind_b) || !$value$plusargs("ind_end=%h",ind_e) ||
       !$value$plusargs("copy_begin=%h",copy_b) || !$value$plusargs("copy_end=%h",copy_e) ||
       !$value$plusargs("drain_begin=%h",drain_b) || !$value$plusargs("drain_end=%h",drain_e))
      $fatal(1,"COMMON_PERF_SYMBOL_ORACLE");
    pc_begin[0]=dep_b;pc_end[0]=dep_e;pc_begin[1]=ind_b;pc_end[1]=ind_e;
    pc_begin[2]=copy_b;pc_end[2]=copy_e;pc_begin[3]=drain_b;pc_end[3]=drain_e;
    bad_pattern=$test$plusargs("bad_pattern");
  end
  // Sampling convention: count rising fabric edges strictly after begin retirement
  // and through the last rising fabric edge before end retirement. Host updates at
  // posedge; the #1ps observer sees post-handshake ownership, avoiding NBA races.
  // Boundary timestamps are checked not to coincide with either sampling instant.
  always @(posedge fabricClock) begin
    if(!commonColdReset) begin
      r_stalls=r_stalls+(io_ddrAxi_r_valid && !io_ddrAxi_r_ready);
      b_stalls=b_stalls+(io_ddrAxi_b_valid && !io_ddrAxi_b_ready);
      read_complete=read_complete+(io_ddrAxi_r_valid && io_ddrAxi_r_ready && io_ddrAxi_r_bits_last);
    end
    #1;
    write_owners=0;
    for(perf_init=0;perf_init<16;perf_init=perf_init+1) write_owners=write_owners+wr_id_used[perf_init];
    if(window>=0) begin
      perf_fabric=perf_fabric+1;
      perf_rd_sum=perf_rd_sum+owners; perf_wr_sum=perf_wr_sum+write_owners;
      if(owners>perf_max_rd) perf_max_rd=owners;
      if(write_owners>perf_max_wr) perf_max_wr=write_owners;
    end
  end
  task begin_window(input integer which);
    begin
      if(window!=-1 || completed!=which) $fatal(1,"COMMON_PERF_WINDOW_ORDER_ORACLE");
      if(($time-phase_ps-fabric_half)%(2*fabric_half)<=1)
        $fatal(1,"COMMON_PERF_EDGE_COLLISION_ORACLE");
      window=which; start_cpu=cpu_edges;start_retired=retired;start_fabric=fabric_edges;start_ps=$time;
      starts_ar=read_count;starts_aw=write_count;starts_r=read_beats;starts_w=write_beats;starts_b=b_completed;
      starts_ar_stall=ar_stalls;starts_aw_stall=aw_stalls;starts_w_stall=w_stalls;
      starts_r_stall=r_stalls;starts_b_stall=b_stalls;starts_overlap=overlap_cycles;
      starts_reads=owners;starts_writes=write_owners;
      start_code_ar=code_ar;start_data_ar=data_ar;start_code_r=code_r;start_data_r=data_r;
      start_code_aw=code_aw;start_data_aw=data_aw;start_code_b=code_b;start_data_b=data_b;
      perf_max_rd=owners;perf_max_wr=write_owners;perf_rd_sum=0;perf_wr_sum=0;
      perf_fabric=0;perf_loads=0;perf_stores=0;perf_retired=0;perf_dual=0;perf_cpu_active=0;
      $display("COMMON_PERF_BEGIN phase=%0d pc=%h time_ps=%0t cpu_edge=%0d fabric_edge=%0d retired=%0d read_outstanding=%0d write_outstanding=%0d",which,pc_begin[which],$time,cpu_edges,fabric_edges,retired,owners,write_owners);
    end
  endtask
  task end_window(input integer which);
    begin
      if(window!=which || completed!=which) $fatal(1,"COMMON_PERF_WINDOW_ORDER_ORACLE");
      if(($time-phase_ps-fabric_half)%(2*fabric_half)<=1)
        $fatal(1,"COMMON_PERF_EDGE_COLLISION_ORACLE");
      if(perf_fabric!=fabric_edges-start_fabric) $fatal(1,"COMMON_PERF_FABRIC_COUNT_ORACLE");
      if(which<2 && (perf_loads!=256 || perf_stores!=0 || data_ar!=start_data_ar || data_aw!=start_data_aw))
        $fatal(1,"COMMON_PERF_WARM_HIT_ORACLE phase=%0d loads=%0d ar=%0d aw=%0d",which,perf_loads,read_count-starts_ar,write_count-starts_aw);
      if(which==2 && (perf_loads!=512 || perf_stores!=512)) $fatal(1,"COMMON_PERF_COPY_COUNT_ORACLE");
      if(which==3 && (fences!=1 || b_completed!=write_count || data_owners!=0 || write_owners!=0 || aw_count!=0 || w_count!=0 || b_count!=0))
        $fatal(1,"COMMON_PERF_REAL_COMPLETION_ORACLE b=%0d aw=%0d pending_b=%0d",b_completed,write_count,b_count);
      $display("COMMON_PERF_WINDOW phase=%0d begin_ps=%0d end_ps=%0t cpu_cycles=%0d retired=%0d fabric_cycles=%0d loads=%0d stores=%0d ar=%0d aw=%0d r=%0d w=%0d b=%0d ar_stall=%0d aw_stall=%0d r_stall=%0d w_stall=%0d b_stall=%0d read_start=%0d write_start=%0d read_end=%0d write_end=%0d max_reads=%0d max_writes=%0d read_owner_cycle_sum=%0d write_owner_cycle_sum=%0d overlap=%0d maintenance=%0d home_drained=%0d",
        which,start_ps,$time,cpu_edges-start_cpu,perf_retired,perf_fabric,perf_loads,perf_stores,
        read_count-starts_ar,write_count-starts_aw,read_beats-starts_r,write_beats-starts_w,b_completed-starts_b,
        ar_stalls-starts_ar_stall,aw_stalls-starts_aw_stall,r_stalls-starts_r_stall,w_stalls-starts_w_stall,b_stalls-starts_b_stall,
        starts_reads,starts_writes,owners,write_owners,perf_max_rd,perf_max_wr,perf_rd_sum,perf_wr_sum,
        overlap_cycles-starts_overlap,io_maintenancePending,io_homeDrained);
      $display("COMMON_DDR_WINDOW phase=%0d code_ar=%0d data_ar=%0d code_r=%0d data_r=%0d code_aw=%0d data_aw=%0d code_b=%0d data_b=%0d code_owners=%0d data_owners=%0d",
        which,code_ar-start_code_ar,data_ar-start_data_ar,code_r-start_code_r,data_r-start_data_r,
        code_aw-start_code_aw,data_aw-start_data_aw,code_b-start_code_b,data_b-start_data_b,code_owners,data_owners);
      window=-1;completed=completed+1;
    end
  endtask
  task observe_retire(input valid,input [63:0] pc,input [31:0] insn,input writesRd,input [4:0] rd,input [63:0] data);
    integer k,is_marker;
    begin
      if(valid===1) begin
        if(!io_bootEnable) $fatal(1,"COMMON_DDR_BOOT_ENABLE_ORACLE");
        retired=retired+1;
        if(pc>=64'h80000000 && pc<64'h80001000) begin
          if(ddr_entered || pc==loader_fail_pc) $fatal(1,"COMMON_DDR_LOADER_FLOW_ORACLE pc=%h",pc);
          rom_retired=rom_retired+1;
        end else if(pc>=64'h80200000 && pc<64'h80200168) begin
          if(loader_fences!=1) $fatal(1,"COMMON_DDR_BEFORE_FENCE_ORACLE");
          ddr_index=(pc-64'h80200000)>>2;
          if(insn!==rom[1024+ddr_index]) $fatal(1,"COMMON_DDR_RETIRED_IMAGE_ORACLE pc=%h insn=%h",pc,insn);
          if(!ddr_entered) begin
            if(pc!=64'h80200000) $fatal(1,"COMMON_DDR_ENTRY_ORACLE pc=%h",pc);
            check_code_image();checkpoint(1);ddr_entered=1;
          end
          ddr_retired=ddr_retired+1;
        end else $fatal(1,"COMMON_DDR_RETIRE_RANGE_ORACLE pc=%h",pc);
        if(pc==pc_fail) $fatal(1,"COMMON_PERF_GUEST_PATTERN_ORACLE pc=%h",pc);
        is_marker=0;
        for(k=0;k<4;k=k+1) begin
          if(pc==pc_begin[k]) begin is_marker=1;begin_window(k); end
          if(pc==pc_end[k]) begin is_marker=1;end_window(k); end
        end
        if(window>=0 && !is_marker) begin
          perf_retired=perf_retired+1;
          if(insn[6:0]==7'b0000011) perf_loads=perf_loads+1;
          if(insn[6:0]==7'b0100011) perf_stores=perf_stores+1;
        end
        if(insn==32'h0000100f) begin
          if(pc==loader_fence_pc) begin
            loader_fences=loader_fences+1;
            if(loader_fences!=1 || code_aw!=6 || code_b!=6 || data_aw!=0 || data_ar!=0)
              $fatal(1,"COMMON_DDR_LOADER_FENCE_ORACLE aw=%0d b=%0d",code_aw,code_b);
            check_code_image();checkpoint(0);
          end else begin fences=fences+1;checkpoint(2);end
          if(b_completed!=write_count || b_count!=0) $fatal(1,"COMMON_PERF_FENCE_B_ORACLE");
          $display("COMMON_PERF_FENCE cpu_edge=%0d fabric_edge=%0d b_completed=%0d writes=%0d maintenance=%0d home_drained=%0d",cpu_edges,fabric_edges,b_completed,write_count,io_maintenancePending,io_homeDrained);
        end
        if(pc==pc_done) guest_done=1;
      end
    end
  endtask
  always @(posedge cpuClock) begin
    if(io_bootEnable) cpu_edges=cpu_edges+1;
    if(cpu_edges>maxcycles) $fatal(1,"COMMON_PERF_BOUNDED_COMPLETION_ORACLE cpu=%0d phase=%0d retired=%0d reads=%0d writes=%0d b=%0d",cpu_edges,window,retired,read_count,write_count,b_completed);
    if(!commonColdReset) begin
      if(io_trap_valid===1) $fatal(1,"COMMON_PERF_TRAP_ORACLE pc=%h cause=%h",io_trap_bits_pc,io_trap_bits_cause);
      observe_retire(io_retire_0_valid,io_retire_0_bits_pc,io_retire_0_bits_instruction,io_retire_0_bits_writesRd,io_retire_0_bits_rd,io_retire_0_bits_data);
      observe_retire(io_retire_1_valid,io_retire_1_bits_pc,io_retire_1_bits_instruction,io_retire_1_bits_writesRd,io_retire_1_bits_rd,io_retire_1_bits_data);
    end
  end
  integer final_i;reg [63:0] expected;
  initial begin
    wait(guest_done);
    // A post-FENCE instruction line can still be in flight at the end marker.
    // Wait for real public home/AXI quiescence, with the CPU watchdog still active.
    wait(io_maintenancePending===0 && io_homeDrained===1 && owners==0 && aw_count==0 && w_count==0 && b_count==0);
    @(negedge fabricClock);
    if(completed!=4 || loader_fences!=1 || b_completed!=write_count || data_b!=64 || code_b!=6 ||
       data_ar!=192 || code_ar+data_ar!=read_count || code_r+data_r!=read_beats ||
       code_aw+data_aw!=write_count || code_b+data_b!=b_completed ||
       data_read_complete!=data_ar || code_read_complete!=code_ar || read_complete!=read_count ||
       io_maintenancePending!==0 || io_homeDrained!==1 || aw_count!=0 || w_count!=0 || b_count!=0 || owners!=0)
      $fatal(1,"COMMON_PERF_FINAL_COMPLETION_ORACLE phases=%0d ar=%0d aw=%0d b=%0d maintenance=%b home=%b",completed,read_count,write_count,b_completed,io_maintenancePending,io_homeDrained);
    for(final_i=0;final_i<512;final_i=final_i+1) begin
      expected=64'h1234567800000000+final_i;
      if(memory_read(32'h20000+8*final_i)!==expected) $fatal(1,"COMMON_PERF_SOURCE_ORACLE index=%0d",final_i);
      if(bad_pattern && final_i==31) expected=expected^64'h1;
      if(memory_read(32'h30000+8*final_i)!==expected)
        $fatal(1,"COMMON_PERF_FINAL_PATTERN_ORACLE index=%0d got=%h expected=%h",final_i,memory_read(32'h30000+8*final_i),expected);
    end
    check_code_image();checkpoint(3);
    $display("COMMON_PERF_TOTAL cpu_cycles=%0d retired=%0d fabric_edges=%0d ar=%0d aw=%0d r=%0d w=%0d b=%0d read_complete=%0d final_words=512",cpu_edges,retired,fabric_edges,read_count,write_count,read_beats,write_beats,b_completed,read_complete);
    $display("COMMON_CPU_PERF_DDR_NATIVE_PASS");$finish;
  end
