`timescale 1ns/1ps
// Behavioral endpoint/backend oracle only. No production ACK ties or vendor-clock qualification.
`define ENDPOINT(N) \
 reg present``N=1,locked``N=1,manualReady``N=1; \
 reg resultValid``N=0,resultError``N=0; reg [31:0] resultHz``N=0,resultToken``N=0; \
 wire quiesce``N,isolate``N,enable``N,programValid``N,programFallback``N,resultReady``N; \
 wire [31:0] programHz``N,programToken``N; \
 reg [3:0] ackRaw``N=0,ackStage``N=0,ack``N=0,inject``N=0,service``N=15; \
 integer owners``N[0:3]; integer acceptedOwners``N=0,completedOwners``N=0,j``N; \
 reg [2:0] heartbeat``N=0; reg hbStage``N=0,hbSync``N=0,hbSeen``N=0; \
 wire resumed``N=hbSync``N!=hbSeen``N; \
 reg raw``N=0; real halfPeriod``N=10.0; wire worker``N=raw``N & enable``N; \
 always begin #(halfPeriod``N) raw``N=~raw``N; end \
 integer backendCount``N=0,programs``N=0,fallbacks``N=0; \
 reg [31:0] heldHz``N=0,heldToken``N=0; reg heldFallback``N=0; \
 reg dropNormal``N=0,failNormal``N=0,failFallback``N=0,mismatch``N=0,stale``N=0,noNormalLock``N=0; \
 wire programReady``N=manualReady``N && backendCount``N==0; \
 wire [31:0] actual``N,errors``N,completed``N; wire [3:0] state``N; wire valid``N,busy``N,success``N; \
 always @(posedge worker``N or posedge reset) begin \
  if(reset) begin heartbeat``N<=0;ackRaw``N<=0;acceptedOwners``N=0;completedOwners``N=0; \
   for(j``N=0;j``N<4;j``N=j``N+1)owners``N[j``N]=0;end \
  else begin heartbeat``N<=heartbeat``N+1; \
   for(j``N=0;j``N<4;j``N=j``N+1)begin \
    if(inject``N[j``N]&&!quiesce``N)begin owners``N[j``N]=owners``N[j``N]+3;acceptedOwners``N=acceptedOwners``N+3;end \
    else if(service``N[j``N]&&owners``N[j``N]>0)begin owners``N[j``N]=owners``N[j``N]-1;completedOwners``N=completedOwners``N+1;end \
    ackRaw``N[j``N]<=quiesce``N&&owners``N[j``N]==0; \
   end \
  end \
 end \
 always @(posedge aon or posedge reset) begin \
  if(reset)begin ackStage``N<=0;ack``N<=0;hbStage``N<=0;hbSync``N<=0;hbSeen``N<=0;end \
  else begin ackStage``N<=ackRaw``N;ack``N<=ackStage``N;hbStage``N<=heartbeat``N[2];hbSync``N<=hbStage``N;hbSeen``N<=hbSync``N;end \
 end \
 always @(posedge aon)begin \
  if(reset)begin backendCount``N<=0;resultValid``N<=0;locked``N<=1;end \
  else begin \
   if(resultValid``N&&resultReady``N)resultValid``N<=0; \
   if(programValid``N&&programReady``N)begin \
    if(enable``N||!isolate``N)fail("backend accepted command before isolated stop"); \
    heldHz``N<=programHz``N;heldToken``N<=programToken``N;heldFallback``N<=programFallback``N; \
    backendCount``N<=5;locked``N<=0;programs``N=programs``N+1; \
    if(programFallback``N)fallbacks``N=fallbacks``N+1; \
   end else if(backendCount``N>0)begin \
    backendCount``N<=backendCount``N-1; \
    if(backendCount``N==3&&stale``N)begin resultValid``N<=1;resultToken``N<=heldToken``N-1;resultHz``N<=heldHz``N;resultError``N<=0;end \
    if(backendCount``N==1)begin \
     if(!dropNormal``N||heldFallback``N)begin \
      resultValid``N<=1;resultToken``N<=heldToken``N; \
      resultHz``N<=heldHz``N+((mismatch``N&&!heldFallback``N)?1:0); \
      resultError``N<=(failNormal``N&&!heldFallback``N)||(failFallback``N&&heldFallback``N); \
      locked``N<=!((noNormalLock``N&&!heldFallback``N)||(failNormal``N&&!heldFallback``N)||(failFallback``N&&heldFallback``N)); \
      halfPeriod``N<=500000000.0/heldHz``N; \
     end \
    end \
   end \
  end \
 end

