`timescale 1ns/1ps
module misc_tb;
 reg clk=0,reset=1,valid=0,resultReady=0,flush=0,d=0;always #5 clk=~clk;
 reg [63:0] bits=0,bitsB=0,integerIn=0;reg [31:0] inst=0;reg [2:0] rm=0;reg [15:0] token=0;
 wire ready,rv,illegal,br,bv,bi;wire [63:0] value,bvalue;wire [4:0] flags,bflags;wire [19:0] owner,bowner;
 MiscHarness dut(.clock(clk),.reset(reset),.io_valid(valid),.io_ready(ready),.io_resultReady(resultReady),.io_resultValid(rv),.io_flush(flush),.io_bits(bits),.io_bitsB(bitsB),.io_integer(integerIn),.io_token(token),.io_owner(owner),.io_baseOwner(bowner),.io_double(d),.io_instruction(inst),.io_rm(rm),.io_value(value),.io_flags(flags),.io_illegal(illegal),.io_baseReady(br),.io_baseValid(bv),.io_baseValue(bvalue),.io_baseFlags(bflags),.io_baseIllegal(bi));
 integer tests=0,retired=0,killedPrepared=0,killedResult=0,stalls=0,nonconvert=0,illegalCases=0,seq=1;real accepted=0,lastFast=-1;integer fastII=0;
 always @(negedge clk) if(!reset)begin
  #0.2;if({ready,rv}!=={br,bv})$fatal(1,"HANDSHAKE_MISMATCH");
  if(rv && {value,flags,illegal,owner}!=={bvalue,bflags,bi,bowner})$fatal(1,"MISC_BASELINE_MISMATCH");
 end
 task automatic transaction(input reg dd,input reg [31:0] ins,input reg [2:0] roundMode,input reg [63:0] a,input reg [63:0] b,input reg [63:0] intv,input reg oracle,input reg [63:0] expected,input reg [4:0] expectedFlags,input reg expectedIllegal,input integer mode);
  reg [19:0] expectedOwner;reg [63:0] held;reg [4:0] heldFlags;
  begin
   @(negedge clk);d=dd;bits=a;bitsB=b;integerIn=intv;inst=ins;rm=roundMode;token=seq;seq=seq+1;expectedOwner={token[3:0],token};valid=1;resultReady=1;flush=0;
   #0.3;if(!ready||!br)$fatal(1,"IDLE_NOT_READY");
   @(posedge clk);accepted=$realtime;
   if(mode==0 && lastFast>=0)begin if(accepted-lastFast!=30.0)$fatal(1,"II_NOT_3");fastII=fastII+1;end
   if(mode==0)lastFast=accepted;else lastFast=-1;
   #0.3;if(rv||ready)$fatal(1,"LATENCY_STAGE1_OR_BUSY");
   @(negedge clk);valid=0;bits=~a;token=token+99;integerIn=~intv;
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
  if(!$value$plusargs("vectors=%s",path))$fatal(1,"VECTORS");f=$fopen(path,"r");if(!f)$fatal(1,"OPEN");
  while(!$feof(f))begin
   rc=$fscanf(f,"%d %d %d %h %h %h %h %h\n",di,si,mi,vb,en,nf,ew,wf);if(rc!=8)$fatal(1,"FORMAT");
   if(row%53==0)begin
    mode=(tests%17==1)?1:(tests%19==2)?2:(tests%23==3)?3:0;
    a=di?vb:{32'hffffffff,vb[31:0]};instruction=32'hc0000053|(di<<25)|((!si)<<20)|(mi<<12);
    transaction(di,instruction,mi,a,0,0,1,en,fpflags(nf),0,mode);
    transaction(di,instruction|(2<<20),mi,a,0,0,1,ew,fpflags(wf),0,0);
   end
   row=row+1;
  end
  // All non-toInteger Misc groups, varied flags/rounding and same owner protocol.
  for(fmt=0;fmt<2;fmt=fmt+1)for(j=0;j<5;j=j+1)for(k=0;k<12;k=k+1)begin
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
  for(fmt=0;fmt<2;fmt=fmt+1)for(j=0;j<5;j=j+1)begin
   instruction=32'h40000053|(fmt<<25)|((!fmt)<<20)|(j<<12);
   transaction(fmt,instruction,j,fmt?64'hffffffff00000001:64'h0000000000000001,0,0,0,0,0,0,0);nonconvert=nonconvert+1;
  end
  for(fmt=0;fmt<2;fmt=fmt+1)for(j=5;j<8;j=j+1)begin
   transaction(fmt,32'hc0000053|(fmt<<25)|(j<<12),j,0,0,0,1,0,0,1,0);illegalCases=illegalCases+1;
  end
  if(tests<4500||killedPrepared<10||killedResult<10||stalls<10||nonconvert!=130||illegalCases!=6||fastII<500)$fatal(1,"COVERAGE");
  $display("PASS_ACTUAL_MISC tests=%0d retired=%0d prepared_flush=%0d result_flush=%0d stall_cycles=%0d nonconvert=%0d illegal=%0d II3_checks=%0d latency2=1 same_cycle_refill=0",tests,retired,killedPrepared,killedResult,stalls,nonconvert,illegalCases,fastII);$finish;
 end
 initial begin #2000000;$fatal(1,"TIMEOUT");end
endmodule
