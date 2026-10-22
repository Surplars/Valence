`timescale 1ns/1ps
// Adapter + real three-mailbox/four-FIFO boundary unit. MAC-local admission and
// upstream owner inputs below are explicit models, not a platform gate proof.
module fixed_mac_epoch_adapter_tb;
  reg fabric=0,fixed125=0,reset=1,fabric_run=1,fixed_run=1;
  integer fabric_half=10,negative=0,faultcase=0;
  initial begin
    if($value$plusargs("fabric_half=%d",fabric_half))begin end
    if($value$plusargs("negative=%d",negative))begin end
    if($value$plusargs("faultcase=%d",faultcase))begin end
    forever #(fabric_half)if(fabric_run)fabric=~fabric;
  end
  initial begin #0.7;forever #4 if(fixed_run)fixed125=~fixed125;end
  reg owner=0,rxVote=0,txVote=0,parkVote=0,txClosed=0,rawHeld=0,terminal=0,retired=0,holdFinal=0;
  reg [7:0] epoch=0;
  reg [3:0] svalid=0,dready=0,slast=0;
  wire [3:0] sready,dvalid,dlast;
  reg [31:0] sdata[0:3];wire [31:0] ddata[0:3];
  reg [3:0] skeep[0:3];wire [3:0] dkeep[0:3];
  integer sent[0:3],received[0:3],target[0:3];
  reg perturb_idle=0,macirq=0;
  wire rxstop,txstop,parkreq,irq,txDrained,rxDrained,parked,released,fault;
  wire commandFire,receiptFire,snapshotBlocked,snapshotFire;
  wire [15:0] commandEpoch,commandSerial,receiptEpoch,receiptSerial,snapshotEpoch,snapshotSerial;
  wire crx,ctx,cp,rrx,rtx,rp,snapshotReleased;
  reg csrValid=0,csrReady=1,macReply=0;
  wire csrAccepted,csrResponse,csrError,macRequest,macResponseReady;
  wire [63:0] csrData;
  integer commands=0,receipts=0,snapshots=0,lastSerial=0,releaseSnapshots=0;
  integer csrRequests=0,csrReplies=0,macRequests=0;
  reg [34:0] ledger[0:31];
  reg releaseSeen=0,expectFault=0;
  integer heldSamples=0,earlyCancel=0;
  CommonFixedMacAdapterFixture dut(
    .fabricClock(fabric),.fixedClock(fixed125),.commonReset(reset),
    .owner_valid(owner),.owner_bits(epoch),.rxStop(rxVote),.txStop(txVote),.park(parkVote),
    .txClosed(txClosed),.rawHeld(rawHeld),.terminalConsumed(terminal),.retired(retired),
    .holdFinalSnapshot(holdFinal),.txDrained(txDrained),.rxDrained(rxDrained),.parked(parked),
    .released(released),.fault(fault),.commandFire(commandFire),.receiptFire(receiptFire),
    .commandBits_epoch(commandEpoch),.commandBits_serial(commandSerial),
    .commandBits_rxStop(crx),.commandBits_txStop(ctx),.commandBits_park(cp),
    .receiptBits_epoch(receiptEpoch),.receiptBits_serial(receiptSerial),
    .receiptBits_rxStop(rrx),.receiptBits_txStop(rtx),.receiptBits_park(rp),
    .snapshotBlocked(snapshotBlocked),.snapshotFire(snapshotFire),
    .snapshotBits_command_epoch(snapshotEpoch),.snapshotBits_command_serial(snapshotSerial),
    .snapshotBits_released(snapshotReleased),
    .registers_request_valid(csrValid),.registers_request_ready(csrAccepted),
    .registers_request_bits_address(64'h10040000),.registers_request_bits_write(1'b0),
    .registers_request_bits_size(3'd3),.registers_request_bits_data(64'b0),
    .registers_request_bits_byteEnable(8'hff),.registers_response_ready(csrReady),
    .registers_response_valid(csrResponse),.registers_response_bits_data(csrData),
    .registers_response_bits_error(csrError),.macRegisters_request_ready(!macReply),
    .macRegisters_request_valid(macRequest),.macRegisters_response_valid(macReply),
    .macRegisters_response_ready(macResponseReady),.macRegisters_response_bits_data(64'h123456789abcdef0),
    .macRegisters_response_bits_error(1'b0),
    .streams_txData_valid(svalid[0]),
    .macStreams_txData_valid(dvalid[0]),
    .streams_txData_ready(sready[0]),
    .macStreams_txData_ready(dready[0]),
    .streams_txData_bits_data(sdata[0]),
    .macStreams_txData_bits_data(ddata[0]),
    .streams_txData_bits_keep(skeep[0]),
    .macStreams_txData_bits_keep(dkeep[0]),
    .streams_txData_bits_last(slast[0]),
    .macStreams_txData_bits_last(dlast[0]),
    .streams_txControl_valid(svalid[1]),
    .macStreams_txControl_valid(dvalid[1]),
    .streams_txControl_ready(sready[1]),
    .macStreams_txControl_ready(dready[1]),
    .streams_txControl_bits_data(sdata[1]),
    .macStreams_txControl_bits_data(ddata[1]),
    .streams_txControl_bits_keep(skeep[1]),
    .macStreams_txControl_bits_keep(dkeep[1]),
    .streams_txControl_bits_last(slast[1]),
    .macStreams_txControl_bits_last(dlast[1]),
    .macStreams_rxData_valid(svalid[2]),
    .streams_rxData_valid(dvalid[2]),
    .macStreams_rxData_ready(sready[2]),
    .streams_rxData_ready(dready[2]),
    .macStreams_rxData_bits_data(sdata[2]),
    .streams_rxData_bits_data(ddata[2]),
    .macStreams_rxData_bits_keep(skeep[2]),
    .streams_rxData_bits_keep(dkeep[2]),
    .macStreams_rxData_bits_last(slast[2]),
    .streams_rxData_bits_last(dlast[2]),
    .macStreams_rxStatus_valid(svalid[3]),
    .streams_rxStatus_valid(dvalid[3]),
    .macStreams_rxStatus_ready(sready[3]),
    .streams_rxStatus_ready(dready[3]),
    .macStreams_rxStatus_bits_data(sdata[3]),
    .streams_rxStatus_bits_data(ddata[3]),
    .macStreams_rxStatus_bits_keep(skeep[3]),
    .streams_rxStatus_bits_keep(dkeep[3]),
    .macStreams_rxStatus_bits_last(slast[3]),
    .streams_rxStatus_bits_last(dlast[3]),
    .admission_rxStopRequest(rxstop),
    .admission_txStopRequest(txstop),
    .admission_rxDrained(rxstop),
    .admission_txDrained(txstop&&!perturb_idle),
    .admission_released(!rxstop&&!txstop),
    .controlPark_request(parkreq),
    .controlPark_released(!parkreq),
    .controlPark_csrDrained(1'b1),
    .controlPark_configDrained(1'b1),
    .controlPark_mdioDrained(1'b1),
    .controlPark_phyParked(parkreq),
    .controlPark_phyFault(4'b0),
    .controlPark_mediaSettled(1'b1),
    .controlPark_statisticsPending(4'b0),
    .controlPark_parked(parkreq),
    .macIrq(macirq),
    .irq(irq)
  );
  function automatic [31:0] payload(input integer c,input integer n);
    payload=32'h9e370000^(c*32'h1234567)^(n*32'h1327);
  endfunction
  generate for(genvar c=0;c<4;c=c+1)begin: channel
    wire sc=c<2?fabric:fixed125,dc=c<2?fixed125:fabric;
    always @*begin
      svalid[c]=!reset&&sent[c]<target[c];sdata[c]=payload(c,sent[c]);
      skeep[c]=(sent[c]%15)+1;slast[c]=(sent[c]%13)==12;
    end
    always @(posedge sc)if(!reset&&svalid[c]&&sready[c])sent[c]=sent[c]+1;
    reg hv=0;reg [36:0] held;
    always @(posedge dc)if(!reset)begin
      if(hv&&(!dvalid[c]||{ddata[c],dkeep[c],dlast[c]}!==held))$fatal(1,"EPOCH_ORACLE_STREAM_STABILITY");
      hv=dvalid[c]&&!dready[c];if(hv)begin held={ddata[c],dkeep[c],dlast[c]};heldSamples=heldSamples+1;end
      if(dvalid[c]&&dready[c])begin
        if(received[c]>=sent[c]||ddata[c]!==payload(c,received[c])||
           dkeep[c]!==((received[c]%15)+1)||dlast[c]!==((received[c]%13)==12))
          $fatal(1,"EPOCH_ORACLE_STREAM_PAYLOAD");
        received[c]=received[c]+1;
      end
    end
  end endgenerate
  always @(posedge fixed125)if(!reset)begin
    if(macReply&&macResponseReady)macReply<=0;
    if(macRequest&&!macReply)begin macReply<=1;macRequests=macRequests+1;end
  end
  reg [15:0] observedSerial;
  reg observedReleased;
  always @(posedge fabric)if(!reset)begin
    if(fault&&!expectFault)$fatal(1,"EPOCH_ORACLE_UNEXPECTED_FAULT epoch=%0d serial=%0d",epoch,lastSerial);
    if(commandFire)begin
      observedSerial=commandSerial;
      if(negative==2&&commands==1)begin observedSerial=lastSerial;$display("EPOCH_NEGATIVE_DUPLICATE_SERIAL");end
      if(commandEpoch!==epoch||observedSerial!=lastSerial+1)$fatal(1,"EPOCH_ORACLE_COMMAND_SERIAL");
      ledger[commands]={commandEpoch,commandSerial,crx,ctx,cp};commands=commands+1;lastSerial=commandSerial;
      if(cp&&!rawHeld)$fatal(1,"EPOCH_ORACLE_PARK_WITHOUT_LIVE_HELD");
    end
    if(snapshotFire)begin
      snapshots=snapshots+1;
      if(snapshotReleased&&snapshotSerial==lastSerial&&snapshotEpoch==epoch)begin releaseSnapshots=releaseSnapshots+1;releaseSeen=1;end
    end
    if(receiptFire)begin
      if(receipts>=commands||{receiptEpoch,receiptSerial,rrx,rtx,rp}!==ledger[receipts])$fatal(1,"EPOCH_ORACLE_RECEIPT_IDENTITY");
      if(!rrx&&!rtx&&!rp&&!releaseSeen)$fatal(1,"EPOCH_ORACLE_RECEIPT_BEFORE_FINAL_SNAPSHOT");
      receipts=receipts+1;
    end
    observedReleased=released;
    if(negative==1&&snapshotBlocked)begin observedReleased=1;$display("EPOCH_NEGATIVE_OLD_RELEASED_SNAPSHOT");end
    if(negative==3&&!terminal&&parked)begin observedReleased=1;$display("EPOCH_NEGATIVE_TERMINAL_BACKPRESSURE");end
    if(negative==4&&snapshotBlocked)begin observedReleased=1;$display("EPOCH_NEGATIVE_FINAL_SNAPSHOT_BACKPRESSURE");end
    if(observedReleased&&(!terminal||holdFinal||!releaseSeen||receipts!=commands))
      $fatal(1,"EPOCH_ORACLE_RELEASE_OWNERSHIP");
    if(csrValid&&csrAccepted)csrRequests=csrRequests+1;
    if(csrResponse&&csrReady)begin
      if(csrReplies>=csrRequests||csrError||csrData!==64'h123456789abcdef0)$fatal(1,"EPOCH_ORACLE_CSR_REPLY");
      csrReplies=csrReplies+1;
    end
  end
  task ft;begin @(posedge fabric);#1;@(negedge fabric);end endtask
  task drain;begin
    while(received[0]!=target[0]||received[1]!=target[1]||received[2]!=target[2]||received[3]!=target[3])ft();
    repeat(20)ft();
  end endtask
  integer n,beforeReceipts,beforeSnapshots;
  initial begin
    for(n=0;n<4;n=n+1)begin sent[n]=0;received[n]=0;target[n]=0;end
    repeat(10)ft();reset=0;repeat(10)ft();
    // Preserve old destination/prefetch owners: TX stop cannot cross old words.
    target[0]=8;target[1]=8;dready=4'b1100;
    while(sent[0]!=8||sent[1]!=8)ft();
    owner=1;epoch=1;rxVote=1;txVote=1;txClosed=1;
    repeat(30)begin ft();if(txstop||txDrained)$fatal(1,"EPOCH_ORACLE_EARLY_TX_STOP");end
    dready=15;drain();while(!txDrained||!rxDrained)ft();
    rawHeld=1;parkVote=1;while(!parked)ft();
    // A real old-serial released observation is consumed but cannot replace
    // this command's proof. Deliberate unit-only adversarial endpoint injection.
    force dut.adapter.io_boundary_observation_valid=1'b1;
    force dut.adapter.io_boundary_observation_bits_command_epoch=16'd1;
    force dut.adapter.io_boundary_observation_bits_command_serial=16'd1;
    force dut.adapter.io_boundary_observation_bits_released=1'b1;
    ft();if(released||fault)$fatal(1,"EPOCH_ORACLE_STALE_SNAPSHOT_USED");
    release dut.adapter.io_boundary_observation_valid;
    release dut.adapter.io_boundary_observation_bits_command_epoch;
    release dut.adapter.io_boundary_observation_bits_command_serial;
    release dut.adapter.io_boundary_observation_bits_released;
    repeat(20)ft();while(!parked)ft();
    // A matched false observation must replace previously true drain proof.
    perturb_idle=1;while(txDrained)ft();repeat(20)ft();perturb_idle=0;while(!parked||!txDrained)ft();
    beforeReceipts=receipts;repeat(40)begin ft();if(released||receipts!=beforeReceipts)$fatal(1,"EPOCH_ORACLE_TERMINAL_NOT_CONSUMED");end
    holdFinal=1;terminal=1;rxVote=0;txVote=0;parkVote=0;rawHeld=0;txClosed=0;
    while(!snapshotBlocked)ft();
    if(rxstop||txstop||parkreq||released)$fatal(1,"EPOCH_ORACLE_FIXED_RELEASE_VS_RECEIPT");
    beforeReceipts=receipts;
    // New data and accepted CSR reply are deliberately live during old release.
    target[2]=8;target[3]=8;dready=3;csrReady=0;csrValid=1;
    while(csrRequests==0)ft();csrValid=0;
    while(!csrResponse)ft();
    repeat(40)begin ft();if(released||receipts!=beforeReceipts)$fatal(1,"EPOCH_ORACLE_FINAL_SNAPSHOT_OWNER");end
    macirq=1;repeat(10)ft();if(!irq)$fatal(1,"EPOCH_ORACLE_IRQ_LEVEL");
    @(negedge fabric);fabric_run=0;#800;
    if(!irq||released)$fatal(1,"EPOCH_ORACLE_PAUSED_FABRIC_LEVEL");fabric_run=1;repeat(10)ft();
    holdFinal=0;while(!released)ft();
    if(received[2]!=0||received[3]!=0||csrReplies!=0)$fatal(1,"EPOCH_ORACLE_NEW_OWNER_TEST_MISSING");
    beforeSnapshots=snapshots;repeat(50)ft();
    if(snapshots!=beforeSnapshots)$fatal(1,"EPOCH_ORACLE_RELEASE_PUBLICATION_RESTARTED");
    retired=1;ft();retired=0;owner=0;terminal=0;
    csrReady=1;dready=15;drain();while(csrReplies!=csrRequests)ft();
    // Cancel a desired PARK after live raw-held disappears: no queued park owner.
    owner=1;epoch=2;rxVote=1;txVote=1;txClosed=1;releaseSeen=0;
    while(!txDrained||!rxDrained)ft();parkVote=1;rawHeld=0;beforeReceipts=receipts;
    repeat(30)begin ft();if(parkreq||parked||receipts!=beforeReceipts)$fatal(1,"EPOCH_ORACLE_UNSENT_PARK_CANCEL");end
    // Real accepted CSR reply blocks the boundary after PARK becomes desired.
    // No PARK command may be pre-queued and strand the following cancellation.
    csrReady=0;csrValid=1;while(csrRequests!=2)ft();csrValid=0;
    while(!csrResponse)ft();rawHeld=1;
    repeat(30)begin ft();if(parkreq||parked||receipts!=beforeReceipts||commands!=4)
      $fatal(1,"EPOCH_ORACLE_UNSENT_PARK_CSR_OWNER");end
    earlyCancel=1;terminal=1;rxVote=0;txVote=0;parkVote=0;txClosed=0;rawHeld=0;
    while(!released)ft();retired=1;ft();retired=0;owner=0;terminal=0;repeat(30)ft();
    if(csrReplies!=1||!csrResponse)$fatal(1,"EPOCH_ORACLE_CANCEL_FRESH_CSR_OWNER");
    csrReady=1;while(csrReplies!=2)ft();
    $display("FIXED_MAC_UNSENT_PARK_CANCEL csr_owner_retained=1 parked_commands=0 released_before_fresh_reply=1");
    if(commands!=receipts||csrRequests!=2||csrReplies!=2||macRequests!=2||releaseSnapshots!=2||heldSamples==0)
      $fatal(1,"EPOCH_ORACLE_FINAL_CONSERVATION");
    if(faultcase!=0)begin
      expectFault=1;beforeReceipts=receipts;
      if(faultcase==1)begin
        force dut.adapter.io_boundary_observation_valid=1'b1;
        force dut.adapter.io_boundary_observation_bits_command_epoch=16'd1;
        force dut.adapter.io_boundary_observation_bits_command_serial=16'd1;
        force dut.adapter.io_boundary_observation_bits_released=1'b1;
      end else if(faultcase==2)begin
        force dut.adapter.io_boundary_consumed_valid=1'b1;
        force dut.adapter.io_boundary_consumed_bits_epoch=16'd2;
        force dut.adapter.io_boundary_consumed_bits_serial=16'd5;
        force dut.adapter.io_boundary_consumed_bits_rxStop=1'b0;
        force dut.adapter.io_boundary_consumed_bits_txStop=1'b0;
        force dut.adapter.io_boundary_consumed_bits_park=1'b0;
      end else if(faultcase==3)begin
        force dut.adapter.serial=16'hffff;owner=1;epoch=3;rxVote=1;
      end
      repeat(5)ft();if(!fault)$fatal(1,"EPOCH_ORACLE_FAULT_NOT_LATCHED");
      release dut.adapter.io_boundary_observation_valid;
      release dut.adapter.io_boundary_observation_bits_command_epoch;
      release dut.adapter.io_boundary_observation_bits_command_serial;
      release dut.adapter.io_boundary_observation_bits_released;
      release dut.adapter.io_boundary_consumed_valid;
      release dut.adapter.io_boundary_consumed_bits_epoch;
      release dut.adapter.io_boundary_consumed_bits_serial;
      release dut.adapter.io_boundary_consumed_bits_rxStop;
      release dut.adapter.io_boundary_consumed_bits_txStop;
      release dut.adapter.io_boundary_consumed_bits_park;
      release dut.adapter.serial;
      owner=1;epoch=3;rxVote=1;
      repeat(30)begin ft();if(!fault||released||receipts!=beforeReceipts||commands!=5)
        $fatal(1,"EPOCH_ORACLE_FAULT_REOPENED_OWNER");end
      $display("FIXED_MAC_EPOCH_FAULT_PASS case=%0d failed_closed=1",faultcase);
    end
    $display("FIXED_MAC_EPOCH_ADAPTER_PASS fabric_half=%0d commands=%0d receipts=%0d release_snapshots=%0d csr=%0d/%0d held=%0d early_cancel=%0d",fabric_half,commands,receipts,releaseSnapshots,csrRequests,csrReplies,heldSamples,earlyCancel);
    $finish;
  end
  initial begin #2000000;$fatal(1,"EPOCH_ORACLE_TIMEOUT commands=%0d receipts=%0d park=%b fault=%b",commands,receipts,parked,fault);end
endmodule