`define PORTS(N) \
 .endpoints_``N``_present(present``N),.endpoints_``N``_drainAcks(ack``N), \
 .endpoints_``N``_gateClosed(!enable``N),.endpoints_``N``_gateOpen(enable``N), \
 .endpoints_``N``_locked(locked``N),.endpoints_``N``_resumed(resumed``N), \
 .endpoints_``N``_quiesce(quiesce``N),.endpoints_``N``_isolate(isolate``N),.endpoints_``N``_clockEnable(enable``N), \
 .endpoints_``N``_program_ready(programReady``N),.endpoints_``N``_program_valid(programValid``N), \
 .endpoints_``N``_program_bits_hz(programHz``N),.endpoints_``N``_program_bits_token(programToken``N), \
 .endpoints_``N``_program_bits_fallback(programFallback``N), \
 .endpoints_``N``_result_ready(resultReady``N),.endpoints_``N``_result_valid(resultValid``N), \
 .endpoints_``N``_result_bits_hz(resultHz``N),.endpoints_``N``_result_bits_token(resultToken``N),.endpoints_``N``_result_bits_error(resultError``N), \
 .status_``N``_actualHz(actual``N),.status_``N``_errors(errors``N),.status_``N``_completed(completed``N), \
 .status_``N``_state(state``N),.status_``N``_actualValid(valid``N),.status_``N``_busy(busy``N),.status_``N``_lastSuccess(success``N)

module clock_rate_component_tb;
 reg aon=0;always #10 aon=~aon;
 reg reset=0;
 `ENDPOINT(0)
 `ENDPOINT(1)
 wire sourceClock=worker0;
 reg reqValid=0,reqWrite=0,respReady=1;
 reg [63:0] reqAddress=0,reqData=0;
 reg [2:0] reqSize=3;reg [7:0] reqMask=255;
 wire reqReady,respValid,respError;wire [63:0] respData;
 ClockRateManagementBoundary dut(.sourceClock(sourceClock),.alwaysOnClock(aon),.commonReset(reset),
  .registers_request_valid(reqValid),.registers_request_ready(reqReady),
  .registers_request_bits_address(reqAddress),.registers_request_bits_write(reqWrite),
  .registers_request_bits_data(reqData),.registers_request_bits_size(reqSize),.registers_request_bits_byteEnable(reqMask),
  .registers_response_ready(respReady),.registers_response_valid(respValid),
  .registers_response_bits_error(respError),.registers_response_bits_data(respData),`PORTS(0),`PORTS(1));
 integer cycles=0,requests=0,replies=0,stoppedCycles=0,stalledReplyCycles=0,cases=0;
 reg checking=0,holdingSourceReply=0,bad=0;reg [63:0] lastRead;
 reg [3:0] previousState0=15;
 always @(posedge sourceClock)if(!reset)begin
  if(reqValid&&reqReady)requests=requests+1;
  if(respValid&&respReady)replies=replies+1;
 end
 always @(posedge aon)if(!reset)begin
  cycles=cycles+1;
  if(checking)begin
   if(state0!=previousState0)begin
    $display("RATE_STATE cycle=%0d state=%0d actual=%0d valid=%b success=%b done=%0d errors=%h ack=%h ce=%b lock=%b programs=%0d",cycles,state0,actual0,valid0,success0,completed0,errors0,ack0,enable0,locked0,programs0);
    previousState0=state0;
   end
   if(!enable0)begin
    stoppedCycles=stoppedCycles+1;
    if(owners0[0]+owners0[1]+owners0[2]+owners0[3]!=0)fail("CPU stopped with unfinished owner/response");
   end
   if(!enable1&&owners1[0]+owners1[1]+owners1[2]+owners1[3]!=0)fail("fabric stopped with unfinished owner");
   if(holdingSourceReply)begin
    stalledReplyCycles=stalledReplyCycles+1;
    if(quiesce0||!enable0)fail("source response stalled but controller began quiesce/stop");
   end
  end
 end
 task automatic fail(input string why);
  begin $display("RATE_COMPONENT_FAIL cycle=%0d %s cpu_state=%0d bus_state=%0d actual=%0d valid=%b success=%b done=%0d errors=%h programs=%0d",cycles,why,state0,state1,actual0,valid0,success0,completed0,errors0,programs0);$fatal(1,"rate component oracle");$finish;end
 endtask
 task automatic waitIdle(input integer bank,input integer expectedSequence,input integer hz,input bit good);
  integer timeout;
  begin timeout=0;
   while((bank==0?(busy0||completed0!=expectedSequence):(busy1||completed1!=expectedSequence)))begin
    @(negedge aon);timeout=timeout+1;if(timeout>400)fail("bounded command completion");end
   if(bank==0)begin if(!valid0||actual0!=hz||success0!==good)fail("CPU applied frequency/completion outcome");end
   else if(!valid1||actual1!=hz||success1!==good)fail("fabric applied frequency/completion outcome");
  end
 endtask
 task automatic access(input bit wr,input integer bank,input integer offset,input [63:0] data,
  input bit expectedError,input integer holdCycles,input integer sizeArg=3,input [7:0] maskArg=255);
  integer timeout,k;reg [63:0] savedData;reg savedError;
  begin
   @(negedge sourceClock);reqValid=1;reqWrite=wr;reqAddress=64'h10080800+bank*128+offset;
   reqData=data;reqSize=sizeArg;reqMask=maskArg;respReady=0;timeout=0;
   do begin @(posedge sourceClock);timeout=timeout+1;if(timeout>80)fail("MMIO request not accepted");end while(!reqReady);
   @(negedge sourceClock);reqValid=0;timeout=0;
   while(!respValid)begin @(negedge sourceClock);timeout=timeout+1;if(timeout>80)fail("MMIO reply missing");end
   savedData=respData;savedError=respError;holdingSourceReply=holdCycles>0;
   for(k=0;k<holdCycles;k=k+1)begin
    @(negedge sourceClock);if(!respValid||respData!==savedData||respError!==savedError)fail("stalled response instability");end
   holdingSourceReply=0;respReady=1;
   @(posedge sourceClock);if(respError!==expectedError)fail("MMIO error result");lastRead=respData;
   @(negedge sourceClock);respReady=0;cases=cases+1;
  end
 endtask
 task automatic readEqual(input integer bank,input integer offset,input [63:0] value);
  begin access(0,bank,offset,0,0,0);if(lastRead!==value)fail("MMIO read value");end
 endtask
 integer i,oldPrograms,oldStopped,timeout;
 initial begin
  // Target clocks start stopped. Give their owner models a real async reset
  // edge, rather than relying on a time-zero declaration initialization event.
  bad=$test$plusargs("BAD_ORACLE");#1;reset=1;repeat(8)@(negedge aon);reset=0;
  timeout=0;while(busy0||busy1)begin @(negedge aon);timeout=timeout+1;if(timeout>80)fail("cold boot50 progress");end
  if(actual0!=50000000||actual1!=50000000||!valid0||!valid1)fail("cold default frequency");checking=1;
  readEqual(0,8,50000000);readEqual(1,8,50000000);
  access(1,0,0,51000000,1,0);access(1,0,0,175000000,1,0);
  access(1,0,8,100000000,1,0);access(1,0,0,100000000,1,0,2,15);
  present1=0;access(1,1,0,100000000,1,0);present1=1;
  access(1,0,48,3,0,0);readEqual(0,56,175000000);readEqual(0,64,3);
  access(1,0,24,1023,0,0);readEqual(0,24,0);
  // Four independently outstanding owner classes. Complete them one at a time.
  @(negedge worker0);service0=0;inject0=15;@(negedge worker0);inject0=0;
  access(1,0,0,100000000,0,8);
  while(!quiesce0)@(negedge aon);
  repeat(8)begin @(negedge aon);if(!enable0||programs0!=0)fail("undrained transaction caused stop/program");end
  for(i=0;i<4;i=i+1)begin service0[i]=1;repeat(4)@(negedge aon);if(i<3&&!enable0)fail("one ACK substituted for all four owner classes");end
  waitIdle(0,1,100000000,1);
  if(bad)begin $display("ORACLE_NEGATIVE_REJECT armed");if(actual0!=100000001)fail("negative actual-Hz oracle");end
  readEqual(0,8,100000000);
  // Independent fabric transition leaves CPU clock/rate operational.
  access(1,1,0,150000000,0,0);waitIdle(1,1,150000000,1);
  if(actual0!=100000000||!enable0)fail("fabric request changed CPU rate");
  // A missing AXI completion prevents ALL clock changes, then times out on old rate.
  @(negedge worker0);service0=7;inject0=8;@(negedge worker0);inject0=0;oldPrograms=programs0;
  access(1,0,0,150000000,0,0);waitIdle(0,2,100000000,0);
  if(programs0!=oldPrograms||!(errors0&16))fail("drain timeout changed backend or lost error");
  service0=15;repeat(12)@(negedge aon);
  // No backend reply: AON progresses while CPU clock is stopped and restores50.
  dropNormal0=1;oldStopped=stoppedCycles;
  access(1,0,0,150000000,0,0);waitIdle(0,3,50000000,0);dropNormal0=0;
  if(stoppedCycles-oldStopped<48||fallbacks0<1||!(errors0&64))fail("AON timeout/fallback did not progress during stop");
  stale0=1;access(1,0,0,100000000,0,0);waitIdle(0,4,100000000,1);stale0=0;
  // An approximate backend frequency is rejected, not silently published.
  mismatch0=1;access(1,0,0,150000000,0,0);waitIdle(0,5,50000000,0);mismatch0=0;
  noNormalLock0=1;access(1,0,0,100000000,0,0);waitIdle(0,6,50000000,0);noNormalLock0=0;
  if(!(errors0&128))fail("lock timeout not recorded");
  access(1,0,24,1023,0,0);readEqual(0,24,0);
  // Fallback failure must stay isolated; no fabricated completed success.
  dropNormal0=1;failFallback0=1;access(1,0,0,100000000,0,0);
  timeout=0;while(state0!=8)begin @(negedge aon);timeout=timeout+1;if(timeout>160)fail("fatal fallback not bounded");end
  repeat(12)@(negedge aon);
  if(enable0||!isolate0||valid0||!(errors0&512))fail("failed fallback escaped isolation");
  if(requests!=replies||acceptedOwners0!=completedOwners0||acceptedOwners1!=completedOwners1)
   fail("request/reply or owner conservation");
  $display("RATE_COMPONENT_PASS aon_cycles=%0d mmio=%0d replies=%0d cases=%0d stopped=%0d stalled=%0d cpu_programs=%0d cpu_fallbacks=%0d fabric_programs=%0d owners=%0d completed_owners=%0d",cycles,requests,replies,cases,stoppedCycles,stalledReplyCycles,programs0,fallbacks0,programs1,acceptedOwners0+acceptedOwners1,completedOwners0+completedOwners1);
  $finish;
 end
 initial begin #2000000;fail("independent wall-time watchdog");end
endmodule
