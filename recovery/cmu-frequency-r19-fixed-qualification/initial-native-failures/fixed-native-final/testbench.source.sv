`timescale 1ns/1ps
// Eight independent clocks, real CPU/Atomic/Home/DDR CDC/timer and real AON results.
// Only the external AXI RAM responder is modeled. No terminal receipt is injected.
module i1_runtime_fixed_tb;
  `include "guest_symbols.svh"
  integer cpuHalf = 5, fabricHalf = 7, aonHalf = 11;
  reg cpuClock = 0, fabricClock = 0, alwaysOnClock = 0, cpuPaused = 0;
  initial begin
    if ($value$plusargs("cpu-half=%d", cpuHalf)) begin end
    forever begin #(cpuHalf); if (!cpuPaused) cpuClock = ~cpuClock; end
  end
  initial begin
    if ($value$plusargs("fabric-half=%d", fabricHalf)) begin end
    #2; forever #(fabricHalf) fabricClock = ~fabricClock;
  end
  initial begin
    if ($value$plusargs("aon-half=%d", aonHalf)) begin end
    #3; forever #(aonHalf) alwaysOnClock = ~alwaysOnClock;
  end
  reg reset = 1, start = 0, program_valid = 0;
  reg [8:0] program_index = 0;
  reg [31:0] program_data = 0;
  reg [1:0] request_valid = 0, resume_valid = 0, cancel_valid = 0, result_ready = 0;
  reg [31:0] request_bits [0:1], resume_bits [0:1], cancel_bits [0:1];
  reg [7:0] resume_epoch [0:1], cancel_epoch [0:1], allocatedEpoch [0:1];
  wire [1:0] request_ready, resume_ready, cancel_ready, result_valid, result_canceled, result_timedOut, held_valid;
  wire [31:0] result_token [0:1], held_token [0:1];
  wire [7:0] result_epoch [0:1], held_epoch [0:1];
  reg holdReleaseAck = 0, holdCompletion = 0, holdCpuCompletion = 0;
  reg externalStop = 0, holdMsiReply = 0;
  reg [63:0] sources = 0;
  wire tileHeld_valid, fabricHeld_valid, retire_valid, trap, fabricIdle;
  wire [7:0] tileHeld_bits, fabricHeld_bits;
  wire releaseAckBlocked, completionBlocked, cpuCompletionBlocked, msiReplyBlocked;
  wire [31:0] releaseBeats, coherentAcquires, retire_instruction, cpuResumed;
  wire [31:0] msiAccepted, msiReplied, msiAccepted11, msiAccepted12, msiAccepted13;
  wire [31:0] fabricPrepares, fabricResumes, fabricCancels, fabricTerminals;
  wire fabricTerminalValid, fabricTerminalReady, cpuLinkReady, fabricLinkReady;
  wire cpuTransportEmpty, fabricTransportEmpty;
  wire busy, timeoutSelected, cleanupFault, epochExhausted, activeLane;
  wire [7:0] activeEpoch; wire [31:0] activeToken;
  wire [63:0] retire_pc, retire_data;
  wire [4:0] retire_rd; wire retire_writesRd;
  reg [31:0] rom [0:511]; reg [4095:0] rom_path;
  reg wrongData = 0;
  integer cycles = 0, aonCycles = 0, resetGeneration = 0;
  integer retires = 0, stores = 0, loads = 0, previousLoads = 0, loops = 0, pendingReads = 0, loopPhase = 0;
  integer requests [0:1], resumes [0:1], cancels [0:1], results [0:1], acceptedCycle [0:1];
  integer expected11 = 0, expected12 = 0, expected13 = 0;
  reg [63:0] expectedData = 0, eventMask = 0, lastPending = 0;
  integer i, lane, old, oldCpuResumed, oldFabricPrepares, oldFabricCancels;

  integer debugHalf = 13;
  reg debugClock = 0, debugLinkUp = 1;
  initial begin
    if ($value$plusargs("debug-half=%d", debugHalf)) begin end
    #4; forever #(debugHalf) debugClock = ~debugClock;
  end
  reg debug_request_valid = 0;
  wire debug_request_ready, debug_response_valid;
  reg [6:0] debug_request_address = 0;
  reg [31:0] debug_request_data = 0;
  reg [1:0] debug_request_op = 0;
  wire [31:0] debug_response_data;
  wire [1:0] debug_response_status;
  wire debugBusy, debugFault, debugHeld_valid;
  wire [7:0] debugHeld_bits;
  reg holdMemoryRequest = 0, holdMemoryResponse = 0, holdControlResponse = 0;
  wire memoryRequestBlocked, memoryResponseBlocked, controlResponseBlocked;
  wire memoryRequestFire, memoryRequestWrite, memoryResponseFire, memoryResponseError;
  wire [63:0] memoryRequestAddress, memoryRequestData, memoryResponseData;
  wire [2:0] memoryRequestSize; wire [7:0] memoryRequestByteEnable;
  wire controlRequestFire, controlRequestWrite, controlResponseFire, controlResponseError;
  wire [63:0] controlRequestAddress, controlRequestData;
  wire dmiOwnersIdle, controlOwnersIdle;
  integer sourceRequests = 0, sourceResponses = 0, plannedMemory = 0, memoryRequests = 0, memoryResponses = 0;
  integer controlRequests = 0, controlResponses = 0, controlWrites = 0, controlReads = 0;
  reg expectedMemoryWrite [0:255];
  reg [31:0] expectedMemoryData [0:255], expectedSourceReply [0:255];
  wire [31:0] debugLineProbes, debugLineProbeDataBeats;
  reg [31:0] expectedMemoryAddress [0:255];
  reg [31:0] readbackDataExpected = 0;
  integer guardStores = 0;
  reg previousBusy = 0;
  integer debugReads = 0, debugTerminals = 0, debugRetirementReceipts = 0;
  reg wrongDrain = 0, expectedFault = 0;
  localparam [31:0] DEBUG_ADDRESS = 32'h80202000;
  localparam [31:0] DEBUG_DATA = 32'h11223344;
  localparam [31:0] GUARD_DATA = 32'h55667788;


  integer rxHalf = 3, txHalf = 17, testCase = 0, negative = 0;
  reg rxClock = 0, txClock = 0;
  initial begin
    if ($value$plusargs("rx-half=%d", rxHalf)) begin end
    #1; forever #(rxHalf) rxClock = ~rxClock;
  end
  initial begin
    if ($value$plusargs("tx-half=%d", txHalf)) begin end
    #6; forever #(txHalf) txClock = ~txClock;
  end
  reg holdRxStatusLast=0, holdTxControlLast=0, holdTxDataLast=0;
  reg holdAxiReadResponse=0, holdAxiWriteResponse=0;
  reg [7:0] gmiiRxData=0;
  reg gmiiRxValid=0, gmiiRxError=0;
  wire [7:0] gmiiTxData, rxDropReasons;
  wire gmiiTxEnable, gmiiTxError;
  wire retirementPermit, epochBusy, epochHeld;
  wire [7:0] epochHeldValue;
  wire runtimePause, rxStopRequest, txStopRequest;
  wire dmaActive, dmaTxIdle, dmaOwnersIdle, rxDrained, txDrained, released;
  wire rxAdmissionClosed, rxAccepted, rxDropped, rxBadFcs, txBusy, txDone;
  wire rxStatusLastBlocked, txControlLastBlocked, txDataLastBlocked;
  wire rxDataFire, rxDataLastFire, rxStatusFire, rxStatusLastFire;
  wire [31:0] rxStatusData, packetLineProbes, packetLineProbeDataBeats;
  wire txControlFire, txDataFire, txDataLastFire, rxDestinationIdle, txSourceIdle;
  wire axiReadResponseBlocked, axiWriteResponseBlocked, axiReadResponseFire, axiWriteResponseFire;
  wire packetMemoryRequestValid, packetMemoryRequestReady, packetMemoryRequestFire;
  wire packetMemoryRequestWrite;
  wire [63:0] packetMemoryRequestAddress, packetMemoryRequestData;
  wire [2:0] packetMemoryRequestSize;
  wire [7:0] packetMemoryRequestByteEnable;
  wire packetMemoryResponseValid, packetMemoryResponseReady, packetMemoryResponseFire, packetMemoryResponseError;
  wire [63:0] packetMemoryResponseData;
  wire packetControlRequestValid, packetControlRequestReady, packetControlRequestFire, packetControlRequestWrite;
  wire [63:0] packetControlRequestAddress, packetControlRequestData;
  wire packetControlResponseValid, packetControlResponseReady, packetControlResponseFire, packetControlResponseError;
  integer packetRequests=0, packetResponses=0, packetReads=0, packetWrites=0;
  integer packetControlRequests=0, packetControlResponses=0, rxArms=0, txLaunches=0;
  integer acceptedFrames=0, droppedFrames=0, closedDrops=0, badFcsDrops=0;
  integer statusWords=0, statusFrames=0, rxDataFrames=0, txControlWords=0, txDataFrames=0;
  integer txFrames=0, wirePosition=0, guestReady=0, heartbeats=0;
  integer debugTerminalsAtResult=0, fabricTerminalsAtResult=0, readResponsesAccepted=0, writeResponsesAccepted=0;
  reg [31:0] wireCrc=32'hffffffff, expectedStatus;
  reg [7:0] expectedWireByte;
  reg previousTxEnable=0;
  localparam [31:0] RX_ADDRESS=32'h80203000, TX_ADDRESS=32'h80204000;
  localparam [31:0] SELECTOR_ADDRESS=32'h80205000;
  localparam integer BODY_BYTES=60, PACKET_WORDS=8;
  wire io_ddrAxi_ar_valid,io_ddrAxi_aw_valid,io_ddrAxi_w_valid,io_ddrAxi_r_ready,io_ddrAxi_b_ready;
  reg io_ddrAxi_ar_ready=0,io_ddrAxi_aw_ready=0,io_ddrAxi_w_ready=0,io_ddrAxi_r_valid=0,io_ddrAxi_b_valid=0;
  wire [31:0] io_ddrAxi_ar_bits_addr,io_ddrAxi_aw_bits_addr;
  wire [3:0] io_ddrAxi_ar_bits_id,io_ddrAxi_aw_bits_id;
  wire [7:0] io_ddrAxi_ar_bits_len,io_ddrAxi_aw_bits_len;
  wire [2:0] io_ddrAxi_ar_bits_size,io_ddrAxi_aw_bits_size;
  wire [1:0] io_ddrAxi_ar_bits_burst,io_ddrAxi_aw_bits_burst;
  wire io_ddrAxi_ar_bits_lock,io_ddrAxi_aw_bits_lock;
  wire [3:0] io_ddrAxi_ar_bits_cache,io_ddrAxi_aw_bits_cache,io_ddrAxi_ar_bits_qos,io_ddrAxi_aw_bits_qos;
  wire [2:0] io_ddrAxi_ar_bits_prot,io_ddrAxi_aw_bits_prot;
  wire [63:0] io_ddrAxi_w_bits_data;
  wire [7:0] io_ddrAxi_w_bits_strb;
  wire io_ddrAxi_w_bits_last;
  reg [3:0] io_ddrAxi_r_bits_id=0,io_ddrAxi_b_bits_id=0;
  reg [63:0] io_ddrAxi_r_bits_data=0;
  reg [1:0] io_ddrAxi_r_bits_resp=0,io_ddrAxi_b_bits_resp=0;
  reg io_ddrAxi_r_bits_last=0;

  integer ddrHalf=19, timebaseHalf=23;
  reg ddrClock=0, timebaseClock=0, ddrPaused=0, timebasePaused=0;
  initial begin
    if($value$plusargs("ddr-half=%d",ddrHalf)) begin end
    #8; forever begin #(ddrHalf); if(!ddrPaused) ddrClock=~ddrClock; end
  end
  initial begin
    if($value$plusargs("timebase-half=%d",timebaseHalf)) begin end
    #9; forever begin #(timebaseHalf); if(!timebasePaused) timebaseClock=~timebaseClock; end
  end
  reg holdTimerResponse=1, holdTimerLocalReply=0;
  wire timerLocalReplyBlocked;
  wire timerResponseBlocked,timerRequestFire,timerResponseFire,timerRequestWrite,timerResponseError;
  wire [63:0] timerRequestAddress,timerRequestData,timerResponseData,timerSnapshot;
  wire timerFabricIdle,timerLocalIdle,timerIrq,ddrFabricEmpty,ddrLocalEmpty;
  wire ddrFabricOwnersIdle,ddrLocalOwnersIdle,ddrFabricReady,ddrLocalReady,timerFabricReady,timerLocalReady;
  wire ddrQualified_valid,timerQualified_valid,ddrRetirementPermit,timerRetirementPermit,ddrBusy,timerBusy,fixedFault;
  wire [7:0] ddrQualified_bits,timerQualified_bits;
  integer timerRequests=0,timerResponses=0,timerDestinationRequests=0,timerDestinationResponses=0;
  integer timerReadsRetired=0,timerStoresRetired=0,proofPauseSeen=0,timerHeartbeatReads=0;
  integer timerRequestsAtHeld=0;
  reg [63:0] snapshotBefore;
  reg [63:0] firstTimerRead=0;
  always @(posedge fabricClock) if(!reset) begin
    if(timerRequestFire) begin
      case(timerRequests)
        0: if(timerRequestAddress!==64'h0200bff8 || timerRequestWrite) $fatal(1,"FIXED_TIMER_SOURCE_REQUEST_ORACLE");
        1: if(timerRequestAddress!==64'h02004000 || !timerRequestWrite || timerRequestData!==0) $fatal(1,"FIXED_TIMER_COMPARE_WRITE_ORACLE");
        2: if(timerRequestAddress!==64'h02004000 || timerRequestWrite) $fatal(1,"FIXED_TIMER_COMPARE_READ_ORACLE");
        default: if(timerRequestAddress!==64'h0200bff8 || timerRequestWrite) $fatal(1,"FIXED_TIMER_HEARTBEAT_REQUEST_ORACLE");
      endcase
      timerRequests=timerRequests+1;
    end
    if(timerResponseFire) begin
      if(timerResponses>=timerRequests || timerResponseError) $fatal(1,"FIXED_TIMER_REPLY_WITHOUT_OWNER");
      if(timerResponses==0) begin
        if(timerResponseData==0) $fatal(1,"FIXED_TIMER_ZERO_READ_TIME");
        firstTimerRead=timerResponseData;
      end else if(timerResponses<3 && timerResponseData!==0) $fatal(1,"FIXED_TIMER_COMPARE_RESPONSE_DATA");
      else if(timerResponses>=3 && timerResponseData==0) $fatal(1,"FIXED_TIMER_HEARTBEAT_RESPONSE_DATA");
      timerResponses=timerResponses+1;
    end
    if((testCase==0 || testCase==3) && fabricHeld_valid && proofPauseSeen==0) begin
      // Stop both fixed clocks before their post-held mailbox captures. This is
      // an adversarial simulation stall, not a physical clock-stop permission.
      ddrPaused=1; timebasePaused=1; proofPauseSeen=1;
    end
    if(fixedFault) $fatal(1,"FIXED_UNEXPECTED_QUALIFIER_FAULT");
    if(ddrQualified_valid && (ddrQualified_bits!==fabricHeld_bits || !fabricHeld_valid ||
        !fabricIdle || !ddrFabricEmpty || !ddrFabricOwnersIdle))
      $fatal(1,"FIXED_DDR_QUALIFIED_WITHOUT_FABRIC_OWNER");
    if(timerQualified_valid && (timerQualified_bits!==fabricHeld_bits || !fabricHeld_valid ||
        !fabricIdle || !timerFabricIdle))
      $fatal(1,"FIXED_TIMER_QUALIFIED_WITHOUT_SOURCE_CONSUMPTION");
  end
  always @(posedge timebaseClock) if(!reset) begin
    if(dut.fixedTimer.mmio.destination_request_valid && dut.fixedTimer.mmio.destination_request_ready)
      timerDestinationRequests=timerDestinationRequests+1;
    if(dut.fixedTimer.mmio.destination_response_valid && dut.fixedTimer.mmio.destination_response_ready)
      timerDestinationResponses=timerDestinationResponses+1;
  end

  CommonI1RuntimeFixedFixture dut(
    .ddrClock(ddrClock), .timebaseClock(timebaseClock),
    .fixed_holdTimerResponse(holdTimerResponse),
    .fixed_holdTimerLocalReply(holdTimerLocalReply),
    .fixed_timerLocalReplyBlocked(timerLocalReplyBlocked),
    .fixed_timerResponseBlocked(timerResponseBlocked),
    .fixed_timerRequestFire(timerRequestFire),
    .fixed_timerResponseFire(timerResponseFire),
    .fixed_timerRequestAddress(timerRequestAddress),
    .fixed_timerRequestWrite(timerRequestWrite),
    .fixed_timerRequestData(timerRequestData),
    .fixed_timerResponseData(timerResponseData),
    .fixed_timerResponseError(timerResponseError),
    .fixed_timerFabricIdle(timerFabricIdle),
    .fixed_timerLocalIdle(timerLocalIdle),
    .fixed_timerIrq(timerIrq),
    .fixed_timerSnapshot(timerSnapshot),
    .fixed_ddrFabricEmpty(ddrFabricEmpty),
    .fixed_ddrLocalEmpty(ddrLocalEmpty),
    .fixed_ddrFabricOwnersIdle(ddrFabricOwnersIdle),
    .fixed_ddrLocalOwnersIdle(ddrLocalOwnersIdle),
    .fixed_ddrFabricReady(ddrFabricReady),
    .fixed_ddrLocalReady(ddrLocalReady),
    .fixed_timerFabricReady(timerFabricReady),
    .fixed_timerLocalReady(timerLocalReady),
    .fixed_ddrQualified_valid(ddrQualified_valid),
    .fixed_ddrQualified_bits(ddrQualified_bits),
    .fixed_timerQualified_valid(timerQualified_valid),
    .fixed_timerQualified_bits(timerQualified_bits),
    .fixed_ddrRetirementPermit(ddrRetirementPermit),
    .fixed_timerRetirementPermit(timerRetirementPermit),
    .fixed_ddrBusy(ddrBusy),
    .fixed_timerBusy(timerBusy),
    .fixed_fault(fixedFault),

    .rxClock(rxClock), .txClock(txClock),
    .packetLineProbes(packetLineProbes), .packetLineProbeDataBeats(packetLineProbeDataBeats),
    .packet_holdRxStatusLast(holdRxStatusLast),
    .packet_holdTxControlLast(holdTxControlLast),
    .packet_holdTxDataLast(holdTxDataLast),
    .packet_holdAxiReadResponse(holdAxiReadResponse),
    .packet_holdAxiWriteResponse(holdAxiWriteResponse),
    .packet_gmiiRxData(gmiiRxData),
    .packet_gmiiRxValid(gmiiRxValid),
    .packet_gmiiRxError(gmiiRxError),
    .packet_gmiiTxData(gmiiTxData),
    .packet_gmiiTxEnable(gmiiTxEnable),
    .packet_gmiiTxError(gmiiTxError),
    .packet_retirementPermit(retirementPermit),
    .packet_epochBusy(epochBusy),
    .packet_epochHeld(epochHeld),
    .packet_epochHeldValue(epochHeldValue),
    .packet_runtimePause(runtimePause),
    .packet_rxStopRequest(rxStopRequest),
    .packet_txStopRequest(txStopRequest),
    .packet_dmaActive(dmaActive),
    .packet_dmaTxIdle(dmaTxIdle),
    .packet_dmaOwnersIdle(dmaOwnersIdle),
    .packet_rxDrained(rxDrained),
    .packet_txDrained(txDrained),
    .packet_released(released),
    .packet_rxAdmissionClosed(rxAdmissionClosed),
    .packet_rxAccepted(rxAccepted),
    .packet_rxDropped(rxDropped),
    .packet_rxDropReasons(rxDropReasons),
    .packet_rxBadFcs(rxBadFcs),
    .packet_txBusy(txBusy),
    .packet_txDone(txDone),
    .packet_rxStatusLastBlocked(rxStatusLastBlocked),
    .packet_txControlLastBlocked(txControlLastBlocked),
    .packet_txDataLastBlocked(txDataLastBlocked),
    .packet_rxDataFire(rxDataFire),
    .packet_rxDataLastFire(rxDataLastFire),
    .packet_rxStatusFire(rxStatusFire),
    .packet_rxStatusData(rxStatusData),
    .packet_rxStatusLastFire(rxStatusLastFire),
    .packet_txControlFire(txControlFire),
    .packet_txDataFire(txDataFire),
    .packet_txDataLastFire(txDataLastFire),
    .packet_rxDestinationIdle(rxDestinationIdle),
    .packet_txSourceIdle(txSourceIdle),
    .packet_axiReadResponseBlocked(axiReadResponseBlocked),
    .packet_axiWriteResponseBlocked(axiWriteResponseBlocked),
    .packet_axiReadResponseFire(axiReadResponseFire),
    .packet_axiWriteResponseFire(axiWriteResponseFire),
    .packet_memoryRequestValid(packetMemoryRequestValid),
    .packet_memoryRequestReady(packetMemoryRequestReady),
    .packet_memoryRequestFire(packetMemoryRequestFire),
    .packet_memoryRequestAddress(packetMemoryRequestAddress),
    .packet_memoryRequestData(packetMemoryRequestData),
    .packet_memoryRequestWrite(packetMemoryRequestWrite),
    .packet_memoryRequestSize(packetMemoryRequestSize),
    .packet_memoryRequestByteEnable(packetMemoryRequestByteEnable),
    .packet_memoryResponseValid(packetMemoryResponseValid),
    .packet_memoryResponseReady(packetMemoryResponseReady),
    .packet_memoryResponseFire(packetMemoryResponseFire),
    .packet_memoryResponseData(packetMemoryResponseData),
    .packet_memoryResponseError(packetMemoryResponseError),
    .packet_controlRequestValid(packetControlRequestValid),
    .packet_controlRequestReady(packetControlRequestReady),
    .packet_controlRequestFire(packetControlRequestFire),
    .packet_controlRequestAddress(packetControlRequestAddress),
    .packet_controlRequestData(packetControlRequestData),
    .packet_controlRequestWrite(packetControlRequestWrite),
    .packet_controlResponseValid(packetControlResponseValid),
    .packet_controlResponseReady(packetControlResponseReady),
    .packet_controlResponseFire(packetControlResponseFire),
    .packet_controlResponseError(packetControlResponseError),
    .ddrAxi_ar_valid(io_ddrAxi_ar_valid),
    .ddrAxi_aw_valid(io_ddrAxi_aw_valid),
    .ddrAxi_w_valid(io_ddrAxi_w_valid),
    .ddrAxi_r_ready(io_ddrAxi_r_ready),
    .ddrAxi_b_ready(io_ddrAxi_b_ready),
    .ddrAxi_ar_ready(io_ddrAxi_ar_ready),
    .ddrAxi_aw_ready(io_ddrAxi_aw_ready),
    .ddrAxi_w_ready(io_ddrAxi_w_ready),
    .ddrAxi_r_valid(io_ddrAxi_r_valid),
    .ddrAxi_b_valid(io_ddrAxi_b_valid),
    .ddrAxi_ar_bits_addr(io_ddrAxi_ar_bits_addr),
    .ddrAxi_aw_bits_addr(io_ddrAxi_aw_bits_addr),
    .ddrAxi_ar_bits_id(io_ddrAxi_ar_bits_id),
    .ddrAxi_aw_bits_id(io_ddrAxi_aw_bits_id),
    .ddrAxi_ar_bits_len(io_ddrAxi_ar_bits_len),
    .ddrAxi_aw_bits_len(io_ddrAxi_aw_bits_len),
    .ddrAxi_ar_bits_size(io_ddrAxi_ar_bits_size),
    .ddrAxi_aw_bits_size(io_ddrAxi_aw_bits_size),
    .ddrAxi_ar_bits_burst(io_ddrAxi_ar_bits_burst),
    .ddrAxi_aw_bits_burst(io_ddrAxi_aw_bits_burst),
    .ddrAxi_ar_bits_lock(io_ddrAxi_ar_bits_lock),
    .ddrAxi_aw_bits_lock(io_ddrAxi_aw_bits_lock),
    .ddrAxi_ar_bits_cache(io_ddrAxi_ar_bits_cache),
    .ddrAxi_aw_bits_cache(io_ddrAxi_aw_bits_cache),
    .ddrAxi_ar_bits_qos(io_ddrAxi_ar_bits_qos),
    .ddrAxi_aw_bits_qos(io_ddrAxi_aw_bits_qos),
    .ddrAxi_ar_bits_prot(io_ddrAxi_ar_bits_prot),
    .ddrAxi_aw_bits_prot(io_ddrAxi_aw_bits_prot),
    .ddrAxi_w_bits_data(io_ddrAxi_w_bits_data),
    .ddrAxi_w_bits_strb(io_ddrAxi_w_bits_strb),
    .ddrAxi_w_bits_last(io_ddrAxi_w_bits_last),
    .ddrAxi_r_bits_id(io_ddrAxi_r_bits_id),
    .ddrAxi_b_bits_id(io_ddrAxi_b_bits_id),
    .ddrAxi_r_bits_data(io_ddrAxi_r_bits_data),
    .ddrAxi_r_bits_resp(io_ddrAxi_r_bits_resp),
    .ddrAxi_b_bits_resp(io_ddrAxi_b_bits_resp),
    .ddrAxi_r_bits_last(io_ddrAxi_r_bits_last),
    .debugClock(debugClock), .debugLinkUp(debugLinkUp),
    .debug_request_valid(debug_request_valid), .debug_request_ready(debug_request_ready),
    .debug_request_bits_address(debug_request_address), .debug_request_bits_data(debug_request_data),
    .debug_request_bits_op(debug_request_op), .debug_response_valid(debug_response_valid),
    .debug_response_ready(1'b1), .debug_response_bits_data(debug_response_data), .debug_response_bits_status(debug_response_status),
    .debugLineProbes(debugLineProbes), .debugLineProbeDataBeats(debugLineProbeDataBeats),
    .debugBusy(debugBusy), .debugFault(debugFault), .debugHeld_valid(debugHeld_valid), .debugHeld_bits(debugHeld_bits),
    .observe_holdMemoryRequest(holdMemoryRequest), .observe_holdMemoryResponse(holdMemoryResponse),
    .observe_holdControlResponse(holdControlResponse), .observe_memoryRequestBlocked(memoryRequestBlocked),
    .observe_memoryResponseBlocked(memoryResponseBlocked), .observe_controlResponseBlocked(controlResponseBlocked),
    .observe_memoryRequestFire(memoryRequestFire), .observe_memoryRequestAddress(memoryRequestAddress),
    .observe_memoryRequestData(memoryRequestData), .observe_memoryRequestWrite(memoryRequestWrite),
    .observe_memoryRequestSize(memoryRequestSize), .observe_memoryRequestByteEnable(memoryRequestByteEnable),
    .observe_memoryResponseFire(memoryResponseFire), .observe_memoryResponseData(memoryResponseData),
    .observe_memoryResponseError(memoryResponseError), .observe_controlRequestFire(controlRequestFire),
    .observe_controlRequestAddress(controlRequestAddress), .observe_controlRequestData(controlRequestData),
    .observe_controlRequestWrite(controlRequestWrite), .observe_controlResponseFire(controlResponseFire),
    .observe_controlResponseError(controlResponseError), .observe_dmiOwnersIdle(dmiOwnersIdle),
    .observe_controlOwnersIdle(controlOwnersIdle),
    .cpuClock(cpuClock), .fabricClock(fabricClock), .alwaysOnClock(alwaysOnClock), .commonColdReset(reset),
    .io_start(start), .io_program_valid(program_valid), .io_program_bits_index(program_index), .io_program_bits_data(program_data),
    .io_requests_0_valid(request_valid[0]), .io_requests_0_bits(request_bits[0]), .io_requests_0_ready(request_ready[0]),
    .io_requests_1_valid(request_valid[1]), .io_requests_1_bits(request_bits[1]), .io_requests_1_ready(request_ready[1]),
    .io_resume_0_valid(resume_valid[0]), .io_resume_0_bits_token(resume_bits[0]), .io_resume_0_bits_epoch(resume_epoch[0]), .io_resume_0_ready(resume_ready[0]),
    .io_resume_1_valid(resume_valid[1]), .io_resume_1_bits_token(resume_bits[1]), .io_resume_1_bits_epoch(resume_epoch[1]), .io_resume_1_ready(resume_ready[1]),
    .io_cancel_0_valid(cancel_valid[0]), .io_cancel_0_bits_token(cancel_bits[0]), .io_cancel_0_bits_epoch(cancel_epoch[0]), .io_cancel_0_ready(cancel_ready[0]),
    .io_cancel_1_valid(cancel_valid[1]), .io_cancel_1_bits_token(cancel_bits[1]), .io_cancel_1_bits_epoch(cancel_epoch[1]), .io_cancel_1_ready(cancel_ready[1]),
    .io_held_0_valid(held_valid[0]), .io_held_0_bits_token(held_token[0]), .io_held_0_bits_epoch(held_epoch[0]),
    .io_held_1_valid(held_valid[1]), .io_held_1_bits_token(held_token[1]), .io_held_1_bits_epoch(held_epoch[1]),
    .io_result_0_valid(result_valid[0]), .io_result_0_ready(result_ready[0]), .io_result_0_bits_token(result_token[0]),
    .io_result_0_bits_epoch(result_epoch[0]), .io_result_0_bits_canceled(result_canceled[0]), .io_result_0_bits_timedOut(result_timedOut[0]),
    .io_result_1_valid(result_valid[1]), .io_result_1_ready(result_ready[1]), .io_result_1_bits_token(result_token[1]),
    .io_result_1_bits_epoch(result_epoch[1]), .io_result_1_bits_canceled(result_canceled[1]), .io_result_1_bits_timedOut(result_timedOut[1]),
    .io_busy(busy), .io_timeoutSelected(timeoutSelected), .io_cleanupFault(cleanupFault), .io_epochExhausted(epochExhausted),
    .io_activeLane(activeLane), .io_activeEpoch(activeEpoch), .io_activeToken(activeToken),
    .io_externalStop(externalStop), .io_holdReleaseAck(holdReleaseAck), .io_holdCompletion(holdCompletion),
    .io_holdCpuCompletion(holdCpuCompletion), .io_cpuCompletionBlocked(cpuCompletionBlocked),
    .io_releaseAckBlocked(releaseAckBlocked), .io_completionBlocked(completionBlocked),
    .io_sources(sources), .io_holdMsiReply(holdMsiReply), .io_msiReplyBlocked(msiReplyBlocked),
    .io_msiAccepted(msiAccepted), .io_msiReplied(msiReplied),
    .io_msiAccepted11(msiAccepted11), .io_msiAccepted12(msiAccepted12), .io_msiAccepted13(msiAccepted13),
    .io_tileHeld_valid(tileHeld_valid), .io_tileHeld_bits(tileHeld_bits),
    .io_fabricHeld_valid(fabricHeld_valid), .io_fabricHeld_bits(fabricHeld_bits),
    .io_retire_valid(retire_valid), .io_retire_bits_pc(retire_pc), .io_retire_bits_instruction(retire_instruction),
    .io_retire_bits_rd(retire_rd), .io_retire_bits_data(retire_data), .io_retire_bits_writesRd(retire_writesRd),
    .io_trap(trap), .io_releaseBeats(releaseBeats), .io_coherentAcquires(coherentAcquires), .io_fabricIdle(fabricIdle),
    .io_cpuResumed(cpuResumed), .io_fabricPrepares(fabricPrepares), .io_fabricResumes(fabricResumes),
    .io_fabricCancels(fabricCancels), .io_fabricTerminals(fabricTerminals),
    .io_fabricTerminalValid(fabricTerminalValid), .io_fabricTerminalReady(fabricTerminalReady),
    .io_cpuLinkReady(cpuLinkReady), .io_fabricLinkReady(fabricLinkReady),
    .io_cpuTransportEmpty(cpuTransportEmpty), .io_fabricTransportEmpty(fabricTransportEmpty));

  // AXI RAM responder copied from cpu_boot_tb: independent AW/W queues,
  // original IDs, full bursts/strobes, and stable responses under backpressure.
  reg [63:0] ram[0:8191];
  function [63:0] memory_read(input [31:0] addr);
    begin
      if(addr<32'h10000) memory_read=ram[addr>>3];
      else begin $fatal(1,"I1_PACKET_RAM_RANGE_ORACLE addr=%h",addr); memory_read=0; end
    end
  endfunction
  task memory_write(input [31:0] addr,input [63:0] data,input [7:0] mask);
    reg [63:0] value; integer j;
    begin
      value=memory_read(addr);
      for(j=0;j<8;j=j+1) if(mask[j]) value[j*8+:8]=data[j*8+:8];
      if(addr<32'h10000) ram[addr>>3]=value;
      else $fatal(1, "I1_PACKET_RAM_WRITE_RANGE addr=%h",addr);
    end
  endtask
  task address_check(input [31:0] addr,input [7:0] len,input [2:0] size,input [1:0] burst);
    begin
      if(burst!==1 || size>3 || addr>=32'h80000000 || (addr&((1<<size)-1))!=0 ||
         ((addr&4095)+((len+1)<<size))>4096)
        $fatal(1,"I1_PACKET_AXI_GEOMETRY_ORACLE addr=%h len=%d size=%d burst=%d",addr,len,size,burst);
    end
  endtask
  // Host owners preserve all four DUT read slots and both write owners; IDs are never collapsed.
  reg rd_used[0:15]; reg wr_id_used[0:15]; reg [31:0] rd_addr[0:15];
  integer rd_due[0:15],rd_len[0:15],rd_size[0:15],rd_beat[0:15],rd_id[0:15],rd_ticket[0:15];
  reg [31:0] aw_addr[0:15]; integer aw_id[0:15],aw_len[0:15],aw_size[0:15];
  reg [63:0] w_data[0:127]; reg [7:0] w_mask[0:127]; reg w_last[0:127];
  integer b_id[0:15],b_due[0:15]; reg [31:0] b_addr[0:15]; reg b_error[0:15];
  integer aw_head=0,aw_tail=0,aw_count=0,w_head=0,w_tail=0,w_count=0,b_head=0,b_tail=0,b_count=0;
  integer sending=-1,ddr_edges=0,fabric_edges=0,cpu_edges=0,read_count=0,write_count=0,read_beats=0,write_beats=0;
  integer line_bursts=0,max_parallel_reads=0,overlap_cycles=0,ar_stalls=0,aw_stalls=0,w_stalls=0;
  integer ar_wait_edges=0,aw_wait_edges=0,wBeforeAwBeats=0,wBeforeAwTails=0;
  integer r_errors=0,b_errors=0,max_read_latency=0,read_latency_sum=0;
  integer b_completed=0,code_b_completed=0,max_pending_b=0;
  integer rd_accepted[0:15];
  integer model_i,slot,owners,n,j,best_ticket,beat_index;
  reg [31:0] target_addr;
  reg ar_held=0,aw_held=0,w_held=0,r_payload_held=0;
  reg [60:0] held_ar,held_aw;
  reg [72:0] held_w;
  wire [60:0] ar_payload={io_ddrAxi_ar_bits_addr,io_ddrAxi_ar_bits_id,io_ddrAxi_ar_bits_len,
    io_ddrAxi_ar_bits_size,io_ddrAxi_ar_bits_burst,io_ddrAxi_ar_bits_lock,io_ddrAxi_ar_bits_cache,
    io_ddrAxi_ar_bits_prot,io_ddrAxi_ar_bits_qos};
  wire [60:0] aw_payload={io_ddrAxi_aw_bits_addr,io_ddrAxi_aw_bits_id,io_ddrAxi_aw_bits_len,
    io_ddrAxi_aw_bits_size,io_ddrAxi_aw_bits_burst,io_ddrAxi_aw_bits_lock,io_ddrAxi_aw_bits_cache,
    io_ddrAxi_aw_bits_prot,io_ddrAxi_aw_bits_qos};
  wire [72:0] w_payload={io_ddrAxi_w_bits_data,io_ddrAxi_w_bits_strb,io_ddrAxi_w_bits_last};
  initial for(model_i=0;model_i<16;model_i=model_i+1) begin rd_used[model_i]=0; wr_id_used[model_i]=0; end

  always @(posedge fabricClock) fabric_edges=fabric_edges+1;
  always @(negedge ddrClock) begin
    if(reset) begin
      io_ddrAxi_ar_ready=0;io_ddrAxi_aw_ready=0;io_ddrAxi_w_ready=0;
      io_ddrAxi_r_valid=0;io_ddrAxi_b_valid=0;
    end else begin

      // Hold every AR for two observed DDR edges before the periodic mask.
      // Periodic masks alone can miss all requests after a CDC phase change.
      io_ddrAxi_ar_ready=(ar_wait_edges>=2 && ddr_edges%5!=1 && ddr_edges%5!=2);
      io_ddrAxi_aw_ready=(aw_wait_edges>=3 && ddr_edges%7!=2 && ddr_edges%7!=3);
      io_ddrAxi_w_ready=(ddr_edges%4!=1);
      if(sending<0) begin
        best_ticket=-1;
        for(model_i=0;model_i<16;model_i=model_i+1)
          if(rd_used[model_i] && rd_due[model_i]<=ddr_edges && rd_ticket[model_i]>best_ticket) begin
            sending=model_i; best_ticket=rd_ticket[model_i];
          end
      end
      io_ddrAxi_r_valid=(sending>=0);
      if(sending>=0 && !r_payload_held) begin
        target_addr=(rd_addr[sending]+(rd_beat[sending]<<rd_size[sending]))&32'hfffffff8;
        io_ddrAxi_r_bits_data=memory_read(target_addr);
        io_ddrAxi_r_bits_id=rd_id[sending];
        io_ddrAxi_r_bits_last=(rd_beat[sending]==rd_len[sending]);
        io_ddrAxi_r_bits_resp=0;
      end
      io_ddrAxi_b_valid=(b_count>0 && b_due[b_head]<=ddr_edges);
      if(b_count>0) begin io_ddrAxi_b_bits_id=b_id[b_head]; io_ddrAxi_b_bits_resp=b_error[b_head]?2:0; end
    end
  end

  always @(posedge ddrClock) begin
    ddr_edges=ddr_edges+1;
    if(!reset) begin
      if(ar_held && (!io_ddrAxi_ar_valid || ar_payload!==held_ar)) $fatal(1,"I1_PACKET_AR_HOLD_ORACLE");
      if(aw_held && (!io_ddrAxi_aw_valid || aw_payload!==held_aw)) $fatal(1,"I1_PACKET_AW_HOLD_ORACLE");
      if(w_held && (!io_ddrAxi_w_valid || w_payload!==held_w)) $fatal(1,"I1_PACKET_W_HOLD_ORACLE");
      if(io_ddrAxi_ar_valid && io_ddrAxi_ar_ready) ar_wait_edges=0;
      else if(io_ddrAxi_ar_valid) ar_wait_edges=ar_wait_edges+1;
      if(io_ddrAxi_aw_valid && io_ddrAxi_aw_ready) aw_wait_edges=0;
      else if(io_ddrAxi_aw_valid) aw_wait_edges=aw_wait_edges+1;
      ar_held=io_ddrAxi_ar_valid && !io_ddrAxi_ar_ready; held_ar=ar_payload; ar_stalls=ar_stalls+ar_held;
      aw_held=io_ddrAxi_aw_valid && !io_ddrAxi_aw_ready; held_aw=aw_payload; aw_stalls=aw_stalls+aw_held;
      w_held=io_ddrAxi_w_valid && !io_ddrAxi_w_ready; held_w=w_payload; w_stalls=w_stalls+w_held;
      r_payload_held=io_ddrAxi_r_valid && !io_ddrAxi_r_ready;
      if(io_ddrAxi_r_valid && io_ddrAxi_r_ready) begin
        read_beats=read_beats+1; r_errors=r_errors+(io_ddrAxi_r_bits_resp!=0);
        if(rd_beat[sending]==rd_len[sending]) begin
          read_latency_sum=read_latency_sum+ddr_edges-rd_accepted[sending];
          if(ddr_edges-rd_accepted[sending]>max_read_latency) max_read_latency=ddr_edges-rd_accepted[sending];
          rd_used[sending]=0; sending=-1;
        end else rd_beat[sending]=rd_beat[sending]+1;
      end
      if(io_ddrAxi_b_valid && io_ddrAxi_b_ready) begin
        if(!wr_id_used[io_ddrAxi_b_bits_id]) $fatal(1,"I1_PACKET_B_OWNER_ID_ORACLE");
        wr_id_used[io_ddrAxi_b_bits_id]=0; b_completed=b_completed+1;
        if(b_addr[b_head]==32'h4000) code_b_completed=code_b_completed+1;
        b_errors=b_errors+(io_ddrAxi_b_bits_resp!=0); b_head=(b_head+1)%16; b_count=b_count-1;
      end
      if(io_ddrAxi_ar_valid) address_check(io_ddrAxi_ar_bits_addr,io_ddrAxi_ar_bits_len,
        io_ddrAxi_ar_bits_size,io_ddrAxi_ar_bits_burst);
      if(io_ddrAxi_aw_valid) address_check(io_ddrAxi_aw_bits_addr,io_ddrAxi_aw_bits_len,
        io_ddrAxi_aw_bits_size,io_ddrAxi_aw_bits_burst);
      if(io_ddrAxi_ar_valid && io_ddrAxi_ar_ready) begin
        expectedReadBeats=expectedReadBeats+io_ddrAxi_ar_bits_len+1;
        slot=-1; for(model_i=0;model_i<16;model_i=model_i+1) if(!rd_used[model_i]) slot=model_i;
        if(slot<0) $fatal(1,"I1_PACKET_READ_OWNER_OVERFLOW");
        for(model_i=0;model_i<16;model_i=model_i+1)
          if(rd_used[model_i] && rd_id[model_i]==io_ddrAxi_ar_bits_id) $fatal(1,"I1_PACKET_READ_OWNER_REUSE_ORACLE");
        rd_used[slot]=1;rd_addr[slot]=io_ddrAxi_ar_bits_addr;rd_id[slot]=io_ddrAxi_ar_bits_id;
        rd_len[slot]=io_ddrAxi_ar_bits_len;rd_size[slot]=io_ddrAxi_ar_bits_size;rd_beat[slot]=0;
        rd_due[slot]=ddr_edges+3+(read_count*7)%13;rd_ticket[slot]=read_count;rd_accepted[slot]=ddr_edges;
        read_count=read_count+1;line_bursts=line_bursts+(io_ddrAxi_ar_bits_len!=0);
      end
      if(io_ddrAxi_aw_valid && io_ddrAxi_aw_ready) begin
        if(aw_count==16) $fatal(1,"I1_PACKET_AW_OWNER_OVERFLOW");
        if(wr_id_used[io_ddrAxi_aw_bits_id]) $fatal(1,"I1_PACKET_WRITE_OWNER_REUSE_ORACLE");
        wr_id_used[io_ddrAxi_aw_bits_id]=1;
        aw_addr[aw_tail]=io_ddrAxi_aw_bits_addr;aw_id[aw_tail]=io_ddrAxi_aw_bits_id;
        aw_len[aw_tail]=io_ddrAxi_aw_bits_len;aw_size[aw_tail]=io_ddrAxi_aw_bits_size;
        aw_tail=(aw_tail+1)%16;aw_count=aw_count+1;write_count=write_count+1;
      end
      if(io_ddrAxi_w_valid && io_ddrAxi_w_ready) begin
        if(aw_count==0) begin wBeforeAwBeats=wBeforeAwBeats+1; wBeforeAwTails=wBeforeAwTails+io_ddrAxi_w_bits_last; end
        if(w_count==128) $fatal(1,"I1_PACKET_W_OWNER_OVERFLOW");
        w_data[w_tail]=io_ddrAxi_w_bits_data;w_mask[w_tail]=io_ddrAxi_w_bits_strb;w_last[w_tail]=io_ddrAxi_w_bits_last;
        w_tail=(w_tail+1)%128;w_count=w_count+1;write_beats=write_beats+1;
      end
      if(aw_count>0 && w_count>=aw_len[aw_head]+1) begin
        if(b_count==16) $fatal(1,"I1_PACKET_B_OWNER_OVERFLOW");
        for(n=0;n<=aw_len[aw_head];n=n+1) begin
          if(w_last[w_head] !== (n==aw_len[aw_head])) $fatal(1,"I1_PACKET_WLAST_ORACLE");
          target_addr=(aw_addr[aw_head]+(n<<aw_size[aw_head]))&32'hfffffff8;
          memory_write(target_addr,w_data[w_head],w_mask[w_head]);
          w_head=(w_head+1)%128;w_count=w_count-1;
        end
        b_id[b_tail]=aw_id[aw_head];b_due[b_tail]=ddr_edges+23+(write_count*3)%31;
        b_error[b_tail]=0; b_addr[b_tail]=aw_addr[aw_head];
        b_tail=(b_tail+1)%16;b_count=b_count+1;aw_head=(aw_head+1)%16;aw_count=aw_count-1;
      end
      if(b_count>max_pending_b) max_pending_b=b_count;
      owners=0; for(model_i=0;model_i<16;model_i=model_i+1) owners=owners+rd_used[model_i];
      if(owners>max_parallel_reads) max_parallel_reads=owners;
      if(owners>0 && (aw_count>0 || w_count>0 || b_count>0)) overlap_cycles=overlap_cycles+1;
    end
  end

  wire [31:0] packetTxLineProbes = dut.packetTxLineProbes;
  wire [31:0] packetTxLineProbeDataBeats = dut.packetTxLineProbeDataBeats;
  integer networkRetirements=0, guestChecked=0, expectedReadBeats=0, cpuTxStores=0;
  integer cpuRxChecks=0, cpuGuardChecks=0, cpuTxChecks=0;
  reg packetStalled=0;
  reg [139:0] heldPacketRequest;
  wire [139:0] packetRequestPayload={packetMemoryRequestAddress,packetMemoryRequestData,
      packetMemoryRequestWrite,packetMemoryRequestSize,packetMemoryRequestByteEnable};
  function automatic [7:0] packet_byte(input bit transmit,input integer position);
    begin packet_byte=(transmit ? 8'h20 : 8'h80)+position; end
  endfunction
  function automatic [63:0] packet_word(input bit transmit,input integer word_index);
    integer j,p; reg [63:0] value;
    begin
      value=0;
      for(j=0;j<8;j=j+1) begin p=word_index*8+j;
        if(p<BODY_BYTES) value[j*8+:8]=packet_byte(transmit,p);
      end
      packet_word=value;
    end
  endfunction
  function automatic [31:0] crc_byte(input [31:0] old_crc,input [7:0] byte_value);
    reg [31:0] c; integer k;
    begin c=old_crc^byte_value;
      for(k=0;k<8;k=k+1) c=c[0] ? (c>>1)^32'hedb88320 : c>>1;
      crc_byte=c;
    end
  endfunction
  always @(posedge alwaysOnClock) begin
    aonCycles=aonCycles+1;
    if(aonCycles>60000) $fatal(1,"I1_PACKET_AON_WATCHDOG");
    if(reset) begin
      previousBusy=0;
      for(integer j=0;j<2;j=j+1) begin
        requests[j]=0; resumes[j]=0; cancels[j]=0; results[j]=0; acceptedCycle[j]=0;
      end
    end else begin
      if(previousBusy && !busy && (fabricTerminals!=results[0]+results[1] ||
          debugTerminals!=fabricTerminals || debugRetirementReceipts!=fabricTerminals ||
          networkRetirements!=fabricTerminals))
        $fatal(1,"I1_PACKET_AON_REOPEN_BEFORE_JOINED_RETIREMENT");
      if(busy && request_ready!=0) $fatal(1,"I1_PACKET_NEW_REQUEST_WHILE_OWNED");
      if((request_valid&request_ready)==3 || held_valid==3 || result_valid==3)
        $fatal(1,"I1_PACKET_SHARED_OWNER_DUPLICATED");
      if(cleanupFault || epochExhausted || debugFault) $fatal(1,"I1_PACKET_UNEXPECTED_RUNTIME_FAULT");
      previousBusy=busy;
      for(integer j=0;j<2;j=j+1) begin
        if(request_valid[j]&&request_ready[j]) begin requests[j]=requests[j]+1; acceptedCycle[j]=aonCycles; end
        if(resume_valid[j]&&resume_ready[j]) resumes[j]=resumes[j]+1;
        if(cancel_valid[j]&&cancel_ready[j]) cancels[j]=cancels[j]+1;
        if(result_valid[j]&&result_ready[j]) results[j]=results[j]+1;
      end
    end
  end
  always @(posedge cpuClock) begin
    cycles=cycles+1;
    if(cycles>200000) $fatal(1,"I1_PACKET_CPU_WATCHDOG");
    if(!reset && start) begin
      if(trap) $fatal(1,"I1_PACKET_REAL_CPU_TRAP");
      if(retire_valid) begin
        retires=retires+1;
        if(retire_pc==PC_TIMER_HEARTBEAT_READ) begin
          if(!retire_writesRd || retire_data==0) $fatal(1,"FIXED_TIMER_HEARTBEAT_RETIREMENT");
          timerHeartbeatReads=timerHeartbeatReads+1;
        end
        if(retire_pc==PC_TIMER_READ) begin
          if(!retire_writesRd || retire_data!==firstTimerRead || firstTimerRead==0)
            $fatal(1,"FIXED_TIMER_ACTUAL_CPU_READ_RETIREMENT");
          timerReadsRetired=timerReadsRetired+1;
        end
        if(retire_pc==PC_TIMER_COMPARE_LOAD) begin
          if(!retire_writesRd || retire_data!==0) $fatal(1,"FIXED_TIMER_ACTUAL_CPU_COMPARE_RETIREMENT");
          timerReadsRetired=timerReadsRetired+1;
        end
        if(retire_pc==PC_TIMER_COMPARE_STORE) timerStoresRetired=timerStoresRetired+1;
        if(retire_pc==PC_GUEST_FAIL) $fatal(1,"I1_PACKET_GUEST_COMPARISON_FAILED");
        if(retire_pc==PC_GUARD_STORE) guardStores=guardStores+1;
        if(retire_pc==PC_TX_INIT_STORE) cpuTxStores=cpuTxStores+1;
        if(retire_pc==PC_RX_CHECK_LOAD) cpuRxChecks=cpuRxChecks+1;
        if(retire_pc==PC_GUARD_CHECK_LOAD) cpuGuardChecks=cpuGuardChecks+1;
        if(retire_pc==PC_TX_CHECK_LOAD) cpuTxChecks=cpuTxChecks+1;
        if(retire_pc==PC_RX_CHECK_LOAD && (!retire_writesRd || retire_rd!=7 || retire_data!==64'h8786858483828180))
          $fatal(1,"NETWORK_ORACLE_PAYLOAD actual CPU RX load retirement");
        if(retire_pc==PC_GUARD_CHECK_LOAD && (!retire_writesRd || retire_rd!=7 || retire_data!==64'h55667788))
          $fatal(1,"NETWORK_ORACLE_GUARD actual CPU same-line neighbor retirement");
        if(retire_pc==PC_TX_CHECK_LOAD && (!retire_writesRd || retire_rd!=7 || retire_data!==64'h2726252423222120))
          $fatal(1,"NETWORK_ORACLE_PAYLOAD actual CPU TX load retirement");
        if(retire_pc==PC_NET_CHECKED && (!retire_writesRd || retire_rd!=21 || retire_data!==1))
          $fatal(1,"I1_PACKET_CPU_CHECK_MARKER_RETIREMENT");
        if(retire_pc==PC_NET_READY) guestReady=guestReady+1;
        if(retire_pc==PC_HEARTBEAT) heartbeats=heartbeats+1;
        if(retire_pc==PC_NET_CHECKED) guestChecked=guestChecked+1;
        if(retire_pc==PC_SELECTOR_LOAD && (!retire_writesRd || retire_data!==(testCase==3 ? 64'd1 : 64'd0)))
          $fatal(1,"I1_PACKET_CPU_BOOT_SELECTOR");
      end
    end
  end
  // Independent DMI ledger: source replies do not retire loader/Home owners.
  always @(posedge debugClock) if(!reset) begin
    if(dut.sequencer.boundary.terminal_valid && dut.sequencer.boundary.terminal_ready) begin
      if(debugTerminals>=results[0]+results[1] || !dut.sequencer.terminalConsumedAtAon)
        $fatal(1,"I1_PACKET_DEBUG_TERMINAL_BEFORE_AON_RECEIPT");
      debugTerminals=debugTerminals+1;
    end
    if(debug_request_valid && debug_request_ready) begin
      if(sourceRequests>=256) $fatal(1,"I1_PACKET_DMI_LEDGER_OVERFLOW");
      if(debug_request_op==2) expectedSourceReply[sourceRequests]=0;
      else if(debug_request_op==1 && debug_request_address==7'h40) expectedSourceReply[sourceRequests]=32'h564c0101;
      else if(debug_request_op==1 && debug_request_address==7'h3c) expectedSourceReply[sourceRequests]=readbackDataExpected;
      else $fatal(1,"I1_PACKET_UNPLANNED_DMI_REQUEST");
      sourceRequests=sourceRequests+1;
    end
    if(debug_response_valid) begin
      if(sourceResponses>=sourceRequests || debug_response_status!==0 ||
          debug_response_data!==expectedSourceReply[sourceResponses])
        $fatal(1,"I1_PACKET_DMI_REPLY_ORACLE");
      sourceResponses=sourceResponses+1;
    end
  end
  reg [63:0] expectedPacketWord;
  reg [7:0] expectedPacketMask;
  integer packetWordIndex;
  always @(posedge fabricClock) if(!reset) begin
    if(dut.sequencer.retirement.destination_valid && dut.sequencer.retirement.destination_ready) begin
      if(debugTerminals!=debugRetirementReceipts+1) $fatal(1,"I1_PACKET_DEBUG_RETIREMENT_ORDER");
      debugRetirementReceipts=debugRetirementReceipts+1;
    end
    if(fabricTerminalValid && fabricTerminalReady) begin
      if(!dut.sequencer.retirementPermit || !dut.sequencer.terminalConsumedAtAon ||
          debugRetirementReceipts!=fabricTerminals+1 || debugTerminals!=fabricTerminals+1 ||
          !retirementPermit || !released || !epochBusy)
        $fatal(1,"I1_PACKET_FABRIC_TERMINAL_WITHOUT_DEBUG_NETWORK_JOIN");
    end
    if(dut.network.io_retired) begin
      if(!retirementPermit || !released || !epochBusy || results[0]+results[1]!=networkRetirements+1)
        $fatal(1,"I1_PACKET_NETWORK_RETIREMENT_RECEIPT");
      networkRetirements=networkRetirements+1;
    end
    if(axiReadResponseFire) readResponsesAccepted=readResponsesAccepted+1;
    if(axiWriteResponseFire) writeResponsesAccepted=writeResponsesAccepted+1;
    // UI and fabric fire in unrelated domains. Only independently accumulated
    // complete ledgers may be compared after the real drain checkpoint.
    if(readResponsesAccepted>read_beats || writeResponsesAccepted>b_completed)
      $fatal(1,"FIXED_AXI_RESPONSE_WITHOUT_UI_ACCEPTANCE");
    if(packetStalled && (!packetMemoryRequestValid || packetRequestPayload!==heldPacketRequest))
      $fatal(1,"I1_PACKET_OFFERED_MEMORY_OWNER_CHANGED");
    packetStalled=packetMemoryRequestValid&&!packetMemoryRequestReady;
    heldPacketRequest=packetRequestPayload;
    if(packetMemoryRequestFire) begin
      packetWordIndex=packetRequests;
      expectedPacketWord=packet_word(testCase==3,packetWordIndex);
      expectedPacketMask=packetWordIndex==PACKET_WORDS-1 ? 8'h0f : 8'hff;
      if(packetRequests>=PACKET_WORDS || packetMemoryRequestSize!==3 ||
          packetMemoryRequestAddress!==(testCase==3 ? {32'b0,TX_ADDRESS} : {32'b0,RX_ADDRESS})+packetWordIndex*8 ||
          packetMemoryRequestWrite!==(testCase!=3))
        $fatal(1,"I1_PACKET_MEMORY_REQUEST_ADDRESS_OR_COUNT index=%0d addr=%h",packetRequests,packetMemoryRequestAddress);
      if(testCase!=3) begin
        if(negative==1 && packetWordIndex==0) expectedPacketWord=expectedPacketWord^1;
        if(packetMemoryRequestByteEnable!==expectedPacketMask)
          $fatal(1,"I1_PACKET_RX_BYTE_ENABLE index=%0d got=%h",packetWordIndex,packetMemoryRequestByteEnable);
        for(integer j=0;j<8;j=j+1) if(expectedPacketMask[j] && packetMemoryRequestData[j*8+:8]!==expectedPacketWord[j*8+:8])
          $fatal(1,"NETWORK_ORACLE_PAYLOAD RX word=%0d byte=%0d",packetWordIndex,j);
        packetWrites=packetWrites+1;
      end else packetReads=packetReads+1;
      packetRequests=packetRequests+1;
    end
    if(packetMemoryResponseFire) begin
      if(packetResponses>=packetRequests || packetMemoryResponseError)
        $fatal(1,"I1_PACKET_MEMORY_RESPONSE_OWNER");
      if(testCase==3) begin
        expectedPacketWord=packet_word(1,packetResponses);
        for(integer j=0;j<8;j=j+1) if(packetResponses*8+j<BODY_BYTES && packetMemoryResponseData[j*8+:8]!==expectedPacketWord[j*8+:8])
          $fatal(1,"I1_PACKET_TX_HOME_READBACK word=%0d byte=%0d",packetResponses,j);
      end
      packetResponses=packetResponses+1;
    end
    if(dmaOwnersIdle && (packetRequests!=packetResponses || packetMemoryRequestValid || packetMemoryResponseValid))
      $fatal(1,"I1_PACKET_DMA_IDLE_WITH_ACCEPTED_OWNER");
    if(rxStatusLastBlocked && (rxDrained || dmaOwnersIdle))
      $fatal(1,"NETWORK_ORACLE_DRAIN retained sixth status word");
    if(packetControlRequestFire) begin
      if(!packetControlRequestWrite) $fatal(1,"I1_PACKET_UNEXPECTED_NETWORK_CONTROL_READ");
      case(packetControlRequests)
        0: if(packetControlRequestAddress!==(testCase==3 ? 64'h10002010 : 64'h10002030) ||
              packetControlRequestData!==(testCase==3 ? {32'b0,TX_ADDRESS} : {32'b0,RX_ADDRESS}))
             $fatal(1,"I1_PACKET_CPU_DESCRIPTOR_ADDRESS");
        1: if(packetControlRequestAddress!==(testCase==3 ? 64'h10002018 : 64'h10002038) ||
              packetControlRequestData!==(testCase==3 ? 64'd60 : 64'd256))
             $fatal(1,"I1_PACKET_CPU_DESCRIPTOR_LENGTH");
        2: begin
          if(packetControlRequestAddress!==(testCase==3 ? 64'h10002020 : 64'h10002040) || packetControlRequestData!==1)
            $fatal(1,"I1_PACKET_CPU_DESCRIPTOR_START");
          if(testCase==3) begin txLaunches=txLaunches+1; holdAxiReadResponse=1; end
          else rxArms=rxArms+1;
        end
        default: $fatal(1,"I1_PACKET_DUPLICATE_CPU_DESCRIPTOR");
      endcase
      packetControlRequests=packetControlRequests+1;
    end
    if(packetControlResponseFire) begin
      if(packetControlResponses>=packetControlRequests || packetControlResponseError)
        $fatal(1,"I1_PACKET_CPU_CONTROL_REPLY_OWNER");
      packetControlResponses=packetControlResponses+1;
    end
    if(rxDataLastFire) rxDataFrames=rxDataFrames+1;
    if(rxStatusFire) begin
      if(statusWords>=6) $fatal(1,"I1_PACKET_DUPLICATE_RX_STATUS");
      case(statusWords)
        0: expectedStatus=32'h50000000;
        3: expectedStatus=32'h00000040;
        5: expectedStatus=BODY_BYTES;
        default: expectedStatus=0;
      endcase
      if(rxStatusData!==expectedStatus || rxStatusLastFire!==(statusWords==5))
        $fatal(1,"I1_PACKET_SIX_WORD_STATUS_ORACLE word=%0d got=%h expected=%h",statusWords,rxStatusData,expectedStatus);
      statusWords=statusWords+1;
      if(rxStatusLastFire) statusFrames=statusFrames+1;
    end
    if(txControlFire) txControlWords=txControlWords+1;
    if(txDataLastFire) txDataFrames=txDataFrames+1;
    if(memoryRequestFire) begin
      if(memoryRequests>=plannedMemory || memoryRequests!=memoryResponses ||
          memoryRequestAddress!=={32'b0,expectedMemoryAddress[memoryRequests]} || memoryRequestSize!==2 ||
          memoryRequestByteEnable!==8'h0f || memoryRequestWrite!==expectedMemoryWrite[memoryRequests] ||
          (memoryRequestWrite && memoryRequestData!=={32'b0,expectedMemoryData[memoryRequests]}))
        $fatal(1,"I1_PACKET_DEBUG_MEMORY_REQUEST_LEDGER");
      memoryRequests=memoryRequests+1;
    end
    if(memoryResponseFire) begin
      if(memoryResponses>=memoryRequests || memoryResponseError ||
          (!expectedMemoryWrite[memoryResponses] && memoryResponseData[31:0]!==expectedMemoryData[memoryResponses]))
        $fatal(1,"I1_PACKET_DEBUG_HOME_RESPONSE_LEDGER");
      memoryResponses=memoryResponses+1;
    end
    if(controlRequestFire) begin
      if(!controlRequestWrite || controlRequestAddress!==64'h10003008 || controlRequestData!==1 || controlRequests!=0)
        $fatal(1,"I1_PACKET_CPU_LOADER_OPEN_LEDGER");
      controlRequests=controlRequests+1;
    end
    if(controlResponseFire) begin
      if(controlResponses>=controlRequests || controlResponseError) $fatal(1,"I1_PACKET_CPU_LOADER_REPLY");
      controlResponses=controlResponses+1;
    end
  end
  always @(posedge rxClock) if(!reset) begin
    if(rxAccepted) acceptedFrames=acceptedFrames+1;
    if(rxDropped) begin
      droppedFrames=droppedFrames+1;
      if(rxDropReasons==8'h02) closedDrops=closedDrops+1;
      else if(rxDropReasons==8'h08) badFcsDrops=badFcsDrops+1;
      else $fatal(1,"I1_PACKET_RX_DROP_REASON got=%h",rxDropReasons);
    end
  end
  reg [31:0] wireFcs;
  always @(posedge txClock) if(!reset) begin
    if(gmiiTxError) $fatal(1,"I1_PACKET_TX_GMII_ERROR");
    if(gmiiTxEnable) begin
      if(testCase!=3 || txFrames!=0 || wirePosition>=BODY_BYTES+12) $fatal(1,"I1_PACKET_UNEXPECTED_TX_FRAME");
      if(wirePosition<7) expectedWireByte=8'h55;
      else if(wirePosition==7) expectedWireByte=8'hd5;
      else if(wirePosition<8+BODY_BYTES) begin
        expectedWireByte=packet_byte(1,wirePosition-8);
        wireCrc=crc_byte(wireCrc,expectedWireByte);
      end else begin
        wireFcs=~wireCrc; expectedWireByte=(wireFcs>>((wirePosition-8-BODY_BYTES)*8))&255;
      end
      if(negative==1 && wirePosition==23) expectedWireByte=expectedWireByte^1;
      if(gmiiTxData!==expectedWireByte)
        $fatal(1,"NETWORK_ORACLE_PAYLOAD TX byte=%0d got=%h expected=%h",wirePosition,gmiiTxData,expectedWireByte);
      wirePosition=wirePosition+1;
    end else if(previousTxEnable) begin
      if(wirePosition!=BODY_BYTES+12) $fatal(1,"I1_PACKET_TX_WIRE_LENGTH got=%0d",wirePosition);
      $display("I1_PACKET_TX_WIRE bytes=%0d crc=%h",wirePosition,~wireCrc);
      txFrames=txFrames+1; wirePosition=0;
    end
    previousTxEnable=gmiiTxEnable;
  end
  task tick; begin @(posedge alwaysOnClock); #1; @(negedge alwaysOnClock); end endtask
  task cpuTick; begin @(posedge cpuClock); #1; @(negedge cpuClock); end endtask
  task fabricTick; begin @(posedge fabricClock); #1; @(negedge fabricClock); end endtask
  task debugTick; begin @(posedge debugClock); #1; @(negedge debugClock); end endtask
  task boot;
    integer n;
    begin
      @(negedge fabricClock); reset=1; #1; start=0;
      request_valid=0; resume_valid=0; cancel_valid=0; result_ready=0;
      repeat(12) tick(); reset=0; repeat(16) fabricTick();
      for(n=0;n<512;n=n+1) begin program_valid=1; program_index=n; program_data=rom[n]; fabricTick(); end
      program_valid=0; start=1;
      while(guestReady==0) cpuTick();
      if(guardStores!=1 || cpuTxStores!=60 || controlRequests!=1 || controlResponses!=1 || packetControlRequests!=3 ||
          packetControlResponses!=3 || (testCase==3 ? txLaunches!=1 : rxArms!=1))
        $fatal(1,"I1_PACKET_REAL_CPU_CONFIGURATION_MISSING control=%0d/%0d packet=%0d/%0d guard=%0d",
            controlRequests,controlResponses,packetControlRequests,packetControlResponses,guardStores);
      $display("I1_PACKET_BOOT case=%0d retires=%0d CPU_network_control=%0d/%0d",testCase,retires,packetControlRequests,packetControlResponses);
    end
  endtask
  task dmi(input [1:0] op,input [6:0] address,input [31:0] data);
    integer beforeRequests,beforeResponses;
    begin
      @(negedge debugClock); beforeRequests=sourceRequests; beforeResponses=sourceResponses;
      debug_request_op=op; debug_request_address=address; debug_request_data=data; debug_request_valid=1;
      while(sourceRequests==beforeRequests) debugTick(); debug_request_valid=0;
      while(sourceResponses==beforeResponses) debugTick();
    end
  endtask
  task planMemoryAt(input bit write,input [31:0] address,input [31:0] data);
    begin expectedMemoryWrite[plannedMemory]=write; expectedMemoryData[plannedMemory]=data;
      expectedMemoryAddress[plannedMemory]=address; plannedMemory=plannedMemory+1; end
  endtask
  task readbackAt(input [31:0] address,input [31:0] expectedValue);
    integer beforeResponses;
    begin
      dmi(2,7'h38,32'h00140000);
      beforeResponses=memoryResponses; planMemoryAt(0,address,expectedValue); dmi(2,7'h39,address);
      while(memoryResponses==beforeResponses) fabricTick();
      readbackDataExpected=expectedValue; dmi(1,7'h3c,0);
      if(sourceRequests!=sourceResponses || memoryRequests!=memoryResponses)
        $fatal(1,"I1_PACKET_DEBUG_READBACK_LEFT_OWNER");
    end
  endtask
  task writeCheckCommand;
    integer beforeResponses;
    begin
      dmi(2,7'h38,32'h00040000); dmi(2,7'h39,SELECTOR_ADDRESS+8);
      beforeResponses=memoryResponses; planMemoryAt(1,SELECTOR_ADDRESS+8,1); dmi(2,7'h3c,1);
      while(memoryResponses==beforeResponses) fabricTick();
      while(guestChecked==0) cpuTick();
      if(guestChecked!=1) $fatal(1,"I1_PACKET_DUPLICATE_ARCHITECTURAL_CHECK");
      $display("I1_PACKET_CPU_COHERENT_READBACK case=%0d checked=%0d RX=%0d guard=%0d TX=%0d",
          testCase,guestChecked,cpuRxChecks,cpuGuardChecks,cpuTxChecks);
    end
  endtask
  task releaseOldTimer;
    begin
      repeat(20) begin tick();
        if(timerRequests!=2 || timerResponses!=1 || timerDestinationRequests!=1 ||
            timerFabricIdle || held_valid!=0 || result_valid!=0 || !busy)
          $fatal(1,"FIXED_ACTIVE_EPOCH_OLD_TIMER_OWNER_LOST");
      end
      timebasePaused=0;
      while(timerResponses<3) fabricTick();
      while(timerReadsRetired<2 || timerStoresRetired<1) cpuTick();
      if(timerDestinationRequests<3 || timerDestinationResponses<3 || !timerIrq)
        $fatal(1,"FIXED_TIMER_REAL_CPU_MMIO_LEDGER");
      $display("I1_FIXED_TIMER_LEDGER source=%0d/%0d fixed=%0d/%0d CPU_reads=%0d CPU_writes=%0d old_owner_drained_during_epoch=1",
          timerRequests,timerResponses,timerDestinationRequests,timerDestinationResponses,timerReadsRetired,timerStoresRetired);
    end
  endtask
  task pauseOldUi;
    integer oldR,oldB;
    begin
      oldR=read_beats; oldB=b_completed; ddrPaused=1;
      repeat(20) begin tick();
        if(read_beats!=oldR || b_completed!=oldB || held_valid!=0 || result_valid!=0 || !busy)
          $fatal(1,"FIXED_PAUSED_UI_LOST_OLD_AXI_OWNER");
      end
      ddrPaused=0;
    end
  endtask
  task requestEpoch(input integer which,input [31:0] token);
    integer beforeCount;
    begin
      @(negedge alwaysOnClock); beforeCount=requests[which]; request_bits[which]=token; request_valid[which]=1;
      while(requests[which]==beforeCount) tick(); request_valid[which]=0; allocatedEpoch[which]=activeEpoch;
    end
  endtask
  task waitHeld(input integer which);
    begin
      while(proofPauseSeen==0) tick();
      repeat(30) begin
        tick();
        if(held_valid!=0 || (ddrQualified_valid || negative==4) || timerQualified_valid || result_valid!=0)
          $fatal(1,"FIXED_ORACLE_STALE_IDLE no post-held fixed clock proof");
      end
      ddrPaused=0;
      while(!ddrQualified_valid) tick();
      repeat(20) begin
        tick();
        if(timerQualified_valid || held_valid!=0) $fatal(1,"FIXED_TIMER_PAUSE_FALSE_QUALIFICATION");
      end
      timebasePaused=0;
      while(!held_valid[which]) tick();
      if(!ddrQualified_valid || !timerQualified_valid || ddrQualified_bits!=allocatedEpoch[which] ||
          timerQualified_bits!=allocatedEpoch[which] || !ddrLocalEmpty || !ddrLocalOwnersIdle ||
          !timerFabricIdle || !timerLocalIdle || timerRequests<3 || timerResponses!=timerRequests)
        $fatal(1,"FIXED_COMBINED_HELD_WITHOUT_FIXED_PROOFS");
      timerRequestsAtHeld=timerRequests;
      snapshotBefore=timerSnapshot;
      repeat(30) tick();
      if(timerSnapshot<=snapshotBefore || !timerIrq)
        $fatal(1,"FIXED_RETAINED_SNAPSHOT_IRQ_NOT_LIVE_DURING_HELD");
      $display("I1_FIXED_FRESH_PROOF epoch=%0d independent_UI_timer=1 retained_snapshot_progress=1 IRQ=1",allocatedEpoch[which]);
      if(!debugHeld_valid || debugHeld_bits!=allocatedEpoch[which] || !tileHeld_valid || !fabricHeld_valid ||
          tileHeld_bits!=allocatedEpoch[which] || fabricHeld_bits!=allocatedEpoch[which] ||
          !fabricIdle || !dmiOwnersIdle || !controlOwnersIdle || !cpuTransportEmpty || !fabricTransportEmpty ||
          !epochBusy || !epochHeld || epochHeldValue!=allocatedEpoch[which] || !dmaOwnersIdle ||
          !dmaTxIdle || !rxDrained || !txDrained || !runtimePause || !rxAdmissionClosed ||
          packetRequests!=packetResponses || packetRequests!=PACKET_WORDS || retirementPermit)
        $fatal(1,"I1_PACKET_COMBINED_HELD_PROOF_MISSING_REAL_OWNER");
    end
  endtask
  task resumeEpoch(input integer which,input [31:0] token);
    integer beforeCount;
    begin
      @(negedge alwaysOnClock); beforeCount=resumes[which]; resume_bits[which]=token;
      resume_epoch[which]=allocatedEpoch[which]; resume_valid[which]=1;
      while(resumes[which]==beforeCount) tick(); resume_valid[which]=0;
    end
  endtask
  task cancelEpoch(input integer which,input [31:0] token);
    integer beforeCount;
    begin
      @(negedge alwaysOnClock); beforeCount=cancels[which]; cancel_bits[which]=token;
      cancel_epoch[which]=allocatedEpoch[which]; cancel_valid[which]=1;
      while(cancels[which]==beforeCount) tick(); cancel_valid[which]=0;
    end
  endtask
  task noPrepareWhileOld(input integer beforePrepares,input integer duration);
    integer observedPrepares;
    begin
      for(integer n=0;n<duration;n=n+1) begin
        tick();
        // Negative control mutates only the observer's prepare count. The same
        // real-old-owner checker remains active for positive and negative runs.
        observedPrepares=fabricPrepares+(negative==2 ? 1 : 0);
        if(observedPrepares!=beforePrepares || held_valid!=0 || result_valid!=0 ||
            (!rxStatusLastBlocked && !axiWriteResponseBlocked && !axiReadResponseBlocked &&
             !txControlLastBlocked && !txDataLastBlocked))
          $fatal(1,"NETWORK_ORACLE_DRAIN early prepare/result with old packet/AXI owner");
      end
    end
  endtask
  task presentBlockedDmi;
    begin
      @(negedge debugClock); debug_request_op=1; debug_request_address=7'h40;
      debug_request_data=0; debug_request_valid=1;
    end
  endtask
  task terminal(input integer which,input [31:0] token,input bit canceled,input bit timedOut);
    integer beforeCount,fabricBefore,sourceBefore,fixedWait;
    begin
      beforeCount=results[which]; fabricBefore=fabricTerminals; sourceBefore=sourceRequests;
      while(!result_valid[which]) tick();
      holdTimerLocalReply=1;
      while(!timerLocalReplyBlocked) tick();
      if(timerRequests<=timerRequestsAtHeld || timerLocalIdle || timerFabricIdle)
        $fatal(1,"FIXED_POST_RESUME_REAL_MMIO_OWNER_MISSING");
      ddrPaused=1; timebasePaused=1;
      repeat(40) begin
        if(!result_valid[which] || result_valid[1-which] || result_token[which]!=token ||
            result_epoch[which]!=allocatedEpoch[which] || result_canceled[which]!=canceled ||
            result_timedOut[which]!=timedOut || !busy || request_ready!=0 ||
            !fabricTerminalValid || fabricTerminalReady || fabricTerminals!=fabricBefore ||
            debugTerminals!=fabricBefore || debugRetirementReceipts!=fabricBefore ||
            networkRetirements!=fabricBefore || retirementPermit || !epochBusy || !runtimePause ||
            !rxAdmissionClosed || debug_request_ready || sourceRequests!=sourceBefore)
          $fatal(1,"I1_PACKET_ACTUAL_TERMINAL_BACKPRESSURE_ORACLE");
        tick();
      end
      $display("I1_PACKET_TERMINAL_BACKPRESSURE epoch=%0d actual_AON_copy=held debug=held network=held",allocatedEpoch[which]);
      result_ready[which]=1;
      while(results[which]==beforeCount) tick(); result_ready[which]=0;
      repeat(30) begin
        tick();
        if(!busy || fabricTerminals!=fabricBefore || ddrRetirementPermit || timerRetirementPermit)
          $fatal(1,"FIXED_RETIREMENT_WITHOUT_FIXED_CLOCK_RECEIPT");
      end
      ddrPaused=0; fixedWait=0;
      while(!ddrRetirementPermit) begin
        tick(); fixedWait=fixedWait+1;
        if(fixedWait==256) $fatal(1,"FIXED_DDR_RETIREMENT_WAIT aonConsumed=%b owner=%b/%b decided=%b/%b cmdSent=%b terminal=%b retired=%b obsIdle=%b canceled=%b clocks=%b/%b join=%b/%b fixedPermit=%b/%b fault=%b/%b qualifiedOnce=%b",
          dut.runtime.io_terminalConsumedAtAon,dut.ddrQualifier.owned_1,dut.ddrQualifier.owned,
          dut.ddrQualifier.decisionChosen,dut.ddrQualifier.decided,dut.ddrQualifier.decisionSent,
          dut.ddrQualifier.terminalReceived,dut.ddrQualifier.retiredReceived,
          dut.ddrQualifier._observation_sourceIdle,dut.ddrQualifier.completion_bits_canceled,ddrClock,timebaseClock,
          dut.sequencer.retirementPermit,retirementPermit,ddrRetirementPermit,timerRetirementPermit,
          dut.ddrQualifier.fault,dut.timerQualifier.fault,dut.ddrQualifier.qualifiedOnce);
      end
      repeat(20) begin
        tick();
        if(!busy || fabricTerminals!=fabricBefore || timerRetirementPermit)
          $fatal(1,"FIXED_TIMER_RETIREMENT_WHILE_PAUSED");
      end
      timebasePaused=0; fixedWait=0;
      // Permit is a fabric-domain level that may last only until the actual
      // terminal fire. An unrelated AON sampling edge may legitimately miss it.
      // The monotonically counted real terminal acceptance is durable evidence.
      while(!timerRetirementPermit && fabricTerminals==fabricBefore) begin
        tick(); fixedWait=fixedWait+1;
        if(fixedWait==256) $fatal(1,"FIXED_TIMER_RETIREMENT_WAIT aonConsumed=%b owner=%b/%b decided=%b/%b cmdSent=%b terminal=%b retired=%b obsIdle=%b canceled=%b clocks=%b/%b join=%b/%b fixedPermit=%b/%b fault=%b/%b qualifiedOnce=%b",
          dut.runtime.io_terminalConsumedAtAon,dut.timerQualifier.owned_1,dut.timerQualifier.owned,
          dut.timerQualifier.decisionChosen,dut.timerQualifier.decided,dut.timerQualifier.decisionSent,
          dut.timerQualifier.terminalReceived,dut.timerQualifier.retiredReceived,
          dut.timerQualifier._observation_sourceIdle,dut.timerQualifier.completion_bits_canceled,ddrClock,timebaseClock,
          dut.sequencer.retirementPermit,retirementPermit,ddrRetirementPermit,timerRetirementPermit,
          dut.ddrQualifier.fault,dut.timerQualifier.fault,dut.timerQualifier.qualifiedOnce);
      end
      if(!timerLocalReplyBlocked || timerLocalIdle || timerRequests==timerResponses)
        $fatal(1,"FIXED_POST_RESUME_OWNER_NOT_RETAINED_THROUGH_RETIREMENT");
      $display("I1_FIXED_POST_RESUME_OWNER real_MMIO=%0d/%0d fixed_reply_held=1 old_epoch_retirement=1",timerRequests,timerResponses);
      while(fabricTerminals==fabricBefore || debugTerminals!=fabricBefore+1 ||
          debugRetirementReceipts!=fabricBefore+1 || networkRetirements!=fabricBefore+1) begin
        if(!busy || request_ready!=0) $fatal(1,"I1_PACKET_AON_REOPEN_BEFORE_ACTUAL_JOIN");
        tick();
      end
      while(busy || debugBusy || epochBusy) tick();
      holdTimerLocalReply=0;
      repeat(12) tick();
      if(results[which]!=beforeCount+1 || fabricTerminals!=fabricBefore+1 || result_valid!=0 ||
          debugTerminals!=fabricTerminals || debugRetirementReceipts!=fabricTerminals ||
          networkRetirements!=fabricTerminals || runtimePause || !released || rxAdmissionClosed)
        $fatal(1,"I1_PACKET_TERMINAL_NOT_EXACTLY_ONCE");
      $display("I1_PACKET_JOINED_RETIREMENT epoch=%0d AON=%0d debug=%0d receipt=%0d network=%0d fabric=%0d",
          allocatedEpoch[which],results[0]+results[1],debugTerminals,debugRetirementReceipts,networkRetirements,fabricTerminals);
    end
  endtask
  task finishBlockedDmi(input integer oldRequests,input integer oldResponses);
    begin
      while(sourceRequests==oldRequests) debugTick(); debug_request_valid=0;
      while(sourceResponses==oldResponses) debugTick(); repeat(8) debugTick();
      if(sourceRequests!=oldRequests+1 || sourceResponses!=oldResponses+1)
        $fatal(1,"I1_PACKET_NEW_DMI_NOT_EXACTLY_ONCE_AFTER_RECEIPT");
    end
  endtask
  task rx_byte(input [7:0] value);
    begin @(negedge rxClock); gmiiRxValid=1; gmiiRxData=value; end
  endtask
  task send_frame(input bit corrupt);
    integer j; reg [31:0] crc,fcs;
    begin
      crc=32'hffffffff;
      for(j=0;j<7;j=j+1) rx_byte(8'h55);
      rx_byte(8'hd5);
      for(j=0;j<BODY_BYTES;j=j+1) begin rx_byte(packet_byte(0,j)); crc=crc_byte(crc,packet_byte(0,j)); end
      fcs=~crc; if(corrupt) fcs=fcs^32'h00010000;
      for(j=0;j<4;j=j+1) rx_byte((fcs>>(j*8))&255);
      @(negedge rxClock); gmiiRxValid=0; gmiiRxData=0;
      repeat(12) @(negedge rxClock);
    end
  endtask
  task checkRam;
    integer j; reg [63:0] data;
    begin
      for(j=0;j<BODY_BYTES;j=j+1) begin
        data=memory_read((testCase==3 ? TX_ADDRESS : RX_ADDRESS)-32'h80200000+(j&~7));
        if(data[(j%8)*8+:8]!==packet_byte(testCase==3,j))
          $fatal(1,"NETWORK_ORACLE_PAYLOAD backing RAM byte=%0d got=%h",j,data[(j%8)*8+:8]);
      end
      data=memory_read(32'h3038);
      if(data[63:32]!== (negative==3 ? GUARD_DATA^32'h1 : GUARD_DATA))
        $fatal(1,"NETWORK_ORACLE_GUARD dirty same-line neighbor got=%h expected=%h",data[63:32],GUARD_DATA);
      if(testCase!=3 && (packetLineProbes<1 || packetLineProbeDataBeats!=8))
        $fatal(1,"I1_PACKET_RX_DIRTY_PROBE_DATA_ORACLE probes=%0d beats=%0d",packetLineProbes,packetLineProbeDataBeats);
      if(testCase==3 && (packetTxLineProbes<1 || packetTxLineProbeDataBeats!=8))
        $fatal(1,"I1_PACKET_TX_DIRTY_PROBE_DATA_ORACLE probes=%0d beats=%0d",packetTxLineProbes,packetTxLineProbeDataBeats);
      $display("I1_PACKET_HOME_MEMORY case=%0d request=%0d reply=%0d RX_probe=%0d/%0d TX_probe=%0d/%0d preserved_guard=%h",
          testCase,packetRequests,packetResponses,packetLineProbes,packetLineProbeDataBeats,packetTxLineProbes,packetTxLineProbeDataBeats,data[63:32]);
    end
  endtask
  integer beforePrepares,beforeRequests,beforeResponses,beforeHeartbeats,init_i;
  reg [31:0] token;
  initial begin
    if(!$value$plusargs("rom=%s",rom_path)) $fatal(1,"I1_PACKET_ROM_REQUIRED");
    if($value$plusargs("case=%d",testCase)) begin end
    if($value$plusargs("negative=%d",negative)) begin end
    if(testCase<0 || testCase>3) $fatal(1,"I1_PACKET_UNKNOWN_CASE");
    $readmemh(rom_path,rom);
    for(init_i=0;init_i<8192;init_i=init_i+1) ram[init_i]=0;
    ram['h5000>>3]=(testCase==3 ? 1 : 0);
    for(init_i=0;init_i<2;init_i=init_i+1) begin request_bits[init_i]=0; resume_bits[init_i]=0; cancel_bits[init_i]=0;
      resume_epoch[init_i]=0; cancel_epoch[init_i]=0; allocatedEpoch[init_i]=0; end
    if(testCase==3) begin holdTxControlLast=1; holdTxDataLast=1; end
    else holdRxStatusLast=1;
    boot();
    while(!timerResponseBlocked) fabricTick();
    if(timerRequests!=1 || timerResponses!=0 || timerDestinationRequests!=1 || timerDestinationResponses!=1 ||
        timerFabricIdle || !timerLocalIdle) $fatal(1,"FIXED_TIMER_ACCEPTED_SOURCE_REPLY_OWNER_MISSING");
    snapshotBefore=timerSnapshot; repeat(30) tick();
    if(timerSnapshot<=snapshotBefore) $fatal(1,"FIXED_TIMER_CONTINUOUS_SNAPSHOT_STALLED_WITH_MMIO");
    timebasePaused=1; holdTimerResponse=0;
    while(timerResponses==0) fabricTick();
    while(timerRequests<2) fabricTick();
    repeat(20) begin tick();
      if(timerResponses!=1 || timerDestinationRequests!=1 || timerFabricIdle || held_valid!=0)
        $fatal(1,"FIXED_TIMER_PAUSED_OLD_REQUEST_FALSE_IDLE");
    end
    token=32'h71000000+testCase; lane=testCase%2; beforePrepares=fabricPrepares;
    if(testCase!=3) begin
      send_frame(0);
      while(!rxStatusLastBlocked) fabricTick();
      if(acceptedFrames!=1 || statusWords!=5 || rxDataFrames!=1 || packetRequests!=0)
        $fatal(1,"I1_PACKET_OLD_RX_STATUS_SETUP accepted=%0d status=%0d requests=%0d",acceptedFrames,statusWords,packetRequests);
      requestEpoch(lane,token); releaseOldTimer();
      while(!rxAdmissionClosed) tick();
      noPrepareWhileOld(beforePrepares,40);
      $display("I1_PACKET_RX_STATUS_HELD status=%0d accepted=%0d AON_epoch=%0d",statusWords,acceptedFrames,allocatedEpoch[lane]);
      if(testCase==1) begin
        while(!timeoutSelected) noPrepareWhileOld(beforePrepares,1);
        if(aonCycles-acceptedCycle[lane]!=4096 || cancels[lane]!=0 || fabricCancels!=0)
          $fatal(1,"I1_PACKET_TRUE_AON_TIMEOUT_ORACLE elapsed=%0d",aonCycles-acceptedCycle[lane]);
        $display("I1_PACKET_AON_TIMEOUT elapsed_aon_edges=%0d old_status_retained=1",aonCycles-acceptedCycle[lane]);
        noPrepareWhileOld(beforePrepares,20);
      end
      holdAxiWriteResponse=1; holdRxStatusLast=0;
      while(!axiWriteResponseBlocked) fabricTick();
      if(packetRequests==0 || packetRequests==packetResponses || b_count==0 || dmaOwnersIdle ||
          b_addr[b_head]<32'h3000 || b_addr[b_head]>=32'h3040)
        $fatal(1,"I1_PACKET_RX_ACCEPTED_B_OWNER_NOT_ESTABLISHED addr=%h",b_addr[b_head]);
      pauseOldUi();
      if(testCase==2) cancelEpoch(lane,token);
      noPrepareWhileOld(beforePrepares,40);
      send_frame(0);
      if(acceptedFrames!=1 || closedDrops!=1 || statusWords!=6 || statusFrames!=1)
        $fatal(1,"I1_PACKET_CLOSED_ADMISSION_CONSERVATION");
      // The first B may acknowledge dirty CPU probe writeback, a genuine
      // dependency of the packet write, rather than the packet payload itself.
      $display("I1_PACKET_RX_B_HELD requests=%0d replies=%0d packet_dependency_B_owners=%0d addr=%h",
          packetRequests,packetResponses,b_count,b_addr[b_head]);
      holdAxiWriteResponse=0;
    end else begin
      while(!axiReadResponseBlocked) fabricTick();
      if(packetRequests==0 || packetRequests==packetResponses || dmaTxIdle || sending<0 ||
          rd_addr[sending]<32'h4000 || rd_addr[sending]>=32'h4040)
        $fatal(1,"I1_PACKET_TX_ACCEPTED_R_OWNER_NOT_ESTABLISHED addr=%h",rd_addr[sending]);
      requestEpoch(lane,token); releaseOldTimer(); pauseOldUi(); noPrepareWhileOld(beforePrepares,40);
      $display("I1_PACKET_TX_PREFETCH_HELD requests=%0d replies=%0d real_R_id=%0d addr=%h",
          packetRequests,packetResponses,io_ddrAxi_r_bits_id,rd_addr[sending]);
      holdAxiReadResponse=0;
      while(!txControlLastBlocked) fabricTick();
      noPrepareWhileOld(beforePrepares,40);
      if(txControlWords!=5 || dmaTxIdle || txFrames!=0) $fatal(1,"I1_PACKET_TX_CONTROL_TAIL_OWNER");
      holdTxControlLast=0;
      while(!txDataLastBlocked) fabricTick();
      noPrepareWhileOld(beforePrepares,40);
      if(dmaTxIdle || txFrames!=0) $fatal(1,"I1_PACKET_TX_DATA_TAIL_OWNER");
      $display("I1_PACKET_TX_TAIL_HELD controls=%0d memory=%0d/%0d",txControlWords,packetRequests,packetResponses);
      holdTxDataLast=0;
      while(!dmaTxIdle) fabricTick();
      if(txDrained || txFrames!=0) $fatal(1,"I1_PACKET_TX_WIRE_TAIL_FALSE_DRAIN");
    end
    if(testCase==0 || testCase==3) begin
      waitHeld(lane); beforeHeartbeats=heartbeats;
      beforeRequests=sourceRequests; beforeResponses=sourceResponses; presentBlockedDmi();
      repeat(40) begin tick();
        if(!held_valid[lane] || sourceRequests!=beforeRequests || debug_request_ready || heartbeats!=beforeHeartbeats)
          $fatal(1,"I1_PACKET_HELD_ADMITTED_CPU_OR_DEBUG");
      end
      @(negedge alwaysOnClock); resume_bits[lane]=token; resume_epoch[lane]=allocatedEpoch[lane]+1;
      resume_valid[lane]=1;
      repeat(20) begin tick();
        if(resume_ready[lane] || result_valid!=0 || !held_valid[lane]) $fatal(1,"FIXED_WRONG_EPOCH_RESUME_ACCEPTED");
      end
      resume_valid[lane]=0;
      resumeEpoch(lane,token);
      fork
        terminal(lane,token,0,0);
        finishBlockedDmi(beforeRequests,beforeResponses);
      join
    end else terminal(lane,token,1,testCase==1);
    if(fabricPrepares!=beforePrepares+1 || fabricTerminals!=1 || requests[lane]!=1 || results[lane]!=1 ||
        fabricCancels!=(testCase==1 || testCase==2 ? 1 : 0) || cancels[lane]!=(testCase==2 ? 1 : 0))
      $fatal(1,"I1_PACKET_EPOCH_CONSERVATION");
    checkRam();
    readbackAt(RX_ADDRESS+60,GUARD_DATA);
    readbackAt(testCase==3 ? TX_ADDRESS : RX_ADDRESS,testCase==3 ? 32'h23222120 : 32'h83828180);
    writeCheckCommand();
    repeat(30) tick();
    if(cpuRxChecks!=(testCase==3 ? 0 : 1) || cpuGuardChecks!=(testCase==3 ? 0 : 1) ||
        cpuTxChecks!=(testCase==3 ? 1 : 0))
      $fatal(1,"I1_PACKET_CPU_READBACK_RETIREMENT_COUNT RX=%0d guard=%0d TX=%0d",
          cpuRxChecks,cpuGuardChecks,cpuTxChecks);
    if(packetRequests!=PACKET_WORDS || packetResponses!=PACKET_WORDS || !dmaOwnersIdle ||
        packetControlRequests!=packetControlResponses || sourceRequests!=sourceResponses || memoryRequests!=memoryResponses ||
        aw_count!=0 || w_count!=0 || b_count!=0 || owners!=0 || sending!=-1 ||
        write_count!=b_completed || read_beats!=expectedReadBeats ||
        readResponsesAccepted!=read_beats || writeResponsesAccepted!=b_completed ||
        networkRetirements!=1 || debugTerminals!=1 || debugRetirementReceipts!=1 || busy || epochBusy)
      $fatal(1,"I1_PACKET_FINAL_CONSERVATION packet=%0d/%0d AXI_R=%0d/%0d AXI_B=%0d/%0d",
          packetRequests,packetResponses,read_beats,expectedReadBeats,b_completed,write_count);
    if(testCase==3) begin
      if(txFrames!=1 || txControlWords!=6 || txDataFrames!=1 || acceptedFrames!=0 || packetWrites!=0 || packetReads!=8)
        $fatal(1,"I1_PACKET_FINAL_TX_CONSERVATION");
    end else if(acceptedFrames!=1 || droppedFrames!=1 || closedDrops!=1 || statusWords!=6 || statusFrames!=1 ||
        rxDataFrames!=1 || packetWrites!=8 || packetReads!=0 || txFrames!=0)
      $fatal(1,"I1_PACKET_FINAL_RX_CONSERVATION");
    if(timerRequests!=timerResponses || timerDestinationRequests!=timerRequests ||
        timerDestinationResponses!=timerRequests || timerHeartbeatReads+3!=timerRequests ||
        !timerFabricIdle || !timerLocalIdle || !timerIrq || ddrBusy || timerBusy ||
        !ddrFabricOwnersIdle || !ddrLocalOwnersIdle || !ddrFabricEmpty || !ddrLocalEmpty)
      $fatal(1,"FIXED_FINAL_INDEPENDENT_LEDGER requests=%0d replies=%0d local=%0d/%0d CPU=%0d",
        timerRequests,timerResponses,timerDestinationRequests,timerDestinationResponses,timerHeartbeatReads);
    if(wBeforeAwBeats==0 || aw_stalls==0 || w_stalls==0 || ar_stalls==0)
      $fatal(1,"FIXED_AXI_CHANNEL_COVERAGE_MISSING W_before_AW=%0d AW_stalls=%0d W_stalls=%0d AR_stalls=%0d",
        wBeforeAwBeats,aw_stalls,w_stalls,ar_stalls);
    $display("I1_FIXED_AXI_CHANNEL_COVERAGE W_before_AW_beats=%0d tails=%0d AW_stalls=%0d W_stalls=%0d AR_stalls=%0d",
        wBeforeAwBeats,wBeforeAwTails,aw_stalls,w_stalls,ar_stalls);
    $display("I1_FIXED_FINAL_LEDGER timer=%0d/%0d UI_read=%0d source_read=%0d UI_B=%0d source_B=%0d retained_IRQ=1",
        timerRequests,timerResponses,read_beats,readResponsesAccepted,b_completed,writeResponsesAccepted);
    // Coordinated cold reset clears all epoch receipts even with both fixed
    // clocks stalled. No unilateral hot-reset support is claimed.
    ddrPaused=1; timebasePaused=1; cpuPaused=1; reset=1; #1; start=0; repeat(8) tick();
    if(ddrBusy || timerBusy || ddrQualified_valid || timerQualified_valid || held_valid!=0 || result_valid!=0)
      $fatal(1,"FIXED_COMMON_RESET_RETAINED_STALE_PROOF");
    reset=0; repeat(8) tick();
    if(ddrLocalReady || timerLocalReady || ddrQualified_valid || timerQualified_valid)
      $fatal(1,"FIXED_PAUSED_RESET_RELEASE_FALSE_READY");
    $display("I1_FIXED_RESET common_cold=1 fixed_clocks_paused=1 stale_proofs_cleared=1");
    $display("I1_RUNTIME_FIXED_PASS case=%0d clocks=%0d/%0d/%0d/%0d/%0d/%0d/%0d/%0d packet=%0d/%0d AXI_R=%0d AXI_B=%0d cpu_checked=%0d",
        testCase,cpuHalf,fabricHalf,aonHalf,debugHalf,rxHalf,txHalf,ddrHalf,timebaseHalf,packetRequests,packetResponses,read_beats,b_completed,guestChecked);
    $finish;
  end
  initial begin #10000000; $fatal(1,"I1_PACKET_GLOBAL_TIMEOUT"); end
endmodule
