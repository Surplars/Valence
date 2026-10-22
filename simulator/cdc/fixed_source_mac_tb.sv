`timescale 1ns/1ps
// Whole real MAC at fixed125, independent fabric, and independent PHY RXC.
// Producer-closed witnesses are this fixture's stimulus contract, not CPU/DMA.
module fixed_source_mac_tb;
  reg fabric=0,fixed125=0,rx=0,reset=1;
  integer fabric_half=10,negative=0;
  initial begin
    if($value$plusargs("fabric_half=%d",fabric_half))begin end
    if($value$plusargs("negative=%d",negative))begin end
    forever #(fabric_half) fabric=~fabric;
  end
  initial begin #0.7;forever #4 fixed125=~fixed125;end
  initial begin #2.7;forever #4 rx=~rx;end
  reg req_valid=0,req_write=0,resp_ready=1;
  reg [63:0] req_address=0,req_data=0;
  wire req_ready,resp_valid,resp_error;
  wire [63:0] resp_data;
  reg [4:0] rise=0,fall=0;
  wire mdc,mdio_out,mdio_oe,mdio_in,link,media_pending,irq;
  wire [1:0] speed;
  wire [7:0] gmii_tx_data;
  wire gmii_tx_enable,gmii_tx_error;
  wire rdvalid,rdlast,rsvalid,rslast;
  wire [31:0] rddata,rsdata;
  wire [3:0] rdkeep,rskeep;
  reg hold_status=0;
  wire rsready=!hold_status||!rslast;
  reg tdvalid=0,tclvalid=0,tdlast=0,tcllast=0;
  reg [31:0] tddata=0,tcldata=0;
  wire tdready,tclready;
  reg cmdvalid=0,cmdrx=0,cmdtx=0,cmdpark=0,ackready=1,obsready=1;
  reg [15:0] epoch=1,serial=0;
  reg txclosed=0,csrclosed=0;
  wire cmdready,ackvalid,obsvalid;
  wire [15:0] ackepoch,ackserial,obsepoch,obsserial;
  wire ackrx,acktx,ackpark,obsrx,obstx,obspark;
  wire txdrained,rxdrained,released,parked,csrdrained;
  wire csr_idle,tx_storage_idle,rx_consumers_idle;
  wire [3:0] phyfault;
  FixedSourceTestGmac dut(
    .fabricClock(fabric),.rawTxClock(fixed125),.rawRxClock(rx),.commonReset(reset),
    .registers_request_valid(req_valid),.registers_request_ready(req_ready),.registers_request_bits_address(req_address),
    .registers_request_bits_write(req_write),.registers_request_bits_size(3'd3),.registers_request_bits_data(req_data),
    .registers_request_bits_byteEnable(8'hff),.registers_response_ready(resp_ready),.registers_response_valid(resp_valid),
    .registers_response_bits_data(resp_data),.registers_response_bits_error(resp_error),
    .streams_txData_valid(tdvalid),.streams_txData_ready(tdready),.streams_txData_bits_data(tddata),.streams_txData_bits_keep(4'hf),.streams_txData_bits_last(tdlast),
    .streams_txControl_valid(tclvalid),.streams_txControl_ready(tclready),.streams_txControl_bits_data(tcldata),.streams_txControl_bits_keep(4'hf),.streams_txControl_bits_last(tcllast),
    .streams_rxData_ready(1'b1),.streams_rxData_valid(rdvalid),.streams_rxData_bits_data(rddata),.streams_rxData_bits_keep(rdkeep),.streams_rxData_bits_last(rdlast),
    .streams_rxStatus_ready(rsready),.streams_rxStatus_valid(rsvalid),.streams_rxStatus_bits_data(rsdata),.streams_rxStatus_bits_keep(rskeep),.streams_rxStatus_bits_last(rslast),
    .command_valid(cmdvalid),.command_ready(cmdready),.command_bits_epoch(epoch),.command_bits_serial(serial),
    .command_bits_rxStop(cmdrx),.command_bits_txStop(cmdtx),.command_bits_park(cmdpark),
    .consumed_valid(ackvalid),.consumed_ready(ackready),.consumed_bits_epoch(ackepoch),.consumed_bits_serial(ackserial),
    .consumed_bits_rxStop(ackrx),.consumed_bits_txStop(acktx),.consumed_bits_park(ackpark),
    .observation_valid(obsvalid),.observation_ready(obsready),.observation_bits_command_epoch(obsepoch),.observation_bits_command_serial(obsserial),
    .observation_bits_command_rxStop(obsrx),.observation_bits_command_txStop(obstx),.observation_bits_command_park(obspark),
    .observation_bits_txDrained(txdrained),.observation_bits_rxDrained(rxdrained),.observation_bits_released(released),
    .observation_bits_parked(parked),.observation_bits_csrDrained(csrdrained),.observation_bits_phyFault(phyfault),
    .txProducersClosed(txclosed),.controlProducersClosed(csrclosed),
    .fabricCsrIdle(csr_idle),.fabricTxStorageIdle(tx_storage_idle),.fabricRxConsumersIdle(rx_consumers_idle),
    .control_0_clockEnable(1'b1),.control_0_quiesce(1'b0),.control_0_isolate(1'b0),.control_0_allowAdmission(1'b1),
    .control_1_clockEnable(1'b1),.control_1_quiesce(1'b0),.control_1_isolate(1'b0),.control_1_allowAdmission(1'b1),
    .rawRgmiiRxRise(rise),.rawRgmiiRxFall(fall),.mdioIn(mdio_in),.mdc(mdc),.mdioOut(mdio_out),.mdioOe(mdio_oe),
    .gmiiTxData(gmii_tx_data),.gmiiTxEnable(gmii_tx_enable),.gmiiTxError(gmii_tx_error),.irq(irq),
    .linkUp(link),.appliedSpeed(speed),.mediaPending(media_pending));
  wire [15:0] page;
  wire [31:0] transactions,status_count,bmsr_count;
  wire configured;
  rtl8211f_pin_model phy(.clk(fixed125),.reset(reset),.mdc(mdc),.mdio_out(mdio_out),.mdio_oe(mdio_oe),.mdio_in(mdio_in),
    .wire_link(1'b1),.wire_speed(2'd2),.full_duplex(1'b1),.an_complete(1'b1),.remote_fault(1'b0),.inject_no_ack(1'b0),
    .page(page),.transaction_count(transactions),.status_count(status_count),.bmsr_count(bmsr_count),.configuration_complete(configured));
  function automatic [31:0] crc_byte(input [31:0] old,input [7:0] b);
    reg [31:0] c;begin c=old;for(integer j=0;j<8;j=j+1)c=(c>>1)^((c[0]^b[j])?32'hedb88320:0);crc_byte=c;end
  endfunction
  function automatic [7:0] body(input integer gen,input integer i);
    begin body=(i<6)?8'hff:((gen*17+i*13)&255);end
  endfunction
  integer received=0,statuses=0,byte_index=0,status_index=0;
  integer csr_accept=0,csr_reply=0,mac_csr_accept=0,mac_csr_reply=0;
  integer td_accept=0,tc_accept=0,td_consume=0,tc_consume=0,rd_accept=0,rs_accept=0,rd_consume=0,rs_consume=0;
  integer commands=0,acks=0,observations=0,raw_drops=0;
  reg [34:0] command_ledger[0:15];
  reg [31:0] observed_word;
  always @(posedge fabric)if(!reset)begin
    if(req_valid&&req_ready)csr_accept=csr_accept+1;
    if(resp_valid&&resp_ready)csr_reply=csr_reply+1;
    if(tdvalid&&tdready)td_accept=td_accept+1;
    if(tclvalid&&tclready)tc_accept=tc_accept+1;
    if(cmdvalid&&cmdready)begin command_ledger[commands]={epoch,serial,cmdrx,cmdtx,cmdpark};commands=commands+1;end
    if(ackvalid&&ackready)begin
      if(acks>=commands||{ackepoch,ackserial,ackrx,acktx,ackpark}!==command_ledger[acks])$fatal(1,"FIXED_ORACLE_RECEIPT exact owner");
      acks=acks+1;
    end
    if(obsvalid&&obsready)begin
      observations=observations+1;
      if(obsepoch!=1||obsserial==0||obsserial>serial)$fatal(1,"FIXED_ORACLE_OBSERVATION tag");
    end
    if(rdvalid)begin
      rd_consume=rd_consume+1;
      observed_word=rddata ^ ((negative==1&&received==1)?32'h1:0);
      if(rdkeep!==4'hf)$fatal(1,"FIXED_ORACLE_RX keep");
      for(integer k=0;k<4;k=k+1)
        if(observed_word[k*8+:8]!==body(received==0?11:22,byte_index+k))$fatal(1,"FIXED_ORACLE_RX payload");
      byte_index=byte_index+4;
      if(rdlast)begin if(byte_index!=64)$fatal(1,"FIXED_ORACLE_RX length");received=received+1;byte_index=0;end
    end
    if(rsvalid&&rsready)begin
      rs_consume=rs_consume+1;
      if(rskeep!==4'hf||rslast!==(status_index==5))$fatal(1,"FIXED_ORACLE_STATUS shape");
      if(rsdata!==((status_index==0)?32'h50000000:((status_index==3||status_index==5)?32'd64:0)))$fatal(1,"FIXED_ORACLE_STATUS value");
      if(rslast)begin statuses=statuses+1;status_index=0;end else status_index=status_index+1;
    end
  end
  integer tx_frames=0,tx_position=0;
  reg tx_previous=0;
  reg [31:0] tx_crc=32'hffffffff;
  reg [7:0] observed_tx,expected_tx;
  always @(posedge fixed125)if(!reset)begin
    if(dut.mac.registers_request_valid&&dut.mac.registers_request_ready)mac_csr_accept=mac_csr_accept+1;
    if(dut.mac.registers_response_valid&&dut.mac.registers_response_ready)mac_csr_reply=mac_csr_reply+1;
    if(dut.mac.streams_txData_valid&&dut.mac.streams_txData_ready)td_consume=td_consume+1;
    if(dut.mac.streams_txControl_valid&&dut.mac.streams_txControl_ready)tc_consume=tc_consume+1;
    if(dut.mac.streams_rxData_valid&&dut.mac.streams_rxData_ready)rd_accept=rd_accept+1;
    if(dut.mac.streams_rxStatus_valid&&dut.mac.streams_rxStatus_ready)rs_accept=rs_accept+1;
    raw_drops=raw_drops+dut.mac.rx.io_dropped;
    if(dut.mac.runtimeAdmissionPort_txStopRequest&&(td_consume!=td_accept||tc_consume!=tc_accept))$fatal(1,"FIXED_ORACLE_TX_FENCE old accepted word");
    if(gmii_tx_enable)begin
      if(tx_frames>=2||gmii_tx_error)$fatal(1,"FIXED_ORACLE_TX extra/error frame");
      observed_tx=gmii_tx_data ^ ((negative==2&&tx_frames==1&&tx_position==8)?8'h1:0);
      if(tx_position<7)expected_tx=8'h55;
      else if(tx_position==7)expected_tx=8'hd5;
      else if(tx_position<72)expected_tx=body(tx_frames==0?31:32,tx_position-8);
      else if(tx_position<76)expected_tx=(~tx_crc)>>((tx_position-72)*8);
      else $fatal(1,"FIXED_ORACLE_TX too long");
      if(observed_tx!==expected_tx)$fatal(1,"FIXED_ORACLE_TX payload/FCS frame=%0d byte=%0d observed=%h expected=%h",tx_frames,tx_position,observed_tx,expected_tx);
      if(tx_position>=8&&tx_position<72)tx_crc=crc_byte(tx_crc,body(tx_frames==0?31:32,tx_position-8));
      tx_position=tx_position+1;
    end else if(tx_previous)begin
      if(tx_position!=76)$fatal(1,"FIXED_ORACLE_TX length");tx_frames=tx_frames+1;tx_position=0;tx_crc=32'hffffffff;
    end
    tx_previous=gmii_tx_enable;
  end
  task automatic cycles(input integer n);begin repeat(n)@(negedge fabric);end endtask
  task automatic offer(input integer offset,input reg wr,input [63:0] data);
    begin @(negedge fabric);req_address=64'h10040000+offset;req_write=wr;req_data=data;req_valid=1;
      @(posedge fabric);while(!req_ready)@(posedge fabric);@(negedge fabric);req_valid=0;end
  endtask
  task automatic mmio(input integer offset,input reg wr,input [63:0] data,output reg [63:0] result);
    begin offer(offset,wr,data);@(posedge fabric);while(!resp_valid)@(posedge fabric);
      if(resp_error)$fatal(1,"FIXED_ORACLE_CSR error offset=%h",offset);result=resp_data;@(negedge fabric);end
  endtask
  task automatic rxbyte(input [7:0] b);begin @(negedge rx);rise={1'b1,b[3:0]};fall={1'b1,b[7:4]};end endtask
  task automatic packet(input integer gen);reg [31:0] crc;begin
    for(integer i=0;i<7;i=i+1)rxbyte(8'h55);rxbyte(8'hd5);crc=32'hffffffff;
    for(integer i=0;i<64;i=i+1)begin rxbyte(body(gen,i));crc=crc_byte(crc,body(gen,i));end
    crc=~crc;for(integer i=0;i<4;i=i+1)rxbyte(crc[i*8+:8]);
    @(negedge rx);rise=0;fall=0;repeat(20)@(negedge rx);
  end endtask
  task automatic txpacket(input integer gen);reg [31:0] word;begin
    for(integer i=0;i<6;i=i+1)begin
      @(negedge fabric);tclvalid=1;tcldata=i==0?32'ha0000000:0;tcllast=i==5;
      @(posedge fabric);while(!tclready)@(posedge fabric);
    end
    @(negedge fabric);tclvalid=0;tcllast=0;
    for(integer i=0;i<16;i=i+1)begin
      word=0;for(integer k=0;k<4;k=k+1)word[k*8+:8]=body(gen,i*4+k);
      @(negedge fabric);tdvalid=1;tddata=word;tdlast=i==15;
      @(posedge fabric);while(!tdready)@(posedge fabric);
    end
    @(negedge fabric);tdvalid=0;tdlast=0;
  end endtask
  task automatic cmd_offer(input reg r,input reg t,input reg p);begin
    @(negedge fabric);serial=serial+1;cmdrx=r;cmdtx=t;cmdpark=p;cmdvalid=1;
  end endtask
  task automatic cmd_accept;begin
    @(posedge fabric);while(!cmdready)@(posedge fabric);@(negedge fabric);cmdvalid=0;
  end endtask
  task automatic cmd_send(input reg r,input reg t,input reg p);begin cmd_offer(r,t,p);cmd_accept();wait(acks==commands);cycles(1);end endtask
  task automatic wait_observation(input integer seq,input reg want_park,input reg want_release);begin
    @(posedge fabric);
    while(!(obsvalid&&obsready&&obsserial==seq&&parked==want_park&&released==want_release))@(posedge fabric);
    @(negedge fabric);
  end endtask
  reg [63:0] result,held;
  integer before_drops,before_commands;
  initial begin
    #127;reset=0;wait(link&&!media_pending);cycles(50);
    if(!configured||page!=0||status_count<4||bmsr_count<4)$fatal(1,"FIXED_ORACLE_PHY initialization");
    $display("FIXED_PHY_READY mdio=%0d actual_source_hz=125000000 fabric_half=%0d",transactions,fabric_half);
    mmio('h18,1,64'h665544332211,result);
    wait(dut.mac.controlPark_configDrained);repeat(10)@(negedge fixed125);
    mmio('h10,1,64'hb,result);cycles(300);
    hold_status=1;packet(11);wait(rsvalid&&rslast);txpacket(31);
    txclosed=1;ackready=0;cmd_offer(1,1,0);cmd_accept();wait(ackvalid);cycles(20);
    if(acks!=0||ackserial!=1||ackepoch!=1)$fatal(1,"FIXED_ORACLE_RECEIPT stalled owner");
    if(rx_consumers_idle^(negative==3))$fatal(1,"FIXED_ORACLE_RX_OWNER stalled status output omitted");
    ackready=1;cycles(3);wait(acks==1);hold_status=0;wait(statuses==1&&rx_consumers_idle);
    wait(tx_frames==1);cycles(30);
    // Source response is still owned even after the fixed CSR bridge is empty.
    resp_ready=0;offer('h00,0,0);wait(resp_valid);held=resp_data;csrclosed=1;
    cmd_offer(1,1,1);before_commands=commands;
    repeat(30)begin @(negedge fabric);
      if(cmdready||commands!=before_commands||(csr_idle^(negative==4))||!resp_valid||resp_data!==held)
        $fatal(1,"FIXED_ORACLE_CSR_OWNER final response consumption");
    end
    resp_ready=1;cmd_accept();wait(acks==commands);wait_observation(2,1,0);
    if(page!=0||phyfault!=0)$fatal(1,"FIXED_ORACLE_PHY parked page/fault");
    before_drops=raw_drops;packet(77);repeat(400)@(negedge fixed125);
    if(raw_drops!=before_drops+1||received!=1||statuses!=1)$fatal(1,"FIXED_ORACLE_DROP explicit closed admission");
    // Release never re-drains newly accepted traffic. Old command has a real
    // consumed receipt; MAC release itself comes from the matching observation.
    cmd_send(0,0,0);txclosed=0;csrclosed=0;wait_observation(3,0,1);
    mmio('h18,0,0,result);if(result!=64'h665544332211)$fatal(1,"FIXED_ORACLE_CSR retained config");
    packet(22);txpacket(32);wait(statuses==2&&tx_frames==2);cycles(500);
    mmio('h48,0,0,result);if(result!=2)$fatal(1,"FIXED_ORACLE_STATISTICS RX frames");
    mmio('h50,0,0,result);if(result!=1)$fatal(1,"FIXED_ORACLE_STATISTICS RX drops");
    mmio('h40,0,0,result);if(result!=2)$fatal(1,"FIXED_ORACLE_STATISTICS TX frames");
    if(csr_accept!=csr_reply||csr_accept!=mac_csr_accept||csr_accept!=mac_csr_reply||
       td_accept!=32||tc_accept!=12||td_consume!=td_accept||tc_consume!=tc_accept||
       rd_accept!=rd_consume||rd_consume!=32||rs_accept!=rs_consume||rs_consume!=12||commands!=acks||acks!=3)
      $fatal(1,"FIXED_ORACLE_CONSERVATION csr=%0d/%0d/%0d/%0d tx=%0d/%0d/%0d/%0d rx=%0d/%0d/%0d/%0d cmd=%0d/%0d",csr_accept,csr_reply,mac_csr_accept,mac_csr_reply,td_accept,td_consume,tc_accept,tc_consume,rd_accept,rd_consume,rs_accept,rs_consume,commands,acks);
    $display("FIXED_SOURCE_MAC_PASS csr=%0d txdata=%0d txcontrol=%0d rxdata=%0d rxstatus=%0d commands=%0d observations=%0d frames=2 drops=1 fixed_hz=125000000 fabric_half=%0d",csr_accept,td_accept,tc_accept,rd_consume,rs_consume,commands,observations,fabric_half);
    $finish;
  end
  initial begin #10000000;$fatal(1,"FIXED_TIMEOUT link=%b mdio=%0d commands=%0d acks=%0d rx=%0d tx=%0d page=%h",link,transactions,commands,acks,received,tx_frames,page);end
endmodule
