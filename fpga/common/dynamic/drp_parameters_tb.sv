`timescale 1ns/1ps
`default_nettype none
// Independent register-image oracle. Golden characterization rows are obtained
// by compiling AMD's pinned C functions, not by calling the DUT's functions.
module drp_parameters_tb;
    reg aon=0,cold=1;
    always #10 aon=~aon;
    reg [1:0] valid=0,consume=3,fb=0;
    reg [31:0] hz[0:1],token[0:1];
    reg [23:0] params[0:1];
    wire [1:0] ready,rv,err,rst,fatal,den,dwe,busy,outstanding;
    wire [31:0] rhz[0:1],rtoken[0:1];
    wire [6:0] addr[0:1];wire [15:0] data[0:1];
    reg [15:0] dout[0:1];reg [1:0] drdy=0;
    reg [15:0] memory[0:1][0:127];
    reg [79:0] golden[32:64];
    reg [15:0] before_image[0:127];
    integer transactions[0:1],writes[0:1];
    integer corrupt_address=-1;
    genvar g;
    generate for(g=0;g<2;g=g+1)begin:lane
      native_clock_drp #(.MAX_PROGRAM_HZ(g==0 ? 300000000 : 250000000)) dut(
        .aon_clock(aon),.cold_reset(cold),.gate_closed(1'b1),.isolated(1'b1),.clock_enable(1'b0),
        .program_valid(valid[g]),.program_ready(ready[g]),.program_hz(hz[g]),.program_token(token[g]),
        .program_parameters(params[g]),.program_fallback(fb[g]),.result_valid(rv[g]),.result_ready(consume[g]),
        .result_hz(rhz[g]),.result_token(rtoken[g]),.result_error(err[g]),.mmcm_reset(rst[g]),.fatal(fatal[g]),
        .drp_address(addr[g]),.drp_data(data[g]),.drp_enable(den[g]),.drp_write(dwe[g]),
        .drp_read_data(dout[g]),.drp_ready(drdy[g]),.busy(busy[g]),.drp_outstanding(outstanding[g]));
      always @(posedge aon)begin
        drdy[g]<=0;
        if(den[g])begin
          if(!rst[g])$fatal(1,"DEN_WITHOUT_RESET");
          transactions[g]=transactions[g]+1;
          drdy[g]<=1;dout[g]<=memory[g][addr[g]];
          if(dwe[g])begin
            memory[g][addr[g]]<=data[g] ^ (addr[g]==corrupt_address ? 16'h0001 : 16'h0000);
            writes[g]=writes[g]+1;
          end
        end
      end
    end endgenerate
    function [15:0] reg1(input integer n);
      reg1=((n/2)%64)*64+(((n+1)/2)%64);
    endfunction
    function [15:0] expected(input integer a,input integer m,input integer o,input [15:0] old);
      begin
        case(a)
          'h27:expected='hffff;
          'h14:expected=(old & 'h1000)|reg1(m);
          'h15:expected=(old & 'h8000)|((m%2)*128);
          'h16:expected=(old & 'hc000)|'h0145;
          'h08:expected=(old & 'h1000)|reg1(o);
          'h09:expected=(old & 'h8000)|((o%2)*128);
          'h18:expected=(old & 'hfc00)|golden[m][47:32];
          'h19:expected=(old & 'h8000)|golden[m][31:16];
          'h1a:expected=(old & 'h8000)|golden[m][15:0];
          'h4e:expected=(old & 'h66ff)|golden[m][79:64];
          'h4f:expected=(old & 'h666f)|golden[m][63:48];
          default:expected=old;
        endcase
      end
    endfunction
    integer cases=0,n,a,start_tx,start_writes,saved_reset;
    task request(input integer lane_id,input [31:0] frequency,input [23:0] configuration,input integer fallback_mode,input integer reject,input integer corrupt);
      integer m,o;
      begin
        @(negedge aon);n=0;
        while(ready[lane_id]!==1'b1 && n<20)begin @(negedge aon);n=n+1;end
        if(ready[lane_id]!==1'b1)$fatal(1,"NOT_READY");
        start_tx=transactions[lane_id];start_writes=writes[lane_id];saved_reset=rst[lane_id];
        for(a=0;a<128;a=a+1)before_image[a]=memory[lane_id][a];
        hz[lane_id]=frequency;params[lane_id]=configuration;fb[lane_id]=fallback_mode;
        token[lane_id]=cases+100;consume[lane_id]=0;valid[lane_id]=1;
        @(negedge aon);valid[lane_id]=0;
        // Mutate live inputs immediately after acceptance: no torn tuple/token.
        hz[lane_id]=32'hffffffff;params[lane_id]=0;token[lane_id]=0;fb[lane_id]=0;
        n=0;while(rv[lane_id]!==1'b1 && n<1000)begin @(negedge aon);n=n+1;end
        if(rv[lane_id]!==1'b1 || err[lane_id]!==reject[0] || rhz[lane_id]!==frequency || rtoken[lane_id]!==cases+100 || fatal[lane_id])
          $fatal(1,"PARAMETER_RESULT frequency=%0d cfg=%h err=%b",frequency,configuration,err[lane_id]);
        repeat(4)begin
          @(negedge aon);
          if(!rv[lane_id] || ready[lane_id] || rhz[lane_id]!==frequency || rtoken[lane_id]!==cases+100)
            $fatal(1,"HELD_RESULT_OR_ATOMICITY");
        end
        if(reject && !corrupt)begin
          if(transactions[lane_id]!=start_tx || rst[lane_id]!==saved_reset[0])$fatal(1,"INVALID_TUPLE_TOUCHED_MMCM");
        end else if(!reject)begin
          m=fallback_mode ? 40 : configuration[15:8];o=fallback_mode ? 20 : configuration[23:16];
          if(writes[lane_id]-start_writes!=11 || transactions[lane_id]-start_tx!=33 || rst[lane_id])
            $fatal(1,"DRP_TRANSACTION_COUNT_OR_RESET");
          for(a=0;a<128;a=a+1)
            if(memory[lane_id][a]!==expected(a,m,o,before_image[a]))
              $fatal(1,"PROFILE_IMAGE_MISMATCH m=%0d o=%0d addr=%h got=%h expected=%h",m,o,a,memory[lane_id][a],expected(a,m,o,before_image[a]));
        end
        consume[lane_id]=1;@(negedge aon);cases=cases+1;
      end
    endtask
    reg [1023:0] path;
    integer i,j,m,o,mhz;
    initial begin
      if(!$value$plusargs("golden=%s",path))$fatal(1,"MISSING_INDEPENDENT_GOLDEN");
      $readmemh(path,golden);
      if($test$plusargs("negative_oracle_table"))golden[40][79:64]=golden[40][79:64]^16'h0100;
      for(i=0;i<2;i=i+1)begin
        hz[i]=0;token[i]=0;params[i]=0;dout[i]=0;transactions[i]=0;writes[i]=0;
        for(j=0;j<128;j=j+1)memory[i][j]=16'ha5a5^(j*137);
      end
      #31;cold=0;
      // Exercise every characterized M, including odd feedback counters.
      for(m=32;m<=62;m=m+1)request(0,1250000*m,{8'd20,m[7:0],8'd10},0,0,0);
      // Initial software grid, both lanes; all register images and tuple atomicity.
      for(mhz=50;mhz<=150;mhz=mhz+5)begin
        o=mhz<80 ? 20 : 10;m=mhz*o/25;
        request(0,mhz*1000000,{o[7:0],m[7:0],8'd10},0,0,0);
        request(1,mhz*1000000,{o[7:0],m[7:0],8'd10},0,0,0);
      end
      request(0,75000000,24'h0b210a,0,0,0); // Odd M33/O11.
      request(0,11718750,24'h803c0a,0,0,0); // O128 encodes 64/64 as zero/zero.
      request(0,10000000,24'h50200a,0,0,0);
      request(0,155000000,24'h0a3e0a,0,0,0);
      request(0,165000000,24'h05210a,0,0,0);
      request(0,300000000,24'h053c0a,0,0,0);
      request(1,250000000,24'h05320a,0,0,0);
      request(1,300000000,24'h053c0a,0,1,0);
      request(0,50000000,24'h142809,0,1,0); // D9.
      request(0,50000000,24'h141f0a,0,1,0); // M31.
      request(0,50000000,24'h14410a,0,1,0); // M65.
      request(0,98437500,24'h103f0a,0,1,0); // M63: characterization conflict.
      request(0,12500000,24'h80400a,0,1,0); // M64: characterization conflict.
      request(0,50000000,24'h00280a,0,1,0);
      request(0,50000000,24'h02280a,0,1,0);
      request(0,50000000,24'h81280a,0,1,0);
      request(0,9999999,24'h50200a,0,1,0);
      request(0,300000001,24'h053c0a,0,1,0);
      request(0,32'hffffffff,24'h80400a,0,1,0);
      request(0,55000000,24'h14280a,0,1,0); // Valid shape, wrong equality.
      request(0,50000001,24'h14280a,0,1,0);
      request(0,100000000,24'h0a280a,1,1,0); // Fallback must be50.
      // Partial new-M programming fails readback, retains reset; normal request
      // cannot bypass recovery. Safe fallback restores every changed field.
      corrupt_address='h4e;request(0,165000000,24'h05210a,0,1,1);
      corrupt_address=-1;
      request(0,100000000,24'h0a280a,0,1,0);
      request(0,50000000,24'hffffff,1,0,0);
      $display("DRP_PARAMETERS_PASS cases=%0d admitted_characterized_M=31 initial_points=21 lanes=2",cases);$finish;
    end
    initial begin #4000000;$fatal(1,"PARAMETERS_TIMEOUT");end
endmodule
`default_nettype wire
