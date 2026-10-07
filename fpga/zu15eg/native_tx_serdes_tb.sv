`timescale 1ns/1ps
// PHY reference stimulus is raw-clock/index driven, never DUT-TXC driven.
// The acceptance target is +2ns relative to raw data launches, not whatever
// phase a chosen pattern happens to produce. Bad phase/data/control must fail.
module native_tx_serdes_tb;
    reg ui_clock=0, cold_reset=1, tx_request=1;
    always #2 ui_clock=~ui_clock;
    reg [4:0] low_symbols=0, high_symbols=0;
    wire [3:0] txd;
    wire ctl, txc, locked;
    native_tx_serdes_probe #(.CLOCK_PATTERN(8'hf0)) dut(
        .ui_pad(ui_clock), .cold_reset(cold_reset), .tx_reset_request(tx_request),
        .symbols_low(low_symbols), .symbols_high(high_symbols),
        .eth_txd(txd), .eth_tx_ctl(ctl), .eth_txc(txc), .locked(locked));
    integer stimulus=-1, previous=-1, expected=-1, checked=0, epochs=0;
    reg monitor=0, phase_monitor=0;
    real last_raw=0, last_pad=0, last_serial=0, last_txc=0;
    function automatic [7:0] payload(input integer i); payload=8'h53 ^ i[7:0]; endfunction
    always @(posedge dut.raw) begin
        if(locked && last_raw && ($realtime-last_raw<7.999 || $realtime-last_raw>8.001)) $fatal(1,"RAW_PERIOD");
        last_raw=$realtime;
        if(dut.reset_raw || !monitor) begin previous=-1; expected=-1; end
        else begin expected=previous; previous=stimulus; end
    end
    always @(posedge dut.pad) begin
        last_pad=$realtime;
        #0.001;
        if(locked && ($realtime-last_raw>0.002 || dut.raw!==1'b1)) $fatal(1,"PAD_RAW_PHASE");
    end
    always @(posedge dut.serial_clock) begin
        if(locked && last_serial && ($realtime-last_serial<1.999 || $realtime-last_serial>2.001)) $fatal(1,"SERIAL_PERIOD");
        last_serial=$realtime;
    end
    always @(posedge txc) if(phase_monitor && !dut.reset_pad) begin
        if(last_txc && ($realtime-last_txc<7.999 || $realtime-last_txc>8.001)) $fatal(1,"TXC_PERIOD");
        if(!last_txc) $display("TXC_PHASE rise_delta=%0.3f",$realtime-last_raw);
        // Installed official UNISIM specifies a 100ps CLK->OQ model delay.
        // This is not a routed pad-delay assumption; STA must use real arcs.
        if($realtime-last_raw<2.099 || $realtime-last_raw>2.101) $fatal(1,"TXC_PHASE_NOT_2NS");
        last_txc=$realtime;
    end
    reg [7:0] gold;
    always @(posedge txc) if(monitor && !dut.reset_pad && expected>=0) begin
        #0.01; gold=payload(expected);
        if(txd!==gold[3:0] || ctl!==((expected>>9)&1)) $fatal(1,"PHY_RISING_SYMBOL index=%0d",expected);
    end
    always @(negedge txc) if(phase_monitor && !dut.reset_pad) begin
        if($realtime-last_raw<6.099 || $realtime-last_raw>6.101) $fatal(1,"TXC_FALL_PHASE_NOT_6NS delta=%0.3f raw=%0.3f pad=%0.3f",$realtime-last_raw,last_raw,last_pad);
        if(monitor && expected>=0) begin
            #0.01;
            if(txd!==gold[7:4] || ctl!==(((expected>>9)^(expected>>8))&1)) $fatal(1,"PHY_FALLING_SYMBOL index=%0d",expected);
            checked=checked+1;
        end
    end
    reg [7:0] stimulus_byte;
    initial begin
        if($test$plusargs("bad_phase")) force dut.clock_serdes.D=8'h3c;
        #121; cold_reset=0; wait(locked);
        for(integer epoch=0;epoch<3;epoch=epoch+1) begin
            @(negedge dut.raw); tx_request=0;
            repeat(12) @(negedge dut.raw); last_txc=0; phase_monitor=1; monitor=1;
            for(integer i=0;i<1024;i=i+1) begin
                @(negedge dut.raw); #1; stimulus=i;
                stimulus_byte=payload(i);
                low_symbols={1'((i>>9)&1),stimulus_byte[3:0]};
                high_symbols={1'(((i>>9)^(i>>8))&1),stimulus_byte[7:4]};
                if($test$plusargs("corrupt_data") && i==300) low_symbols=low_symbols^5'h01;
                if($test$plusargs("corrupt_control") && i==800) high_symbols=high_symbols^5'h10;
            end
            @(negedge dut.raw); #1; stimulus=-1; low_symbols=0; high_symbols=0;
            repeat(2) @(negedge txc); #0.1; monitor=0; phase_monitor=0;
            #1.17; tx_request=1;
            #1; if(txd!==0 || ctl!==0 || txc!==0) $fatal(1,"ASYNC_RESET");
            repeat(8) @(negedge dut.raw);
            if(epoch<2) begin
                cold_reset=1; last_raw=0; last_serial=0;
                #123.17; cold_reset=0; wait(locked);
            end
            epochs=epochs+1;
        end
        if(checked!=3072 || epochs!=3) $fatal(1,"MISSING_SYMBOLS count=%0d",checked);
        $display("PASS_NATIVE_TX_SERDES_SHORT bytes=3072 encodings=4 reset_epochs=3 cold_relocks=2 phase_ns=2");
        $finish;
    end
    initial begin #100000; $fatal(1,"TX_SERDES_TIMEOUT"); end
endmodule
