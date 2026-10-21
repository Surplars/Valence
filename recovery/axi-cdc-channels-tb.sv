`timescale 1ns/1ps
// Independent edge-driven channel oracle. Synthetic payloads test transport,
// not memory ordering, legal transaction generation, physical CDC or drain ACKs.
module axi_cdc_channels_tb;
reg fabricClock=0, ddrClock=0, commonColdReset=1;
reg [4:0] inValid=0, outReady=0;
wire [4:0] inReady,outValid;
reg [63:0] inData[0:4]; reg [15:0] inMeta[0:4];
wire [63:0] outData[0:4]; wire [15:0] outMeta[0:4];
wire [1:0] empty,link;
Axi4CdcFixture dut(.fabricClock(fabricClock),.ddrClock(ddrClock),.commonColdReset(commonColdReset),
 .inValid(inValid),.inReady(inReady),.outValid(outValid),.outReady(outReady),.empty(empty),.link(link),
 .inData_0(inData[0]),.inMeta_0(inMeta[0]),.outData_0(outData[0]),.outMeta_0(outMeta[0]),
 .inData_1(inData[1]),.inMeta_1(inMeta[1]),.outData_1(outData[1]),.outMeta_1(outMeta[1]),
 .inData_2(inData[2]),.inMeta_2(inMeta[2]),.outData_2(outData[2]),.outMeta_2(outMeta[2]),
 .inData_3(inData[3]),.inMeta_3(inMeta[3]),.outData_3(outData[3]),.outMeta_3(outMeta[3]),
 .inData_4(inData[4]),.inMeta_4(inMeta[4]),.outData_4(outData[4]),.outMeta_4(outMeta[4]));
reg [79:0] expected[0:4][0:2047];
reg [79:0] held[0:4], actual, value;
reg [4:0] stalled=0;
integer sent[0:4],received[0:4],width[0:4];
integer t,n,phase,stalls=0,blocked=0,abandoned=0,stopped=0;
reg nf,nd,riseF,riseD,srcEdge,dstEdge,allDone,bad,injected=0;
reg [63:0] randomState=64'h729abd8e13465fed;
function automatic [63:0] scramble(input [63:0] x);
 reg [63:0] y;
 begin y=x^(x<<13); y=y^(y>>7); scramble=y^(y<<17); end
endfunction
task clearEpoch;
 begin
  inValid=0; outReady=0; stalled=0;
  for(integer j=0;j<5;j=j+1) begin
   sent[j]=0;received[j]=0;offerIndex[j]=0;inData[j]=0;inMeta[j]=0;
  end
 end
endtask
initial begin
 bad=$test$plusargs("BAD_ORACLE");
 width[0]=61;width[1]=73;width[2]=6;width[3]=61;width[4]=71;
 clearEpoch();
 // Inputs update after each clock evaluation; handshakes sampled BEFORE edges.
 for(t=0;t<40000;t=t+1) begin
  if(t==20 || t==5040) commonColdReset=0;
  if(t==5000) begin
   for(n=0;n<5;n=n+1) abandoned=abandoned+sent[n]-received[n];
   commonColdReset=1; clearEpoch();
  end
  // Unrelated clocks, reversed speed ordering after reset, and a stopped fabric.
  nf=t<5000 ? ((t%10)>=5) : ((t%6)>=3);
  nd=t<5000 ? ((t%4)>=2) : ((t%14)>=7);
  if(t>=3000 && t<3400) begin nf=0;stopped=stopped+1;end
  riseF=nf&&!fabricClock;riseD=nd&&!ddrClock;
  if(!commonColdReset) for(n=0;n<5;n=n+1) begin
   srcEdge=(n==2||n==4)?riseD:riseF;
   dstEdge=(n==2||n==4)?riseF:riseD;
   if(srcEdge && inValid[n]) begin
    if(inReady[n]) begin
     expected[n][sent[n]]={inMeta[n],inData[n]};sent[n]=sent[n]+1;
    end else blocked=blocked+1;
   end
   if(dstEdge) begin
    actual={outMeta[n],outData[n]};
    if(stalled[n] && (!outValid[n] || actual!==held[n]))
     $fatal(1,"AXI_CDC_FAIL held payload lane=%0d",n);
    if(outValid[n]) begin
     if(bad&&!injected) begin actual=actual^80'd1;injected=1;end
     if(received[n]>=sent[n] || actual!==expected[n][received[n]]) begin
      if(bad) $display("ORACLE_NEGATIVE_REJECT");
      $fatal(1,"AXI_CDC_FAIL mismatch lane=%0d sent=%0d received=%0d",n,sent[n],received[n]);
     end
     held[n]={outMeta[n],outData[n]};stalled[n]=!outReady[n];
     if(outReady[n]) received[n]=received[n]+1; else stalls=stalls+1;
    end else stalled[n]=0;
   end
  end
  fabricClock=nf;ddrClock=nd; #1;
  // Only change a source offer after its accepting edge, or when no offer exists.
  if(!commonColdReset) begin
   for(n=0;n<5;n=n+1) begin
    randomState=scramble(randomState);
    if(!inValid[n] || sent[n]>offerIndex[n]) begin
     inValid[n]=0;
     if(sent[n]<400 && (n!=0 || (t%5000)>180) && randomState[1:0]!=0) begin
      randomState=scramble(randomState);value={randomState[15:0],randomState};
      value=value & ((80'd1<<width[n])-1);
      inData[n]=value[63:0];inMeta[n]=value[79:64];
      offerIndex[n]=sent[n];inValid[n]=1;
     end
    end
    outReady[n]=((t%5000)>250) && ((t/(37+n))%4!=1) && randomState[3:2]!=0;
   end
  end
  allDone=t>5040;
  for(n=0;n<5;n=n+1) allDone=allDone&&(received[n]==400);
  if(allDone && empty==3) begin
   if(stalls==0||blocked==0||stopped==0) $fatal(1,"AXI_CDC_FAIL missing coverage");
   $display("AXI_CDC_PASS beats=2000 stalls=%0d blocked=%0d stopped=%0d abandoned=%0d ticks=%0d",stalls,blocked,stopped,abandoned,t);
   $finish;
  end
 end
 $fatal(1,"AXI_CDC_FAIL timeout");
end
integer offerIndex[0:4];
endmodule
