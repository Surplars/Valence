`timescale 1ns/1ps
module network_packet_runtime_tb;
  integer fabric_half=5, rx_half=3, tx_half=7, phase_ps=1300, test_case=0, negative=0;
  reg fabricClock=0, rxClock=0, txClock=0, commonColdReset=1;
  initial begin
    if ($value$plusargs("fabric_half=%d",fabric_half)) begin end
    if ($value$plusargs("rx_half=%d",rx_half)) begin end
    if ($value$plusargs("tx_half=%d",tx_half)) begin end
    if ($value$plusargs("phase_ps=%d",phase_ps)) begin end
    if ($value$plusargs("case=%d",test_case)) begin end
    if ($value$plusargs("negative=%d",negative)) begin end
  end
  initial begin #0.1; forever #(fabric_half) fabricClock=~fabricClock; end
  initial begin #0.2; #(phase_ps/1000.0); forever #(rx_half) rxClock=~rxClock; end
  initial begin #0.3; #(phase_ps/1700.0); forever #(tx_half) txClock=~txClock; end
  reg ctl_valid=0, ctl_write=0, ctl_response_ready=1;
  reg [63:0] ctl_address=0, ctl_data=0;
  wire ctl_ready, ctl_response_valid, ctl_response_error;
  wire [63:0] ctl_response_data;
  wire mem_valid, mem_write, mem_response_ready;
  wire [63:0] mem_address, mem_data;
  wire [2:0] mem_size;
  wire [7:0] mem_mask;
  reg hold_mem_request=0, hold_mem_response=0;
  integer head=0, tail=0, outstanding=0, memory_requests=0, memory_replies=0, memory_reads=0, memory_writes=0;
  reg [63:0] replies[0:31], memory[0:8191], expected_write_data[0:8191];
  reg [7:0] expected_write_mask[0:8191];
  integer write_seen[0:8191];
  integer expected_writes=0;
  wire mem_ready=!commonColdReset && !hold_mem_request && outstanding<16;
  wire mem_response_valid=!commonColdReset && !hold_mem_response && outstanding!=0;
  wire [63:0] mem_response_data=replies[head];
  wire runtime_pause, rx_stop_request, tx_stop_request;
  reg prepare_valid=0, downstream_ready=0, terminal_consumed=0, retired=0;
  reg [7:0] prepare_epoch=0;
  wire prepare_ready,downstream_valid,retirement_permit,epoch_busy,epoch_held;
  wire [7:0] downstream_epoch,held_epoch;
  integer prepares=0,retirements=0;
  reg hold_rx_status_last=0, hold_tx_control_last=0, hold_tx_data_last=0;
  reg [7:0] rx_data=0;
  reg rx_valid=0, rx_error=0;
  wire [7:0] tx_data, rx_drop_reasons;
  wire tx_enable, tx_error, dma_active, dma_tx_idle, dma_owners_idle;
  wire rx_drained, tx_drained, released, rx_closed, rx_accepted, rx_dropped, rx_bad_fcs;
  wire tx_busy, tx_done, status_blocked, control_blocked, data_blocked;
  wire rx_data_fire, rx_data_last_fire, rx_status_fire, rx_status_last_fire;
  wire [31:0] rx_status_data;
  wire tx_control_fire, tx_data_fire, tx_data_last_fire, rx_destination_idle, tx_source_idle;
  CommonNetworkPacketRuntimeFixture dut(
    .fabricClock(fabricClock),.rxClock(rxClock),.txClock(txClock),.commonColdReset(commonColdReset),
    .io_control_request_valid(ctl_valid),.io_control_request_ready(ctl_ready),
    .io_control_request_bits_address(ctl_address),.io_control_request_bits_write(ctl_write),
    .io_control_request_bits_size(3'd3),.io_control_request_bits_data(ctl_data),
    .io_control_request_bits_byteEnable(8'hff),.io_control_response_valid(ctl_response_valid),
    .io_control_response_ready(ctl_response_ready),.io_control_response_bits_data(ctl_response_data),
    .io_control_response_bits_error(ctl_response_error),.io_memory_request_valid(mem_valid),
    .io_memory_request_ready(mem_ready),.io_memory_request_bits_address(mem_address),
    .io_memory_request_bits_write(mem_write),.io_memory_request_bits_size(mem_size),
    .io_memory_request_bits_data(mem_data),.io_memory_request_bits_byteEnable(mem_mask),
    .io_memory_response_valid(mem_response_valid),.io_memory_response_ready(mem_response_ready),
    .io_memory_response_bits_data(mem_response_data),.io_memory_response_bits_error(1'b0),
    .io_runtimePause(runtime_pause),.io_rxStopRequest(rx_stop_request),.io_txStopRequest(tx_stop_request),
    .io_prepareValid(prepare_valid),.io_prepareEpoch(prepare_epoch),.io_prepareReady(prepare_ready),
    .io_downstreamPrepareValid(downstream_valid),.io_downstreamPrepareReady(downstream_ready),
    .io_downstreamPrepareEpoch(downstream_epoch),.io_terminalConsumedAtAon(terminal_consumed),
    .io_retired(retired),.io_retirementPermit(retirement_permit),.io_epochBusy(epoch_busy),
    .io_epochHeld(epoch_held),.io_epochHeldValue(held_epoch),
    .io_holdRxStatusLast(hold_rx_status_last),.io_holdTxControlLast(hold_tx_control_last),
    .io_holdTxDataLast(hold_tx_data_last),.io_gmiiRxData(rx_data),.io_gmiiRxValid(rx_valid),
    .io_gmiiRxError(rx_error),.io_gmiiTxData(tx_data),.io_gmiiTxEnable(tx_enable),
    .io_gmiiTxError(tx_error),.io_dmaActive(dma_active),.io_dmaTxIdle(dma_tx_idle),
    .io_dmaOwnersIdle(dma_owners_idle),.io_rxDrained(rx_drained),.io_txDrained(tx_drained),
    .io_released(released),.io_rxAdmissionClosed(rx_closed),.io_rxAccepted(rx_accepted),
    .io_rxDropped(rx_dropped),.io_rxDropReasons(rx_drop_reasons),.io_rxBadFcs(rx_bad_fcs),
    .io_txBusy(tx_busy),.io_txDone(tx_done),.io_rxStatusLastBlocked(status_blocked),
    .io_txControlLastBlocked(control_blocked),.io_txDataLastBlocked(data_blocked),
    .io_rxDataFire(rx_data_fire),.io_rxDataLastFire(rx_data_last_fire),.io_rxStatusFire(rx_status_fire),
    .io_rxStatusData(rx_status_data),.io_rxStatusLastFire(rx_status_last_fire),
    .io_txControlFire(tx_control_fire),.io_txDataFire(tx_data_fire),.io_txDataLastFire(tx_data_last_fire),
    .io_rxDestinationIdle(rx_destination_idle),.io_txSourceIdle(tx_source_idle)
  );
  function automatic [7:0] frame_byte(input integer id,input integer position);
    begin
      if(position==0) frame_byte=8'h02;
      else if(position<5) frame_byte=0;
      else if(position==5) frame_byte=1;
      else if(position==6) frame_byte=8'h02;
      else if(position<11) frame_byte=0;
      else if(position==11) frame_byte=id;
      else if(position==12) frame_byte=8'h08;
      else if(position==13) frame_byte=0;
      else frame_byte=(id*29+position*7+3)&255;
    end
  endfunction
  function automatic [31:0] crc_byte(input [31:0] old_crc,input [7:0] byte_value);
    reg [31:0] c; integer k;
    begin c=old_crc^byte_value; for(k=0;k<8;k=k+1) c=c[0] ? (c>>1)^32'hedb88320 : c>>1; crc_byte=c; end
  endfunction
  integer mindex,b,mi;
  reg [63:0] held_mem_payload;
  reg [63:0] held_mem_address;
  reg [7:0] held_mem_mask;
  reg held_mem_write, stalled_mem=0;
  // Negative control mutates only the monitor's observed drain level. The
  // ordinary retained-status checker below has no injection-dependent branch.
  wire observed_rx_drained = rx_drained || (negative==2 && status_blocked);
  always @(posedge fabricClock) begin
    if(commonColdReset) begin
      head<=0; tail<=0; outstanding<=0; memory_requests<=0; memory_replies<=0;
      memory_reads<=0; memory_writes<=0; stalled_mem<=0;
    end else begin
      if(stalled_mem && (!mem_valid || mem_address!==held_mem_address || mem_data!==held_mem_payload ||
          mem_mask!==held_mem_mask || mem_write!==held_mem_write)) $fatal(1,"PACKET_MEMORY_HELD_VALID changed under pause");
      stalled_mem<=mem_valid&&!mem_ready;
      if(mem_valid&&!mem_ready) begin held_mem_payload<=mem_data; held_mem_address<=mem_address;
        held_mem_mask<=mem_mask; held_mem_write<=mem_write; end
      if(mem_valid&&mem_ready) begin
        if(mem_address<64'h80200000 || mem_address>=64'h80210000 || mem_address[2:0]!=0 || mem_size!=3)
          $fatal(1,"PACKET_MEMORY_ADDRESS invalid");
        mindex=(mem_address-64'h80200000)>>3;
        replies[tail]<=mem_write ? 0 : memory[mindex]; tail<=(tail+1)%32;
        memory_requests<=memory_requests+1;
        if(mem_write) begin
          if(expected_write_mask[mindex]===0 || mem_mask!==expected_write_mask[mindex] || write_seen[mindex]!=0)
            $fatal(1,"PACKET_RX_WRITE_LEDGER duplicate/unexpected addr=%h mask=%h expected=%h",mem_address,mem_mask,expected_write_mask[mindex]);
          for(b=0;b<8;b=b+1) if(mem_mask[b]) begin
            if(mem_data[b*8+:8]!==expected_write_data[mindex][b*8+:8])
              $fatal(1,"PACKET_ORACLE_PAYLOAD RX addr=%h byte=%0d got=%h expected=%h",mem_address,b,mem_data[b*8+:8],expected_write_data[mindex][b*8+:8]);
            memory[mindex][b*8+:8]<=mem_data[b*8+:8];
          end
          write_seen[mindex]<=1; memory_writes<=memory_writes+1;
        end else memory_reads<=memory_reads+1;
      end
      if(mem_response_valid&&mem_response_ready) begin head<=(head+1)%32; memory_replies<=memory_replies+1; end
      case({mem_valid&&mem_ready,mem_response_valid&&mem_response_ready})
        2'b10: outstanding<=outstanding+1; 2'b01: outstanding<=outstanding-1;
      endcase
      if(dma_owners_idle && (outstanding!=0 || mem_valid || mem_response_valid))
        $fatal(1,"PACKET_ORACLE_DRAIN asserted while accepted memory owner exists");
      if(status_blocked && (observed_rx_drained || dma_owners_idle))
        $fatal(1,"PACKET_ORACLE_DRAIN retained status owner forbids idle");
    end
  end
  integer accepted_frames=0,dropped_frames=0,closed_drops=0,bad_fcs_drops=0;
  always @(posedge rxClock) if(!commonColdReset) begin
    if(rx_accepted) accepted_frames<=accepted_frames+1;
    if(rx_dropped) begin
      dropped_frames<=dropped_frames+1;
      if(rx_drop_reasons==8'h02) closed_drops<=closed_drops+1;
      else if(rx_drop_reasons==8'h08) bad_fcs_drops<=bad_fcs_drops+1;
      else $fatal(1,"PACKET_RX_DROP_REASON unexpected %h",rx_drop_reasons);
    end
  end
  always @(posedge fabricClock) if(!commonColdReset) begin
    if(prepare_valid&&prepare_ready) begin
      if(!downstream_valid || !downstream_ready || downstream_epoch!=prepare_epoch || !epoch_held ||
          !dma_owners_idle || !rx_drained || !tx_drained)
        $fatal(1,"PACKET_EPOCH_PREPARE_LEDGER premature/wrong prepare");
      prepares<=prepares+1;
    end
    if(retired) begin
      if(!retirement_permit || !released || !epoch_busy) $fatal(1,"PACKET_EPOCH_RETIREMENT_LEDGER");
      retirements<=retirements+1;
    end
  end
  integer status_words=0,status_frames=0,rx_data_frames=0,tx_control_words=0,tx_data_frames=0;
  integer status_lengths[0:15], status_expected_count=0;
  reg [31:0] expected_status;
  always @(posedge fabricClock) if(!commonColdReset) begin
    if(rx_data_last_fire) rx_data_frames<=rx_data_frames+1;
    if(rx_status_fire) begin
      if(status_frames>=status_expected_count) $fatal(1,"PACKET_STATUS_LEDGER unexpected frame");
      case(status_words%6)
        0: expected_status=32'h50000000;
        3: expected_status=32'h00000040;
        5: expected_status=status_lengths[status_frames];
        default: expected_status=0;
      endcase
      if(rx_status_data!==expected_status || rx_status_last_fire!==(status_words%6==5))
        $fatal(1,"PACKET_STATUS6 mismatch index=%0d got=%h expected=%h last=%b",status_words,rx_status_data,expected_status,rx_status_last_fire);
      status_words<=status_words+1;
      if(rx_status_last_fire) status_frames<=status_frames+1;
    end
    if(tx_control_fire) tx_control_words<=tx_control_words+1;
    if(tx_data_last_fire) tx_data_frames<=tx_data_frames+1;
  end
  integer tx_ids[0:15],tx_lengths[0:15],tx_expected_count=0,tx_frames=0,wire_position=0;
  integer body_position,wire_body_length;
  reg [31:0] wire_crc=32'hffffffff,wire_fcs;
  reg [7:0] expected_byte;
  reg previous_tx_enable=0;
  always @(posedge txClock) if(!commonColdReset) begin
    if(tx_error) $fatal(1,"PACKET_TX_GMII_ERROR");
    if(tx_enable) begin
      if(tx_frames>=tx_expected_count) $fatal(1,"PACKET_TX_UNEXPECTED_FRAME");
      wire_body_length=tx_lengths[tx_frames]<60 ? 60 : tx_lengths[tx_frames];
      if(wire_position<7) expected_byte=8'h55;
      else if(wire_position==7) expected_byte=8'hd5;
      else if(wire_position<8+wire_body_length) begin
        body_position=wire_position-8;
        expected_byte=body_position<tx_lengths[tx_frames] ? frame_byte(tx_ids[tx_frames],body_position) : 0;
        wire_crc=crc_byte(wire_crc,expected_byte);
      end else begin
        wire_fcs=~wire_crc;
        expected_byte=(wire_fcs>>((wire_position-8-wire_body_length)*8))&255;
      end
      if(negative==1 && wire_position==23) expected_byte=expected_byte^1;
      if(tx_data!==expected_byte) $fatal(1,"PACKET_ORACLE_PAYLOAD TX frame=%0d byte=%0d got=%h expected=%h",tx_frames,wire_position,tx_data,expected_byte);
      wire_position=wire_position+1;
    end else if(previous_tx_enable) begin
      if(wire_position!=tx_lengths[tx_frames]+12) $fatal(1,"PACKET_TX_WIRE_LENGTH %0d",wire_position);
      $display("PACKET_TX_WIRE frame=%0d id=%0d bytes=%0d crc=%h",tx_frames,tx_ids[tx_frames],wire_position,~wire_crc);
      tx_frames=tx_frames+1; wire_position=0; wire_crc=32'hffffffff;
    end
    previous_tx_enable=tx_enable;
  end
  task automatic cycles(input integer n); repeat(n) @(posedge fabricClock); endtask
  task automatic access(input bit wr,input integer offset,input [63:0] value,output [63:0] result);
    integer n;
    begin
      @(negedge fabricClock); ctl_valid=1; ctl_write=wr; ctl_address=64'h10002000+offset; ctl_data=value;
      n=0; @(posedge fabricClock); while(!ctl_ready) begin n=n+1; if(n>1000) $fatal(1,"PACKET_MMIO_REQUEST_TIMEOUT"); @(posedge fabricClock); end
      @(negedge fabricClock); ctl_valid=0;
      n=0; @(posedge fabricClock); while(!ctl_response_valid) begin n=n+1; if(n>1000) $fatal(1,"PACKET_MMIO_RESPONSE_TIMEOUT"); @(posedge fabricClock); end
      if(ctl_response_error) $fatal(1,"PACKET_MMIO_ERROR offset=%h data=%h",offset,value);
      result=ctl_response_data;
      @(negedge fabricClock);
    end
  endtask
  task automatic wr(input integer offset,input [63:0] value); reg [63:0] unused; access(1,offset,value,unused); endtask
  task automatic rd(input integer offset,output [63:0] value); access(0,offset,0,value); endtask
  task automatic add_rx(input integer id,input integer offset,input integer len);
    integer w,j,p; reg [63:0] word; reg [7:0] mask;
    begin
      for(w=0;w<(len+7)/8;w=w+1) begin
        word=0; mask=0;
        for(j=0;j<8;j=j+1) begin p=w*8+j; if(p<len) begin word[j*8+:8]=frame_byte(id,p); mask[j]=1; end end
        expected_write_data[(offset>>3)+w]=word; expected_write_mask[(offset>>3)+w]=mask;
        if(negative==3 && w==0) expected_write_data[(offset>>3)+w]=word^1;
        expected_writes=expected_writes+1;
      end
      status_lengths[status_expected_count]=len; status_expected_count=status_expected_count+1;
    end
  endtask
  task automatic add_tx(input integer id,input integer offset,input integer len);
    integer w,j,p; reg [63:0] word;
    begin
      for(w=0;w<(len+7)/8;w=w+1) begin
        word=0; for(j=0;j<8;j=j+1) begin p=w*8+j; if(p<len) word[j*8+:8]=frame_byte(id,p); end
        memory[(offset>>3)+w]=word;
      end
      tx_ids[tx_expected_count]=id; tx_lengths[tx_expected_count]=len; tx_expected_count=tx_expected_count+1;
    end
  endtask
  task automatic rx_byte(input [7:0] value); begin @(negedge rxClock); rx_valid=1; rx_data=value; end endtask
  task automatic send_frame(input integer id,input integer len,input bit corrupt);
    integer j; reg [31:0] crc,fcs;
    begin
      crc=32'hffffffff;
      for(j=0;j<7;j=j+1) rx_byte(8'h55);
      rx_byte(8'hd5);
      for(j=0;j<len;j=j+1) begin rx_byte(frame_byte(id,j)); crc=crc_byte(crc,frame_byte(id,j)); end
      fcs=~crc; if(corrupt) fcs=fcs^32'h00010000;
      for(j=0;j<4;j=j+1) rx_byte((fcs>>(j*8))&255);
      @(negedge rxClock); rx_valid=0; rx_data=0;
      repeat(12) @(negedge rxClock);
    end
  endtask
  task automatic arm_rx(input integer offset); begin wr(48,64'h80200000+offset); wr(56,256); wr(64,3); end endtask
  task automatic start_tx(input integer offset,input integer len); begin wr(16,64'h80200000+offset); wr(24,len); wr(32,3); end endtask
  task automatic post_rx(input integer offset); begin wr(160,64'h80200000+offset); wr(168,256); wr(176,1); end endtask
  task automatic post_tx(input integer offset,input integer len); begin wr(224,64'h80200000+offset); wr(232,len); wr(240,4); end endtask
  task automatic wait_flag(input integer which);
    integer n; bit value;
    begin
      n=0; value=0;
      while(!value) begin
        @(negedge fabricClock); n=n+1;
        case(which)
          0: value=status_blocked; 1:value=rx_closed; 2:value=dma_owners_idle;
          3:value=rx_drained; 4:value=tx_drained; 5:value=control_blocked; 6:value=data_blocked;
          7:value=dma_tx_idle; 8:value=mem_valid; 9:value=released;
          10:value=memory_writes>0; 11:value=memory_reads>=4;
          12:value=downstream_valid; 13:value=retirement_permit;
        endcase
        if(n>10000) $fatal(1,"PACKET_WAIT_TIMEOUT flag=%0d reads=%0d writes=%0d outstanding=%0d txframes=%0d",which,memory_reads,memory_writes,outstanding,tx_frames);
      end
    end
  endtask
  task automatic close_admission;
    begin
      @(negedge fabricClock);
      if(epoch_busy) $fatal(1,"PACKET_EPOCH_NEW_WHILE_OWNED");
      prepare_epoch=prepare_epoch+1; prepare_valid=1; downstream_ready=0;
    end
  endtask
  task automatic finish_close;
    begin
      wait_flag(7); wait_flag(3); wait_flag(4); wait_flag(2); wait_flag(12);
      cycles(25);
      if(!epoch_busy || !epoch_held || held_epoch!=prepare_epoch || prepare_ready || retirement_permit ||
          !runtime_pause || !rx_stop_request || !tx_stop_request)
        $fatal(1,"PACKET_EPOCH_PREPARE_BACKPRESSURE");
      @(negedge fabricClock); downstream_ready=1;
      @(posedge fabricClock); if(!prepare_ready) $fatal(1,"PACKET_EPOCH_PREPARE_NOT_ACCEPTED");
      @(negedge fabricClock); prepare_valid=0; downstream_ready=0;
      cycles(30);
      if(!epoch_busy || !epoch_held || !runtime_pause || retirement_permit || !rx_closed)
        $fatal(1,"PACKET_EPOCH_TERMINAL_BACKPRESSURE released without receipt");
      $display("PACKET_EPOCH_HELD epoch=%0d prepares=%0d modeled_terminal=backpressured",prepare_epoch,prepares);
    end
  endtask
  task automatic reopen;
    begin
      @(negedge fabricClock); terminal_consumed=1;
      @(posedge fabricClock);
      @(negedge fabricClock); terminal_consumed=0;
      if(retirement_permit) $fatal(1,"PACKET_EPOCH_RELEASE_BEFORE_RX_MAILBOX_ACK");
      wait_flag(9); wait_flag(13);
      // A new offer cannot overtake the still-owned terminal receipt.
      @(negedge fabricClock); prepare_valid=1; prepare_epoch=prepare_epoch+1;
      cycles(20);
      if(prepare_ready || downstream_valid || !epoch_busy || !retirement_permit)
        $fatal(1,"PACKET_EPOCH_NEW_PREPARE_OVERTOOK_RETIREMENT");
      @(negedge fabricClock); prepare_valid=0; prepare_epoch=prepare_epoch-1; retired=1;
      @(posedge fabricClock);
      @(negedge fabricClock); retired=0;
      cycles(3);
      if(epoch_busy || runtime_pause) $fatal(1,"PACKET_EPOCH_RETIREMENT_STUCK");
      @(negedge fabricClock); prepare_valid=1;
      cycles(15);
      if(epoch_busy || runtime_pause || prepare_ready || downstream_valid)
        $fatal(1,"PACKET_DUPLICATE_RETIRED_EPOCH_ACCEPTED");
      @(negedge fabricClock); prepare_epoch=prepare_epoch-1;
      cycles(15);
      if(epoch_busy || runtime_pause || prepare_ready || downstream_valid)
        $fatal(1,"PACKET_STALE_RETIRED_EPOCH_ACCEPTED");
      @(negedge fabricClock); prepare_valid=0; prepare_epoch=prepare_epoch+1;
      $display("PACKET_EPOCH_RELEASED epoch=%0d receipts=%0d",prepare_epoch,retirements);
    end
  endtask
  task automatic check_writes;
    integer j;
    begin
      if(memory_writes!=expected_writes) $fatal(1,"PACKET_RX_WRITE_COUNT got=%0d expected=%0d",memory_writes,expected_writes);
      for(j=0;j<8192;j=j+1) if(expected_write_mask[j]!=0 && write_seen[j]!=1) $fatal(1,"PACKET_RX_MISSING_WRITE %0d",j);
    end
  endtask
  reg [63:0] value;
  integer before_reads,before_writes,timeout_count,j;
  initial begin
    for(j=0;j<8192;j=j+1) begin memory[j]=0; expected_write_data[j]=0; expected_write_mask[j]=0; write_seen[j]=0; end
    cycles(8); @(negedge fabricClock); commonColdReset=0; cycles(25);
    if(test_case==0) begin
      add_rx(1,'h100,61); arm_rx('h100); hold_rx_status_last=1;
      fork
        send_frame(1,61,0);
        begin repeat(25) @(posedge rxClock); close_admission(); end
      join
      wait_flag(0); wait_flag(1); cycles(15);
      if(rx_drained || dma_owners_idle || status_words!=5 || rx_data_frames!=1 || memory_writes!=0)
        $fatal(1,"PACKET_STATUS6_DRAIN status=%0d writes=%0d",status_words,memory_writes);
      $display("PACKET_RX_STATUS6_HELD accepted=%0d status=%0d",accepted_frames,status_words);
      @(negedge fabricClock); hold_mem_response=1; hold_rx_status_last=0;
      wait_flag(10); cycles(30);
      if(dma_owners_idle || outstanding==0) $fatal(1,"PACKET_RX_ACCEPTED_REPLY_OWNER lost");
      send_frame(8,61,0); send_frame(9,65,0);
      if(accepted_frames!=1 || closed_drops!=2) $fatal(1,"PACKET_CLOSED_RX_LEDGER accepted=%0d closed=%0d",accepted_frames,closed_drops);
      @(negedge fabricClock); hold_mem_response=0;
      fork
        send_frame(30,256,0);
        begin
          repeat(10) @(posedge rxClock);
          finish_close();
          if(!rx_valid || !rx_closed || !rx_drained)
            $fatal(1,"PACKET_CLOSED_PHYSICAL_RX_BLOCKED_DRAIN");
          $display("PACKET_CLOSED_WIRE_ACTIVE_DRAIN epoch=%0d",prepare_epoch);
        end
      join
      check_writes();
      add_rx(2,'h200,65); arm_rx('h200); cycles(10);
      if(!dma_active || !dma_owners_idle) $fatal(1,"PACKET_ARMED_EMPTY_RX_NOT_PARKED");
      before_writes=memory_writes; send_frame(10,61,0);
      if(memory_writes!=before_writes || closed_drops!=4) $fatal(1,"PACKET_PAUSED_RX_DESCRIPTOR consumed");
      reopen(); send_frame(2,65,0);
      timeout_count=0; while(memory_writes!=expected_writes) begin cycles(1); timeout_count=timeout_count+1;
        if(timeout_count>10000) $fatal(1,"PACKET_RX_RESUME_TIMEOUT"); end
      wait_flag(2); cycles(10);
      check_writes(); wr(64,2); arm_rx('h300); send_frame(3,61,1); cycles(20);
      if(bad_fcs_drops!=1 || accepted_frames!=2 || status_frames!=2 || memory_writes!=expected_writes)
        $fatal(1,"PACKET_BAD_FCS_LEDGER bad=%0d accepted=%0d status=%0d",bad_fcs_drops,accepted_frames,status_frames);
      close_admission(); finish_close();
      $display("PACKET_RX_LEDGER accepted=%0d closed_drops=%0d bad_fcs=%0d status_words=%0d writes=%0d",accepted_frames,closed_drops,bad_fcs_drops,status_words,memory_writes);
    end else if(test_case==1) begin
      add_tx(4,'h1000,61); add_tx(5,'h1100,65);
      hold_mem_request=1; hold_tx_control_last=1; hold_tx_data_last=1;
      start_tx('h1000,61); wait_flag(8); close_admission(); cycles(35);
      if(!mem_valid || dma_tx_idle || dma_owners_idle || memory_reads!=0) $fatal(1,"PACKET_TX_HELD_PREFETCH_OWNER lost");
      @(negedge fabricClock); hold_mem_response=1; hold_mem_request=0;
      wait_flag(11); cycles(20);
      if(outstanding!=4 || dma_tx_idle) $fatal(1,"PACKET_TX_PREFETCH_CREDITS got=%0d",outstanding);
      @(negedge fabricClock); hold_mem_response=0;
      wait_flag(5); cycles(20);
      if(dma_tx_idle || tx_control_words!=5) $fatal(1,"PACKET_TX_CONTROL_TAIL lost");
      @(negedge fabricClock); hold_tx_control_last=0;
      wait_flag(6); cycles(20);
      if(dma_tx_idle || tx_frames!=0) $fatal(1,"PACKET_TX_DATA_TAIL lost");
      @(negedge fabricClock); hold_tx_data_last=0;
      wait_flag(7);
      if(tx_drained) $fatal(1,"PACKET_TX_WIRE_TAIL falsely drained");
      finish_close(); cycles(5);
      if(tx_frames!=1 || tx_control_words!=6 || tx_data_frames!=1) $fatal(1,"PACKET_TX_OLD_OWNER_LEDGER");
      before_reads=memory_reads; start_tx('h1100,65); cycles(40);
      if(memory_reads!=before_reads || !dma_tx_idle || !dma_owners_idle || !dma_active)
        $fatal(1,"PACKET_PAUSED_LEGACY_TX_LAUNCHED");
      reopen();
      timeout_count=0; while(tx_frames!=2) begin cycles(1); timeout_count=timeout_count+1; if(timeout_count>10000) $fatal(1,"PACKET_TX_RESUME_TIMEOUT"); end
      close_admission(); finish_close();
      if(memory_reads!=17 || tx_control_words!=12 || tx_data_frames!=2) $fatal(1,"PACKET_TX_FINAL_LEDGER reads=%0d",memory_reads);
      $display("PACKET_TX_LEDGER frames=%0d reads=%0d control_words=%0d",tx_frames,memory_reads,tx_control_words);
    end else if(test_case==2) begin
      add_rx(11,'h100,61); add_rx(12,'h200,65); add_rx(13,'h300,60);
      add_tx(14,'h1000,61); add_tx(15,'h1100,65);
      wr(184,1); post_rx('h100); post_rx('h200); post_rx('h300);
      wr(240,1); hold_mem_response=1; post_tx('h1000,61); wait_flag(11); close_admission(); post_tx('h1100,65);
      @(negedge fabricClock); hold_mem_response=0; finish_close(); cycles(10);
      rd(248,value); if(value!==64'h40101) $fatal(1,"PACKET_POSTED_TX_PAUSE_OWNERS got=%h",value);
      rd(192,value); if(value!==64'h10002) $fatal(1,"PACKET_POSTED_RX_PAUSE_OWNERS got=%h",value);
      if(!dma_active || !dma_owners_idle || tx_frames!=1) $fatal(1,"PACKET_POSTED_EMPTY_PARKING");
      before_reads=memory_reads; send_frame(21,61,0); send_frame(22,65,0); cycles(20);
      if(memory_reads!=before_reads || memory_writes!=0 || accepted_frames!=0 || closed_drops!=2) $fatal(1,"PACKET_POSTED_PAUSE_CHANGED_LEDGER");
      reopen(); send_frame(11,61,0); send_frame(12,65,0); send_frame(13,60,0);
      timeout_count=0; value=0;
      while(value!=64'h300) begin rd(192,value); timeout_count=timeout_count+1; if(timeout_count>1000) $fatal(1,"PACKET_POSTED_RX_COMPLETION_TIMEOUT %h",value); end
      timeout_count=0; while(tx_frames!=2) begin cycles(1); timeout_count=timeout_count+1; if(timeout_count>10000) $fatal(1,"PACKET_POSTED_TX_RESUME_TIMEOUT"); end
      close_admission(); finish_close(); check_writes();
      for(j=0;j<3;j=j+1) begin
        rd(200,value); if(value!=64'h80200100+j*256) $fatal(1,"PACKET_RX_COMPLETION_ADDRESS %h",value);
        rd(208,value); if(value!=status_lengths[j]) $fatal(1,"PACKET_RX_COMPLETION_METADATA %h",value);
        wr(216,1);
      end
      for(j=0;j<2;j=j+1) begin
        rd(224,value); if(value!=64'h80201000+j*256) $fatal(1,"PACKET_TX_COMPLETION_ADDRESS %h",value);
        rd(232,value); if(value!=tx_lengths[j]) $fatal(1,"PACKET_TX_COMPLETION_METADATA %h",value);
        wr(240,8);
      end
      rd(192,value); if(value!=0) $fatal(1,"PACKET_RX_COMPLETION_POP_OWNERS %h",value);
      rd(248,value); if(value!=64'h40000) $fatal(1,"PACKET_TX_COMPLETION_POP_OWNERS %h",value);
      // Pausing launch must not alter the existing empty-queue MMIO ABI.
      wr(240,2); rd(240,value); if(value!=0) $fatal(1,"PACKET_PAUSED_EMPTY_TX_DISABLE");
      wr(240,1); rd(240,value); if(value!=1) $fatal(1,"PACKET_PAUSED_EMPTY_TX_ENABLE");
      wr(240,2);
      if(accepted_frames!=3 || status_frames!=3 || tx_frames!=2 || closed_drops!=2) $fatal(1,"PACKET_POSTED_FINAL_LEDGER");
      $display("PACKET_POSTED_LEDGER accepted=%0d status_words=%0d writes=%0d txframes=%0d closed=%0d",accepted_frames,status_words,memory_writes,tx_frames,closed_drops);
    end else if(test_case==3) begin
      add_tx(16,'h1000,61); hold_mem_response=1;
      start_tx('h1000,61); wait_flag(11); close_admission(); wait_flag(1); cycles(20);
      if(!epoch_busy || !runtime_pause || outstanding!=4 || memory_replies!=0 || tx_frames!=0 || downstream_valid)
        $fatal(1,"PACKET_RESET_ACTIVE_OWNER_NOT_ESTABLISHED");
      $display("PACKET_RESET_DISCARDED epoch=%0d accepted_reads=%0d unreplied_reads=%0d tx_frames=%0d",prepare_epoch,memory_requests,outstanding,tx_frames);
      @(negedge fabricClock); commonColdReset=1; prepare_valid=0; prepare_epoch=0;
      downstream_ready=0; terminal_consumed=0; retired=0; hold_mem_response=0; tx_expected_count=0;
      cycles(8); @(negedge fabricClock); commonColdReset=0; cycles(25);
      if(epoch_busy || runtime_pause || !dma_owners_idle || outstanding!=0 || mem_valid || tx_frames!=0)
        $fatal(1,"PACKET_RESET_STALE_OWNER_SURVIVED");
      add_tx(17,'h1200,60); start_tx('h1200,60);
      timeout_count=0; while(tx_frames!=1) begin cycles(1); timeout_count=timeout_count+1;
        if(timeout_count>10000) $fatal(1,"PACKET_RESET_FRESH_PACKET_TIMEOUT"); end
      close_admission(); finish_close();
      if(memory_reads!=8 || memory_replies!=8 || tx_frames!=1)
        $fatal(1,"PACKET_RESET_FRESH_LEDGER");
      $display("PACKET_RESET_FRESH_LEDGER txframes=%0d accepted=%0d replied=%0d",tx_frames,memory_requests,memory_replies);
    end else $fatal(1,"unknown packet case");
    cycles(20);
    if(memory_requests!=memory_replies || outstanding!=0 || !dma_owners_idle || !rx_drained || !tx_drained)
      $fatal(1,"PACKET_FINAL_OWNER_LEDGER requests=%0d replies=%0d outstanding=%0d",memory_requests,memory_replies,outstanding);
    reopen(); cycles(20);
    if(epoch_busy || !released || runtime_pause || prepares!=retirements)
      $fatal(1,"PACKET_FINAL_EPOCH_LEDGER prepares=%0d retirements=%0d",prepares,retirements);
    $display("NETWORK_PACKET_RUNTIME_PASS case=%0d clocks=%0d/%0d/%0d memory=%0d/%0d",test_case,fabric_half,rx_half,tx_half,memory_requests,memory_replies);
    $finish;
  end
  initial begin #20000000; $fatal(1,"PACKET_GLOBAL_TIMEOUT"); end
endmodule
