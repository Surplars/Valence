`timescale 1ns/1ps
// Real CDC transport. The MAC-local idle/control endpoints here are explicit
// test models, not a real MAC/CPU/DMA proof. Real MAC is tested separately.
module fixed_mac_pipelined_tb;
  reg fabric=0,fixed125=0,reset=1,fabric_run=1,fixed_run=1;
  integer fabric_half=10,negative=0,held_response=1;
  initial begin
    if($value$plusargs("fabric_half=%d",fabric_half))begin end
    if($value$plusargs("negative=%d",negative))begin end
    if($value$plusargs("held_response=%d",held_response))begin end
    forever #(fabric_half)if(fabric_run)fabric=~fabric;
  end
  initial begin #0.7;forever #4 if(fixed_run)fixed125=~fixed125;end
  reg [3:0] svalid=0,directed_ready=0,random_ready=0;
  reg random_phase=0,preload_check=0;
  wire [3:0] dready=random_phase?random_ready:directed_ready;
  integer consecutive[0:3],random_stalls[0:3];
  real preload_time[0:3];
  wire [3:0] sready,dvalid;
  reg [31:0] sdata[0:3]; wire [31:0] ddata[0:3];
  reg [3:0] skeep[0:3]; wire [3:0] dkeep[0:3];
  reg [3:0] slast=0; wire [3:0] dlast;
  integer sent[0:3],received[0:3];
  integer target=0,generation=0;
  real started[0:3],ended[0:3];
  integer window_bytes[0:3];
  reg [3:0] held_valid=0; reg [36:0] held[0:3];
  reg cmdvalid=0,cmdrx=0,cmdtx=0,cmdpark=0,ackready=1,obsready=1,perturb_idle=0,macirq=0;
  reg [15:0] serial=0;
  wire cmdready,ackvalid,ackrx,acktx,ackpark,obsvalid,obsparked,rxstop,txstop,parkreq,irq;
  wire [15:0] ackepoch,ackserial,obsepoch,obsserial;
  wire obsrx,obstx,obspark,obstxdrained,obsrxdrained,obsreleased,obscsr,obsconfig,obsmdio,obsphy,obsmedia;
  wire [3:0] obsfault,obsstats;
  wire [51:0] observation_word={obsepoch,obsserial,obsrx,obstx,obspark,obstxdrained,obsrxdrained,
    obsreleased,obsparked,obscsr,obsconfig,obsmdio,obsphy,obsmedia,obsfault,obsstats};
  reg obs_held_valid=0;
  reg [51:0] obs_held;
  reg check_old_votes=0;
  integer observation_count=0,observation_stall=0,early_release_seen=0,false_seen=0;
  wire csr_idle,tx_storage_idle,rx_consumers_idle,tx_consumers_idle,rx_storage_idle;
  integer command_count=0,ack_count=0,stall_samples=0;
  reg [34:0] commands[0:15];
  FixedMacBoundary dut(
    .fabricClock(fabric),
    .fixedClock(fixed125),
    .commonReset(reset),
    .registers_request_valid(1'b0),
    .registers_request_bits_address(64'b0),
    .registers_request_bits_write(1'b0),
    .registers_request_bits_size(3'd3),
    .registers_request_bits_data(64'b0),
    .registers_request_bits_byteEnable(8'hff),
    .registers_response_ready(1'b1),
    .macRegisters_request_ready(1'b1),
    .macRegisters_response_valid(1'b0),
    .macRegisters_response_bits_data(64'b0),
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
    .command_valid(cmdvalid),
    .command_ready(cmdready),
    .command_bits_epoch(16'd1),
    .command_bits_serial(serial),
    .command_bits_rxStop(cmdrx),
    .command_bits_txStop(cmdtx),
    .command_bits_park(cmdpark),
    .consumed_valid(ackvalid),
    .consumed_ready(ackready),
    .consumed_bits_epoch(ackepoch),
    .consumed_bits_serial(ackserial),
    .consumed_bits_rxStop(ackrx),
    .consumed_bits_txStop(acktx),
    .consumed_bits_park(ackpark),
    .observation_ready(obsready),
    .observation_valid(obsvalid),
    .observation_bits_command_epoch(obsepoch),
    .observation_bits_command_serial(obsserial),
    .observation_bits_command_rxStop(obsrx),
    .observation_bits_command_txStop(obstx),
    .observation_bits_command_park(obspark),
    .observation_bits_txDrained(obstxdrained),
    .observation_bits_rxDrained(obsrxdrained),
    .observation_bits_released(obsreleased),
    .observation_bits_csrDrained(obscsr),
    .observation_bits_configDrained(obsconfig),
    .observation_bits_mdioDrained(obsmdio),
    .observation_bits_phyParked(obsphy),
    .observation_bits_mediaSettled(obsmedia),
    .observation_bits_phyFault(obsfault),
    .observation_bits_statisticsPending(obsstats),
    .observation_bits_parked(obsparked),
    .txProducersClosed(1'b1),
    .controlProducersClosed(1'b1),
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
    .irq(irq),
    .fabricCsrIdle(csr_idle),
    .fabricTxStorageIdle(tx_storage_idle),
    .fabricRxConsumersIdle(rx_consumers_idle),
    .fixedTxConsumersIdle(tx_consumers_idle),
    .fixedRxStorageIdle(rx_storage_idle));
  function automatic [31:0] payload(input integer channel,input integer index,input integer gen);
    payload=32'h9e370000^(channel*32'h1234567)^(index*32'h1327)^(gen*32'h5aa51234);
  endfunction
  generate for(genvar c=0;c<4;c=c+1)begin: channel
    wire source_clock=c<2?fabric:fixed125;
    wire destination_clock=c<2?fixed125:fabric;
    reg [31:0] lfsr=32'h19ad37cf ^ (c*32'h45678);
    reg source_held=0;
    reg [36:0] source_word;
    always @(negedge destination_clock)begin
      lfsr={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
      random_ready[c]=lfsr[0]|lfsr[3];
    end
    always @(posedge source_clock or posedge reset)begin
      if(reset)source_held=0;
      else begin
        if(source_held&&(!svalid[c]||{sdata[c],skeep[c],slast[c]}!==source_word))
          $fatal(1,"BOUNDARY_ORACLE_SOURCE_STABILITY channel=%0d",c);
        source_held=svalid[c]&&!sready[c];
        if(source_held)source_word={sdata[c],skeep[c],slast[c]};
      end
    end
    always @*begin
      svalid[c]=!reset&&(sent[c]<target);
      sdata[c]=payload(c,sent[c],generation);
      skeep[c]=(generation==0&&sent[c]<2048)?4'hf:(sent[c]%15)+1;
      slast[c]=(sent[c]%13)==12;
    end
    always @(posedge source_clock or posedge reset)begin
      if(reset)sent[c]<=0;
      else if(svalid[c]&&sready[c])sent[c]<=sent[c]+1;
    end
    reg [31:0] observed;
    always @(posedge destination_clock or posedge reset)begin
      if(reset)begin received[c]=0;held_valid[c]=0;started[c]=0;ended[c]=0;window_bytes[c]=0;end
      else begin
        if(held_valid[c]&&(!dvalid[c]||{ddata[c],dkeep[c],dlast[c]}!==held[c]))$fatal(1,"BOUNDARY_ORACLE_STABILITY channel=%0d",c);
        held_valid[c]=dvalid[c]&&!dready[c];
        if(held_valid[c])begin held[c]={ddata[c],dkeep[c],dlast[c]};stall_samples=stall_samples+1;end
        if(random_phase&&dvalid[c]&&!dready[c])random_stalls[c]=random_stalls[c]+1;
        if(dvalid[c]&&dready[c])begin
          if(preload_check&&consecutive[c]<16)begin
            if(consecutive[c]>0&&held_response&&$realtime-preload_time[c]!=(c<2?8:2*fabric_half))
              $fatal(1,"BOUNDARY_ORACLE_II preloaded channel=%0d gap=%f",c,$realtime-preload_time[c]);
            preload_time[c]=$realtime;consecutive[c]=consecutive[c]+1;
          end
          observed=ddata[c]^((negative==1&&c==2&&received[c]==128)||(negative==4&&generation==1&&received[c]==0)?32'd1:32'd0);
          if(received[c]>=sent[c]||observed!==payload(c,received[c],generation)||dkeep[c]!==((generation==0&&received[c]<2048)?15:(received[c]%15)+1)||dlast[c]!==((received[c]%13)==12))
            $fatal(1,"BOUNDARY_ORACLE_PAYLOAD channel=%0d word=%0d gen=%0d observed=%h",c,received[c],generation,observed);
          if(received[c]>64&&received[c]<=1984)begin
            for(integer b=0;b<4;b=b+1)if(dkeep[c][b])window_bytes[c]=window_bytes[c]+1;
          end
          if(received[c]==64)started[c]=$realtime;
          if(received[c]==1984)ended[c]=$realtime;
          received[c]=received[c]+1;
        end
      end
    end
  end endgenerate
  always @(posedge fabric or posedge reset)begin
    if(reset)begin command_count=0;ack_count=0;obs_held_valid=0;end
    else begin
      if(cmdvalid&&cmdready)begin commands[command_count]={16'd1,serial,cmdrx,cmdtx,cmdpark};command_count=command_count+1;end
      if(obs_held_valid&&(!obsvalid||observation_word!==obs_held))$fatal(1,"BOUNDARY_ORACLE_OBSERVATION held payload");
      obs_held_valid=obsvalid&&!obsready;
      if(obs_held_valid)begin obs_held=observation_word;observation_stall=observation_stall+1;end
      if(obsvalid&&obsready)begin
        observation_count=observation_count+1;
        if(obsserial==0||obsserial>command_count||{obsepoch,obsserial,obsrx,obstx,obspark}!==commands[obsserial-1])
          $fatal(1,"BOUNDARY_ORACLE_OBSERVATION exact accepted command echo");
        if(!obscsr||!obsconfig||!obsmdio||!obsmedia||obsfault!=0||obsstats!=0||obsphy!=obsparked)
          $fatal(1,"BOUNDARY_ORACLE_OBSERVATION coherent known fields");
        if(obsserial==2&&obsreleased)early_release_seen=1;
        if(obsserial==4&&!obstxdrained)false_seen=1;
      end
      if(ackvalid&&ackready)begin
        if(ack_count>=command_count||{ackepoch,(ackserial^(negative==3?16'd1:16'd0)),ackrx,acktx,ackpark}!==commands[ack_count])$fatal(1,"BOUNDARY_ORACLE_RECEIPT exact payload");
        ack_count=ack_count+1;
      end
    end
  end
  always @(posedge fixed125)if(!reset&&check_old_votes)begin
    if(!txstop||!parkreq)$fatal(1,"BOUNDARY_ORACLE_RELEASE old vote withdrawn before command consumption");
    if(dut.commands.destination_valid&&dut.commands.destination_ready&&dut.commands.destination_bits[18:3]==5)
      check_old_votes=0;
  end
  task automatic cycles(input integer n);begin repeat(n)@(negedge fabric);end endtask
  task automatic send_command(input reg r,input reg t,input reg p);begin
    @(negedge fabric);serial=serial+1;cmdrx=r;cmdtx=t;cmdpark=p;cmdvalid=1;
    @(posedge fabric);while(!cmdready)@(posedge fabric);@(negedge fabric);cmdvalid=0;
  end endtask
  real mbps,ceiling;
  integer discarded[0:3],discarded2[0:3],paused_sent[0:3],paused_received[0:3];
  initial begin
    for(integer c=0;c<4;c=c+1)begin consecutive[c]=0;random_stalls[c]=0;preload_time[c]=0;end
    #127;reset=0;cycles(10);target=32;
    cycles(120);repeat(120)@(negedge fixed125);
    for(integer c=0;c<4;c=c+1)if(sent[c]!=17||received[c]!=0||sready[c])
      $fatal(1,"BOUNDARY_ORACLE_CAPACITY channel=%0d accepted=%0d consumed=%0d",c,sent[c],received[c]);
    preload_check=1;directed_ready=15;
    wait(received[0]==32&&received[1]==32&&received[2]==32&&received[3]==32);
    preload_check=0;
    for(integer c=0;c<4;c=c+1)if(consecutive[c]!=16)$fatal(1,"BOUNDARY_ORACLE_II coverage");
    $display("BOUNDARY_PRELOADED capacity=17,17,17,17 contiguous_words=16,16,16,16 held_response=%0d",held_response);
    target=2048;
    wait(received[0]==2048&&received[1]==2048&&received[2]==2048&&received[3]==2048);
    for(integer c=0;c<4;c=c+1)begin
      if(window_bytes[c]!=7680)$fatal(1,"BOUNDARY_ORACLE_THROUGHPUT invalid-byte accounting");
      mbps=window_bytes[c]*1000.0/(ended[c]-started[c]);
      ceiling=held_response?((fabric_half>=4)?2000.0/fabric_half:500.0):
        (c<2?((fabric_half>=8)?2000.0/fabric_half:250.0):((fabric_half>=2)?1000.0/fabric_half:500.0));
      if(mbps<ceiling*0.90||mbps>ceiling*1.01)$fatal(1,"BOUNDARY_ORACLE_THROUGHPUT channel=%0d mbps=%f ceiling=%f",c,mbps,ceiling);
      $display("BOUNDARY_THROUGHPUT channel=%0d bytes_per_second=%0.0f measured_words=1920 keep_counted_bytes=7680 fabric_half=%0d fixed_half=4",c,mbps*1000000,fabric_half);
    end
    cycles(20);directed_ready=0;target=2049;
    wait(sent[0]==2049&&sent[1]==2049&&sent[2]==2049&&sent[3]==2049);
    wait(tx_storage_idle&&rx_storage_idle&&dvalid==15);cycles(5);
    if((tx_consumers_idle^(negative==2))||rx_consumers_idle)$fatal(1,"BOUNDARY_ORACLE_OWNER held outputs not pointer empty");
    ackready=0;send_command(1,1,0);wait(ackvalid);cycles(15);
    if(txstop||ack_count!=0)$fatal(1,"BOUNDARY_ORACLE_OWNER close before old output consumed");
    // Early release while old destination outputs are still held: completion
    // must not require successful TX stop, park, or draining those old words.
    ackready=1;wait(ack_count==1);cycles(3);
    send_command(0,0,0);wait(ack_count==2);wait(early_release_seen);cycles(5);
    if(txstop||rxstop||parkreq||received[0]!=2048||received[1]!=2048||!dvalid[0]||!dvalid[1])
      $fatal(1,"BOUNDARY_ORACLE_EARLY_RELEASE retained old data");
    send_command(1,1,0);wait(ack_count==3);cycles(5);
    directed_ready=15;wait(received[0]==2049&&received[1]==2049&&received[2]==2049&&received[3]==2049);
    wait(txstop);cycles(3);
    send_command(1,1,1);wait(ack_count==4);wait(parkreq);
    wait(obsvalid&&obsserial==4&&obstxdrained&&obsparked);@(negedge fabric);obsready=0;
    wait(obsvalid);cycles(20);
    // Synthetic idle revocation must retain old applied votes AND propagate a
    // coherent false observation after the previously held true snapshot drains.
    @(negedge fixed125);perturb_idle=1;repeat(15)begin @(negedge fixed125);if(!parkreq||!txstop)$fatal(1,"BOUNDARY_ORACLE_APPLIED vote revoked");end
    obsready=1;wait(false_seen);perturb_idle=0;
    wait(obsvalid&&obsserial==4&&obstxdrained&&obsparked);
    check_old_votes=1;send_command(0,0,0);target=2050;wait(ack_count==5);wait(!parkreq&&!txstop&&!rxstop);
    if(check_old_votes)$fatal(1,"BOUNDARY_ORACLE_RELEASE missing actual consumption");
    wait(received[0]==2050&&received[1]==2050&&received[2]==2050&&received[3]==2050);cycles(10);
    // Stop fabric only at low phase; retained IRQ is a persistent level, not
    // a promise to capture a short arbitrary interrupt during a stopped clock.
    @(negedge fabric);fabric_run=0;macirq=1;repeat(30)@(negedge fixed125);
    fabric_run=1;wait(irq);cycles(5);macirq=0;wait(!irq);
    // Both clocks may pause independently with owned RAM/prefetch/output data.
    // Full credits do not become speculative ready merely because another edge occurs.
    directed_ready=0;target=2090;cycles(100);repeat(100)@(negedge fixed125);
    for(integer c=0;c<4;c=c+1)begin
      if(sent[c]-received[c]!=17||sready[c])$fatal(1,"BOUNDARY_ORACLE_CAPACITY full before pause");
      paused_sent[c]=sent[c];paused_received[c]=received[c];
    end
    @(negedge fabric);fabric_run=0;repeat(100)@(negedge fixed125);
    for(integer c=0;c<4;c=c+1)if(sent[c]!=paused_sent[c]||received[c]!=paused_received[c])$fatal(1,"BOUNDARY_ORACLE_PAUSE fabric");
    fabric_run=1;cycles(10);@(negedge fixed125);fixed_run=0;cycles(100);
    for(integer c=0;c<4;c=c+1)if(sent[c]!=paused_sent[c]||received[c]!=paused_received[c])$fatal(1,"BOUNDARY_ORACLE_PAUSE fixed");
    fixed_run=1;cycles(10);random_phase=1;target=6146;
    wait(received[0]==6146&&received[1]==6146&&received[2]==6146&&received[3]==6146);
    random_phase=0;directed_ready=15;cycles(10);
    for(integer c=0;c<4;c=c+1)if(random_stalls[c]<100)$fatal(1,"BOUNDARY_ORACLE_RANDOM insufficient stalls");
    $display("BOUNDARY_STRESS ordered_words=6146,6146,6146,6146 random_stalls=%0d,%0d,%0d,%0d pauses=fabric,fixed ram_index_wraps_per_lane=384 full_pointer_wraps_per_lane=192",random_stalls[0],random_stalls[1],random_stalls[2],random_stalls[3]);
    // Explicit common cold reset discards accepted transport words. Save exact
    // outstanding counts; a new generation makes any stale post-reset word fail.
    directed_ready=0;target=6200;cycles(30);repeat(30)@(negedge fixed125);
    for(integer c=0;c<4;c=c+1)begin discarded[c]=sent[c]-received[c];if(discarded[c]==0)$fatal(1,"BOUNDARY_ORACLE_RESET missing owned work");end
    @(negedge fixed125);fixed_run=0;target=0;reset=1;#41;reset=0;cycles(10);
    if(dvalid!=0||ackvalid||irq)$fatal(1,"BOUNDARY_ORACLE_RESET stale valid");
    fixed_run=1;cycles(10);generation=1;directed_ready=15;target=64;
    wait(received[0]==64&&received[1]==64&&received[2]==64&&received[3]==64);cycles(10);
    if(!csr_idle||!tx_storage_idle||!rx_storage_idle||!tx_consumers_idle||!rx_consumers_idle||stall_samples==0||observation_stall==0||!early_release_seen||!false_seen)$fatal(1,"BOUNDARY_ORACLE_FINAL owner");
    directed_ready=0;target=128;cycles(100);repeat(100)@(negedge fixed125);
    for(integer c=0;c<4;c=c+1)begin discarded2[c]=sent[c]-received[c];if(discarded2[c]!=17)$fatal(1,"BOUNDARY_ORACLE_RESET second capacity");end
    @(negedge fabric);fabric_run=0;target=0;reset=1;#41;reset=0;repeat(30)@(negedge fixed125);
    if(dvalid!=0||ackvalid||irq)$fatal(1,"BOUNDARY_ORACLE_RESET fabric paused stale valid");
    fabric_run=1;cycles(10);generation=2;directed_ready=15;target=96;
    wait(received[0]==96&&received[1]==96&&received[2]==96&&received[3]==96);cycles(20);
    if(!tx_storage_idle||!rx_storage_idle||!tx_consumers_idle||!rx_consumers_idle)$fatal(1,"BOUNDARY_ORACLE_FINAL second reset owner");
    $display("BOUNDARY_RESET_SECOND reset_discard=%0d,%0d,%0d,%0d postreset=96,96,96,96 paused=fabric",discarded2[0],discarded2[1],discarded2[2],discarded2[3]);
    $display("FIXED_MAC_PIPELINED_PASS reset_discard=%0d,%0d,%0d,%0d postreset=64,64,64,64 stalled_samples=%0d observation_stalls=%0d early_release=1 false_snapshot=1 fixed_hz=125000000 fabric_half=%0d",discarded[0],discarded[1],discarded[2],discarded[3],stall_samples,observation_stall,fabric_half);
    $finish;
  end
  initial begin #2000000;$fatal(1,"BOUNDARY_TIMEOUT sent=%0d,%0d,%0d,%0d received=%0d,%0d,%0d,%0d commands=%0d/%0d",sent[0],sent[1],sent[2],sent[3],received[0],received[1],received[2],received[3],command_count,ack_count);end
endmodule
