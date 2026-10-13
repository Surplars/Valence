`timescale 1ns/1ps
module mac_handoff_tb;
`include "mac_ports.svh"
 always #4 rawTxClock = ~rawTxClock;
 always #5 sourceClock = ~sourceClock;
 reg rxClockRun=1;
 always #4 if(rxClockRun) rawRxClock = ~rawRxClock;
 reg [10:0] stimulus=11'h400;
 wire [7:0] stimData=stimulus[7:0];wire stimError=stimulus[8],stimValid=stimulus[9],stimStep=stimulus[10];
 reg link=1, admissionStop=0, mediaStop=0, ingressEpochReset=0;
 reg rateOffer=0; reg [1:0] rate=2;
 reg [47:0] address=48'h021122334455;
 reg promiscuous=0;
 reg [10:0] history[0:127]; reg [10:0] shadowGold=0, managedGold=0;
 integer rawCycles=0, rxEdges=0, tuples=0, validTuples=0, qualifiedBytes=0;
 integer guardEmpty=0,guardPending=0,guardParser=0,guardStats=0;
 integer lastValidTail=0, emptyPending=0, ackEdges=0;
 integer accepted=0,dropped=0,badFcs=0, reasons[0:7];
 integer rxByteRead=0,rxByteWrite=0,rxFrames=0,expectedFrames=0,statusFrames=0;
 reg [7:0] expectedRx[0:65535]; integer expectedRxEnd[0:255];
 reg [7:0] frameBody[0:4095],frameWire[0:4111]; integer bodyLen,wireLen;
 integer txByteRead=0,txByteWrite=0,txFrames=0,expectedTxFrames=0;
 reg [7:0] expectedTx[0:65535]; integer expectedTxEnd[0:255];
 integer txSpeed=2,txPhase=0,txGap=0,txStepChecks=0;
 reg txClockGold=0, txKnown=0, txWireActive=0, txLowHalf=0;
 reg [3:0] txNibble=0,txLow=0;reg txDv=0;
 integer halfTicks=0, lastWireEnd=0,wireStart=0, wireByteStart=0;
 integer i,j,k,n,oldAccepted,oldDropped,oldRxFrames,oldTxFrames;
 reg checkEnabled=0, holdRx=0,holdStatus=0,abortMode=0;
 reg txResumeAwait=0;integer txResumePhase=-1;
 integer txEdges=0,txAborts=0,txDoneCount=0,txRejects=0,oldAborts,oldDone;
 reg [36:0] stalledRx; reg stalledValid=0;
 reg preStep; integer prePhase,preSpeed,preGap; reg fireRate;
 integer cases=0,solePending=0,wakeCases=0,stopCases=0,resetCases=0;
 reg trialTrace=0;reg prePendingGuard; integer configCoincident=0,stopCoincident=0,targetCycle,offset;
 reg sameConfigEdge,oldConfigBit,sameStopEdge;
 function [31:0] crcByte(input [31:0] c,input [7:0] b);
  reg [31:0] x;integer z;begin x=c;for(z=0;z<8;z=z+1)begin
   if((x[0]^b[z]))x=(x>>1)^32'hedb88320;else x=x>>1;
  end crcByte=x;end
 endfunction
 task makeFrame(input integer length,input integer seed);
  reg [31:0] c;integer a;begin
   bodyLen=length;for(a=0;a<length;a=a+1)frameBody[a]=((a*73+seed*19+11)^(a>>3))&255;
   frameBody[0]=2;frameBody[1]='h11;frameBody[2]='h22;frameBody[3]='h33;frameBody[4]='h44;frameBody[5]='h55;
   frameBody[12]=8;frameBody[13]=0;
   for(a=0;a<7;a=a+1)frameWire[a]='h55;frameWire[7]='hd5;
   c='hffffffff;for(a=0;a<length;a=a+1)begin frameWire[a+8]=frameBody[a];c=crcByte(c,frameBody[a]);end
   c=~c;for(a=0;a<4;a=a+1)frameWire[8+length+a]=(c>>(8*a))&255;
   wireLen=length+12;
  end
 endtask
 task idle(input integer count);begin
  @(negedge rawTxClock);#1;stimulus=11'h400;
  repeat(count)begin @(negedge rawTxClock);#1;end
 end endtask
 task tuple(input [10:0] value);begin @(negedge rawTxClock);#1;stimulus=value;end endtask
 task receiveFrame(input integer length,input integer seed,input integer factor,input integer mode);
  integer a,b;begin
   makeFrame(length,seed);
   if(mode==0)begin for(a=0;a<bodyLen;a=a+1)begin expectedRx[rxByteWrite]=frameBody[a];rxByteWrite=rxByteWrite+1;end
    expectedRxEnd[expectedFrames]=rxByteWrite;expectedFrames=expectedFrames+1;end
   for(a=0;a<wireLen;a=a+1)begin
    for(b=0;b<factor-1;b=b+1)tuple({1'b0,1'b1,(mode==2 && a==22),frameWire[a]});
    tuple({1'b1,1'b1,(mode==2 && a==22),(mode==1 && a==wireLen-1)?(frameWire[a]^8'h01):frameWire[a]});
   end
   tuple(11'h400);cases=cases+1;
  end
 endtask
 task waitRx(input integer frames);integer t;begin
  t=0;while((rxFrames<frames || statusFrames<frames || dut._rx_io_busy || !dut._rxStats_sourceIdle || !dut._rxDiagnostics_sourceIdle)&&t<10000)begin idle(1);t=t+1;end
  if(t==10000)$fatal(1,"RX_DRAIN_TIMEOUT frames=%0d/%0d state=%0d accepted=%0d drops=%0d",rxFrames,frames,dut.rx.state,accepted,dropped);
 end endtask
 task sendControl;integer a,t;begin
  for(a=0;a<6;a=a+1)begin @(negedge sourceClock);streams_txControl_valid=1;streams_txControl_bits_data=a==0?32'ha0000000:0;
   streams_txControl_bits_keep=15;streams_txControl_bits_last=a==5;t=0;
   @(posedge sourceClock);while(!streams_txControl_ready&&t<10000)begin @(posedge sourceClock);t=t+1;end
   if(t==10000)$fatal(1,"TX_CONTROL_TIMEOUT");
  end @(negedge sourceClock);streams_txControl_valid=0;
 end endtask
 task transmitFrame(input integer length,input integer seed);integer a,b,t,count;reg[31:0] word;begin
  makeFrame(length,seed);for(a=0;a<wireLen;a=a+1)begin expectedTx[txByteWrite]=frameWire[a];txByteWrite=txByteWrite+1;end
  expectedTxEnd[expectedTxFrames]=txByteWrite;expectedTxFrames=expectedTxFrames+1;
  sendControl();for(a=0;a<length;a=a+4)begin word=0;count=(length-a<4)?length-a:4;
   for(b=0;b<count;b=b+1)word=word|(frameBody[a+b]<<(8*b));
   @(negedge sourceClock);streams_txData_valid=1;streams_txData_bits_data=word;streams_txData_bits_keep=(1<<count)-1;streams_txData_bits_last=(a+count)==length;
   t=0;@(posedge sourceClock);while(!streams_txData_ready&&t<10000)begin @(posedge sourceClock);t=t+1;end
   if(t==10000)$fatal(1,"TX_DATA_TIMEOUT");
  end @(negedge sourceClock);streams_txData_valid=0;cases=cases+1;
 end endtask
 task waitTx(input integer frames);integer t;begin
  t=0;while((txFrames<frames || dut._tx_io_busy)&&t<50000)begin idle(1);t=t+1;end
  if(t==50000)$fatal(1,"TX_DRAIN_TIMEOUT %0d/%0d",txFrames,frames);idle(20);
 end endtask
 task setRate(input integer speed);integer t;begin
  @(negedge sourceClock);rate=speed;rateOffer=1;t=0;
  @(posedge sourceClock);while(!dut._txRate_source_ready&&t<2000)begin @(posedge sourceClock);t=t+1;end
  @(negedge sourceClock);rateOffer=0;
  t=0;while((txSpeed!=speed || txGap!=0)&&t<4000)begin idle(1);t=t+1;end
  if(t==4000)$fatal(1,"RATE_TIMEOUT");idle(100);lastWireEnd=0;cases=cases+1;
 end endtask
 task wireEdge(input reg ck,input reg[4:0] data);
  reg[7:0] value;integer factor;begin
   halfTicks=halfTicks+1;factor=txSpeed==2?1:txSpeed==1?10:100;
   if(!txKnown)begin txClockGold=ck;txKnown=1;end
   else if(ck!=txClockGold)begin
    txClockGold=ck;
    if(ck)begin txDv=data[4];txNibble=data[3:0];
     if(txDv&&!txWireActive)begin
      if(lastWireEnd!=0 && halfTicks-lastWireEnd<24*factor)$fatal(1,"TX_IFG_TOO_SHORT");
      txWireActive=1;txLowHalf=0;wireStart=halfTicks;wireByteStart=txByteRead;
     end
     if(!txDv&&txWireActive)begin
      if(txLowHalf)$fatal(1,"TX_ODD_NIBBLE");
      if(!abortMode && (txFrames>=expectedTxFrames || txByteRead!=expectedTxEnd[txFrames]))$fatal(1,"TX_FRAME_LENGTH %0d",txByteRead);
      if(!abortMode && halfTicks-wireStart!=(txByteRead-wireByteStart)*2*factor)$fatal(1,"TX_LINE_RATE");
      if(!abortMode)txFrames=txFrames+1;txWireActive=0;lastWireEnd=halfTicks;
     end
    end else if(txDv)begin
     if(!data[4])$fatal(1,"TX_ERROR_SYMBOL");
     if(txSpeed==2)begin value={data[3:0],txNibble};
      if(!abortMode && (txByteRead>=txByteWrite || value!==expectedTx[txByteRead]))$fatal(1,"TX_WIRE_ORACLE index=%0d value=%h expected=%h",txByteRead,value,expectedTx[txByteRead]);if(!abortMode)txByteRead=txByteRead+1;
     end else begin
      if(data[3:0]!=txNibble)$fatal(1,"TX_LOW_RATE_NIBBLE");
      if(!txLowHalf)begin txLow=txNibble;txLowHalf=1;end
      else begin value={txNibble,txLow};txLowHalf=0;
       if(!abortMode && (txByteRead>=txByteWrite || value!==expectedTx[txByteRead]))$fatal(1,"TX_WIRE_ORACLE index=%0d",txByteRead);if(!abortMode)txByteRead=txByteRead+1;
      end
     end
    end
   end
  end
 endtask
 always @(posedge commonReset)begin
  for(integer a=0;a<128;a=a+1)history[a]=0;shadowGold=0;managedGold=0;
 end
 always @(posedge rawTxClock)begin
  rawCycles=rawCycles+1;
  if(dut.ingress.release_0.resetOut)begin for(integer a=0;a<128;a=a+1)history[a]=0;end
  else begin for(integer a=127;a>0;a=a-1)history[a]=history[a-1];history[0]=stimulus;end
  if(dut._rawTxRelease_resetOut)begin txSpeed=2;txPhase=0;txGap=0;end
  else begin
   preStep=txPhase==0 && txGap==0;prePhase=txPhase;preSpeed=txSpeed;preGap=txGap;
   fireRate=dut._txRate_destination_valid && dut._encode_io_rate_ready;
   if(fireRate)begin txSpeed=dut._txRate_destination_bits;txPhase=txSpeed==2?0:1;txGap=12;end
   else begin txPhase=txPhase==((txSpeed==2)?0:(txSpeed==1)?9:99)?0:txPhase+1;if(prePhase==0&&txGap!=0)txGap=txGap-1;end
  end
  #0.002;if(checkEnabled)begin wireEdge(rgmiiTxClockRise,rgmiiTxRise);wireEdge(rgmiiTxClockFall,rgmiiTxFall);end
 end
 always @(negedge rawTxClock)begin
  shadowGold=dut._rawTxRelease_resetOut?0:history[127];
  #0.002;if(checkEnabled&&dut.rawHandoff.falling.sampled[10:0]!==shadowGold)$fatal(1,"FALLING_TUPLE_ORACLE");
 end
 always @(posedge rxClock)begin
  rxEdges=rxEdges+1;
  prePendingGuard=dut._rawHandoff_rxPending;
  sameConfigEdge=checkEnabled && dut.rx.state==0 && dut.rx.io_gmiiValid && dut.rx.io_byteStep && dut.rx.io_enable && !dut.rx.io_stopNewFrames && dut._rxConfig_destination_valid;
  oldConfigBit=dut.rxImage_promiscuous;
  if(trialTrace && ((dut.rx.state==0 && dut.rx.io_gmiiValid && dut.rx.io_byteStep) || dut._rxConfig_destination_valid))$display("CONFIG_TRACE offset=%0d raw=%0d first=%b cfgValid=%b busy=%b old=%b new=%b",offset,rawCycles,dut.rx.state==0&&dut.rx.io_gmiiValid&&dut.rx.io_byteStep,dut._rxConfig_destination_valid,dut._rx_io_busy,dut.rxImage_promiscuous,dut._rxConfig_destination_bits_promiscuous);
  sameStopEdge=checkEnabled && dut.rx.state==0 && dut.rx.io_gmiiValid && dut.rx.io_byteStep && dut.rxStop.command.destination_valid && dut.rxStop.command.destination_bits;

  if(dut._rxRelease_resetOut)managedGold=0;
  else begin
   if(checkEnabled)begin
    if({dut.rx.io_byteStep,dut.rx.io_gmiiValid,dut.rx.io_gmiiError,dut.rx.io_gmiiData}!==managedGold)$fatal(1,"RX_ENABLED_EDGE_ORACLE cycle=%0d got=%h want=%h",rawCycles,dut._rawHandoff_rxPayload,managedGold);
    tuples=tuples+1;if(managedGold[9])validTuples=validTuples+1;if(managedGold[9]&&managedGold[10])qualifiedBytes=qualifiedBytes+1;
    if(!dut._ingress_empty)guardEmpty=guardEmpty+1;
    if(dut._rawHandoff_rxPending)guardPending=guardPending+1;
    if(dut._rx_io_busy)guardParser=guardParser+1;
    if(!dut._rxStats_sourceIdle || !dut._rxDiagnostics_sourceIdle)guardStats=guardStats+1;
    if(dut._ingress_empty&&dut._rawHandoff_rxPending)begin emptyPending=emptyPending+1;
     if(dut._rxDrain_sync_levelOut && !dut._rx_io_busy && dut._rxFifo_sourceIdle && dut._rxStats_sourceIdle && !dut._rxConfig_destination_valid && dut._rxDiagnostics_sourceIdle)begin solePending=solePending+1;$display("LAST_VALID_PENDING_WINDOW raw=%0d shadow=%h managed=%h busy=%b empty=%b",rawCycles,shadowGold,managedGold,dut._rx_io_busy,dut._ingress_empty);end
     if(localIdle_1)$display("PENDING_IDLE_EXPOSED raw=%0d",rawCycles);end
    if(dut._rx_io_accepted)accepted=accepted+1;if(dut._rx_io_dropped)dropped=dropped+1;if(dut._rx_io_badFcs)badFcs=badFcs+1;
    for(integer a=0;a<8;a=a+1)if(dut._rx_io_dropReasons[a])reasons[a]=reasons[a]+1;
    if(dut.agent_1._request_levelOut && (!dut._ingress_empty || dut._rawHandoff_rxPending || dut._rx_io_busy || !dut._rxStats_sourceIdle || !dut._rxDiagnostics_sourceIdle))begin
     #0.001;if(control_1_ack)$fatal(1,"ACK_OWNER_ORACLE prePending=%b raw=%0d",prePendingGuard,rawCycles);
    end
   end
   if(sameConfigEdge)begin #0.001;
    if(dut.rx.promiscuous!==oldConfigBit)$fatal(1,"CONFIG_FIRST_BYTE_SNAPSHOT");
    configCoincident=configCoincident+1;$display("CONFIG_FIRST_VALID_SAME_EDGE raw=%0d capturedOld=%b appliedNew=%b",rawCycles,oldConfigBit,dut.rxImage_promiscuous);
   end
   if(sameStopEdge)begin #0.001;
    if(dut._rx_io_ownedBusy)$fatal(1,"STOP_FIRST_BYTE_ADMITTED");
    stopCoincident=stopCoincident+1;$display("STOP_FIRST_VALID_SAME_EDGE raw=%0d owned=%b",rawCycles,dut._rx_io_ownedBusy);
   end
   managedGold=shadowGold;
  end
 end
 always @(posedge txClock)begin
  txEdges=txEdges+1;
  if(txResumeAwait)begin txResumePhase=prePhase;txResumeAwait=0;
   if(preSpeed!=0 || prePhase==0)$fatal(1,"TX_RESUME_PHASE_NOT_COVERED speed=%0d phase=%0d",preSpeed,prePhase);
   $display("TX_MANAGED_RESUME speed=%0d phase=%0d shadowStep=%b",preSpeed,prePhase,dut._rawHandoff_txByteStep);
  end
  if(checkEnabled&&!dut._txRelease_resetOut)begin if(dut._tx_io_aborted)txAborts=txAborts+1;if(dut._tx_io_done)txDoneCount=txDoneCount+1;if(dut._tx_io_rejected)txRejects=txRejects+1;end
  if(checkEnabled&&!dut._txRelease_resetOut)begin
   if(dut._rawHandoff_txByteStep!==(prePhase==0&&preGap==0))$fatal(1,"TX_EPOCH_ORACLE phase=%0d gap=%0d",prePhase,preGap);
   txStepChecks=txStepChecks+1;
  end
 end
 always @(negedge sourceClock)begin
  streams_rxData_ready=checkEnabled&&!holdRx&&(rawCycles%5!=1);
  streams_rxStatus_ready=checkEnabled&&!holdStatus&&(rawCycles%7!=2);
 end
 always @(posedge sourceClock)if(checkEnabled&&!dut._cpuRelease_resetOut)begin
  if(stalledValid && (!streams_rxData_valid || {streams_rxData_bits_last,streams_rxData_bits_keep,streams_rxData_bits_data}!==stalledRx))$fatal(1,"RX_STALL_STABILITY");
  stalledValid=streams_rxData_valid&&!streams_rxData_ready;stalledRx={streams_rxData_bits_last,streams_rxData_bits_keep,streams_rxData_bits_data};
  if(streams_rxData_valid&&streams_rxData_ready)begin
   for(integer a=0;a<4;a=a+1)if(streams_rxData_bits_keep[a])begin
    if(rxByteRead>=rxByteWrite || streams_rxData_bits_data[a*8+:8]!==expectedRx[rxByteRead])$fatal(1,"RX_FRAME_BYTE_ORACLE index=%0d got=%h expected=%h",rxByteRead,streams_rxData_bits_data[a*8+:8],expectedRx[rxByteRead]);rxByteRead=rxByteRead+1;
   end
   if(streams_rxData_bits_last)begin
    if(rxFrames>=expectedFrames || rxByteRead!=expectedRxEnd[rxFrames])$fatal(1,"RX_FRAME_LAST_ORACLE");rxFrames=rxFrames+1;
   end
  end
  if(streams_rxStatus_valid&&streams_rxStatus_ready&&streams_rxStatus_bits_last)statusFrames=statusFrames+1;
 end
 initial begin
  for(i=0;i<8;i=i+1)reasons[i]=0;
  force dut._physicalIngress_data=stimData;force dut._physicalIngress_error=stimError;
  force dut._physicalIngress_valid=stimValid;force dut._physicalIngress_byteStep=stimStep;
  force dut._media_io_linkUp=link;force dut._media_io_stopNewTraffic=mediaStop;force dut._media_io_ingressReset=ingressEpochReset;
  force dut._media_io_pending=1'b0;force dut._media_io_txRate_valid=rateOffer;force dut._media_io_txRate_bits=rate;force dut._media_io_rxRate_valid=1'b0;
  force dut._csr_io_ports_0_rxEnable=1'b1;force dut._csr_io_ports_0_txEnable=1'b1;
  force dut._csr_io_ports_0_macAddress=address;force dut._csr_io_ports_0_promiscuous=promiscuous;
  force dut._csr_io_ports_0_broadcastEnable=1'b1;force dut._csr_io_ports_0_rxStopRequest=admissionStop;
  control_0_clockEnable=1;control_1_clockEnable=1;control_0_allowAdmission=1;control_1_allowAdmission=1;
  mdioIn=1;registers_response_ready=1;commonReset=1;
  idle(5);commonReset=0;n=0;
  while((dut.rxImage_rxEnable!==1'b1 || dut._rxLink_sync_levelOut!==1'b1 || dut._rxConfig_sourceIdle!==1'b1 || dut._rx_io_busy!==1'b0) && n<500)begin idle(1);n=n+1;end
  if(n==500)$fatal(1,"INITIAL_HANDSHAKE_TIMEOUT");
  $display("INITIAL_CONFIG_HANDSHAKE raw=%0d waited=%0d image=%b mailboxIdle=%b parserBusy=%b",rawCycles,n,dut.rxImage_rxEnable,dut._rxConfig_sourceIdle,dut._rx_io_busy);
  checkEnabled=1;
  if(!dut.rxImage_rxEnable||!dut._rxLink_sync_levelOut)$fatal(1,"INITIAL_CONFIGURATION rxImage=%b link=%b dirty=%b ready=%b valid=%b sent=%h current=%h reset=%b clock=%b",dut.rxImage_rxEnable,dut._rxLink_sync_levelOut,dut.dirty,dut._rxConfig_source_ready,dut._rxConfig_destination_valid,dut.sentConfig,dut._sentConfig_T,dut._rxRelease_resetOut,rxClock);
  receiveFrame(64,1,1,0);idle(160);waitRx(expectedFrames);
  receiveFrame(67,2,10,0);idle(160);waitRx(expectedFrames);
  receiveFrame(61,3,100,0);idle(160);waitRx(expectedFrames);
  oldDropped=dropped;receiveFrame(64,4,1,1);idle(250);if(dropped!=oldDropped+1||badFcs!=1)$fatal(1,"BAD_FCS_ACCOUNTING");
  oldDropped=dropped;receiveFrame(64,5,10,2);idle(300);if(dropped!=oldDropped+1)$fatal(1,"PHY_ERROR_ACCOUNTING");
  for(i=2;i>=0;i=i-1)begin setRate(i);transmitFrame(67,10+i);transmitFrame(61,20+i);waitTx(expectedTxFrames);end
  // TX remains phase-aligned even when its managed clock was stopped while
  // RAW phase/rateGap and the falling byteStep shadow kept advancing.
  control_0_quiesce=1;control_0_isolate=1;idle(120);
  if(!control_0_ack)$fatal(1,"TX_STOP_ACK");control_0_clockEnable=0;idle(12);
  oldTxFrames=txEdges;idle(37);if(txEdges!=oldTxFrames)$fatal(1,"TX_GATE_DID_NOT_STOP");
  fork
   transmitFrame(64,35);
   begin n=0;while(!control_0_wake&&n<100)begin @(negedge rawTxClock);n=n+1;end
    if(n==100)$fatal(1,"TX_WAKE_TIMEOUT");
    while(txPhase!=30)@(negedge rawTxClock);#1;
    txResumeAwait=1;control_0_clockEnable=1;control_0_quiesce=0;control_0_isolate=0;
   end
  join
  waitTx(expectedTxFrames);cases=cases+1;stopCases=stopCases+1;wakeCases=wakeCases+1;
  // Real link abort while TX owns a frame. The external wire is intentionally
  // truncated, then the next frame must restart with independent preamble/FCS.
  setRate(2);abortMode=1;oldAborts=txAborts;oldDone=txDoneCount;oldTxFrames=txByteRead;
  transmitFrame(127,36);n=0;while(!txWireActive&&n<1000)begin idle(1);n=n+1;end
  if(n==1000)$fatal(1,"TX_ABORT_NO_FRAME");idle(14);link=0;mediaStop=1;
  n=0;while((dut._tx_io_busy||txWireActive)&&n<2000)begin idle(1);n=n+1;end
  if(n==2000||txAborts!=oldAborts+1||txDoneCount!=oldDone)$fatal(1,"TX_ABORT_OWNER_ACCOUNTING");
  expectedTxFrames=expectedTxFrames-1;txByteWrite=oldTxFrames;abortMode=0;link=1;mediaStop=0;idle(100);
  transmitFrame(62,37);waitTx(expectedTxFrames);cases=cases+1;
  // The requested stop is already synchronized before a single valid byte.
  // This creates the real sole-pending window: empty=1, parser still search,
  // all downstream owners idle, and only managed.valid prevents ACK.
  setRate(2);control_1_quiesce=1;control_1_isolate=1;idle(100);
  if(!control_1_ack)$fatal(1,"QUIESCE_IDLE_ACK");
  oldDropped=dropped;tuple(11'h655);tuple(11'h400);idle(180);
  if(dropped!=oldDropped+1 || reasons[2]!=1 || solePending==0)$fatal(1,"LAST_VALID_WINDOW_NOT_COVERED");
  idle(100);if(!control_1_ack)$fatal(1,"EOF_DIAGNOSTICS_NOT_DRAINED");cases=cases+1;
  // Long byteStep=0 EOF gap is retained without a fabricated frame outcome.
  oldDropped=dropped;tuple(11'h655);tuple(11'h000);repeat(170)begin @(negedge rawTxClock);#1;end
  if(dropped!=oldDropped || !dut._rx_io_busy || control_1_ack)$fatal(1,"EOF_GAP_OWNERSHIP");
  tuple(11'h400);idle(220);if(dropped!=oldDropped+1)$fatal(1,"EOF_GAP_DROP");cases=cases+1;
  // Actual gate closes only after ACK, then first-frame wake must finish before
  // the original 128 RAW epochs reach the handoff.
  if(!control_1_ack)$fatal(1,"STOP_WITHOUT_ACK");control_1_clockEnable=0;idle(12);
  oldRxFrames=rxEdges;idle(16);if(rxEdges!=oldRxFrames)$fatal(1,"RX_GATE_DID_NOT_STOP");stopCases=stopCases+1;
  fork
   receiveFrame(63,41,1,0);
   begin n=0;while(!control_1_wake&&n<80)begin @(negedge rawTxClock);n=n+1;end
    if(n==80)$fatal(1,"FIRST_FRAME_WAKE_TIMEOUT");
    @(negedge rawTxClock);#1;control_1_clockEnable=1;control_1_quiesce=0;control_1_isolate=0;wakeCases=wakeCases+1;
   end
  join
  idle(180);waitRx(expectedFrames);cases=cases+1;
  // Real output/status ownership must survive recovered RXC stopping.
  holdRx=1;holdStatus=1;receiveFrame(127,42,1,0);idle(220);
  if(accepted!=expectedFrames)$fatal(1,"STALL_FRAME_NOT_ACCEPTED");rxClockRun=0;control_1_quiesce=1;
  idle(80);if(control_1_ack)$fatal(1,"ACK_WITH_STALLED_OUTPUT");
  holdRx=0;idle(160);if(control_1_ack || !streams_rxStatus_valid)$fatal(1,"ACK_WITH_STALLED_STATUS");
  holdStatus=0;waitRx(expectedFrames);idle(100);if(!control_1_ack)$fatal(1,"STOPPED_RXC_DRAIN_FAILED");
  rxClockRun=1;control_1_quiesce=0;cases=cases+1;
  // Unadmitted physical traffic owns no packet bank, but does keep CMU busy.
  admissionStop=1;idle(100);if(!dut._rxStop_stopNewFrames)$fatal(1,"ADMISSION_NOT_CLOSED");
  oldDropped=dropped;tuple(11'h655);repeat(180)begin @(negedge rawTxClock);#1;end
  control_1_quiesce=1;repeat(180)begin @(negedge rawTxClock);#1;end
  if(dut._rx_io_ownedBusy || !dut._rxStop_drained || !dut._rx_io_busy || control_1_ack)$fatal(1,"UNADMITTED_OWNER_CONTRACT");
  // Configuration may complete during the unowned drain without stopping it.
  promiscuous=1;repeat(100)begin @(negedge rawTxClock);#1;end
  if(!dut.rxImage_promiscuous || dut._rxConfig_destination_valid)$fatal(1,"CONFIG_UNADMITTED_DRAIN");
  tuple(11'h400);idle(250);if(dropped!=oldDropped+1||reasons[1]!=1||!control_1_ack)$fatal(1,"UNADMITTED_EOF_ACCOUNTING");
  admissionStop=0;control_1_quiesce=0;promiscuous=0;idle(100);cases=cases+1;
  // Admitted preamble must keep its old config snapshot and block stop ACK.
  oldDropped=dropped;tuple(11'h655);tuple(11'h255);repeat(150)begin @(negedge rawTxClock);#1;end
  if(!dut._rx_io_ownedBusy)$fatal(1,"PREAMBLE_NOT_OWNED");
  admissionStop=1;promiscuous=1;repeat(100)begin @(negedge rawTxClock);#1;end
  if(dut._rxStop_drained||!dut._rxConfig_destination_valid||dut.rx.promiscuous)$fatal(1,"PREAMBLE_CONFIG_OWNER");
  tuple(11'h400);idle(250);if(dropped!=oldDropped+1||!dut._rxStop_drained||!dut.rxImage_promiscuous)$fatal(1,"PREAMBLE_DRAIN");
  admissionStop=0;promiscuous=0;idle(100);cases=cases+1;
  // Align the external CPU/RAW stimulus epoch, then offer at RAW offset 124.
  // The 10 ns CPU and 8 ns RAW grids otherwise cannot present a new mailbox
  // value on every RAW edge. Observe real handshakes, never force their state.
  trialTrace=1;for(offset=124;offset<=124 && configCoincident==0;offset=offset+1)begin
   while(rawCycles%5!=4)idle(1);
   oldDropped=dropped;tuple(11'h655);tuple(11'h400);targetCycle=rawCycles+offset;
   while(rawCycles<targetCycle)@(negedge rawTxClock);#1;promiscuous=1;
   idle(100);if(dropped!=oldDropped+1)$fatal(1,"CONFIG_EDGE_DROP");promiscuous=0;idle(100);cases=cases+1;
  end
  if(configCoincident==0)$fatal(1,"CONFIG_CONCURRENT_EDGE_NOT_COVERED");
  trialTrace=0;for(offset=124;offset<=124 && stopCoincident==0;offset=offset+1)begin
   while(rawCycles%5!=4)idle(1);
   oldDropped=dropped;tuple(11'h655);tuple(11'h400);targetCycle=rawCycles+offset;
   while(rawCycles<targetCycle)@(negedge rawTxClock);#1;admissionStop=1;
   idle(100);if(dropped!=oldDropped+1)$fatal(1,"STOP_EDGE_DROP");admissionStop=0;idle(100);cases=cases+1;
  end
  if(stopCoincident==0)$fatal(1,"STOP_CONCURRENT_EDGE_NOT_COVERED");
  // Media abort at an admitted preamble preserves prior completed payload.
  oldDropped=dropped;tuple(11'h655);tuple(11'h255);repeat(150)begin @(negedge rawTxClock);#1;end
  link=0;mediaStop=1;ingressEpochReset=1;repeat(30)begin @(negedge rawTxClock);#1;end
  tuple(11'h400);idle(250);if(dropped!=oldDropped+1||reasons[7]!=1)$fatal(1,"MEDIA_ABORT_ACCOUNTING");
  link=1;mediaStop=0;ingressEpochReset=0;idle(100);receiveFrame(65,43,1,0);idle(180);waitRx(expectedFrames);cases=cases+1;
  // Async assertion while the managed clock is stopped; reset release remains
  // local. Repeat two RAW phases and do not remove original 128-cycle delay.
  for(k=0;k<2;k=k+1)begin
   control_1_quiesce=1;idle(100);if(!control_1_ack)$fatal(1,"RESET_STOP_ACK");
   control_1_clockEnable=0;idle(12);oldRxFrames=rxEdges;#(k+1);commonReset=1;#0.002;
   if(dut.rawHandoff.managed!==0||dut.rawHandoff.falling.sampled!==0)$fatal(1,"ASYNC_RESET_STOPPED_FF");
   idle(6);commonReset=0;idle(10);if(rxEdges!=oldRxFrames || !dut._rxRelease_resetOut)$fatal(1,"STOPPED_RESET_RELEASE");
   control_1_clockEnable=1;control_1_quiesce=0;control_1_isolate=0;idle(230);resetCases=resetCases+1;
   receiveFrame(60+k,50+k,1,0);idle(180);waitRx(expectedFrames);
  end
  if(txResumePhase<=0)$fatal(1,"TX_RESUME_PHASE_MISSING");
  if(rxByteRead!=rxByteWrite || txByteRead!=txByteWrite || rxFrames!=expectedFrames || txFrames!=expectedTxFrames)$fatal(1,"FINAL_PORT_LEDGER");
  $display("MAC_LIFECYCLE_COVERAGE solePending=%0d guardEmpty=%0d guardPending=%0d guardParser=%0d guardStats=%0d gates=%0d wake=%0d reset=%0d drops=%0d",solePending,guardEmpty,guardPending,guardParser,guardStats,stopCases,wakeCases,resetCases,dropped);
  $display("MAC_HANDOFF_LIFECYCLE_PASS cases=%0d rxFrames=%0d rxBytes=%0d txFrames=%0d txBytes=%0d tupleEdges=%0d validTuples=%0d qualifiedBytes=%0d txEpochChecks=%0d pendingWindow=%0d",cases,rxFrames,rxByteRead,txFrames,txByteRead,tuples,validTuples,qualifiedBytes,txStepChecks,emptyPending);
  $finish;
 end
 initial begin #10000000;$fatal(1,"GLOBAL_TIMEOUT");end
endmodule
