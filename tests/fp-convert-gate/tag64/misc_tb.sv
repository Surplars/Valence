`timescale 1ns/1ps
module misc_tb;
 reg clk=0,reset=1,valid=0,resultReady=0,flush=0,d=0;always #5 clk=~clk;
 reg [63:0] bits=0,bitsB=0,integerIn=0;reg [31:0] inst=0;reg [2:0] rm=0;reg [63:0] token=0;
 wire ready,rv,illegal,br,bv,bi;wire [63:0] value,bvalue;wire [4:0] flags,bflags;wire [67:0] owner,bowner;
 MiscHarness dut(.clock(clk),.reset(reset),.io_valid(valid),.io_ready(ready),.io_resultReady(resultReady),.io_resultValid(rv),.io_flush(flush),.io_bits(bits),.io_bitsB(bitsB),.io_integer(integerIn),.io_token(token),.io_owner(owner),.io_baseOwner(bowner),.io_double(d),.io_instruction(inst),.io_rm(rm),.io_value(value),.io_flags(flags),.io_illegal(illegal),.io_baseReady(br),.io_baseValid(bv),.io_baseValue(bvalue),.io_baseFlags(bflags),.io_baseIllegal(bi));
 reg [31:0] acceptedHigh=0;
 integer tests=0,retired=0,killedPrepared=0,killedResult=0,stalls=0,nonconvert=0,illegalCases=0,seq=1;real accepted=0,lastFast=-1;integer fastII=0;
 always @(negedge clk) if(!reset)begin
  #0.2;if({ready,rv}!=={br,bv})$fatal(1,"HANDSHAKE_MISMATCH");
  if(rv && {value,flags,illegal,owner}!=={bvalue,bflags,bi,bowner})$fatal(1,"MISC_BASELINE_MISMATCH");
 end
 task automatic transaction(input reg dd,input reg [31:0] ins,input reg [2:0] roundMode,input reg [63:0] a,input reg [63:0] b,input reg [63:0] intv,input reg oracle,input reg [63:0] expected,input reg [4:0] expectedFlags,input reg expectedIllegal,input integer mode);
  reg [67:0] expectedOwner;reg [63:0] held;reg [4:0] heldFlags;
  begin
   @(negedge clk);d=dd;bits=a;bitsB=b;integerIn=intv;inst=ins;rm=roundMode;token=64'h0000000000001235 | ((64'h1 << (32+(seq%32))));seq=seq+1;expectedOwner={token[3:0],token};valid=1;resultReady=1;flush=0;
   #0.3;if(!ready||!br)$fatal(1,"IDLE_NOT_READY");
   @(posedge clk);accepted=$realtime;acceptedHigh=acceptedHigh|token[63:32];
   if(mode==0 && lastFast>=0)begin if(accepted-lastFast!=30.0)$fatal(1,"II_NOT_3");fastII=fastII+1;end
   if(mode==0)lastFast=accepted;else lastFast=-1;
   #0.3;if(rv||ready)$fatal(1,"LATENCY_STAGE1_OR_BUSY");
   @(negedge clk);valid=0;bits=~a;token=token ^ 64'hffff000000000000;integerIn=~intv;
   if(mode==1)flush=1;
   if(mode==2)resultReady=0;
   @(posedge clk);#0.3;
   if(mode==1)begin
    if(rv)$fatal(1,"FLUSH_PREPARED_GHOST");killedPrepared=killedPrepared+1;
    @(negedge clk);flush=0;@(posedge clk);#0.3;if(rv)$fatal(1,"POST_FLUSH_GHOST");
   end else begin
    if(!rv||ready)$fatal(1,"LATENCY_STAGE2_OR_REFILL");
    if(owner!==expectedOwner||bowner!==expectedOwner)$fatal(1,"OWNER_CHANGED");
    if({value,flags,illegal}!=={bvalue,bflags,bi})$fatal(1,"BASELINE_VALUE_FLAGS");
    if(oracle && {value,flags,illegal}!=={expected,expectedFlags,expectedIllegal})$fatal(1,"MISC_ORACLE_MISMATCH inst=%h got=%h/%h/%b expected=%h/%h/%b",ins,value,flags,illegal,expected,expectedFlags,expectedIllegal);
    held=value;heldFlags=flags;
    if(mode==2)begin
     repeat(3)begin @(negedge clk);valid=1;@(posedge clk);#0.3;if(!rv||ready||value!==held||flags!==heldFlags||owner!==expectedOwner)$fatal(1,"BACKPRESSURE_UNSTABLE");stalls=stalls+1;end
     @(negedge clk);valid=0;resultReady=1;
    end
    if(mode==3)begin
     @(negedge clk);flush=1;resultReady=1;valid=1;#0.3;if(rv||ready)$fatal(1,"FLUSH_RESULT_HANDSHAKE");
     @(posedge clk);#0.3;killedResult=killedResult+1;
     @(negedge clk);flush=0;valid=0;@(posedge clk);#0.3;if(rv)$fatal(1,"FLUSH_RESULT_GHOST");
    end else begin @(posedge clk);#0.3;if(rv||!ready)$fatal(1,"RETIRE_NOT_IDLE");retired=retired+1;end
   end
   tests=tests+1;
  end
 endtask
 integer f,rc,row=0,di,si,mi,mode,fun,j,k,fmt;reg [63:0] vb,en,ew,a,b;reg [2:0] nf,wf;reg [31:0] instruction;reg [1023:0] path;
 function automatic [4:0] fpflags(input reg[2:0] x);fpflags={|x[2:1],3'b000,x[0]};endfunction
 initial begin
  repeat(3)@(posedge clk);@(negedge clk);reset=0;
  // Same index=5 and low tag=0x1235 throughout; every owner differs only
  // in high tag bits. Poison offered high bits after acceptance and while held.
  for(fmt=0;fmt<2;fmt=fmt+1)for(j=0;j<4;j=j+1)begin
   a=fmt?64'h3ff8000000000000:64'hffffffff3fc00000;
   instruction=32'hc0000053|(fmt<<25);
   transaction(fmt,instruction,0,a,0,0,1,2,1,0,j);
   transaction(fmt,instruction,0,a,0,0,1,2,1,0,0);
   transaction(fmt,instruction|(2<<20),0,a,0,0,1,2,1,0,0);
  end
  for(fmt=0;fmt<2;fmt=fmt+1)begin
   a=fmt?64'h41e0000000000000:64'hffffffff4f000000;
   transaction(fmt,32'hc0000053|(fmt<<25),0,a,0,0,1,64'h7fffffff,16,0,2);
   a=fmt?64'h7ff0000000000001:64'hffffffff7f800001;
   transaction(fmt,32'hc0000053|(fmt<<25)|(1<<20),0,a,0,0,1,64'hffffffffffffffff,16,0,0);
  end
  // All non-toInteger Misc groups, varied flags/rounding and same owner protocol.
  for(fmt=0;fmt<2;fmt=fmt+1)for(j=0;j<1;j=j+1)for(k=0;k<12;k=k+1)begin
   case(k)
    0:instruction=32'h20000053;
    1:instruction=32'h20001053;
    2:instruction=32'h20002053;
    3:instruction=32'h28000053;
    4:instruction=32'h28001053;
    5:instruction=32'ha0000053;
    6:instruction=32'ha0001053;
    7:instruction=32'ha0002053;
    8:instruction=32'he0001053;
    9:instruction=32'he0000053;
    10:instruction=32'hf0000053;
    11:instruction=32'hd0000053|((j%4)<<20)|(j<<12);
   endcase
   instruction=instruction|(fmt<<25);a=fmt?64'hbff8000000000000:64'hffffffffbfc00000;b=fmt?64'h7ff0000000000001:64'hffffffff7f800001;
   transaction(fmt,instruction,j,a,b,64'h80000000ffffffff,0,0,0,0,tests%4);nonconvert=nonconvert+1;
  end
  for(fmt=0;fmt<2;fmt=fmt+1)for(j=0;j<1;j=j+1)begin
   instruction=32'h40000053|(fmt<<25)|((!fmt)<<20)|(j<<12);
   transaction(fmt,instruction,j,fmt?64'hffffffff00000001:64'h0000000000000001,0,0,0,0,0,0,0);nonconvert=nonconvert+1;
  end
  for(fmt=0;fmt<2;fmt=fmt+1)for(j=5;j<8;j=j+1)begin
   transaction(fmt,32'hc0000053|(fmt<<25)|(j<<12),j,0,0,0,1,0,0,1,0);illegalCases=illegalCases+1;
  end
  if(acceptedHigh!==32'hffffffff)$fatal(1,"HIGH_TAG_COVERAGE");
  if(tests<50||killedPrepared<2||killedResult<2||stalls<6||nonconvert!=26||illegalCases!=6||fastII<2)$fatal(1,"COVERAGE");
  $display("PASS_ACTUAL_MISC_TAG64 index5_lowtag1235_highbits32to63 tests=%0d retired=%0d prepared_flush=%0d result_flush=%0d stall_cycles=%0d nonconvert=%0d illegal=%0d II3_checks=%0d latency2=1 same_cycle_refill=0",tests,retired,killedPrepared,killedResult,stalls,nonconvert,illegalCases,fastII);$finish;
 end
 initial begin #2000000;$fatal(1,"TIMEOUT");end
endmodule
