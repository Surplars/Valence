`timescale 1ns/1ps
// Independent-edge production-boundary regression. This is digital CDC/order
// proof only: PHY discovery is bypassed, BUFGCE is a declared behavioral model.
module mac_boundary_cdc_tb;
    reg cpu=0,aon=0,raw_tx=0,raw_rx=0,rx_run=0;
    real rx_half=4.0;
    always #5 cpu=~cpu;
    initial begin #2.3; forever #10 aon=~aon; end
    initial begin #1.1; forever #4 raw_tx=~raw_tx; end
    initial begin #3.2; forever begin #(rx_half); if(rx_run)raw_rx=~raw_rx; else raw_rx=0; end end
    reg reset=0,stop_tx=0,stop_rx=0;
    reg requested_link=1;
    reg [1:0] requested_speed=2;
    reg [4:0] rise=0,fall=0;
    reg req_valid=0,req_write=0,resp_ready=1;
    reg [63:0] req_addr=0,req_data=0;
    wire req_ready,resp_valid,resp_error;
    wire [63:0] resp_data;
    reg txv=0,txlast=0,ctlv=0,ctllast=0;
    reg [31:0] txdata=0,ctldata=0;
    reg [3:0] txkeep=15;
    wire txready,ctlready,rxv,rxlast,statusv,statuslast;
    wire [31:0] rxdata,statusdata;
    wire [3:0] rxkeep,statuskeep;
    reg data_service=1,status_service=1;
    integer cpu_edges=0;
    wire rxready=data_service && (cpu_edges%7!=1) && (cpu_edges%7!=2);
    wire statusready=status_service && (cpu_edges%5!=2);
    wire tx_clock,rx_clock,stopped_tx,stopped_rx,fault_tx,fault_rx,link,pending;
    wire [1:0] applied;
    TriSpeedManagedBoundaryCdcTop dut(
        .sourceClock(cpu),.alwaysOnClock(aon),.rawTxClock(raw_tx),.rawRxClock(raw_rx),.commonReset(reset),
        .stop_0(stop_tx),.stop_1(stop_rx),.txClock(tx_clock),.rxClock(rx_clock),
        .stopped_0(stopped_tx),.stopped_1(stopped_rx),.fault_0(fault_tx),.fault_1(fault_rx),
        .linkUp(link),.appliedSpeed(applied),.mediaPending(pending),
        .rawRgmiiRxRise(rise),.rawRgmiiRxFall(fall),
        .registers_request_valid(req_valid),.registers_request_ready(req_ready),
        .registers_request_bits_address(req_addr),.registers_request_bits_write(req_write),
        .registers_request_bits_size(3'd3),.registers_request_bits_data(req_data),.registers_request_bits_byteEnable(8'hff),
        .registers_response_valid(resp_valid),.registers_response_ready(resp_ready),
        .registers_response_bits_data(resp_data),.registers_response_bits_error(resp_error),
        .streams_txData_valid(txv),.streams_txData_ready(txready),.streams_txData_bits_data(txdata),
        .streams_txData_bits_keep(txkeep),.streams_txData_bits_last(txlast),
        .streams_txControl_valid(ctlv),.streams_txControl_ready(ctlready),.streams_txControl_bits_data(ctldata),
        .streams_txControl_bits_keep(4'hf),.streams_txControl_bits_last(ctllast),
        .streams_rxData_valid(rxv),.streams_rxData_ready(rxready),.streams_rxData_bits_data(rxdata),
        .streams_rxData_bits_keep(rxkeep),.streams_rxData_bits_last(rxlast),
        .streams_rxStatus_valid(statusv),.streams_rxStatus_ready(statusready),.streams_rxStatus_bits_data(statusdata),
        .streams_rxStatus_bits_keep(statuskeep),.streams_rxStatus_bits_last(statuslast));
    // Only environmental discovery is bypassed. All admission, ownership,
    // consumed-image ACK and endpoint-ready signals remain actual production.
    initial begin
        force dut.gmac.media.io_requestedLink=requested_link;
        force dut.gmac.media.io_requestedSpeed=requested_speed;
    end
    always @(dut.gmac.physicalIngress.commonReset)if($test$plusargs("trace_epoch"))
        $display("EPOCH_RESET_EDGE time=%0t value=%b state=%0d active=%b changed=%b link=%b sourceReady=%b destReady=%b returned=%b",$time,dut.gmac.physicalIngress.commonReset,dut.gmac.media.state,dut.gmac.media.activeLink,dut.gmac.media.changed,link,dut.gmac.physicalIngress.sourceReady,dut.gmac.physicalIngress.destinationReady,dut.gmac.media.io_ingressReady);
    function automatic [31:0] crc_byte(input [31:0] crc,input [7:0] value);
        reg [31:0] work; begin work=crc;
            for(integer b=0;b<8;b=b+1)work=(work>>1)^((work[0]^value[b])?32'hedb88320:0);
            crc_byte=work;
        end
    endfunction
    function automatic [7:0] body_byte(input integer generation,input integer position);
        reg [7:0] value; begin
            value=((position*73+generation*19+11)^(position>>3))&255;
            case(position)0:value=2;1:value=8'h11;2:value=8'h22;3:value=8'h33;4:value=8'h44;
                5:value=8'h55;12:value=8'h08;13:value=0;endcase
            body_byte=value;
        end
    endfunction
    // Monotonic generation keys, never a reused DUT slot number, identify all
    // expectations. >4 successive frames force physical bank reuse.
    integer rx_length[0:127],rx_generation[0:127];
    integer rx_tail=0,rx_head=0,rx_position=0,status_head=0,status_position=0;
    integer tx_length[0:127],tx_generation[0:127],tx_reject[0:127];
    reg [7:0] tx_wire[0:127][0:4095];
    integer tx_tail=0,tx_head=0,tx_position=0,tx_admitted=0;
    integer tx_slots=1,tx_native_ends=0,max_native_owners=0,expected_reject_total=0,queued_abort_checks=0;
    integer tx_done=0,tx_rejected=0,tx_aborted=0,rx_accepted=0,rx_dropped=0,rx_badfcs=0;
    integer expected_drops=0,expected_tx_bytes=0,expected_rx_bytes=0;
    integer tx_delta_done=0,tx_delta_rejected=0,tx_delta_bytes=0,tx_delta_aborted=0;
    integer rx_delta_accepted=0,rx_delta_dropped=0,rx_delta_badfcs=0,rx_delta_bytes=0;
    integer tx_offers=0,rx_offers=0,tx_consumes=0,rx_consumes=0;
    integer tx_offer_speed[0:127],rx_offer_speed[0:127];
    integer rate_closed_consumes=0,halt_checks=0,gate_checks=0,rate_changes=0,rx_edge_closes=0;
    integer source_sample_checks=0,wire_sample_checks=0;
    reg negative_payload_used=0,negative_event_used=0,negative_drain_used=0;
    reg rx_was_stalled=0,status_was_stalled=0;
    reg previous_stopped_tx=0,previous_stopped_rx=0;
    reg [36:0] held_rx=0,held_status=0;
    reg [31:0] expected_status;
    reg [7:0] expected_byte;
    reg observed_rx_stopped;
    integer expected_reject;
    always @(posedge cpu) begin
        cpu_edges=cpu_edges+1;
        if(!reset && !dut.gmac.cpuRelease.resetOut)begin
            if(fault_tx || fault_rx)$fatal(1,"MAC_CDC_GATE_POLICY_FAULT");
            if(dut.gmac.txRate.sourceIdle && tx_consumes!=tx_offers)$fatal(1,"MAC_CDC_PHANTOM_TX_ACK");
            if(dut.gmac.rxRate.sourceIdle && rx_consumes!=rx_offers)$fatal(1,"MAC_CDC_PHANTOM_RX_ACK");
            if(dut.gmac.media.io_txRate_valid && dut.gmac.media.io_txRate_ready)begin
                tx_offer_speed[tx_offers]=dut.gmac.media.io_txRate_bits;tx_offers=tx_offers+1;end
            if(dut.gmac.media.io_rxRate_valid && dut.gmac.media.io_rxRate_ready)begin
                rx_offer_speed[rx_offers]=dut.gmac.media.io_rxRate_bits;rx_offers=rx_offers+1;end
            if(link && (tx_consumes!=tx_offers || rx_consumes!=rx_offers ||
                !dut.gmac.txRate.sourceIdle || !dut.gmac.rxRate.sourceIdle ||
                !dut.gmac.physicalIngress.sourceReady || !dut.gmac.physicalIngress.destinationReady ||
                !dut.gmac.media.io_ingressReady))$fatal(1,"MAC_CDC_EARLY_REOPEN tx=%0d/%0d rx=%0d/%0d idle=%b/%b epoch=%b/%b returned=%b link=%b pending=%b",tx_consumes,tx_offers,rx_consumes,rx_offers,dut.gmac.txRate.sourceIdle,dut.gmac.rxRate.sourceIdle,dut.gmac.physicalIngress.sourceReady,dut.gmac.physicalIngress.destinationReady,dut.gmac.media.io_ingressReady,link,pending);
            if(dut.gmac.media.io_stopNewTraffic && ctlready && dut.gmac.adapter.controlIndex==0)
                $fatal(1,"MAC_CDC_CPU_ADMISSION_CLOSE");
            if(ctlv && ctlready && dut.gmac.adapter.controlIndex==0)tx_admitted=tx_admitted+1;
            if(rx_was_stalled && (!rxv || {rxlast,rxkeep,rxdata}!==held_rx))$fatal(1,"MAC_CDC_RX_HOLD");
            if(status_was_stalled && (!statusv || {statuslast,statuskeep,statusdata}!==held_status))$fatal(1,"MAC_CDC_STATUS_HOLD");
            rx_was_stalled=rxv&&!rxready;held_rx={rxlast,rxkeep,rxdata};
            status_was_stalled=statusv&&!statusready;held_status={statuslast,statuskeep,statusdata};
            if(rxv && rxready)begin
                if(rx_head>=rx_tail)$fatal(1,"MAC_CDC_UNEXPECTED_RX_GENERATION");
                if(rxkeep!==((rx_length[rx_head]-rx_position>=4)?4'hf:((1<<(rx_length[rx_head]-rx_position))-1)))
                    $fatal(1,"MAC_CDC_RX_KEEP");
                for(integer b=0;b<4;b=b+1)if(rxkeep[b])begin
                    expected_byte=body_byte(rx_generation[rx_head],rx_position);
                    if($test$plusargs("bad_payload")&&!negative_payload_used)begin
                        expected_byte=expected_byte^8'h80;negative_payload_used=1;end
                    if(rxdata[8*b+:8]!==expected_byte)
                        $fatal(1,"MAC_CDC_PAYLOAD_ORACLE generation=%0d byte=%0d",rx_generation[rx_head],rx_position);
                    rx_position=rx_position+1;
                end
                if(rxlast !== (rx_position==rx_length[rx_head]))$fatal(1,"MAC_CDC_RX_LAST");
                if(rxlast)begin rx_head=rx_head+1;rx_position=0;end
            end
            if(statusv && statusready)begin
                if(status_head>=rx_head)$fatal(1,"MAC_CDC_STATUS_BEFORE_DATA");
                expected_status=(status_position==0)?32'h50000000:(status_position==3)?32'd64:
                    (status_position==5)?rx_length[status_head]:0;
                if(statuskeep!==15 || statuslast!==(status_position==5) || statusdata!==expected_status)
                    $fatal(1,"MAC_CDC_STATUS_ORACLE generation=%0d word=%0d",rx_generation[status_head],status_position);
                if(status_position==5)begin status_head=status_head+1;status_position=0;end
                else status_position=status_position+1;
            end
            if(dut.gmac.txStats.delta_valid)begin
                tx_delta_done=tx_delta_done+dut.gmac.txStats.delta_bits_0;
                tx_delta_rejected=tx_delta_rejected+dut.gmac.txStats.delta_bits_1;
                tx_delta_bytes=tx_delta_bytes+dut.gmac.txStats.delta_bits_2;
                tx_delta_aborted=tx_delta_aborted+dut.gmac.txStats.delta_bits_3;
            end
            if(dut.gmac.rxStats.delta_valid)begin
                rx_delta_accepted=rx_delta_accepted+dut.gmac.rxStats.delta_bits_0;
                rx_delta_dropped=rx_delta_dropped+dut.gmac.rxStats.delta_bits_1;
                rx_delta_badfcs=rx_delta_badfcs+dut.gmac.rxStats.delta_bits_2;
                rx_delta_bytes=rx_delta_bytes+dut.gmac.rxStats.delta_bits_3;
            end
            // An independent ledger, not synchronized idle equality, constrains
            // the instant a real policy is allowed to report stopped.
            if(stopped_tx && !previous_stopped_tx && (tx_head!=tx_admitted || !dut.gmac.adapter.io_txIdle ||
                !dut.gmac.txFifo.sourceIdle || !dut.gmac.txFifo.destinationIdle || dut.gmac.tx.io_busy ||
                !dut.gmac.txStats.sourceIdle || !dut.gmac.txStats.destinationIdle ||
                !dut.gmac.txConfig.sourceIdle || dut.gmac.txConfig.destination_valid))
                $fatal(1,"MAC_CDC_TX_STOP_OWNER_ORACLE");
            observed_rx_stopped=stopped_rx;
            if($test$plusargs("bad_drain") && rx_head>status_head && !negative_drain_used)begin
                observed_rx_stopped=1;negative_drain_used=1;end
            if(observed_rx_stopped && !previous_stopped_rx && (status_head!=rx_accepted || !dut.gmac.adapter.io_rxIdle ||
                !dut.gmac.rxFifo.sourceIdle || !dut.gmac.rxFifo.destinationIdle || dut.gmac.rx.io_busy ||
                !dut.gmac.ingress.empty || !dut.gmac.rxStats.sourceIdle || !dut.gmac.rxStats.destinationIdle ||
                !dut.gmac.rxDiagnostics.sourceIdle || !dut.gmac.rxDiagnostics.destinationIdle ||
                !dut.gmac.rxConfig.sourceIdle || dut.gmac.rxConfig.destination_valid))
                $fatal(1,"MAC_CDC_RX_STOP_OWNER_ORACLE status=%0d accepted=%0d planned=%0d adapter=%b fifos=%b/%b busy=%b ingress=%b stats=%b/%b diag=%b/%b config=%b/%b",status_head,rx_accepted,rx_tail,dut.gmac.adapter.io_rxIdle,dut.gmac.rxFifo.sourceIdle,dut.gmac.rxFifo.destinationIdle,dut.gmac.rx.io_busy,dut.gmac.ingress.empty,dut.gmac.rxStats.sourceIdle,dut.gmac.rxStats.destinationIdle,dut.gmac.rxDiagnostics.sourceIdle,dut.gmac.rxDiagnostics.destinationIdle,dut.gmac.rxConfig.sourceIdle,dut.gmac.rxConfig.destination_valid);
            previous_stopped_tx=stopped_tx;previous_stopped_rx=stopped_rx;
        end
    end
    reg expected_open,expected_epoch;
    always @(posedge cpu) begin
        expected_open=dut.gmac.media.io_linkUp;
        expected_epoch=!(dut.gmac.media.state==4 || (dut.gmac.media.state==0 &&
            dut.gmac.media.activeLink && !dut.gmac.media.changed));
        if(!reset && !dut.gmac.cpuRelease.resetOut)begin
            #0.2;if(dut.gmac.mediaOpen!==expected_open)$fatal(1,"MAC_CDC_SOURCE_REGISTER");
            if(dut.gmac.media.io_ingressReset!==expected_epoch)$fatal(1,"MAC_CDC_EPOCH_SOURCE_REGISTER");
            source_sample_checks=source_sample_checks+1;
        end
    end
    reg expected_empty,expected_wire;
    always @(posedge raw_tx)begin
        expected_empty=dut.gmac.ingress.empty;
        expected_wire=!dut.gmac.tx.io_busy&&dut.gmac.txFifo.destinationIdle&&dut.gmac.encode.io_idle;
        if(!reset && !dut.gmac.rawTxRelease.resetOut)begin
            if(dut.gmac.encode.io_rate_valid && dut.gmac.encode.io_rate_ready)begin
                if(tx_consumes>=tx_offers || dut.gmac.encode.io_rate_bits!=tx_offer_speed[tx_consumes] ||
                    !dut.gmac.encode.io_datapathIdle || !dut.gmac.encode.io_idle)
                    $fatal(1,"MAC_CDC_TX_RATE_CONSUME_ORACLE");
                tx_consumes=tx_consumes+1;
            end
            #0.2;
            if(dut.gmac.ingressEmptySource!==expected_empty || dut.gmac.txWireDrainedSource!==expected_wire)
                $fatal(1,"MAC_CDC_RETURN_SOURCE_REGISTER");
            wire_sample_checks=wire_sample_checks+1;
        end
    end
    always @(posedge raw_rx)if(!reset && !dut.gmac.rawRxRelease.resetOut)begin
        if(dut.gmac.decode.io_abort!==!dut.gmac.physicalIngress.captureEnable ||
            dut.gmac.decode.io_admissionClosed!==dut.gmac.decode.io_abort)$fatal(1,"MAC_CDC_RAW_OPEN_ABORT");
        if(dut.gmac.decode.io_rate_valid && dut.gmac.decode.io_rate_ready)begin
            if(rx_consumes>=rx_offers || dut.gmac.decode.io_rate_bits!=rx_offer_speed[rx_consumes] ||
                !dut.gmac.decode.io_admissionClosed)$fatal(1,"MAC_CDC_RX_RATE_CONSUME_ORACLE");
            rx_consumes=rx_consumes+1;rate_closed_consumes=rate_closed_consumes+1;
        end
        if(dut.gmac.physicalIngress.overflow || dut.gmac.physicalIngress.wholeFrameSkipped || dut.gmac.decode.io_oddNibble)
            $fatal(1,"MAC_CDC_UNEXPECTED_RAW_EVENT");
    end
    always @(posedge tx_clock)if(!reset && !dut.gmac.txRelease.resetOut)begin
        if(dut.gmac.tx.io_abort!==!dut.gmac.txLink_sync.levelOut ||
            (dut.gmac.tx.io_enable && dut.gmac.tx.io_abort))$fatal(1,"MAC_CDC_TX_OPEN_ABORT");
        if(dut.gmac.tx.io_frame_valid && dut.gmac.tx.io_frame_ready && dut.gmac.tx.io_frame_bits_last)
            tx_native_ends=tx_native_ends+1;
        if(dut.gmac.tx.io_gmiiEnable && dut.gmac.encode.io_byteStep)begin
            if(tx_head>=tx_tail || tx_position>=tx_length[tx_head]+12 ||
                dut.gmac.tx.io_gmiiData!==tx_wire[tx_head][tx_position] || dut.gmac.tx.io_gmiiError)
                $fatal(1,"MAC_CDC_TX_WIRE_ORACLE generation=%0d byte=%0d",tx_head,tx_position);
            tx_position=tx_position+1;
        end
        if(dut.gmac.tx.io_done || dut.gmac.tx.io_rejected)begin
            expected_reject=tx_reject[tx_head];
            if($test$plusargs("bad_event")&&!negative_event_used)begin
                expected_reject=1-expected_reject;negative_event_used=1;end
            if(tx_head>=tx_tail || (dut.gmac.tx.io_done&&dut.gmac.tx.io_rejected) ||
                dut.gmac.tx.io_rejected!==expected_reject ||
                (dut.gmac.tx.io_done && tx_position!=tx_length[tx_head]+12))
                $fatal(1,"MAC_CDC_TX_EVENT_ORACLE generation=%0d",tx_head);
            tx_done=tx_done+dut.gmac.tx.io_done;tx_rejected=tx_rejected+dut.gmac.tx.io_rejected;
            tx_aborted=tx_aborted+dut.gmac.tx.io_aborted;
            tx_head=tx_head+1;tx_position=0;
        end else if(dut.gmac.tx.io_aborted)$fatal(1,"MAC_CDC_ABORT_WITHOUT_OUTCOME");
        if(tx_native_ends-tx_head>max_native_owners)max_native_owners=tx_native_ends-tx_head;
    end
    always @(posedge rx_clock)if(!reset && !dut.gmac.rxRelease.resetOut)begin
        if(dut.gmac.rx.io_abort!==!dut.gmac.rxLink_sync.levelOut ||
            (dut.gmac.rx.io_enable && dut.gmac.rx.io_abort))$fatal(1,"MAC_CDC_RX_OPEN_ABORT");
        rx_accepted=rx_accepted+dut.gmac.rx.io_accepted;rx_dropped=rx_dropped+dut.gmac.rx.io_dropped;
        rx_badfcs=rx_badfcs+dut.gmac.rx.io_badFcs;
    end
    task automatic cpu_wait(input integer n);begin repeat(n)@(negedge cpu);end endtask
    task automatic mmio(input integer offset,input reg write,input [63:0] value,output reg [63:0] result);
        begin
            @(negedge cpu);req_addr=64'h10040000+offset;req_write=write;req_data=value;req_valid=1;
            @(posedge cpu);while(!req_ready)@(posedge cpu);
            @(negedge cpu);req_valid=0;
            @(posedge cpu);while(!resp_valid)@(posedge cpu);
            if(resp_error)$fatal(1,"MAC_CDC_MMIO_ERROR offset=%0h",offset);result=resp_data;
            @(negedge cpu);
        end
    endtask
    task automatic rx_idle(input integer cycles);begin
        @(negedge raw_rx);rise=0;fall=0;repeat(cycles)@(negedge raw_rx);
    end endtask
    task automatic rx_byte(input [7:0] value);begin
        @(negedge raw_rx);
        if(requested_speed==2)begin rise={1'b1,value[3:0]};fall={1'b1,value[7:4]};end
        else begin
            rise={1'b1,value[3:0]};fall={1'b1,value[3:0]};
            @(negedge raw_rx);rise={1'b1,value[7:4]};fall={1'b1,value[7:4]};
        end
    end endtask
    task automatic send_rx(input integer length,input integer generation,input reg publish);
        reg [31:0] crc;begin
            if(publish)begin rx_length[rx_tail]=length;rx_generation[rx_tail]=generation;rx_tail=rx_tail+1;
                expected_rx_bytes=expected_rx_bytes+length;end
            for(integer i=0;i<7;i=i+1)rx_byte(8'h55);rx_byte(8'hd5);crc=32'hffffffff;
            for(integer i=0;i<length;i=i+1)begin rx_byte(body_byte(generation,i));crc=crc_byte(crc,body_byte(generation,i));end
            crc=~crc;for(integer i=0;i<4;i=i+1)rx_byte((crc>>(i*8))&255);
            rx_idle(16);
        end
    endtask
    task automatic close_rx_boundary(input reg last_byte);
        reg [31:0] crc;integer before_drop;begin
            before_drop=rx_dropped;
            if(!last_byte)begin
                rx_byte(8'h55);@(posedge raw_rx);
            end else begin
                // Enough prefix reaches the real fixed-clock parser before the
                // close; no physical EOF is allowed to publish this generation.
                for(integer i=0;i<7;i=i+1)rx_byte(8'h55);rx_byte(8'hd5);crc=32'hffffffff;
                for(integer i=0;i<256;i=i+1)begin
                    rx_byte(body_byte(250,i));crc=crc_byte(crc,body_byte(250,i));end
                crc=~crc;for(integer i=0;i<4;i=i+1)rx_byte((crc>>(i*8))&255);
                @(posedge raw_rx);expected_drops=expected_drops+1;
            end
            @(negedge cpu);requested_link=0;rx_idle(16);cpu_wait(500);
            if(rx_accepted!=rx_tail || rx_dropped!=before_drop+(last_byte?1:0))
                $fatal(1,"MAC_CDC_RX_EDGE_CLOSE_ORACLE last=%0d drops=%0d before=%0d",last_byte,rx_dropped,before_drop);
            reopen(2);rx_edge_closes=rx_edge_closes+1;
        end
    endtask
    task automatic prepare_tx(input integer length,input integer generation,input reg reject_frame,output integer id);
        reg [31:0] crc;begin
            id=tx_tail;tx_tail=tx_tail+1;tx_length[id]=length;tx_generation[id]=generation;tx_reject[id]=reject_frame;
            for(integer i=0;i<7;i=i+1)tx_wire[id][i]=8'h55;tx_wire[id][7]=8'hd5;crc=32'hffffffff;
            for(integer i=0;i<length;i=i+1)begin tx_wire[id][8+i]=body_byte(generation,i);crc=crc_byte(crc,body_byte(generation,i));end
            crc=~crc;for(integer i=0;i<4;i=i+1)tx_wire[id][8+length+i]=(crc>>(i*8))&255;
            if(!reject_frame)expected_tx_bytes=expected_tx_bytes+length;
            else expected_reject_total=expected_reject_total+1;
        end
    endtask
    task automatic tx_control;begin
        for(integer i=0;i<6;i=i+1)begin
            @(negedge cpu);ctlv=1;ctldata=(i==0)?32'ha0000000:0;ctllast=(i==5);
            @(posedge cpu);while(!ctlready)@(posedge cpu);
        end
        @(negedge cpu);ctlv=0;ctllast=0;
    end endtask
    task automatic tx_body(input integer length,input integer generation,input integer close_word);
        integer count;begin
            for(integer position=0;position<length;position=position+4)begin
                @(negedge cpu);txv=1;txdata=0;count=((length-position)>=4)?4:(length-position);
                txkeep=(1<<count)-1;txlast=(position+count==length);
                for(integer b=0;b<count;b=b+1)txdata[8*b+:8]=body_byte(generation,position+b);
                @(posedge cpu);while(!txready)@(posedge cpu);
                if(position/4==close_word)begin @(negedge cpu);txv=0;requested_link=0;end
            end
            @(negedge cpu);txv=0;txlast=0;
        end
    endtask
    task automatic send_tx(input integer length,input integer generation,input integer close_word);
        integer id;begin prepare_tx(length,generation,close_word>=0,id);tx_control;tx_body(length,generation,close_word);end
    endtask
    task automatic drain;begin
        wait(rx_head==rx_tail && status_head==rx_tail && tx_head==tx_tail);cpu_wait(350);
    end endtask
    task automatic reopen(input integer speed);begin
        @(negedge cpu);requested_link=1;requested_speed=speed;
        wait(link && applied==speed);rx_idle(20);cpu_wait(200);
    end endtask
    task automatic rate_change(input integer speed,input integer generation);begin
        @(negedge cpu);requested_speed=speed;
        @(negedge raw_rx);rx_half=(speed==2)?4.0:(speed==1)?20.0:200.0;
        wait(!link);wait(link&&applied==speed);rx_idle(20);cpu_wait(200);
        send_rx(61,generation,1);send_tx(60,generation+100,-1);drain;rate_changes=rate_changes+1;
    end endtask
    reg [63:0] value;
    integer old_rx_consume,old_rx_head,old_offers,old_rx_drops,burst_id,native_target;
    initial begin
        if(!$value$plusargs("tx_slots=%d",tx_slots))$fatal(1,"MAC_CDC_MISSING_TX_PARAMETER");
        #0.5;reset=1;#1.0;
        if(dut.gmac.tx.io_abort!==1 || dut.gmac.rx.io_abort!==1 || dut.gmac.decode.io_abort!==1 ||
            dut.gmac.physicalIngress.captureEnable!==0)$fatal(1,"MAC_CDC_COLD_NOT_FAIL_CLOSED");
        #36.3;reset=0;
        cpu_wait(80);
        mmio(24,1,64'h021122334455,value);cpu_wait(200);mmio(16,1,11,value);
        cpu_wait(180);
        if(link || rx_consumes!=0 || rx_accepted || rx_dropped || tx_done || tx_rejected ||
            dut.gmac.physicalIngress.sourceReady)$fatal(1,"MAC_CDC_COLD_ABSENT_RX_PHANTOM");
        if(tx_consumes!=1 || rx_offers!=1)$fatal(1,"MAC_CDC_COLD_RATE_DID_NOT_PROGRESS_CLOSED");
        rx_run=1;wait(link);rx_idle(20);cpu_wait(200);
        send_rx(60,1,1);send_tx(60,101,-1);drain;
        send_rx(61,2,1);send_rx(128,3,1);send_rx(2048,4,1);send_tx(2048,104,-1);drain;
        send_tx(256,105,-1);send_tx(256,106,-1);send_tx(256,107,-1);drain;
        if(tx_slots==2)begin
            native_target=tx_native_ends+2;
            prepare_tx(256,108,1,burst_id);tx_control;tx_body(256,108,-1);
            prepare_tx(256,109,1,burst_id);tx_control;tx_body(256,109,-1);
            wait(tx_native_ends==native_target);
            if(tx_native_ends-tx_head!=2)$fatal(1,"MAC_CDC_QUEUED_ABORT_WITNESS_MISSING");
            @(negedge cpu);requested_link=0;drain;reopen(2);queued_abort_checks=queued_abort_checks+1;
        end
        // Every ordered rate pair: 2->1,1->0,0->2,2->0,0->1,1->2.
        rate_change(1,11);rate_change(0,12);rate_change(2,13);
        rate_change(0,14);rate_change(1,15);rate_change(2,16);
        // A completed RX bank and its status are retained while the next
        // physical frame stops. Only the latter partial epoch may disappear.
        data_service=0;status_service=0;send_rx(128,30,1);cpu_wait(350);
        for(integer i=0;i<7;i=i+1)rx_byte(8'h55);rx_byte(8'hd5);
        for(integer i=0;i<48;i=i+1)rx_byte(body_byte(31,i));
        @(negedge raw_rx);old_rx_drops=rx_dropped;rx_run=0;cpu_wait(350);old_rx_head=rx_head;
        if(rx_dropped!=old_rx_drops)$fatal(1,"MAC_CDC_HALTED_PHANTOM_EOF_EVENT");
        if(rx_accepted!=rx_tail || rx_head==rx_tail)$fatal(1,"MAC_CDC_COMPLETED_RX_OWNER_NOT_HELD");
        @(negedge cpu);requested_link=0;expected_drops=expected_drops+1;cpu_wait(300);
        if(!dut.gmac.media.io_ingressReset || dut.gmac.physicalIngress.sourceReady ||
            dut.gmac.physicalIngress.destinationReady)$fatal(1,"MAC_CDC_HALTED_EPOCH_NOT_ASSERTED");
        data_service=1;cpu_wait(500);
        if(rx_head!=rx_tail || status_head==rx_tail || dut.gmac.media.io_rxDrained)
            $fatal(1,"MAC_CDC_HALTED_COMPLETED_PACKET_DRAIN_ORACLE");
        status_service=1;drain;halt_checks=halt_checks+1;
        old_rx_consume=rx_consumes;old_offers=rx_offers;
        @(negedge cpu);requested_link=1;requested_speed=1;cpu_wait(200);
        if(link || rx_consumes!=old_rx_consume || rx_offers<=old_offers || dut.gmac.rxRate.sourceIdle)
            $fatal(1,"MAC_CDC_HALTED_RATE_ACK_ORACLE");
        // Supersede an outstanding rate generation; its genuine ACK must not
        // open the new request. Returned source-ready also needs actual RXC.
        requested_speed=0;cpu_wait(30);rx_half=200.0;rx_run=1;
        wait(link&&applied==0);
        if(rx_consumes<old_rx_consume+2)$fatal(1,"MAC_CDC_STALE_RATE_GENERATION_REOPEN");
        old_rx_drops=rx_dropped;
        // Keep DV high across release: embedded SFD inside the old frame is stale.
        send_rx(61,32,0);cpu_wait(500);
        if(rx_head!=rx_tail || rx_accepted!=rx_tail || rx_dropped!=old_rx_drops)
            $fatal(1,"MAC_CDC_STALE_FRAME_REPLAY");
        send_rx(60,33,1);drain;halt_checks=halt_checks+1;
        rate_change(2,34);
        // A full CPU-cycle speed pulse must close admission immediately and
        // assert the physical epoch at the next CPU edge, then re-ACK current
        // speed. It must not reuse the old ready level from the open epoch.
        old_offers=rx_offers;
        @(negedge cpu);requested_speed=1;#0.1;
        if(link || !dut.gmac.adapter.io_stopNewTx)$fatal(1,"MAC_CDC_PULSE_ADMISSION");
        @(posedge cpu);#0.2;
        if(!dut.gmac.media.io_ingressReset || dut.gmac.physicalIngress.sourceReady ||
            dut.gmac.physicalIngress.destinationReady)$fatal(1,"MAC_CDC_PULSE_EPOCH_NOT_CLOSED");
        @(negedge cpu);requested_speed=2;
        wait(link);if(rx_offers<=old_offers)$fatal(1,"MAC_CDC_PULSE_REUSED_READY_ACK");
        rx_idle(20);cpu_wait(200);
        close_rx_boundary(0);close_rx_boundary(1);
        // CPU closes on first and last data beat. Already admitted ownership
        // drains to LAST with precisely one abort/rejection per generation.
        send_tx(128,201,0);drain;reopen(2);
        send_tx(128,202,31);drain;reopen(2);
        // Stop RX while a real status tail is held; clock may stop only after
        // the host consumes the tail and the statistics/config mailboxes drain.
        status_service=0;send_rx(60,40,1);wait(rx_head==rx_tail);stop_rx=1;cpu_wait(250);
        if(stopped_rx)$fatal(1,"MAC_CDC_STATUS_TAIL_GATED");
        status_service=1;drain;wait(stopped_rx);gate_checks=gate_checks+1;
        stop_rx=0;wait(!stopped_rx);cpu_wait(200);send_rx(60,41,1);drain;
        // TX policy sees last beat + FIFO pending/output + wire + IFG owners.
        fork begin send_tx(128,203,-1);end begin wait(txv);cpu_wait(8);stop_tx=1;end join
        drain;wait(stopped_tx);gate_checks=gate_checks+1;
        @(negedge cpu);requested_link=0;cpu_wait(1);requested_link=1;
        wait(!stopped_tx);stop_tx=0;wait(link);cpu_wait(250);send_tx(60,204,-1);drain;
        // A raw first RX byte wakes an actually stopped managed-RX gate while
        // the fixed-clock wake-delay owns the first-frame waveform.
        stop_rx=1;wait(stopped_rx);send_rx(128,42,1);drain;
        stop_rx=0;wait(!stopped_rx);cpu_wait(300);gate_checks=gate_checks+1;
        if(tx_head!=tx_tail || tx_admitted!=tx_tail || rx_head!=rx_tail || status_head!=rx_tail || tx_position || rx_position || status_position ||
            rx_accepted!=rx_tail || rx_dropped!=expected_drops || rx_badfcs || tx_aborted!=expected_reject_total || tx_rejected!=expected_reject_total ||
            tx_done+tx_rejected!=tx_tail || tx_delta_done!=tx_done || tx_delta_rejected!=tx_rejected ||
            tx_delta_aborted!=tx_aborted || tx_delta_bytes!=expected_tx_bytes || rx_delta_accepted!=rx_tail ||
            rx_delta_dropped!=expected_drops || rx_delta_badfcs || rx_delta_bytes!=expected_rx_bytes)
            $fatal(1,"MAC_CDC_FINAL_EVENT_LEDGER tx=%0d/%0d done=%0d rejected=%0d abort=%0d rx=%0d/%0d accepted=%0d drop=%0d expectedDrop=%0d txBytes=%0d/%0d rxBytes=%0d/%0d",
                tx_head,tx_tail,tx_done,tx_rejected,tx_aborted,rx_head,rx_tail,rx_accepted,rx_dropped,expected_drops,
                tx_delta_bytes,expected_tx_bytes,rx_delta_bytes,expected_rx_bytes);
        mmio(64,0,0,value);if(value!=tx_done)$fatal(1,"MAC_CDC_CSR_TX_TOTAL");
        mmio(72,0,0,value);if(value!=rx_tail)$fatal(1,"MAC_CDC_CSR_RX_TOTAL");
        mmio(80,0,0,value);if(value!=expected_drops)$fatal(1,"MAC_CDC_CSR_DROP_TOTAL");
        if(rate_changes<6 || halt_checks!=2 || gate_checks!=3 || rx_edge_closes!=2 || rate_closed_consumes!=rx_consumes ||
            tx_consumes!=tx_offers || rx_consumes!=rx_offers || tx_native_ends!=tx_tail ||
            (tx_slots==2 && (max_native_owners<2 || queued_abort_checks!=1)))$fatal(1,"MAC_CDC_COVERAGE_INCOMPLETE");
        $display("MAC_BOUNDARY_NATIVE_CDC_PASS tx_slots=%0d max_native_owners=%0d queued_abort_checks=%0d tx_generations=%0d rx_generations=%0d tx_done=%0d tx_rejected=%0d rx_dropped=%0d rate_changes=%0d tx_consumes=%0d rx_consumes=%0d halted_checks=%0d gate_checks=%0d rx_edge_closes=%0d source_samples=%0d return_samples=%0d clocks=100_125_125_25_2p5MHz phy_bypass=1 vendor_timing=0",tx_slots,max_native_owners,queued_abort_checks,tx_tail,rx_tail,tx_done,tx_rejected,rx_dropped,rate_changes,tx_consumes,rx_consumes,halt_checks,gate_checks,rx_edge_closes,source_sample_checks,wire_sample_checks);
        $finish;
    end
    initial begin #20000000;$fatal(1,"MAC_CDC_TIMEOUT time=%0t link=%b pending=%b tx=%0d/%0d rx=%0d/%0d status=%0d rate=%0d/%0d",$time,link,pending,tx_head,tx_tail,rx_head,rx_tail,status_head,rx_consumes,rx_offers);end
endmodule
