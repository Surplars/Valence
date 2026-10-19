  // Read-only bounded diagnostic of the exact unchanged A1 failure. No force.
  `define PR dut.fabric.crossbar.routers_0
  `define PA dut.fabric.crossbar.arbiters_0
  integer diag_lines=0,diag_retire=0;
  always @(negedge fabricClock) begin
    #1;
    if(io_bootEnable && diag_lines<250 && (`PR.io_host_a_valid || `PR.io_host_d_valid ||
       `PR.io_banks_0_d_valid || `PR.io_banks_1_d_valid || `PA.io_manager_a_valid || `PA.io_manager_d_valid)) begin
      diag_lines=diag_lines+1;
      $display("PERF_DIAG t=%0t next_edge=%0t rst=%b links=%b%b A=%b%b addr=%h src=%h size=%h hit=%b D=%b%b src=%h b0=%b%b src0=%h b1=%b%b src1=%h occ=%h owners=%h chosen=%b last=%b dBurst=%b dRemain=%d romA=%b%b addr=%h src=%h romD=%b%b src=%h axiAR=%b%b axiR=%b%b rid=%h rlast=%b",
        $time,$time+1999,`PR.reset,io_cpuLinkReady,io_fabricLinkReady,
        `PR.io_host_a_valid,`PR.io_host_a_ready,`PR.io_host_a_bits_address,`PR.io_host_a_bits_source,`PR.io_host_a_bits_size,`PR._hit_decoder_io_hitMask,
        `PR.io_host_d_valid,`PR.io_host_d_ready,`PR.io_host_d_bits_source,
        `PR.io_banks_0_d_valid,`PR.io_banks_0_d_ready,`PR.io_banks_0_d_bits_source,
        `PR.io_banks_1_d_valid,`PR.io_banks_1_d_ready,`PR.io_banks_1_d_bits_source,
        `PR._GEN_17,`PR._GEN_18,`PR._replies_io_chosen,`PR.replies.ctrl_validMask_grantMask_lastGrant,`PR.dBurst,`PR.dRemaining,
        `PA.io_manager_a_valid,`PA.io_manager_a_ready,`PA.io_manager_a_bits_address,`PA.io_manager_a_bits_source,
        `PA.io_manager_d_valid,`PA.io_manager_d_ready,`PA.io_manager_d_bits_source,
        io_ddrAxi_ar_valid,io_ddrAxi_ar_ready,io_ddrAxi_r_valid,io_ddrAxi_r_ready,io_ddrAxi_r_bits_id,io_ddrAxi_r_bits_last);
    end
  end
  always @(negedge cpuClock) begin
    if(io_bootEnable && diag_retire<60) begin
      if(io_retire_0_valid) begin diag_retire=diag_retire+1;$display("PERF_DIAG_RETIRE t=%0t lane=0 pc=%h insn=%h rd=%d data=%h",$time,io_retire_0_bits_pc,io_retire_0_bits_instruction,io_retire_0_bits_rd,io_retire_0_bits_data);end
      if(io_retire_1_valid) begin diag_retire=diag_retire+1;$display("PERF_DIAG_RETIRE t=%0t lane=1 pc=%h insn=%h rd=%d data=%h",$time,io_retire_1_bits_pc,io_retire_1_bits_instruction,io_retire_1_bits_rd,io_retire_1_bits_data);end
    end
  end
  initial begin #132100000; $fatal(1,"PERF_DIAG_SIM_TIME_BOUND"); end
  `undef PR
  `undef PA
