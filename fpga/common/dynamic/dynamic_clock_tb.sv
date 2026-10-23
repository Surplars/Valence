`timescale 1ns/1ps
`default_nettype none
module dynamic_clock_tb;
    reg aon=0,source=0,cold=1;
    always #10 aon=~aon;
    always #2 source=~source;
    reg [1:0] enable=0,isolated=3,valid=0,ready=3,fallback=0;
    reg [31:0] hz[0:1],token[0:1];
    wire [1:0] clk,present,closed,opened,locked,resumed,fatal,pready,rvalid,rerror;
    wire [31:0] rhz[0:1],rtoken[0:1];
    native_dynamic_clock_domain #(.DRP_TIMEOUT_CYCLES(32),.DRP_DRAIN_CYCLES(128)) cpu(
        .aon_clock(aon),.common_cold_reset(cold),.source_clock250(source),
        .clock_enable(enable[0]),.isolate(isolated[0]),.program_valid(valid[0]),.program_ready(pready[0]),
        .program_hz(hz[0]),.program_token(token[0]),.program_parameters(hz[0]==100000000 ? 24'h0a280a : 24'h14280a),.program_fallback(fallback[0]),
        .result_valid(rvalid[0]),.result_ready(ready[0]),.result_hz(rhz[0]),.result_token(rtoken[0]),
        .result_error(rerror[0]),.managed_clock(clk[0]),.present(present[0]),
        .gate_closed(closed[0]),.gate_open(opened[0]),.locked(locked[0]),.resumed(resumed[0]),.fatal(fatal[0]));
    native_dynamic_clock_domain #(.DRP_TIMEOUT_CYCLES(32),.DRP_DRAIN_CYCLES(128)) fabric(
        .aon_clock(aon),.common_cold_reset(cold),.source_clock250(source),
        .clock_enable(enable[1]),.isolate(isolated[1]),.program_valid(valid[1]),.program_ready(pready[1]),
        .program_hz(hz[1]),.program_token(token[1]),.program_parameters(hz[1]==100000000 ? 24'h0a280a : 24'h14280a),.program_fallback(fallback[1]),
        .result_valid(rvalid[1]),.result_ready(ready[1]),.result_hz(rhz[1]),.result_token(rtoken[1]),
        .result_error(rerror[1]),.managed_clock(clk[1]),.present(present[1]),
        .gate_closed(closed[1]),.gate_open(opened[1]),.locked(locked[1]),.resumed(resumed[1]),.fatal(fatal[1]));
    task check_drp(input [6:0] address,input write,input [15:0] data);
        begin
            case(address)
              7'h27: if(write && data!==16'hffff) $fatal(1,"DRP_POWER_MISMATCH");
              7'h08: if(write && data!==16'h128a && data!==16'h1145) $fatal(1,"DRP_OUTPUT_MISMATCH");
              7'h09,7'h15: if(write && data!==16'h8000) $fatal(1,"DRP_INTEGER_STATE_MISMATCH");
              7'h14: if(write && data!==16'h1514) $fatal(1,"DRP_FEEDBACK_MISMATCH");
              7'h16: if(write && data!==16'hc145) $fatal(1,"DRP_INPUT_MISMATCH");
              7'h18: if(write && data!==16'h00fa) $fatal(1,"DRP_LOCK1_MISMATCH");
              7'h19: if(write && data!==16'h7c01) $fatal(1,"DRP_LOCK2_MISMATCH");
              7'h1a: if(write && data!==16'h7fe9) $fatal(1,"DRP_LOCK3_MISMATCH");
              7'h4e: if(write && data!==16'h9800) $fatal(1,"DRP_FILTER1_MISMATCH");
              7'h4f: if(write && data!==16'h0890) $fatal(1,"DRP_FILTER2_MISMATCH");
              default: $fatal(1,"DRP_ADDRESS_NOT_ALLOWLISTED");
            endcase
        end
    endtask
    always @(posedge aon)begin
        if(cpu.den)check_drp(cpu.address,cpu.dwe,cpu.write_data);
        if(fabric.den)check_drp(fabric.address,fabric.dwe,fabric.write_data);
    end
    integer cpu_edges=0,fabric_edges=0,aon_edges=0,checks=0;
    integer retention0=0,retention1=0;
    realtime last_cpu=-1,last_fabric=-1;
    reg monitor=0;
    always @(posedge aon)aon_edges=aon_edges+1;
    always @(posedge clk[0])begin
        cpu_edges=cpu_edges+1;
        if(closed[0] && !cold)$fatal(1,"CPU_EDGE_AFTER_CLOSE_ACK");
    end
    always @(posedge clk[1])begin
        fabric_edges=fabric_edges+1;
        if(closed[1] && !cold)$fatal(1,"FABRIC_EDGE_AFTER_CLOSE_ACK");
    end
    always @(posedge clk[0] or posedge cold)if(cold)retention0<=0;else retention0<=retention0+1;
    always @(posedge clk[1] or posedge cold)if(cold)retention1<=0;else retention1<=retention1+1;
    always @(clk[0])begin
        if(monitor && last_cpu>=0 && $realtime-last_cpu<4.999)$fatal(1,"CPU_RUNT_PULSE");
        last_cpu=$realtime;
    end
    always @(clk[1])begin
        if(monitor && last_fabric>=0 && $realtime-last_fabric<4.999)$fatal(1,"FABRIC_RUNT_PULSE");
        last_fabric=$realtime;
    end
    task wait_locks;
        integer limit;
        begin
            limit=0;while(locked!==3 && limit<5000)begin @(negedge aon);limit=limit+1;end
            if(locked!==3)$fatal(1,"BOOT_OR_RELOCK_TIMEOUT locks=%b fatal=%b",locked,fatal);
        end
    endtask
    task close_domain(input integer d);
        integer limit;
        begin
            @(negedge aon);isolated[d]=1;enable[d]=0;
            // A command inversion must never produce the close ACK immediately.
            #1;if(closed[d])$fatal(1,"COMBINATIONAL_FAKE_CLOSE_ACK");
            limit=0;while(closed[d] !== 1'b1 && limit<100)begin @(negedge aon);limit=limit+1;end
            if(closed[d]!==1'b1)$fatal(1,"GATE_CLOSE_TIMEOUT");
        end
    endtask
    task open_domain(input integer d);
        integer limit;
        begin
            @(negedge aon);enable[d]=1;
            #1;if(opened[d] || resumed[d])$fatal(1,"STALE_OPEN_EDGE_WITNESS");
            limit=0;while(resumed[d] !== 1'b1 && limit<100)begin @(negedge aon);limit=limit+1;end
            if(opened[d] !== 1'b1 || resumed[d] !== 1'b1 || locked[d] !== 1'b1)$fatal(1,"OPEN_WITHOUT_EDGES_OR_LOCK");
            isolated[d]=0;
        end
    endtask
    task command(input integer d,input integer frequency,input integer id,input integer fb,input integer expect_error);
        integer limit;
        begin
            @(negedge aon);hz[d]=frequency;token[d]=id;fallback[d]=fb;valid[d]=1;
            limit=0;while(pready[d] !== 1'b1 && limit<300)begin @(negedge aon);limit=limit+1;end
            if(pready[d]!==1'b1)$fatal(1,"PROGRAM_READY_TIMEOUT");
            @(negedge aon);valid[d]=0;
            limit=0;while(rvalid[d] !== 1'b1 && limit<500)begin @(negedge aon);limit=limit+1;end
            if(rvalid[d]!==1'b1 || rhz[d]!==frequency || rtoken[d]!==id || rerror[d]!==expect_error[0])
                $fatal(1,"WRONG_PROGRAM_RESULT hz=%d token=%d error=%b",rhz[d],rtoken[d],rerror[d]);
            @(negedge aon);checks=checks+1;
        end
    endtask
    task rates(input integer c,input integer f);
        integer x,y,z;
        begin
            @(negedge aon);x=cpu_edges;y=fabric_edges;z=aon_edges;
            repeat(100)@(negedge aon);
            if(cpu_edges-x!=c || fabric_edges-y!=f || aon_edges-z!=100)
                $fatal(1,"CLOCK_RATE_OR_INDEPENDENCE cpu=%d fabric=%d aon=%d",cpu_edges-x,fabric_edges-y,aon_edges-z);
            checks=checks+1;
        end
    endtask
    integer kept,old_fabric,old_aon,old_transactions;
    always @(enable) begin
        if($test$plusargs("negative_fake_closed"))begin
            if(enable[0])force cpu.gate_closed=1'b0;else force cpu.gate_closed=1'b1;
        end
        if($test$plusargs("negative_fake_resumed"))begin
            if(enable[0])force cpu.resumed=1'b1;else force cpu.resumed=1'b0;
        end
    end
    initial begin
        hz[0]=0;hz[1]=0;token[0]=0;token[1]=0;
        #101;cold=0;wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
        old_fabric=fabric_edges;old_aon=aon_edges;
        close_domain(0);kept=retention0;command(0,100000000,1,0,0);
        if(retention0!=kept || fabric_edges<=old_fabric || aon_edges<=old_aon)$fatal(1,"OWNER_OR_FIXED_CLOCK_DISTURBED");
        wait_locks();open_domain(0);rates(200,100);
        close_domain(1);command(1,100000000,2,0,0);wait_locks();open_domain(1);rates(200,200);
        close_domain(0);command(0,50000000,3,1,0);wait_locks();open_domain(0);rates(100,200);
        close_domain(1);command(1,50000000,4,1,0);wait_locks();open_domain(1);rates(100,100);
        // Hz/parameter mismatch must not cause even one DRP access.
        close_domain(0);old_transactions=cpu.mmcm.transactions;
        command(0,55000000,5,0,1);
        if(cpu.mmcm.transactions!=old_transactions)$fatal(1,"MISMATCHED_RATE_PROGRAMMED");
        open_domain(0);
        // Readback mismatch: accepted operation completed; fallback is safe.
        close_domain(0);cpu.mmcm.corrupt_next_write=1;command(0,100000000,6,0,1);
        if(!cpu.program_reset || !closed[0])$fatal(1,"READBACK_FAILURE_NOT_ISOLATED");
        command(0,50000000,7,1,0);wait_locks();open_domain(0);rates(100,100);
        // A timeout response cannot allow the late DRDY to complete fallback.
        close_domain(0);cpu.mmcm.inject_delay=60;command(0,100000000,8,0,1);
        if(pready[0])$fatal(1,"LATE_DRP_NOT_QUARANTINED");
        command(0,50000000,9,1,0);wait_locks();open_domain(0);rates(100,100);
        // Cold reset after100 must explicitly restore O20, not trust RST.
        close_domain(0);command(0,100000000,10,0,0);wait_locks();open_domain(0);rates(200,100);
        monitor=0;@(negedge aon);cold=1;enable=0;isolated=3;repeat(5)@(negedge aon);
        cold=0;wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
        // Common reset during an already-issued DRP transfer must not erase
        // transport ownership or let stale DRDY complete the boot50 command.
        close_domain(0);cpu.mmcm.inject_delay=60;
        @(negedge aon);hz[0]=100000000;token[0]=19;fallback[0]=0;valid[0]=1;
        while(pready[0]!==1'b1)@(negedge aon);
        @(negedge aon);valid[0]=0;
        while(cpu.mmcm.pending!==1'b1)@(negedge aon);
        monitor=0;cold=1;enable=0;isolated=3;repeat(5)@(negedge aon);cold=0;
        wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
        // Result must remain stable under consumer backpressure, blocking reuse.
        close_domain(0);ready[0]=0;command(0,100000000,20,0,0);
        repeat(8)begin
            @(negedge aon);
            if(rvalid[0]!==1'b1 || rhz[0]!==32'd100000000 || rtoken[0]!==32'd20 ||
               rerror[0]!==1'b0 || pready[0]!==1'b0)$fatal(1,"RESULT_BACKPRESSURE_CORRUPTION");
        end
        ready[0]=1;@(negedge aon);wait_locks();open_domain(0);rates(200,100);
        // Completed DRP but no LOCKED must remain closed and permit explicit fallback.
        close_domain(0);cpu.mmcm.never_lock=1;command(0,50000000,21,0,0);
        repeat(40)@(negedge aon);
        if(locked[0]!==1'b0 || closed[0]!==1'b1 || resumed[0]!==1'b0 || fatal[0]!==1'b0)
            $fatal(1,"LOCK_FAILURE_WRONGLY_RESUMED");
        cpu.mmcm.never_lock=0;command(0,50000000,22,1,0);wait_locks();open_domain(0);rates(100,100);
        // A disable command alone does not excuse lock loss before close proof.
        @(negedge aon);enable[0]=0;isolated[0]=1;cpu.mmcm.never_lock=1;
        repeat(30)@(negedge aon);
        if(fatal[0]!==1'b1 || cold || fatal[1]!==1'b0)$fatal(1,"CLOSE_TAIL_UNLOCK_IGNORED");
        cpu.mmcm.never_lock=0;monitor=0;
        @(negedge aon);cold=1;enable=0;isolated=3;repeat(5)@(negedge aon);
        cold=0;wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
        // Unexpected live lock loss is not a cold reset and cannot reopen.
        cpu.mmcm.never_lock=1;repeat(30)@(negedge aon);
        if(fatal[0]!==1'b1 || resumed[0]!==1'b0 || cold || fatal[1]!==1'b0)
            $fatal(1,"UNEXPECTED_UNLOCK_NOT_ISOLATED");
        cpu.mmcm.never_lock=0;enable[0]=0;monitor=0;
        @(negedge aon);cold=1;enable=0;isolated=3;repeat(5)@(negedge aon);
        cold=0;wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
        if(cpu.mmcm.registers[7'h08]!==16'h128a || cpu.mmcm.registers[7'h09]!==16'h8000 ||
           cpu.mmcm.registers[7'h27]!==16'hffff)$fatal(1,"DRP_RESERVED_OR_POWER_BITS_CORRUPTED");
        // Permanent DRP loss is fatal. No cold reset, owner deletion or reopening.
        close_domain(0);kept=retention0;cpu.mmcm.never_ready=1;
        command(0,100000000,11,0,1);repeat(150)@(negedge aon);
        if(!fatal[0] || pready[0] || !closed[0] || opened[0] || retention0!=kept || cold)
            $fatal(1,"PERMANENT_DRP_FAILURE_NOT_FAIL_CLOSED");
        if(fatal[1] || !resumed[1])$fatal(1,"CPU_FAILURE_DISTURBED_FABRIC");
        $display("DYNAMIC_CLOCK_BEHAVIORAL_PASS checks=%0d cpu_edges=%0d fabric_edges=%0d aon_edges=%0d",checks,cpu_edges,fabric_edges,aon_edges);
        $finish;
    end
    initial begin #2000000;$fatal(1,"TEST_TIMEOUT");end
endmodule
`default_nettype wire
