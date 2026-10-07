`timescale 1ns/1ps
// Actual production clock + RGMII + reset boundary. Independent byte/phase
// oracle; no private pad-probe DUT and no CPU/SDF/board qualification claim.
module native_tx_quarter_board_tb;
    reg ui_clock=0, cold_reset=1, tx_request=1, delay_reset=1;
    always #2 ui_clock=~ui_clock;
    reg [4:0] low_symbols=0, high_symbols=0;
    wire raw, quarter_clock, forward_epoch, ref_clock, locked, reset_raw, reset_pad, delay_ready;
    wire [3:0] txd;
    wire ctl, txc;
    native_gmac_quarter_clock clock_dut(.ui_clock(ui_clock), .cold_reset(cold_reset),
        .tx_source(raw), .tx_pad_source(quarter_clock), .tx_forward_source(forward_epoch),
        .delay_source(ref_clock), .locked(locked));
    native_tx_word_reset_boundary release_dut(.clock_tx(raw),
        .inhibit(cold_reset | ~locked | tx_request | ~delay_ready),
        .reset_raw(reset_raw), .reset_forward(reset_pad));
    native_rgmii #(.FPGA_TX_CLOCK_SHIFT(1), .ISOLATE_TX_PAD_CLOCK(1),
        .TX_QUARTER_DDR(1), .RX_DATA_DELAY_PS(0)) dut(
        .tx_clock(raw), .tx_pad_clock(quarter_clock), .tx_forward_clock(forward_epoch),
        .tx_forward_reset(reset_pad), .tx_reset(reset_raw), .rx_clock(raw), .rx_reset(1'b1),
        .delay_clock(ref_clock), .delay_reset(delay_reset), .delay_ready(delay_ready),
        .gmii_tx_data({high_symbols[3:0],low_symbols[3:0]}), .gmii_tx_enable(low_symbols[4]),
        .gmii_tx_error(low_symbols[4]^high_symbols[4]), .rgmii_rx_data(4'b0), .rgmii_rx_control(1'b0),
        .rgmii_tx_data(txd), .rgmii_tx_control(ctl), .rgmii_tx_clock(txc),
        .gmii_rx_data(), .gmii_rx_valid(), .gmii_rx_error(), .gigabit_link());
    integer stimulus=-1, previous=-1, expected=-1, checked=0, epochs=0, gold_index=-1;
    integer setup_checks=0, hold_checks=0, edge_checks=0;
    reg monitor=0, phase_monitor=0;
    real last_raw=0, last_quarter=0, last_txc=0, last_transition=0;
    function automatic [7:0] payload(input integer i); payload=8'h53 ^ i[7:0]; endfunction
    always @(posedge raw) begin
        if(locked && last_raw && ($realtime-last_raw<7.999 || $realtime-last_raw>8.001)) $fatal(1,"RAW_PERIOD");
        last_raw=$realtime;
        if(reset_raw || !monitor) begin previous=-1; expected=-1; end
        else begin expected=previous; previous=stimulus; end
    end
    always @(posedge quarter_clock) begin
        if(locked && last_quarter && ($realtime-last_quarter<3.999 || $realtime-last_quarter>4.001)) $fatal(1,"QUARTER_DDR_PERIOD");
        last_quarter=$realtime;
    end
    always @(txd or ctl) if(monitor && !reset_pad) begin
        last_transition=$realtime;
        // Official functional SIP samples D at 1ps or CLK->OQ at 100ps.
        // Both must follow the ACTIVE positive edge. No PHY budget change.
        if($realtime-last_quarter<0 || $realtime-last_quarter>0.101)
            $fatal(1,"QUARTER_DDR_UNUSED_EDGE_CHANGED delta=%0.3f",$realtime-last_quarter);
        edge_checks=edge_checks+1;
    end
    always @(posedge txc) if(phase_monitor && !reset_pad) begin
        if(last_txc && ($realtime-last_txc<7.999 || $realtime-last_txc>8.001)) $fatal(1,"TXC_PERIOD");
        if($realtime-last_raw<2.099 || $realtime-last_raw>2.101) $fatal(1,"TXC_RISE_NOT_2NS");
        last_txc=$realtime;
    end
    always @(negedge txc) if(phase_monitor && !reset_pad)
        if($realtime-last_raw<6.099 || $realtime-last_raw>6.101) $fatal(1,"TXC_FALL_NOT_6NS");
    reg [7:0] gold;
    always @(posedge txc) if(monitor && !reset_pad) begin
        gold_index=expected;
        if(gold_index>=0) begin
            #0.01; gold=payload(gold_index);
            if(txd!==gold[3:0] || ctl!==((gold_index>>9)&1)) $fatal(1,"PHY_RISING_SYMBOL index=%0d",gold_index);
        end
    end
    always @(negedge txc) if(monitor && !reset_pad && gold_index>=0) begin
        #0.01;
        if(txd!==gold[7:4] || ctl!==(((gold_index>>9)^(gold_index>>8))&1)) $fatal(1,"PHY_FALLING_SYMBOL index=%0d",gold_index);
        checked=checked+1;
    end
    task automatic check_eye;
        reg [4:0] symbol;
        begin
            if($realtime-last_transition<1.250) $fatal(1,"PHY_SETUP_EYE");
            setup_checks=setup_checks+1; symbol={ctl,txd};
            #1.250;
            if({ctl,txd}!==symbol) $fatal(1,"PHY_HOLD_EYE");
            hold_checks=hold_checks+1;
        end
    endtask
    always @(posedge txc or negedge txc) if(monitor && !reset_pad) check_eye();
    reg [7:0] stimulus_byte;
    task automatic release_delay;
        begin
            wait(locked); repeat(80) @(posedge ref_clock);
            @(negedge ref_clock); delay_reset=0; wait(delay_ready);
        end
    endtask
    initial begin
        if($test$plusargs("bad_phase")) force dut.tx_clock_ddr.D2=dut.quarter_phase;
        // The inputs share a net. Inject only the official ODDR's separate
        // captured falling-half register, otherwise input force aliases D1.
        if($test$plusargs("duplicate_breach")) force dut.lanes[0].tx_ddr.QD2_posedge_int=1'b1;
        if($test$plusargs("capture_breach")) force dut.quarter_tx_boundary.capture_word=dut.quarter_phase;
        if($test$plusargs("phase_stop")) force dut.quarter_tx_boundary.phase_high=1'b0;
        #121; cold_reset=0; release_delay();
        for(integer epoch=0;epoch<3;epoch=epoch+1) begin
            @(negedge raw); tx_request=0;
            repeat(12) @(negedge raw); last_txc=0; phase_monitor=1; monitor=1;
            for(integer i=0;i<1024;i=i+1) begin
                @(negedge raw); #1; stimulus=i; stimulus_byte=payload(i);
                low_symbols={1'((i>>9)&1),stimulus_byte[3:0]};
                high_symbols={1'(((i>>9)^(i>>8))&1),stimulus_byte[7:4]};
                if($test$plusargs("corrupt_data") && i==300) low_symbols=low_symbols^5'h01;
                if($test$plusargs("corrupt_control") && i==800) high_symbols=high_symbols^5'h10;
            end
            @(negedge raw); #1; stimulus=-1; low_symbols=0; high_symbols=0;
            repeat(3) @(negedge txc); #0.1; monitor=0; phase_monitor=0; gold_index=-1;
            #1.17; tx_request=1;
            #1; if(txd!==0 || ctl!==0 || txc!==0) $fatal(1,"ASYNC_RESET");
            repeat(8) @(negedge raw);
            if(epoch<2) begin
                delay_reset=1; cold_reset=1; last_raw=0; last_quarter=0;
                #123.17; cold_reset=0; release_delay();
            end
            epochs=epochs+1;
        end
        if(checked!=3072 || epochs!=3 || setup_checks<6144 || hold_checks<6144 || edge_checks<3000)
            $fatal(1,"MISSING_COVERAGE bytes=%0d setup=%0d hold=%0d edge=%0d",checked,setup_checks,hold_checks,edge_checks);
        $display("PASS_NATIVE_TX_QUARTER_BOARD_SHORT bytes=3072 encodings=4 reset_epochs=3 cold_relocks=2 setup=%0d hold=%0d edge=%0d",setup_checks,hold_checks,edge_checks);
        $finish;
    end
    initial begin #100000; $fatal(1,"TX_QUARTER_DDR_TIMEOUT"); end
endmodule
