  // This fragment replaces only the boot fixture observers. DUT and host remain intact.
  integer retired=0,rom_retired=0,guest_done=0,uart_count=0;
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
      if(which<2 && (perf_loads!=256 || perf_stores!=0 || read_count!=starts_ar || write_count!=starts_aw))
        $fatal(1,"COMMON_PERF_WARM_HIT_ORACLE phase=%0d loads=%0d ar=%0d aw=%0d",which,perf_loads,read_count-starts_ar,write_count-starts_aw);
      if(which==2 && (perf_loads!=512 || perf_stores!=512)) $fatal(1,"COMMON_PERF_COPY_COUNT_ORACLE");
      if(which==3 && (fences!=1 || b_completed!=write_count || owners!=0 || write_owners!=0 || aw_count!=0 || w_count!=0 || b_count!=0))
        $fatal(1,"COMMON_PERF_REAL_COMPLETION_ORACLE b=%0d aw=%0d pending_b=%0d",b_completed,write_count,b_count);
      $display("COMMON_PERF_WINDOW phase=%0d begin_ps=%0d end_ps=%0t cpu_cycles=%0d retired=%0d fabric_cycles=%0d loads=%0d stores=%0d ar=%0d aw=%0d r=%0d w=%0d b=%0d ar_stall=%0d aw_stall=%0d r_stall=%0d w_stall=%0d b_stall=%0d read_start=%0d write_start=%0d read_end=%0d write_end=%0d max_reads=%0d max_writes=%0d read_owner_cycle_sum=%0d write_owner_cycle_sum=%0d overlap=%0d maintenance=%0d home_drained=%0d",
        which,start_ps,$time,cpu_edges-start_cpu,perf_retired,perf_fabric,perf_loads,perf_stores,
        read_count-starts_ar,write_count-starts_aw,read_beats-starts_r,write_beats-starts_w,b_completed-starts_b,
        ar_stalls-starts_ar_stall,aw_stalls-starts_aw_stall,r_stalls-starts_r_stall,w_stalls-starts_w_stall,b_stalls-starts_b_stall,
        starts_reads,starts_writes,owners,write_owners,perf_max_rd,perf_max_wr,perf_rd_sum,perf_wr_sum,
        overlap_cycles-starts_overlap,io_maintenancePending,io_homeDrained);
      window=-1;completed=completed+1;
    end
  endtask
  task observe_retire(input valid,input [63:0] pc,input [31:0] insn,input writesRd,input [4:0] rd,input [63:0] data);
    integer k,is_marker;
    begin
      if(valid===1) begin
        if(!io_bootEnable || pc<64'h80000000 || pc>=64'h80020000) $fatal(1,"COMMON_PERF_RETIRE_RANGE_ORACLE pc=%h",pc);
        retired=retired+1;rom_retired=rom_retired+1;
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
          fences=fences+1;
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
    @(negedge fabricClock);
    if(completed!=4 || b_completed!=write_count || b_completed!=64 || read_count!=192 || read_complete!=read_count ||
       io_maintenancePending!==0 || io_homeDrained!==1 || aw_count!=0 || w_count!=0 || b_count!=0 || owners!=0)
      $fatal(1,"COMMON_PERF_FINAL_COMPLETION_ORACLE phases=%0d ar=%0d aw=%0d b=%0d maintenance=%b home=%b",completed,read_count,write_count,b_completed,io_maintenancePending,io_homeDrained);
    for(final_i=0;final_i<512;final_i=final_i+1) begin
      expected=64'h1234567800000000+final_i;
      if(memory_read(32'h20000+8*final_i)!==expected) $fatal(1,"COMMON_PERF_SOURCE_ORACLE index=%0d",final_i);
      if(bad_pattern && final_i==31) expected=expected^64'h1;
      if(memory_read(32'h30000+8*final_i)!==expected)
        $fatal(1,"COMMON_PERF_FINAL_PATTERN_ORACLE index=%0d got=%h expected=%h",final_i,memory_read(32'h30000+8*final_i),expected);
    end
    $display("COMMON_PERF_TOTAL cpu_cycles=%0d retired=%0d fabric_edges=%0d ar=%0d aw=%0d r=%0d w=%0d b=%0d read_complete=%0d final_words=512",cpu_edges,retired,fabric_edges,read_count,write_count,read_beats,write_beats,b_completed,read_complete);
    $display("COMMON_CPU_PERF_NATIVE_PASS");$finish;
  end
