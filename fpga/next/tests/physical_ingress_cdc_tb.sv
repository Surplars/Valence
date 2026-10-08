`timescale 1ns/1ps
// Independent-edge CDC/epoch bench. Uses actual generated physical-ingress RTL;
// no vendor primitive timing model and no board/STA qualification claim.
module physical_ingress_cdc_tb;
    reg source_clock=0, destination_clock=0, source_run=1;
    real source_half=4.0;
    always begin #(source_half); if(source_run) source_clock=~source_clock; else source_clock=0; end
    initial begin #1; forever #4 destination_clock=~destination_clock; end
    reg cold_reset=1, epoch_reset=0, capture_enable=0;
    wire reset=cold_reset|epoch_reset;
    reg [7:0] source_data=0;
    reg source_valid=0, source_error=0, source_step=1;
    wire [7:0] data;
    wire valid,error,step,idle,source_ready,destination_ready,overflow,skipped;
    EthernetPhysicalIngress dut(.sourceClock(source_clock),.destinationClock(destination_clock),
        .commonReset(reset),.sourceData(source_data),.sourceValid(source_valid),.sourceError(source_error),
        .sourceByteStep(source_step),.physicalValid(source_valid),.captureEnable(capture_enable),
        .data(data),.valid(valid),.error(error),.byteStep(step),.idle(idle),
        .sourceReady(source_ready),.destinationReady(destination_ready),.overflow(overflow),.wholeFrameSkipped(skipped));
    reg [7:0] prepared[0:4095],expected[0:31][0:4095];
    reg corrupt_once=0;
    integer length[0:31],prepared_length=0,head=0,tail=0,position=0,checked=0,epochs=0;
    integer raw_events=0,destination_events=0,halt_checks=0;
    reg in_frame=0,frame_error=0;
    always @(posedge source_clock) raw_events=raw_events+1;
    always @(posedge reset) begin in_frame=0;position=0;frame_error=0; end
    always @(posedge destination_clock) begin
        destination_events=destination_events+1;
        if(!reset && destination_ready && step) begin
            if(valid) begin
                if(!in_frame) begin in_frame=1;position=0;frame_error=0; end
                // Partial-prefix tests deliberately have no expected complete
                // frame. Such bytes may exist before an explicit epoch abort.
                if(head<tail) begin
                    if(position>=length[head] || data!==expected[head][position])
                        $fatal(1,"INGRESS_CDC_BYTE_ORACLE frame=%0d byte=%0d",head,position);
                end
                position=position+1;frame_error=frame_error|error;
            end else if(in_frame) begin
                if(head>=tail || position!=length[head] || frame_error)
                    $fatal(1,"INGRESS_CDC_EOF_ORACLE head=%0d tail=%0d bytes=%0d",head,tail,position);
                head=head+1;checked=checked+1;in_frame=0;position=0;
            end
        end
    end
    function automatic [31:0] crc_byte(input [31:0] crc,input [7:0] value);
        reg [31:0] work;begin work=crc;for(integer b=0;b<8;b=b+1)
            work=(work>>1)^(((work[0]^value[b])!=0)?32'hedb88320:0);crc_byte=work;end
    endfunction
    task automatic prepare(input integer body_length,input integer seed,input integer publish);
        reg [31:0] crc;reg [7:0] byte_value;integer body;begin
            body=body_length<60?60:body_length;crc=32'hffffffff;
            for(integer i=0;i<7;i=i+1)prepared[i]=8'h55;prepared[7]=8'hd5;
            for(integer i=0;i<body;i=i+1)begin
                byte_value=((i*73+seed*19+11)^(i>>3))&255;
                case(i)0:byte_value=2;1:byte_value=8'h11;2:byte_value=8'h22;3:byte_value=8'h33;
                    4:byte_value=8'h44;5:byte_value=8'h55;12:byte_value=8'h08;13:byte_value=0;endcase
                prepared[8+i]=byte_value;crc=crc_byte(crc,byte_value);
            end
            crc=~crc;for(integer i=0;i<4;i=i+1)prepared[8+body+i]=(crc>>(8*i))&255;
            prepared_length=body+12;
            if(publish)begin
                if(tail>=32)$fatal(1,"TB expected-frame capacity");length[tail]=prepared_length;
                for(integer i=0;i<prepared_length;i=i+1)expected[tail][i]=prepared[i];
                if($test$plusargs("bad_payload")&&!corrupt_once)begin
                    expected[tail][23]=expected[tail][23]^8'h80;corrupt_once=1;
                end
                tail=tail+1;
            end
        end
    endtask
    task automatic byte_value(input [7:0] value,input integer period);
        begin
            @(negedge source_clock);source_data=value;source_valid=1;source_step=1;
            for(integer j=1;j<period;j=j+1)begin @(negedge source_clock);source_step=0;end
        end
    endtask
    task automatic physical_idle(input integer cycles);
        begin @(negedge source_clock);source_valid=0;source_step=1;source_error=0;
            repeat(cycles)@(negedge source_clock);end
    endtask
    task automatic send_frame(input integer body,input integer seed,input integer period);
        integer target;begin prepare(body,seed,1);target=tail;
            for(integer i=0;i<prepared_length;i=i+1)byte_value(prepared[i],period);
            physical_idle(12);wait(head==target);repeat(4)@(posedge destination_clock);
            if(overflow || skipped)$fatal(1,"Nominal independent-clock ingress overflowed");
        end
    endtask
    task automatic halt_reset_restart(input real next_half,input integer next_period,input integer seed);
        integer old_checked;begin
            prepare(512,seed,0);
            for(integer i=0;i<47;i=i+1)byte_value(prepared[i],1);
            @(negedge source_clock);source_run=0;old_checked=checked;
            repeat(200)@(posedge destination_clock);
            if(checked!=old_checked || !in_frame || step)$fatal(1,"Stopped RXC fabricated EOF");
            #1.37;capture_enable=0;epoch_reset=1;
            #0.1;if(source_ready || destination_ready)$fatal(1,"Epoch assertion did not reset BOTH endpoints");
            repeat(4)@(posedge destination_clock);#1.19;epoch_reset=0;
            repeat(20)@(posedge destination_clock);
            if(source_ready || !destination_ready || valid || checked!=old_checked)
                $fatal(1,"Stopped source epoch released/replayed without source edges");
            halt_checks=halt_checks+1;
            source_half=next_half;source_run=1;wait(source_ready);repeat(4)@(negedge source_clock);
            capture_enable=1;
            // Still inside the old physical frame: an embedded full Ethernet
            // preamble/FCS must not be treated as a fresh epoch's SOP.
            prepare(85,seed+1,0);
            for(integer i=0;i<prepared_length;i=i+1)byte_value(prepared[i],next_period);
            physical_idle(12);repeat(100)@(posedge destination_clock);
            if(valid || in_frame || checked!=old_checked)$fatal(1,"Old epoch embedded SFD replayed after restart");
            send_frame(1514,seed+2,next_period);epochs=epochs+1;
        end
    endtask
    initial begin
        if(crc_byte(32'hffffffff,8'h31)===32'hxxxxxxxx)$fatal(1,"CRC reference unknown");
        #37.3;cold_reset=0;wait(source_ready&&destination_ready);physical_idle(8);capture_enable=1;physical_idle(4);
        send_frame(60,1,1);send_frame(61,2,1);send_frame(1514,3,1);send_frame(2048,4,1);
        halt_reset_restart(20.0,2,10);halt_reset_restart(200.0,2,20);
        halt_reset_restart(4.0,1,30);halt_reset_restart(20.0,2,40);
        if(checked!=8 || epochs!=4 || halt_checks!=4 || head!=tail)$fatal(1,"CDC coverage incomplete");
        $display("PHYSICAL_INGRESS_NATIVE_CDC_PASS frames=%0d epoch_resets=%0d stopped_source_checks=%0d raw_edges=%0d destination_edges=%0d speeds=125_25_2p5MHz stale_replay=0 vendor_timing=0",checked,epochs,halt_checks,raw_events,destination_events);
        $finish;
    end
    initial begin #10000000;$fatal(1,"Physical ingress native CDC timeout");end
endmodule
