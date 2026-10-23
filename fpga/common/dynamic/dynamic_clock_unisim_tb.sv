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
    // Focused board target mode uses literal register images, independently
    // checked against the pinned AMD LOW table and integer counter equations.
    reg board_mode=0;
    reg [1:0] audit_enable=0, audit_pending=0;
    integer audit_step[0:1],audit_completed[0:1],pending_step[0:1];
    reg [23:0] audit_parameters[0:1];
    reg [15:0] audit_original[0:1],audit_written[0:1];
    function automatic [6:0] audit_address(input integer i);
        case(i)
          0:audit_address=7'h27;1:audit_address=7'h14;2:audit_address=7'h15;
          3:audit_address=7'h16;4:audit_address=7'h08;5:audit_address=7'h09;
          6:audit_address=7'h18;7:audit_address=7'h19;8:audit_address=7'h1a;
          9:audit_address=7'h4e;10:audit_address=7'h4f;
          default:audit_address=7'h7f;
        endcase
    endfunction
    function automatic [15:0] audit_mask(input integer i);
        case(i)
          0:audit_mask=16'h0000;1,4:audit_mask=16'h1000;3:audit_mask=16'hc000;
          6:audit_mask=16'hfc00;9:audit_mask=16'h66ff;10:audit_mask=16'h666f;
          default:audit_mask=16'h8000;
        endcase
    endfunction
    function automatic [15:0] audit_image(input [23:0] cfg,input integer i);
        begin
            case(i)
              0:audit_image=16'hffff;
              1:audit_image=cfg==24'h05270a ? 16'h04d4 : cfg==24'h0a3e0a ? 16'h07df : 16'h0514;
              2:audit_image=cfg==24'h05270a ? 16'h0080 : 16'h0000;
              3:audit_image=16'h0145;
              4:audit_image=cfg==24'h05270a ? 16'h0083 : cfg==24'h0a3e0a ? 16'h0145 : 16'h028a;
              5:audit_image=cfg==24'h05270a ? 16'h0080 : 16'h0000;
              6:audit_image=16'h00fa;7:audit_image=16'h7c01;8:audit_image=16'h7fe9;
              9:audit_image=cfg==24'h0a3e0a ? 16'h9900 : 16'h9800;
              10:audit_image=16'h0890;
              default:audit_image=16'hxxxx;
            endcase
            if($test$plusargs("bad_board_image") && i==1)audit_image=audit_image ^ 16'h0001;
        end
    endfunction
    generate for(k=0;k<2;k=k+1)begin:board_audit
        integer word_index,kind;
        reg [15:0] expected_word;
        always @(posedge aon)if(audit_enable[k])begin
            if(domain[k].dut.den)begin
                if(audit_pending[k] || audit_step[k]>=33)$fatal(1,"BOARD_DRP_EXTRA_OR_OVERLAPPING_TRANSACTION");
                word_index=audit_step[k]/3;kind=audit_step[k]%3;
                if(domain[k].dut.address!==audit_address(word_index) || domain[k].dut.dwe!==(kind==1))
                    $fatal(1,"BOARD_DRP_ADDRESS_OR_ORDER lane=%0d step=%0d",k,audit_step[k]);
                if(kind==1)begin
                    expected_word=(audit_original[k] & audit_mask(word_index)) | audit_image(audit_parameters[k],word_index);
                    if(domain[k].dut.write_data!==expected_word)$fatal(1,"BOARD_DRP_WRITE_IMAGE lane=%0d word=%0d actual=%h expected=%h",k,word_index,domain[k].dut.write_data,expected_word);
                    audit_written[k]=expected_word;
                end
                pending_step[k]=audit_step[k];audit_step[k]=audit_step[k]+1;audit_pending[k]=1;
            end
            if(domain[k].dut.drdy)begin
                if(!audit_pending[k])$fatal(1,"BOARD_DRP_UNOWNED_RESPONSE");
                if(pending_step[k]%3==0)audit_original[k]=domain[k].dut.read_data;
                if(pending_step[k]%3==2 && domain[k].dut.read_data!==audit_written[k])
                    $fatal(1,"BOARD_DRP_READBACK_IMAGE lane=%0d word=%0d",k,pending_step[k]/3);
                audit_completed[k]=audit_completed[k]+1;audit_pending[k]=0;
            end
        end
    end endgenerate
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
            if(board_mode)begin
                if(configuration!=24'h05270a && configuration!=24'h0a3e0a && configuration!=24'h14280a)
                    $fatal(1,"BOARD_PROFILE_NOT_IN_FOCUSED_ORACLE");
                audit_parameters[d]=configuration;audit_step[d]=0;audit_completed[d]=0;
                audit_pending[d]=0;audit_enable[d]=1;
            end
            $display("NATIVE_PROFILE_START t=%0t lane=%0d hz=%0d token=%0d D=%0d M=%0d O=%0d fallback=%0d expected_reject=%0d",$time,d,frequency,id,configuration[7:0],configuration[15:8],configuration[23:16],fallback_mode,reject);
            n=0;while(pready[d]!==1'b1 && n<500)begin @(negedge aon);n=n+1;end
            if(pready[d]!==1'b1)$fatal(1,"UNISIM_NO_PROGRAM_READY");
            @(negedge aon);valid[d]=0;
            n=0;while(rvalid[d]!==1'b1 && n<5000)begin @(negedge aon);n=n+1;end
            if(rvalid[d]!==1'b1 || rhz[d]!==frequency || rtoken[d]!==id || rerror[d]!==reject[0])
                $fatal(1,"UNISIM_DRP_RESULT_FAILED");
            if(reject && transactions[d]!=previous_transactions)$fatal(1,"UNISIM_REJECT_TOUCHED_DRP");
            if(board_mode)begin
                if(audit_step[d]!=33 || audit_completed[d]!=33 || audit_pending[d])
                    $fatal(1,"BOARD_DRP_INCOMPLETE_READBACK");
                audit_enable[d]=0;
                $display("BOARD_DRP_VERIFIED lane=%0d token=%0d words=11 commands=33 completions=33",d,id);
            end
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
        board_mode=$test$plusargs("board195155");
        #1001;cold=0;wait_locks();open_domain(0);open_domain(1);monitor=1;rates(100,100);
        if(board_mode)begin
            // Exact firmware tuples. Normal software return50, not fallback mode.
            switch_profile(0,195000000,195,24'h05270a,0,0);
            rates($test$plusargs("bad_board_rate") ? 400 : 390,100);
            switch_profile(1,155000000,155,24'h0a3e0a,0,0);rates(390,310);
            switch_profile(1,50000000,501,24'h14280a,0,0);rates(390,100);
            switch_profile(0,50000000,502,24'h14280a,0,0);rates(100,100);
`ifdef VALENCE_USE_UNISIM
            $display("DYNAMIC_BOARD_195_155_UNISIM_PASS checks=%0d exact_words=44 drp_commands=132 VENDOR_PRIMITIVES=1 SOC=0 STA=0 BOARD=0",checks);
`else
            $display("DYNAMIC_BOARD_195_155_MODEL_SMOKE_PASS checks=%0d VENDOR_PRIMITIVES=0",checks);
`endif
            $finish;
        end
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
