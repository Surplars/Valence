`timescale 1ps/1ps
module tb;
reg clockMac;
reg clockDma;
reg commonReset;
reg io_control_request_valid;
wire io_control_request_ready;
reg [63:0] io_control_request_bits_address;
reg io_control_request_bits_write;
reg [2:0] io_control_request_bits_size;
reg [63:0] io_control_request_bits_data;
reg [7:0] io_control_request_bits_byteEnable;
wire io_control_response_valid;
reg io_control_response_ready;
wire [63:0] io_control_response_bits_data;
wire io_control_response_bits_error;
wire io_memory_request_valid;
reg io_memory_request_ready;
wire [63:0] io_memory_request_bits_address;
wire io_memory_request_bits_write;
wire [2:0] io_memory_request_bits_size;
wire [63:0] io_memory_request_bits_data;
wire [7:0] io_memory_request_bits_byteEnable;
reg io_memory_response_valid;
wire io_memory_response_ready;
reg [63:0] io_memory_response_bits_data;
reg io_memory_response_bits_error;
reg [7:0] io_gmiiData;
reg io_gmiiValid;
reg io_gmiiError;
wire io_cdcSourceIdle;
wire io_cdcDestinationIdle;
wire io_macFrameValid;
wire io_macFrameReady;
wire [37:0] io_macFrameBits;
wire io_cdcFrameValid;
wire io_cdcFrameReady;
wire [37:0] io_cdcFrameBits;
wire io_accepted;
wire io_dropped;
wire io_dataFire;
wire [31:0] io_dataWord;
wire [3:0] io_dataKeep;
wire [31:0] io_statusWord;
wire [3:0] io_statusKeep;
wire [2:0] io_dmaState;
wire io_macPending;
wire io_dmaPending;
wire io_bankRelease;
wire io_dataLast;
wire io_statusFire;
wire io_statusLast;
wire io_collectDone;
wire io_completion;
wire io_failed;
wire [63:0] io_activeAddress;
wire [16:0] io_activeBytes;
wire [2:0] io_owned;
wire [2:0] io_completed;
wire [2:0] io_pending;
wire [9:0] io_outstanding;
wire [2:0] io_macOccupied;
wire [1:0] io_macPrefetchOccupied;
wire [2:0] io_dmaPrefetchOccupied;
wire io_creditStall;
wire io_storeEmpty;
EthernetClockedRx dut(
 .clockMac(clockMac),
 .clockDma(clockDma),
 .commonReset(commonReset),
 .io_control_request_valid(io_control_request_valid),
 .io_control_request_ready(io_control_request_ready),
 .io_control_request_bits_address(io_control_request_bits_address),
 .io_control_request_bits_write(io_control_request_bits_write),
 .io_control_request_bits_size(io_control_request_bits_size),
 .io_control_request_bits_data(io_control_request_bits_data),
 .io_control_request_bits_byteEnable(io_control_request_bits_byteEnable),
 .io_control_response_valid(io_control_response_valid),
 .io_control_response_ready(io_control_response_ready),
 .io_control_response_bits_data(io_control_response_bits_data),
 .io_control_response_bits_error(io_control_response_bits_error),
 .io_memory_request_valid(io_memory_request_valid),
 .io_memory_request_ready(io_memory_request_ready),
 .io_memory_request_bits_address(io_memory_request_bits_address),
 .io_memory_request_bits_write(io_memory_request_bits_write),
 .io_memory_request_bits_size(io_memory_request_bits_size),
 .io_memory_request_bits_data(io_memory_request_bits_data),
 .io_memory_request_bits_byteEnable(io_memory_request_bits_byteEnable),
 .io_memory_response_valid(io_memory_response_valid),
 .io_memory_response_ready(io_memory_response_ready),
 .io_memory_response_bits_data(io_memory_response_bits_data),
 .io_memory_response_bits_error(io_memory_response_bits_error),
 .io_gmiiData(io_gmiiData),
 .io_gmiiValid(io_gmiiValid),
 .io_gmiiError(io_gmiiError),
 .io_cdcSourceIdle(io_cdcSourceIdle),
 .io_cdcDestinationIdle(io_cdcDestinationIdle),
 .io_macFrameValid(io_macFrameValid),
 .io_macFrameReady(io_macFrameReady),
 .io_macFrameBits(io_macFrameBits),
 .io_cdcFrameValid(io_cdcFrameValid),
 .io_cdcFrameReady(io_cdcFrameReady),
 .io_cdcFrameBits(io_cdcFrameBits),
 .io_accepted(io_accepted),
 .io_dropped(io_dropped),
 .io_dataFire(io_dataFire),
 .io_dataWord(io_dataWord),
 .io_dataKeep(io_dataKeep),
 .io_statusWord(io_statusWord),
 .io_statusKeep(io_statusKeep),
 .io_dmaState(io_dmaState),
 .io_macPending(io_macPending),
 .io_dmaPending(io_dmaPending),
 .io_bankRelease(io_bankRelease),
 .io_dataLast(io_dataLast),
 .io_statusFire(io_statusFire),
 .io_statusLast(io_statusLast),
 .io_collectDone(io_collectDone),
 .io_completion(io_completion),
 .io_failed(io_failed),
 .io_activeAddress(io_activeAddress),
 .io_activeBytes(io_activeBytes),
 .io_owned(io_owned),
 .io_completed(io_completed),
 .io_pending(io_pending),
 .io_outstanding(io_outstanding),
 .io_macOccupied(io_macOccupied),
 .io_macPrefetchOccupied(io_macPrefetchOccupied),
 .io_dmaPrefetchOccupied(io_dmaPrefetchOccupied),
 .io_creditStall(io_creditStall),
 .io_storeEmpty(io_storeEmpty)
);
localparam MAXF=8192, RAM=64'h80200000, REGS=64'h10002000;
integer length=1514, count=4096, warmup=16, total, latency=4, law=0, phase=1700, mutation=0, resetcase=0;
integer dc=0, mc=0, source=0, accepted=0, dropped=0, completed=0, reclaimed=0;
integer primaryAccepted=0, primaryDropped=0, primaryCompleted=0, fixedCompleted=0;
integer writes=0, acks=0, aq[0:MAXF-1], aqh=0, aqt=0, verdict=0;
integer postedSlot[0:MAXF+3], postedGeneration[0:MAXF+3], ph=0,pt=0;
integer postingSlot=0;
integer generation[0:3], ownerGeneration[0:3], cqSlot[0:MAXF-1], cqFrame[0:MAXF-1], cqh=0,cqt=0;
integer owner[0:3], fwrites[0:MAXF-1], facks[0:MAXF-1], fdata[0:MAXF-1], fstatus[0:MAXF-1];
reg fdone[0:MAXF-1], fcomplete[0:MAXF-1];
time eof[0:MAXF-1], beginTime=0, measuredStart=0, sourceEnd=0, finalTime;
reg [7:0] mem[0:65535];
// Ordered response ring is host state, independent of DUT owner counters.
integer rseq[0:7], rdue[0:7], raccept[0:7], rh=0, rt=0, rn=0;
reg [63:0] raddr[0:7], rdata[0:7]; reg [7:0] rmask[0:7];
reg held=0, macHeld=0, cdcHeld=0;
reg [139:0] heldOffer; reg [37:0] macHeldBits, cdcHeldBits;
reg sourceOn=0, sourceDone=0, monitorOn=0, fixedCaptured=0;
integer readyStalls=0, creditStalls=0, emptyStalls=0, descriptorStalls=0;
integer offerAge=0, maxOffer=0, maxAck=0, maxOutstanding=0, maxMac=0;
integer i,j,s,q,b,take,off,expectedMask; reg [63:0] value; reg [139:0] offer;
reg [31:0] expectedStatus;
integer macBeats=0, cdcBeats=0; reg [37:0] beatq[0:65535]; integer bqh=0,bqt=0,bqn=0;
integer completionLatency[0:MAXF-1];
integer macHist[0:4], dmaHist[0:4], outstandingHist[0:4], macPrefHist[0:2];
integer offerHist[0:1023], ackHist[0:1023], offersMeasured=0, acksMeasured=0;
function automatic integer histPercentile(input integer which,input integer numerator);
 integer n,sum,target;begin sum=0;target=((which==0?offersMeasured:acksMeasured)*numerator+99)/100;histPercentile=0;
 for(n=0;n<1024;n=n+1)begin sum=sum+(which==0?offerHist[n]:ackHist[n]);if(sum<target)histPercentile=n+1;end
 end endfunction
function automatic integer completionPercentile(input integer numerator);
 integer n,k,rank,target,candidate;begin target=(primaryCompleted*numerator+99)/100;completionPercentile=0;
 for(n=warmup;n<total;n=n+1)if(fcomplete[n])begin candidate=completionLatency[n];rank=0;
 for(k=warmup;k<total;k=k+1)if(fcomplete[k] && completionLatency[k]<=candidate)rank=rank+1;
 if(rank>=target && (completionPercentile==0 || candidate<completionPercentile))completionPercentile=candidate;
 end end endfunction

function automatic [7:0] bodyByte(input integer seq,input integer pos);
 reg [31:0] mix;
 begin
 mix=((pos*73+(seq+391)*19+11)^(pos>>3));
 case(pos)
 0:bodyByte=2;1:bodyByte=8'h11;2:bodyByte=8'h22;3:bodyByte=8'h33;4:bodyByte=8'h44;5:bodyByte=8'h55;
 6,7,8,9:bodyByte=seq>>(8*(pos-6)); 12:bodyByte=8;13:bodyByte=0;
 default:bodyByte=mix[7:0];endcase
 end
endfunction
function automatic [31:0] frameCrc(input integer seq);
 integer n,k; reg [31:0] crc; reg [7:0] byteval;
 begin crc=32'hffffffff;
 for(n=0;n<length;n=n+1)begin byteval=bodyByte(seq,n);for(k=0;k<8;k=k+1)begin
 if((crc[0]^byteval[k])!=0)crc=(crc>>1)^32'hedb88320;else crc=crc>>1;
 end end frameCrc=~crc;end
endfunction
function automatic integer getSlot(input reg[63:0] address);
 begin if(address<RAM+256 || address>=RAM+256+8192)$fatal(1,"slot address outside ledger");getSlot=(address-RAM-256)/2048;end
endfunction
function automatic integer readyLaw(input integer cycle);
 reg[31:0] mix;begin mix=cycle*32'd1103515245+12345;
 readyLaw=law==0?1:law==1?(cycle%17>=7):((mix>>16)%4!=0);end
endfunction
function automatic integer replyLaw(input integer cycle);
 begin replyLaw=law<2?1:(cycle%23>=9);end
endfunction

initial begin
 i=$value$plusargs("length=%d",length);i=$value$plusargs("frames=%d",count);i=$value$plusargs("latency=%d",latency);
 i=$value$plusargs("law=%d",law);i=$value$plusargs("phase=%d",phase);i=$value$plusargs("mutation=%d",mutation);i=$value$plusargs("resetcase=%d",resetcase);
 total=count+warmup;if(total>=MAXF||length<60||length>2048||latency<1)$fatal(1,"invalid arguments");
 clockMac=0;forever #4000 clockMac=~clockMac;
end
initial begin : dma_clock integer arg;arg=$value$plusargs("phase=%d",phase);clockDma=0;#(phase);forever #5000 clockDma=~clockDma;end

// Drive all external memory responses on falling DMA edges; once offered hold
// them until accepted, regardless of subsequent service-law stalls.
always @(negedge clockDma) begin
 if(commonReset)begin io_memory_request_ready=0;io_memory_response_valid=0;end
 else begin
 io_memory_request_ready=readyLaw(dc);
 if(!io_memory_response_valid || io_memory_response_ready)begin
 io_memory_response_valid=(rn>0 && rdue[rh]<=dc+1 && replyLaw(dc));
 io_memory_response_bits_data=0;io_memory_response_bits_error=0;
 end
 end
end

always @(posedge clockMac) begin
 mc=mc+1;
 if(!commonReset && monitorOn)begin
 if(io_accepted===1'b1 || io_dropped===1'b1)begin
 if(verdict>=source || eof[verdict]==0 || io_accepted===io_dropped)$fatal(1,"MAC verdict without unique ended wire frame");
 if(io_accepted)begin aq[aqt]=verdict;aqt=aqt+1;accepted=accepted+1;if(verdict>=warmup)primaryAccepted=primaryAccepted+1;end
 else begin dropped=dropped+1;if(verdict>=warmup)primaryDropped=primaryDropped+1;end
 verdict=verdict+1;
 end
 if(macHeld && (io_macFrameValid!==1'b1 || io_macFrameBits!==macHeldBits))$fatal(1,"MAC offer changed while blocked");
 macHeld=io_macFrameValid && !io_macFrameReady;macHeldBits=io_macFrameBits;
 if(io_macFrameValid && io_macFrameReady)begin
 if(bqt-bqh>=65536)$fatal(1,"CDC reference queue overflow");beatq[bqt%65536]=io_macFrameBits;bqt=bqt+1;macBeats=macBeats+1;
 end
 if(io_macOccupied>maxMac)maxMac=io_macOccupied;
 if(sourceOn)begin macHist[io_macOccupied]=macHist[io_macOccupied]+1;macPrefHist[io_macPrefetchOccupied]=macPrefHist[io_macPrefetchOccupied]+1;end
 end
end

always @(posedge clockDma) begin
 dc=dc+1;
 if(!commonReset && monitorOn)begin
 if(cdcHeld && (io_cdcFrameValid!==1'b1 || io_cdcFrameBits!==cdcHeldBits))$fatal(1,"CDC offer changed while blocked");
 cdcHeld=io_cdcFrameValid && !io_cdcFrameReady;cdcHeldBits=io_cdcFrameBits;
 if(io_cdcFrameValid && io_cdcFrameReady)begin
 if(bqh>=bqt || io_cdcFrameBits!==beatq[bqh%65536])$fatal(1,"CDC frame payload/order ledger mismatch");bqh=bqh+1;cdcBeats=cdcBeats+1;
 end
 if(io_dataFire)begin
 s=getSlot(io_activeAddress);
 if(owner[s]<0)begin
 if(ph>=pt || postedSlot[ph]!=s || io_activeAddress!==(RAM+256+2048*postedSlot[ph]) || postedGeneration[ph]!=generation[s])$fatal(1,"descriptor launch order/generation mismatch");
 ownerGeneration[s]=postedGeneration[ph];ph=ph+1;
 if(aqh>=aqt)$fatal(1,"DMA data before MAC validation");owner[s]=aq[aqh];aqh=aqh+1;end
 q=owner[s];take=(length-fdata[q]>=4)?4:length-fdata[q];
 if(take<=0 || io_dataKeep!==((1<<take)-1) || io_dataLast!==(fdata[q]+take==length))$fatal(1,"DMA stream keep/last mismatch");
 for(b=0;b<take;b=b+1)if(((io_dataWord>>(8*b))&255)!=={24'd0,bodyByte(q,fdata[q]+b)})$fatal(1,"DMA frame byte mismatch");
 fdata[q]=fdata[q]+take;if(io_dataLast)fdone[q]=1;
 end
 if(io_statusFire)begin
 s=getSlot(io_activeAddress);q=owner[s];if(q<0 || !fdone[q])$fatal(1,"status without complete data owner");
 fstatus[q]=fstatus[q]+1;expectedStatus=fstatus[q]==1?32'h50000000:fstatus[q]==4?64:fstatus[q]==6?length:0;
 if(fstatus[q]>6 || io_statusKeep!==4'hf || io_statusLast!==(fstatus[q]==6) || io_statusWord!==expectedStatus)$fatal(1,"packet/status association mismatch");
 end
 if(io_memory_response_valid && io_memory_response_ready)begin
 if(rn<=0)$fatal(1,"response without request");q=rseq[rh];
 for(b=0;b<8;b=b+1)if(rmask[rh][b])mem[raddr[rh]-RAM+b]=(rdata[rh]>>(8*b))&255;
 if(q>=warmup)begin if(dc-raccept[rh]>=1024)$fatal(1,"ack histogram range exceeded");ackHist[dc-raccept[rh]]=ackHist[dc-raccept[rh]]+1;acksMeasured=acksMeasured+1;end
 facks[q]=facks[q]+1;acks=acks+1;if(dc-raccept[rh]>maxAck)maxAck=dc-raccept[rh];rh=(rh+1)%8;rn=rn-1;
 // A consumed response is withdrawn before the next falling-edge decision.
 io_memory_response_valid<=0;
 end
 offer={io_memory_request_bits_address,io_memory_request_bits_data,io_memory_request_bits_byteEnable,io_memory_request_bits_size,io_memory_request_bits_write};
 if(held && (io_memory_request_valid!==1'b1 || offer!==heldOffer))$fatal(1,"memory offer unstable under backpressure");
 held=io_memory_request_valid && !io_memory_request_ready;heldOffer=offer;
 if(held)begin readyStalls=readyStalls+1;offerAge=offerAge+1;end
 if(io_memory_request_valid && io_memory_request_ready)begin
 if(io_memory_request_bits_write!==1'b1 || io_memory_request_bits_size!==3 || io_memory_request_bits_address[2:0]!==0)$fatal(1,"invalid scalar write format");
 s=getSlot(io_memory_request_bits_address);q=owner[s];
 if(q<0 || !fdone[q] || fstatus[q]!=6 || eof[q]==0 || fcomplete[q])$fatal(1,"write before own frame/status validation or after completion");
 off=io_memory_request_bits_address-(RAM+256+2048*s);take=(length-off>=8)?8:length-off;expectedMask=(1<<take)-1;
 if(off!=fwrites[q]*8 || off>=length || io_memory_request_bits_byteEnable!==expectedMask[7:0])$fatal(1,"duplicate/missing write or bad tail mask");
 value=io_memory_request_bits_data;if(mutation==1 && writes==0)value=value^1;
 for(b=0;b<take;b=b+1)if(((value>>(8*b))&255)!=={56'd0,bodyByte(q,off+b)})$fatal(1,"independent byte oracle mismatch");
 if(rn>=4)$fatal(1,"write credits exceeded");rseq[rt]=q;rdue[rt]=dc+latency;raccept[rt]=dc;raddr[rt]=io_memory_request_bits_address;rdata[rt]=value;rmask[rt]=io_memory_request_bits_byteEnable;rt=(rt+1)%8;rn=rn+1;
 if(q>=warmup)begin if(offerAge>=1024)$fatal(1,"offer histogram range exceeded");offerHist[offerAge]=offerHist[offerAge]+1;offersMeasured=offersMeasured+1;end
 fwrites[q]=fwrites[q]+1;writes=writes+1;if(offerAge>maxOffer)maxOffer=offerAge;offerAge=0;
 end
 if(io_completion)begin
 s=getSlot(io_activeAddress);q=owner[s];if(q<0)$fatal(1,"completion without posted generation");
 if(mutation==2 && completed==0)fwrites[q]=fwrites[q]+1;
 if(facks[q]!=fwrites[q] || fwrites[q]!=(length+7)/8)$fatal(1,"completion before all write acknowledgements");
 if(mutation==3 && completed==0)fcomplete[q]=1;
 if(fcomplete[q] || io_failed!==1'b0)$fatal(1,"duplicate generation or failed completion");
 for(b=0;b<length;b=b+1)if(mem[256+s*2048+b]!==bodyByte(q,b))$fatal(1,"committed byte mismatch");
 for(b=length;b<2048;b=b+1)if(mem[256+s*2048+b]!==8'ha5)$fatal(1,"tail sentinel overwritten");
 cqSlot[cqt]=s;cqFrame[cqt]=q;cqt=cqt+1;
 fcomplete[q]=1;completionLatency[q]=($time-eof[q])/1000;completed=completed+1;if(q>=warmup)begin primaryCompleted=primaryCompleted+1;if(sourceEnd>0 && $time<sourceEnd)fixedCompleted=fixedCompleted+1;end
 end
 if(rn>maxOutstanding)maxOutstanding=rn;
 if(sourceOn)begin dmaHist[io_dmaPrefetchOccupied]=dmaHist[io_dmaPrefetchOccupied]+1;outstandingHist[io_outstanding]=outstandingHist[io_outstanding]+1;end
 creditStalls=creditStalls+io_creditStall;emptyStalls=emptyStalls+io_storeEmpty;
 descriptorStalls=descriptorStalls+(io_dmaState==0 && io_pending==0 && !io_cdcDestinationIdle);
 
 end
end

task automatic access(input integer offset,input bit wr,input reg[63:0] data,output reg[63:0] result);
 integer limit;begin
 @(negedge clockDma);io_control_request_bits_address=REGS+offset;io_control_request_bits_write=wr;io_control_request_bits_data=data;io_control_request_valid=1;
 limit=dc+10000;@(posedge clockDma);while(io_control_request_ready!==1'b1)begin if(dc>limit)$fatal(1,"MMIO request timeout");@(posedge clockDma);end
 if(offset==176 && wr && data==1)begin
 if(pt>=MAXF+4)$fatal(1,"posted ledger overflow");
 generation[postingSlot]=generation[postingSlot]+1;postedSlot[pt]=postingSlot;postedGeneration[pt]=generation[postingSlot];pt=pt+1;
 end
 @(negedge clockDma);io_control_request_valid=0;io_control_response_ready=1;
 @(posedge clockDma);while(io_control_response_valid!==1'b1)begin if(dc>limit)$fatal(1,"MMIO response timeout");@(posedge clockDma);end
 result=io_control_response_bits_data;if(io_control_response_bits_error!==0)$fatal(1,"MMIO error");
 @(negedge clockDma);io_control_response_ready=0;
 end endtask

task automatic post(input integer slot);reg[63:0] unused;begin access(160,1,RAM+256+2048*slot,unused);access(168,1,2048,unused);postingSlot=slot;access(176,1,1,unused);end endtask

task automatic sendByte(input reg[7:0] byteval);begin @(negedge clockMac);io_gmiiValid=1;io_gmiiData=byteval;@(posedge clockMac);end endtask

initial begin : wire_source
 integer seq,n;reg[31:0] crc;
 wait(sourceOn);
 for(seq=0;seq<total;seq=seq+1)begin
 crc=frameCrc(seq);
 for(n=0;n<7;n=n+1)begin sendByte(8'h55);if(n==0)begin if(seq==0)beginTime=$time;if(seq==warmup)begin measuredStart=$time;sourceEnd=$time+count*(length+24)*64'd8000;end end end
 sendByte(8'hd5);for(n=0;n<length;n=n+1)sendByte(bodyByte(seq,n));
 for(n=0;n<4;n=n+1)sendByte((crc>>(8*n))&255);
 eof[seq]=$time;source=seq+1;
 @(negedge clockMac);io_gmiiValid=0;io_gmiiData=0;
 repeat(12)@(posedge clockMac);
 end
 if(sourceEnd!=$time+8000)$fatal(1,"continuous legal-IFG timing mismatch");sourceDone=1;
end

initial begin : control_agent
 reg[63:0] state,addr,meta,unused;integer slot,n,deadline;
 commonReset=1;io_control_request_valid=0;io_control_response_ready=0;io_control_request_bits_address=REGS;io_control_request_bits_write=0;io_control_request_bits_size=3;io_control_request_bits_data=0;io_control_request_bits_byteEnable=255;
 io_memory_request_ready=0;io_memory_response_valid=0;io_memory_response_bits_data=0;io_memory_response_bits_error=0;io_gmiiValid=0;io_gmiiData=0;io_gmiiError=0;
 for(n=0;n<5;n=n+1)begin macHist[n]=0;dmaHist[n]=0;outstandingHist[n]=0;end
 for(n=0;n<3;n=n+1)macPrefHist[n]=0;
 for(n=0;n<1024;n=n+1)begin offerHist[n]=0;ackHist[n]=0;end
 for(n=0;n<65536;n=n+1)mem[n]=8'ha5;
 for(n=0;n<MAXF;n=n+1)begin fwrites[n]=0;facks[n]=0;fdata[n]=0;fstatus[n]=0;fdone[n]=0;fcomplete[n]=0;eof[n]=0;end
 for(n=0;n<4;n=n+1)begin owner[n]=-1;generation[n]=0;ownerGeneration[n]=0;end
 #77300;commonReset=0;repeat(12)@(negedge clockMac);
 // Coordinated reset abort during capture, with DV remaining high across
 // reset release. No accepted memory traffic exists in this reset epoch.
 if(resetcase!=0)begin
 repeat(7)sendByte(8'h55);sendByte(8'hd5);repeat(23)sendByte(8'h33);
 #1377;commonReset=1;#55333;commonReset=0;
 repeat(20)sendByte(8'h55);sendByte(8'hd5);repeat(67)sendByte(8'h44);
 @(negedge clockMac);io_gmiiValid=0;
 repeat(12)@(negedge clockMac);
 if(io_macOccupied!==0 || io_memory_request_valid!==0 || io_cdcDestinationIdle!==1)$fatal(1,"partial-frame reset epoch leaked");
 end
 if(mutation==4)begin force dut.mac.occupied=3'd5;repeat(2)@(negedge clockMac);$fatal(1,"assertion negative control escaped");end
 monitorOn=1;access(184,1,1,unused);for(slot=0;slot<4;slot=slot+1)post(slot);sourceOn=1;
 deadline=dc+total*(length+100)*20+100000;
 while(!sourceDone || verdict<total || completed<accepted || reclaimed<completed || rn!=0)begin
 if(dc>deadline)$fatal(1,"bounded final-drain timeout");access(192,0,0,state);
 if(((state>>8)&255)!=0)begin
 access(200,0,0,addr);access(208,0,0,meta);slot=getSlot(addr);
 if(addr!==(RAM+256+2048*slot) || cqh>=cqt || cqSlot[cqh]!=slot || cqFrame[cqh]!=owner[slot] || ownerGeneration[slot]!=generation[slot] || owner[slot]<0 || !fcomplete[owner[slot]] || meta!==length)$fatal(1,"MMIO completion ledger mismatch");
 access(216,1,1,unused);cqh=cqh+1;owner[slot]=-1;reclaimed=reclaimed+1;
 for(n=0;n<2048;n=n+1)mem[256+2048*slot+n]=8'ha5;post(slot);
 end
 end
 repeat(12)@(negedge clockDma);finalTime=$time;
 if(accepted<4 || writes==0)$fatal(1,"vacuous admission/write result");
 if(cqh!=cqt || pt-ph!=4)$fatal(1,"posted/completion generation ledger not drained");
 if(accepted+dropped!=total || completed!=accepted || primaryCompleted!=primaryAccepted || primaryAccepted+primaryDropped!=count)$fatal(1,"frame conservation");
 if(held || macHeld || cdcHeld || rn!=0 || aqh!=aqt || bqh!=bqt || macBeats!=cdcBeats)$fatal(1,"residual external ownership");
 for(n=0;n<4;n=n+1)if(owner[n]!=-1)$fatal(1,"residual descriptor generation");
 if(io_macOccupied!==0 || io_macPrefetchOccupied!==0 || io_dmaPrefetchOccupied!==0 || io_outstanding!==0 || io_macPending!==0 || io_dmaPending!==0 || io_cdcSourceIdle!==1 || io_cdcDestinationIdle!==1)$fatal(1,"hardware storage not drained");
 if(io_owned!==4 || io_completed!==0 || io_pending!==3 || io_dmaState!==1)$fatal(1,"final posted ownership mismatch");
 for(n=0;n<256;n=n+1)if(mem[n]!==8'ha5)$fatal(1,"leading sentinel overwritten");
 for(n=256+8192;n<65536;n=n+1)if(mem[n]!==8'ha5)$fatal(1,"trailing sentinel overwritten");
 $display("CLOCKED_RX_PASS length=%0d offered=%0d warmup=%0d accepted=%0d dropped=%0d completed=%0d primary_accepted=%0d primary_dropped=%0d primary_completed=%0d fixed_completed=%0d writes=%0d acks=%0d latency=%0d law=%0d phase_ps=%0d resetcase=%0d begin_ps=%0t measured_start_ps=%0t source_end_ps=%0t final_ps=%0t fixed_mbps=%f total_mbps=%f ready_stalls=%0d credit_stalls=%0d empty_stalls=%0d descriptor_stalls=%0d max_offer_cycles=%0d max_ack_cycles=%0d max_outstanding=%0d max_mac=%0d mac_beats=%0d cdc_beats=%0d",length,count,warmup,accepted,dropped,completed,primaryAccepted,primaryDropped,primaryCompleted,fixedCompleted,writes,acks,latency,law,phase,resetcase,beginTime,measuredStart,sourceEnd,finalTime,fixedCompleted*length*8.0*1e6/(sourceEnd-measuredStart),primaryCompleted*length*8.0*1e6/(finalTime-measuredStart),readyStalls,creditStalls,emptyStalls,descriptorStalls,maxOffer,maxAck,maxOutstanding,maxMac,macBeats,cdcBeats);
 $display("METRICS offer_p50_cycles=%0d offer_p95_cycles=%0d ack_p50_cycles=%0d ack_p95_cycles=%0d completion_p50_ns=%0d completion_p95_ns=%0d mac_occupancy=%0d,%0d,%0d,%0d,%0d mac_prefetch=%0d,%0d,%0d dma_prefetch=%0d,%0d,%0d,%0d,%0d write_outstanding=%0d,%0d,%0d,%0d,%0d",histPercentile(0,50),histPercentile(0,95),histPercentile(1,50),histPercentile(1,95),completionPercentile(50),completionPercentile(95),macHist[0],macHist[1],macHist[2],macHist[3],macHist[4],macPrefHist[0],macPrefHist[1],macPrefHist[2],dmaHist[0],dmaHist[1],dmaHist[2],dmaHist[3],dmaHist[4],outstandingHist[0],outstandingHist[1],outstandingHist[2],outstandingHist[3],outstandingHist[4]);
 $finish;
end

endmodule
