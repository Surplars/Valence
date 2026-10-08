`timescale 1ns/1ps
// New adapter logic with phase-related ideal reference clocks. The unchanged
// PLL/DIV tree still requires its existing vendor-model proof and new board STA.
module trispeed_quarter_pad_tb;
    reg raw=0,pad=0,reference=0,inhibit=1;
    initial begin #4;forever begin raw=1;#4;raw=0;#4;end end
    initial begin #4;forever begin pad=1;#2;pad=0;#2;end end
    always #1 reference=~reference;
    wire reset_raw,reset_pad;
    native_tx_word_reset_boundary release_dut(.clock_tx(raw),.inhibit(inhibit),
        .reset_raw(reset_raw),.reset_forward(reset_pad));
    reg rate_valid=0;reg [1:0] rate_bits=2;
    reg [7:0] gmii_data=0;reg gmii_enable=0,gmii_error=0;
    wire rate_ready,byte_step,codec_idle;wire [1:0] applied;
    wire [4:0] rise,fall;wire clock_rise,clock_fall;
    TriSpeedRgmiiTx codec(.clock(raw),.reset(reset_raw),.io_rate_ready(rate_ready),
        .io_rate_valid(rate_valid),.io_rate_bits(rate_bits),.io_datapathIdle(~gmii_enable),
        .io_appliedSpeed(applied),.io_byteStep(byte_step),.io_gmiiData(gmii_data),
        .io_gmiiEnable(gmii_enable),.io_gmiiError(gmii_error),.io_rise(rise),.io_fall(fall),
        .io_clockRise(clock_rise),.io_clockFall(clock_fall),.io_idle(codec_idle));
    wire [3:0] txd;wire txctl,txc,delay_ready;
    native_rgmii_trispeed_quarter boundary(.tx_clock(raw),.tx_pad_clock(pad),.tx_pad_reset(reset_pad),
        .rx_clock(raw),.tx_reset(reset_raw),.rx_reset(1'b1),.delay_clock(reference),.delay_reset(inhibit),
        .tx_rise(rise),.tx_fall(fall),.txc_rise(clock_rise),.txc_fall(clock_fall),
        .rgmii_rx_data(4'b0),.rgmii_rx_control(1'b0),.rx_rise(),.rx_fall(),
        .rgmii_tx_data(txd),.rgmii_tx_control(txctl),.rgmii_tx_clock(txc),.delay_ready(delay_ready));
    reg monitor=0,packet=0,nibble_high=0,rise_enable=0;
    integer clock_rate=2,pending_rate=2,frame_rate=2,expected_seed=0,expected_bytes=0,position=0;
    integer frames=0,bytes=0,half_checks=0,phase_checks=0,duplicate_checks=0,reset_epochs=0;
    real rate_activation=-1,last_edge=-1,last_pad_positive=-1,last_data=-1,last_capture=-1;
    reg [3:0] rise_nibble;
    function automatic real half_period(input integer rate);
        case(rate)2:half_period=4.0;1:half_period=20.0;default:half_period=200.0;endcase
    endfunction
    function automatic [7:0] payload(input integer index,input integer seed);
        payload=((index*73+seed*19+11)^(index>>3))&255;
    endfunction
    function automatic bit errbit(input integer index);errbit=(index%29)==7;endfunction
    always @(posedge raw)if(rate_valid&&rate_ready&&!reset_raw)begin
        pending_rate=rate_bits;
        //125MHz output register -> capture at raw+6 -> quarter low at raw+8
        // -> delayed clock edge at raw+10 plus the fixed behavioral CLK-to-Q.
        rate_activation=$realtime+10.1;
    end
    always @(posedge pad)last_pad_positive=$realtime;
    always @(txd or txctl)if(monitor&&!reset_pad)begin
        if($realtime-last_pad_positive<0.099 || $realtime-last_pad_positive>0.101)
            $fatal(1,"QUARTER_DATA_CHANGED_ON_UNUSED_EDGE");
        if(last_capture>=0&&$realtime-last_capture<1.250)$fatal(1,"NOMINAL_PHY_HOLD_WINDOW");
        last_data=$realtime;phase_checks=phase_checks+1;
    end
    always @(txc)if(monitor&&!reset_pad)begin
        if(last_edge>=0)begin
            if($realtime-last_edge<half_period(clock_rate)-0.001 ||
               $realtime-last_edge>half_period(clock_rate)+0.001)
                $fatal(1,"QUARTER_CLOCK_PULSE_LENGTH rate=%0d got=%0.3f",clock_rate,$realtime-last_edge);
            half_checks=half_checks+1;
        end
        if($realtime-last_pad_positive<2.099 || $realtime-last_pad_positive>2.101)
            $fatal(1,"QUARTER_CLOCK_CHANGED_ON_WRONG_EDGE");
        last_edge=$realtime;
        if(txc && rate_activation>=0 && $realtime>=rate_activation-0.001)begin
            clock_rate=pending_rate;rate_activation=-1;
        end
        if(last_data>=0&&$realtime-last_data<1.250)$fatal(1,"NOMINAL_PHY_SETUP_WINDOW");
        last_capture=$realtime;
    end
    always @(posedge txc)if(monitor&&!reset_pad)begin
        rise_enable=txctl;rise_nibble=txd;
        if(txctl)begin
            if(!packet)begin packet=1;nibble_high=0;position=0;frame_rate=clock_rate;end
            if(position>=expected_bytes)$fatal(1,"QUARTER_TX_EXTRA_BYTE");
            if(txd!==((payload(position,expected_seed)>>(nibble_high?4:0))&15))
                $fatal(1,"QUARTER_TX_RISING_NIBBLE index=%0d",position);
        end else if(packet)begin
            if(position!=expected_bytes||nibble_high)$fatal(1,"QUARTER_TX_LENGTH_OR_PHASE");
            packet=0;frames=frames+1;
        end
    end
    always @(negedge txc)if(monitor&&!reset_pad&&rise_enable)begin
        if(txctl!==(1'b1^errbit(position)))$fatal(1,"QUARTER_TX_CONTROL_ORACLE");
        if(frame_rate==2)begin
            if(txd!==((payload(position,expected_seed)>>4)&15))$fatal(1,"QUARTER_TX_FALLING_NIBBLE");
            position=position+1;bytes=bytes+1;
        end else begin
            if(txd!==rise_nibble)$fatal(1,"QUARTER_TX_NIBBLE_DUPLICATION");duplicate_checks=duplicate_checks+1;
            if(nibble_high)begin position=position+1;bytes=bytes+1;end
            nibble_high=~nibble_high;
        end
    end
    task automatic set_rate(input integer selected);
        begin @(negedge raw);rate_bits=selected;rate_valid=1;
            do @(posedge raw);while(!rate_ready);#0.01;rate_valid=0;
            repeat(1600)@(negedge raw);
            if(applied!=selected)$fatal(1,"QUARTER_RATE_APPLY");
        end
    endtask
    task automatic send_frame(input integer count,input integer seed);
        integer target;begin expected_seed=seed;expected_bytes=count;target=frames+1;
            @(negedge raw);gmii_enable=1;gmii_data=payload(0,seed);gmii_error=errbit(0);
            for(integer i=0;i<count;i=i+1)begin
                do @(posedge raw);while(!byte_step);
                #0.01;
                if(i+1<count)begin gmii_data=payload(i+1,seed);gmii_error=errbit(i+1);end
                else begin gmii_enable=0;gmii_error=0;gmii_data=0;end
            end
            wait(frames==target);repeat(1600)@(negedge raw);
        end
    endtask
    initial begin
        if($test$plusargs("bad_phase"))force boundary.previous_clock=1'b0;
        #41.7;inhibit=0;wait(!reset_pad);repeat(10)@(negedge raw);monitor=1;last_edge=-1;clock_rate=2;
        for(integer epoch=0;epoch<2;epoch=epoch+1)begin
            set_rate(2);send_frame(128,10+epoch);
            set_rate(1);send_frame(129,20+epoch);
            set_rate(0);send_frame(130,30+epoch);
            set_rate(2);set_rate(0);set_rate(1);set_rate(2);
            monitor=0;last_capture=-1;#1.17;inhibit=1;#0.1;
            if(txc!==0||txd!==0||txctl!==0)$fatal(1,"QUARTER_ASYNC_RESET_PIN_QUIESCENCE");
            repeat(5)@(negedge raw);inhibit=0;wait(!reset_pad);repeat(12)@(negedge raw);
            clock_rate=2;pending_rate=2;rate_activation=-1;last_edge=-1;last_data=-1;monitor=1;reset_epochs=reset_epochs+1;
        end
        if(frames!=6||bytes!=774||duplicate_checks<1000||phase_checks<500)$fatal(1,"Quarter coverage incomplete");
        $display("TRISPEED_QUARTER_PAD_BEHAVIOR_PASS frames=%0d bytes=%0d half_checks=%0d duplicate_checks=%0d reset_epochs=%0d fixed_skew_ns=2.0 vendor_models=0 routed_timing=0",frames,bytes,half_checks,duplicate_checks,reset_epochs);
        $finish;
    end
    initial begin #3000000;$fatal(1,"Tri-speed quarter pad timeout");end
endmodule
