`timescale 1ns/1ps
`default_nettype none
// Vendor-library test only. Must NOT compile behavioral_primitives.sv here.
module dynamic_clock_unisim_tb;
    reg aon=0,source=0,cold=1;
    always #10 aon=~aon;
    always #2 source=~source;
    reg [1:0] enable=0,isolated=3,valid=0,fallback=0;
    reg [31:0] hz[0:1],token[0:1];
    reg [23:0] parameters[0:1];
    wire [1:0] clk,present,closed,opened,locked,resumed,fatal,pready,rvalid,rerror;
    wire [31:0] rhz[0:1],rtoken[0:1];
    genvar k;
    generate for(k=0;k<2;k=k+1)begin:domain
        native_dynamic_clock_domain #(.MAX_PROGRAM_HZ(k==0 ? 300000000 : 250000000)) dut(
            .aon_clock(aon),.common_cold_reset(cold),.source_clock250(source),
            .clock_enable(enable[k]),.isolate(isolated[k]),.program_valid(valid[k]),.program_ready(pready[k]),
            .program_hz(hz[k]),.program_token(token[k]),.program_parameters(parameters[k]),.program_fallback(fallback[k]),
            .result_valid(rvalid[k]),.result_ready(1'b1),.result_hz(rhz[k]),.result_token(rtoken[k]),
            .result_error(rerror[k]),.managed_clock(clk[k]),.present(present[k]),
            .gate_closed(closed[k]),.gate_open(opened[k]),.locked(locked[k]),.resumed(resumed[k]),.fatal(fatal[k]));
    end endgenerate
    integer edges0=0,edges1=0,aon_edges=0,checks=0;
    integer transactions[0:1];
    always @(posedge aon)begin
      if(domain[0].dut.den)transactions[0]=transactions[0]+1;
      if(domain[1].dut.den)transactions[1]=transactions[1]+1;
    end
    realtime last0=-1,last1=-1;
    reg monitor=0;
    always @(posedge aon)aon_edges=aon_edges+1;
    always @(posedge clk[0])begin edges0=edges0+1;if(closed[0] && !cold)$fatal(1,"UNISIM_CPU_EDGE_AFTER_ACK");end
    always @(posedge clk[1])begin edges1=edges1+1;if(closed[1] && !cold)$fatal(1,"UNISIM_FABRIC_EDGE_AFTER_ACK");end
    always @(clk[0])begin
        if(monitor && last0>=0 && $realtime-last0<1.55)$fatal(1,"UNISIM_CPU_RUNT");last0=$realtime;
    end
    always @(clk[1])begin
        if(monitor && last1>=0 && $realtime-last1<1.55)$fatal(1,"UNISIM_FABRIC_RUNT");last1=$realtime;
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
    task switch_profile(input integer d,input integer frequency,input integer id,input [23:0] configuration,input integer fallback_mode,input integer reject);
        integer n,previous_transactions;
        begin
            @(negedge aon);enable[d]=0;isolated[d]=1;#1;
            if(closed[d]!==1'b0)$fatal(1,"UNISIM_FAKE_CLOSE");
            n=0;while(closed[d]!==1'b1 && n<500)begin @(negedge aon);n=n+1;end
            if(closed[d]!==1'b1)$fatal(1,"UNISIM_NO_CLOSE");
            parameters[d]=configuration;
            hz[d]=frequency;token[d]=id;fallback[d]=fallback_mode;valid[d]=1;
            previous_transactions=transactions[d];
            $display("NATIVE_PROFILE_START t=%0t lane=%0d hz=%0d token=%0d D=%0d M=%0d O=%0d fallback=%0d expected_reject=%0d",$time,d,frequency,id,configuration[7:0],configuration[15:8],configuration[23:16],fallback_mode,reject);
            n=0;while(pready[d]!==1'b1 && n<500)begin @(negedge aon);n=n+1;end
            if(pready[d]!==1'b1)$fatal(1,"UNISIM_NO_PROGRAM_READY");
            @(negedge aon);valid[d]=0;
            n=0;while(rvalid[d]!==1'b1 && n<5000)begin @(negedge aon);n=n+1;end
            if(rvalid[d]!==1'b1 || rhz[d]!==frequency || rtoken[d]!==id || rerror[d]!==reject[0])
                $fatal(1,"UNISIM_DRP_RESULT_FAILED");
            if(reject && transactions[d]!=previous_transactions)$fatal(1,"UNISIM_REJECT_TOUCHED_DRP");
            @(negedge aon);wait_locks();open_domain(d);checks=checks+1;
            $display("NATIVE_PROFILE_DONE t=%0t lane=%0d token=%0d",$time,d,id);
        end
    endtask
    task switch_rate(input integer d,input integer frequency,input integer id);
        integer m,o;
        begin
            o=frequency<80000000 ? 20 : frequency<160000000 ? 10 : 5;
            m=frequency/1000000*o/25;
            switch_profile(d,frequency,id,{o[7:0],m[7:0],8'd10},frequency==50000000,0);
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
    integer mhz;
    initial begin
        parameters[0]=0;parameters[1]=0;transactions[0]=0;transactions[1]=0;
        hz[0]=0;hz[1]=0;token[0]=0;token[1]=0;
        #1001;cold=0;wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
        switch_rate(0,100000000,1);rates(200,100);
        switch_rate(1,100000000,2);rates(200,200);
        switch_rate(0,50000000,3);rates(100,200);
        switch_rate(1,50000000,4);rates(100,100);
        // Every initial software point, each lane independently, roundtrip50.
        for(mhz=50;mhz<=150;mhz=mhz+5)begin
            switch_rate(0,mhz*1000000,100+mhz);rates(mhz*2,100);
            switch_rate(0,50000000,300+mhz);rates(100,100);
            switch_rate(1,mhz*1000000,500+mhz);rates(100,mhz*2);
            switch_rate(1,50000000,700+mhz);rates(100,100);
        end
        switch_profile(0,75000000,901,24'h0b210a,0,0);rates(150,100); // Odd M/O.
        switch_profile(0,11718750,902,24'h803c0a,0,0);rates(23,100); // Counter64 encoding.
        switch_profile(0,98437500,911,24'h103f0a,0,1);rates(23,100); // M63 excluded.
        switch_profile(0,12500000,912,24'h80400a,0,1);rates(23,100); // M64 excluded.
        switch_rate(0,300000000,903);rates(600,100);
        switch_rate(1,250000000,904);rates(600,500);
        switch_profile(1,300000000,905,24'h053c0a,0,1);rates(600,500); // Fabric cap.
        switch_profile(0,55000000,906,24'h14280a,0,1);rates(600,500); // Hz mismatch.
        switch_profile(0,50000000,907,24'h142809,0,1);rates(600,500); // Bad D.
        switch_profile(0,32'hffffffff,908,24'h80400a,0,1);rates(600,500); // Overflow attempt.
        switch_profile(0,50000000,909,24'hffffff,1,0);rates(100,500); // Autonomous fallback.
        switch_profile(1,50000000,910,24'hffffff,1,0);rates(100,100);
        switch_rate(0,150000000,5);rates(300,100);
        monitor=0;@(negedge aon);cold=1;enable=0;isolated=3;repeat(10)@(negedge aon);
        cold=0;wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
`ifdef VALENCE_USE_UNISIM
        $display("DYNAMIC_CLOCK_UNISIM_PASS checks=%0d VENDOR_PRIMITIVES=1 SOC=0 STA=0 BOARD=0",checks);
`else
        $display("DYNAMIC_CLOCK_VENDOR_TB_MODEL_SMOKE_PASS checks=%0d VENDOR_PRIMITIVES=0",checks);
`endif
        $finish;
    end
    initial begin #50000000;$fatal(1,"UNISIM_TEST_TIMEOUT");end
endmodule
`default_nettype wire
