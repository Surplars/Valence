`timescale 1ns/1ps
// Fixed, phase-related RAW125/PAD250 only. Continuous pin comparison starts
// while reset is asserted, not after a warm-up window. Vendor runs exclude
// rgmii_behavioral_primitives.sv and use official UNISIM ODDRE1/OSERDESE3.
module tx_pad_reset_tb;
    reg raw=0,pad=0,reference=0,run_clocks=1;
    integer tick=0;
    always #2 if(run_clocks) begin
        tick=(tick+1)%4;
        case(tick)
          0: begin raw=1;pad=1;end
          1: pad=0;
          2: begin raw=0;pad=1;end
          3: pad=0;
        endcase
    end
    always #1 reference=~reference;
    reg cold=1,ready_input=1;
    wire inhibit=cold || !ready_input;
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
    // TX-only proof: unused RX calibration/reset is not stimulated or qualified.
    // Actual 2025.2 IDELAYE3 prints a generic TIME-mode notice on every reset.
    // TX common/local reset, injected RDY inhibit and all pin oracles stay active.
    wire [5:0] old_pins,new_pins;
    native_rgmii_trispeed_quarter #(.LOCAL_PAD_RESET_RELEASE(0)) baseline(
        .tx_clock(raw),.tx_pad_clock(pad),.tx_pad_reset(reset_pad),.rx_clock(raw),
        .tx_reset(reset_raw),.rx_reset(1'b1),.delay_clock(reference),.delay_reset(1'b0),
        .tx_rise(rise),.tx_fall(fall),.txc_rise(clock_rise),.txc_fall(clock_fall),
        .rgmii_rx_data(4'b0),.rgmii_rx_control(1'b0),.rx_rise(),.rx_fall(),
        .rgmii_tx_data(old_pins[3:0]),.rgmii_tx_control(old_pins[4]),.rgmii_tx_clock(old_pins[5]),.delay_ready());
    native_rgmii_trispeed_quarter #(.LOCAL_PAD_RESET_RELEASE(1)) candidate(
        .tx_clock(raw),.tx_pad_clock(pad),.tx_pad_reset(reset_pad),.rx_clock(raw),
        .tx_reset(reset_raw),.rx_reset(1'b1),.delay_clock(reference),.delay_reset(1'b0),
        .tx_rise(rise),.tx_fall(fall),.txc_rise(clock_rise),.txc_fall(clock_fall),
        .rgmii_rx_data(4'b0),.rgmii_rx_control(1'b0),.rx_rise(),.rx_fall(),
        .rgmii_tx_data(new_pins[3:0]),.rgmii_tx_control(new_pins[4]),.rgmii_tx_clock(new_pins[5]),.delay_ready());
    reg monitor=0,packet=0,nibble_high=0,rise_enable=0,abort_expected=0;
    reg [3:0] rise_nibble;
    integer frame_rate=2,seed=0,expected_bytes=0,position=0;
    integer frames=0,bytes=0,pin_checks=0,pair_checks=0,release_checks=0,aborts=0,pauses=0;
    real last_pad_rise=-1,last_pad_fall=-1,last_tx_edge=-1;
    wire [3:0] seen_data=new_pins[3:0] ^ (($test$plusargs("bad_payload") && packet)?4'h1:4'h0);
    wire seen_control=new_pins[4] ^ (($test$plusargs("bad_control") && packet)?1'b1:1'b0);
    function automatic [7:0] payload(input integer index,input integer salt);
        payload=((index*73+salt*19+11)^(index>>3))&255;
    endfunction
    function automatic bit errbit(input integer index);errbit=(index%5)==2;endfunction
    function automatic real half_period(input integer rate);
        case(rate)2:half_period=4.0;1:half_period=20.0;default:half_period=200.0;endcase
    endfunction
    // All edges, including the vendor primitive's startup hold. No warm-up mask.
    always @(pad) begin
        if(pad)last_pad_rise=$realtime;else last_pad_fall=$realtime;
        #0.5;
        if(monitor)begin
            if(new_pins!==old_pins)$fatal(1,"TX_RESET_PIN_MITER old=%b new=%b time=%0t",old_pins,new_pins,$time);
            if((^new_pins)===1'bx)$fatal(1,"TX_RESET_UNKNOWN_PIN");
            if(reset_pad && new_pins!==0)$fatal(1,"TX_RESET_HELD_OUTPUT");
            pin_checks=pin_checks+1;
        end
    end
    // Independently check complete-pair capture; no reference RTL state machine.
    reg [11:0] expected_pair;
    always @(negedge pad) if(monitor && !reset_pad)begin
        expected_pair={clock_fall,clock_rise,fall,rise};
        if(!candidate.phase_high)begin
            #0.5;
            if(!reset_pad && {candidate.high_clock,candidate.low_clock,candidate.high_symbol,candidate.low_symbol}!==expected_pair)
                $fatal(1,"TX_RESET_COMPLETE_PAIR_CAPTURE");
            pair_checks=pair_checks+1;
        end
    end
    always @(negedge reset_pad) if(monitor)begin
        // RAW release t0, local release t2, first phase transition t4,
        // first complete-pair capture t6. The clocks must be running here.
        #0.5;
        if(candidate.serializer_reset!==1 || candidate.phase_high!==1)$fatal(1,"TX_RESET_RELEASE_T0");
        @(negedge pad);#0.5;
        if(candidate.serializer_reset!==0 || candidate.phase_high!==1 || candidate.low_symbol!==0 || candidate.high_symbol!==0)
            $fatal(1,"TX_RESET_RELEASE_T2");
        @(posedge pad);#0.5;
        if(candidate.phase_high!==0)$fatal(1,"TX_RESET_RELEASE_T4");
        @(negedge pad);#0.5;
        release_checks=release_checks+1;
    end
    always @(new_pins[3:0] or new_pins[4])if(monitor && !reset_pad)begin
        if($realtime-last_pad_rise<0 || $realtime-last_pad_rise>0.4)
            $fatal(1,"TX_RESET_DATA_EDGE");
    end
    always @(new_pins[5])if(monitor && !reset_pad)begin
        if($realtime-last_pad_fall<0 || $realtime-last_pad_fall>0.4)
            $fatal(1,"TX_RESET_CLOCK_EDGE");
        if(packet && last_tx_edge>=0 && run_clocks &&
           ($realtime-last_tx_edge<half_period(frame_rate)-0.01 || $realtime-last_tx_edge>half_period(frame_rate)+0.01))
            $fatal(1,"TX_RESET_CLOCK_PULSE rate=%0d got=%0.3f",frame_rate,$realtime-last_tx_edge);
        last_tx_edge=$realtime;
    end
    always @(posedge new_pins[5])if(monitor && !reset_pad)begin
        rise_enable=seen_control;rise_nibble=seen_data;
        if(seen_control)begin
            if(!packet)begin packet=1;nibble_high=0;position=0;end
            if(position>=expected_bytes)$fatal(1,"TX_RESET_EXTRA_BYTE");
            if(seen_data!==((payload(position,seed)>>(nibble_high?4:0))&15))
                $fatal(1,"TX_RESET_RISING_NIBBLE index=%0d",position);
        end else if(packet)begin
            if(position!=expected_bytes || nibble_high)$fatal(1,"TX_RESET_FRAME_LENGTH");
            packet=0;frames=frames+1;
        end
    end
    always @(negedge new_pins[5])if(monitor && !reset_pad && rise_enable)begin
        if(seen_control!==(1'b1^errbit(position)))$fatal(1,"TX_RESET_CONTROL");
        if(frame_rate==2)begin
            if(seen_data!==((payload(position,seed)>>4)&15))$fatal(1,"TX_RESET_FALLING_NIBBLE");
            position=position+1;bytes=bytes+1;
        end else begin
            if(seen_data!==rise_nibble)$fatal(1,"TX_RESET_NIBBLE_DUPLICATION");
            if(nibble_high)begin position=position+1;bytes=bytes+1;end
            nibble_high=~nibble_high;
        end
    end
    always @(posedge inhibit)begin
        gmii_enable=0;gmii_error=0;rate_valid=0;
        if(monitor)begin
            if(packet && !abort_expected)$fatal(1,"TX_RESET_UNEXPECTED_ABORT");
            if(packet)aborts=aborts+1;
            packet=0;rise_enable=0;nibble_high=0;last_tx_edge=-1;
            #0.5;
            if(new_pins!==0 || old_pins!==0)$fatal(1,"TX_RESET_ASYNC_QUIESCENCE");
        end
    end
    always @(posedge raw)if(monitor && reset_raw && (gmii_enable || rate_valid))
        $fatal(1,"TX_RESET_FIXTURE_ADMISSION_WHILE_HELD");
    task automatic set_rate(input integer selected);
        begin
            @(negedge raw);rate_bits=selected;rate_valid=1;
            do @(posedge raw);while(!rate_ready);
            #0.01;rate_valid=0;
            // Real adapter enforces twelve complete idle bytes on a speed command.
            // Pin monitors remain enabled throughout this protocol interval.
            @(negedge raw);while(!byte_step)@(negedge raw);
            if(applied!=selected)$fatal(1,"TX_RESET_RATE_APPLY");
            frame_rate=selected;
        end
    endtask
    task automatic pause_pair;
        reg [5:0] held;begin
            #0.7;run_clocks=0;#0.5;held=new_pins;
            #37.3;
            if(new_pins!==held)$fatal(1,"TX_RESET_STOPPED_PINS_CHANGED");
            last_tx_edge=-1;run_clocks=1;pauses=pauses+1;
        end
    endtask
    task automatic send_frame(input integer count,input integer salt,input bit pause_mid);
        integer target;begin
            seed=salt;expected_bytes=count;target=frames+1;
            @(negedge raw);gmii_enable=1;gmii_data=payload(0,salt);gmii_error=errbit(0);
            for(integer i=0;i<count;i=i+1)begin
                do @(posedge raw);while(!byte_step);
                #0.01;
                if(i+1<count)begin gmii_data=payload(i+1,salt);gmii_error=errbit(i+1);end
                else begin gmii_enable=0;gmii_error=0;gmii_data=0;end
                if(pause_mid && i==4)pause_pair();
            end
            wait(frames==target);
        end
    endtask
    task automatic reset_epoch(input real phase,input bit stop_high,input bit rdy_loss);
        begin
            @(negedge raw);#phase;
            if(rdy_loss)ready_input=0;else cold=1;
            #1;
            if(stop_high)@(posedge pad);else @(negedge pad);
            #0.6;run_clocks=0;#8;
            if(new_pins!==0 || old_pins!==0)$fatal(1,"TX_RESET_STOPPED_RESET_OUTPUT");
            cold=0;ready_input=1;#17;
            if(!reset_pad || new_pins!==0)$fatal(1,"TX_RESET_RELEASE_WITHOUT_CLOCK");
            run_clocks=1;wait(!reset_pad);
            // Four ODDRE1 startup cycles, continuously observed, then one complete
            // pair. This is not a monitor warm-up; first-pin miter never stops.
            repeat(6)@(posedge pad);
            abort_expected=0;frame_rate=2;
        end
    endtask
    initial begin
        // UNISIM global startup is held in reset; first DUT release is observed.
        #201;monitor=1;
        if($test$plusargs("bad_phase"))force candidate.previous_clock=1'b0;
        if($test$plusargs("bad_reset"))force candidate.pad_release.pad_release_reset=1'b0;
        cold=0;wait(!reset_pad);repeat(6)@(posedge pad);
        send_frame(9,1,0); // FIRST frame at default gigabit, no speed-command gap.
        for(integer r=0;r<3;r=r+1)begin
            set_rate(r);send_frame(9,10+r,1);
            // Abort an explicitly owned partial frame on inhibit, then verify a
            // fresh first frame after cold reset / injected RDY loss.
            seed=20+r;expected_bytes=64;abort_expected=1;
            @(negedge raw);gmii_enable=1;gmii_data=payload(0,seed);gmii_error=errbit(0);
            wait(packet);#0.7;
            reset_epoch(0.3+r, r%2, r!=0);
            send_frame(9,30+r,0);
        end
        reset_epoch(3.3, 1, 1); // RDY loss while idle, with clocks stopped high.
        send_frame(9,40,0);
        if(frames!=8 || aborts!=3 || pauses!=3 || release_checks!=5 || bytes<72 || pin_checks<1000 || pair_checks<500)
            $fatal(1,"TX_RESET_COVERAGE frames=%0d aborts=%0d pauses=%0d releases=%0d bytes=%0d",frames,aborts,pauses,release_checks,bytes);
        $display("TX_PAD_RESET_PASS frames=%0d bytes=%0d aborts=%0d paired_pauses=%0d releases=%0d pin_checks=%0d pair_checks=%0d",frames,bytes,aborts,pauses,release_checks,pin_checks,pair_checks);
        $finish;
    end
    initial begin #2000000;$fatal(1,"TX_RESET_TIMEOUT");end
endmodule
