`timescale 1ns/1ps
`default_nettype none
// Vendor-library test only. Must NOT compile behavioral_primitives.sv here.
module dynamic_clock_unisim_tb;
    reg aon=0,source=0,cold=1;
    always #10 aon=~aon;
    always #2 source=~source;
    reg [1:0] enable=0,isolated=3,valid=0,fallback=0;
    reg [31:0] hz[0:1],token[0:1];
    wire [1:0] clk,present,closed,opened,locked,resumed,fatal,pready,rvalid,rerror;
    wire [31:0] rhz[0:1],rtoken[0:1];
    genvar k;
    generate for(k=0;k<2;k=k+1)begin:domain
        native_dynamic_clock_domain dut(
            .aon_clock(aon),.common_cold_reset(cold),.source_clock250(source),
            .clock_enable(enable[k]),.isolate(isolated[k]),.program_valid(valid[k]),.program_ready(pready[k]),
            .program_hz(hz[k]),.program_token(token[k]),.program_fallback(fallback[k]),
            .result_valid(rvalid[k]),.result_ready(1'b1),.result_hz(rhz[k]),.result_token(rtoken[k]),
            .result_error(rerror[k]),.managed_clock(clk[k]),.present(present[k]),
            .gate_closed(closed[k]),.gate_open(opened[k]),.locked(locked[k]),.resumed(resumed[k]),.fatal(fatal[k]));
    end endgenerate
    integer edges0=0,edges1=0,aon_edges=0,checks=0;
    realtime last0=-1,last1=-1;
    reg monitor=0;
    always @(posedge aon)aon_edges=aon_edges+1;
    always @(posedge clk[0])begin edges0=edges0+1;if(closed[0] && !cold)$fatal(1,"UNISIM_CPU_EDGE_AFTER_ACK");end
    always @(posedge clk[1])begin edges1=edges1+1;if(closed[1] && !cold)$fatal(1,"UNISIM_FABRIC_EDGE_AFTER_ACK");end
    always @(clk[0])begin
        if(monitor && last0>=0 && $realtime-last0<4.9)$fatal(1,"UNISIM_CPU_RUNT");last0=$realtime;
    end
    always @(clk[1])begin
        if(monitor && last1>=0 && $realtime-last1<4.9)$fatal(1,"UNISIM_FABRIC_RUNT");last1=$realtime;
    end
    task wait_locks;
        integer n;
        begin
            n=0;while(locked!==2'b11 && n<25000)begin @(negedge aon);n=n+1;end
            if(locked!==2'b11 || fatal!==2'b00)$fatal(1,"UNISIM_LOCK_FAILED");
        end
    endtask
    task open_domain(input integer d);
        integer n;
        begin
            @(negedge aon);enable[d]=1;#1;
            if(opened[d]!==1'b0 || resumed[d]!==1'b0)$fatal(1,"UNISIM_STALE_OPEN");
            n=0;while(resumed[d]!==1'b1 && n<500)begin @(negedge aon);n=n+1;end
            if(resumed[d]!==1'b1 || locked[d]!==1'b1)$fatal(1,"UNISIM_NO_RESUME");
            isolated[d]=0;
        end
    endtask
    task switch_rate(input integer d,input integer frequency,input integer id);
        integer n;
        begin
            @(negedge aon);enable[d]=0;isolated[d]=1;#1;
            if(closed[d]!==1'b0)$fatal(1,"UNISIM_FAKE_CLOSE");
            n=0;while(closed[d]!==1'b1 && n<500)begin @(negedge aon);n=n+1;end
            if(closed[d]!==1'b1)$fatal(1,"UNISIM_NO_CLOSE");
            hz[d]=frequency;token[d]=id;fallback[d]=frequency==50000000;valid[d]=1;
            n=0;while(pready[d]!==1'b1 && n<500)begin @(negedge aon);n=n+1;end
            if(pready[d]!==1'b1)$fatal(1,"UNISIM_NO_PROGRAM_READY");
            @(negedge aon);valid[d]=0;
            n=0;while(rvalid[d]!==1'b1 && n<5000)begin @(negedge aon);n=n+1;end
            if(rvalid[d]!==1'b1 || rhz[d]!==frequency || rtoken[d]!==id || rerror[d]!==1'b0)
                $fatal(1,"UNISIM_DRP_RESULT_FAILED");
            @(negedge aon);wait_locks();open_domain(d);checks=checks+1;
        end
    endtask
    task rates(input integer c,input integer f);
        integer x,y,z;
        begin
            @(negedge aon);x=edges0;y=edges1;z=aon_edges;repeat(100)@(negedge aon);
            // One edge tolerance only for measurement-window boundary phase.
            if(edges0-x<c-1 || edges0-x>c+1 || edges1-y<f-1 || edges1-y>f+1 || aon_edges-z!=100)
                $fatal(1,"UNISIM_FREQUENCY_OR_INDEPENDENCE cpu=%0d fabric=%0d",edges0-x,edges1-y);
            checks=checks+1;
        end
    endtask
    initial begin
        hz[0]=0;hz[1]=0;token[0]=0;token[1]=0;
        #1001;cold=0;wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
        switch_rate(0,100000000,1);rates(200,100);
        switch_rate(1,100000000,2);rates(200,200);
        switch_rate(0,50000000,3);rates(100,200);
        switch_rate(1,50000000,4);rates(100,100);
        switch_rate(0,100000000,5);rates(200,100);
        monitor=0;@(negedge aon);cold=1;enable=0;isolated=3;repeat(10)@(negedge aon);
        cold=0;wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
`ifdef VALENCE_USE_UNISIM
        $display("DYNAMIC_CLOCK_UNISIM_PASS checks=%0d VENDOR_PRIMITIVES=1 SOC=0 STA=0 BOARD=0",checks);
`else
        $display("DYNAMIC_CLOCK_VENDOR_TB_MODEL_SMOKE_PASS checks=%0d VENDOR_PRIMITIVES=0",checks);
`endif
        $finish;
    end
    initial begin #2000000;$fatal(1,"UNISIM_TEST_TIMEOUT");end
endmodule
`default_nettype wire
