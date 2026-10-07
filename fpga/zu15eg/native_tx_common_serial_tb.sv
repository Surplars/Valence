`timescale 1ns/1ps
// Byte/index/clock-independent oracle plus setup/hold and unused-edge guards.
module native_tx_common_serial_tb;
    reg ui_clock=0, cold_reset=1, tx_request=1;
    always #2 ui_clock=~ui_clock;
    reg [4:0] low_symbols=0, high_symbols=0;
    wire [3:0] txd;
    wire ctl, txc, locked;
    native_tx_common_serial_probe dut(.ui_pad(ui_clock), .cold_reset(cold_reset), .tx_reset_request(tx_request),
        .symbols_low(low_symbols), .symbols_high(high_symbols),
        .eth_txd(txd), .eth_tx_ctl(ctl), .eth_txc(txc), .locked(locked));
    integer stimulus=-1, previous=-1, expected=-1, checked=0, epochs=0, gold_index=-1, before_expected=-1;
    integer setup_checks=0, hold_checks=0, edge_checks=0;
    reg monitor=0, phase_monitor=0;
    real last_raw=0, last_serial=0, last_data_clock=0, last_txc=0, last_transition=0;
    function automatic [7:0] payload(input integer i); payload=8'h53 ^ i[7:0]; endfunction
    always @(posedge dut.raw) begin
        if(locked && last_raw && ($realtime-last_raw<7.999 || $realtime-last_raw>8.001)) $fatal(1,"RAW_PERIOD");
        last_raw=$realtime;
        if(dut.reset_raw || !monitor) begin previous=-1; expected=-1; before_expected=-1; end
        else begin before_expected=expected; expected=previous; previous=stimulus; end
    end
    always @(posedge dut.serial_clock) begin
        if(locked && last_serial && ($realtime-last_serial<1.999 || $realtime-last_serial>2.001)) $fatal(1,"SERIAL_PERIOD");
        last_serial=$realtime;
    end
    always @(posedge dut.serial_clock) begin
        if(locked && last_data_clock && ($realtime-last_data_clock<1.999 || $realtime-last_data_clock>2.001)) $fatal(1,"COMMON_SERIAL_PERIOD");
        last_data_clock=$realtime;
    end
    // Functionally changing a lane on the unused edge invalidates the STA
    // edge exemption. Check all pins, not just sampled nibbles.
    always @(txd or ctl) if(monitor && !dut.reset_pad) begin
        last_transition=$realtime;
        // Official functional SIP can resolve a sampled D change in 1ps
        // or through its 100ps CLK->OQ path. Both must follow the ACTIVE
        // edge, never the unused opposite edge; PHY budget stays 1.250ns.
        if($realtime-last_serial<0 || $realtime-last_serial>0.101 ||
            !(($realtime-last_raw>=2.000 && $realtime-last_raw<=2.101) ||
              ($realtime-last_raw>=6.000 && $realtime-last_raw<=6.101)))
            $fatal(1,"COMMON_SERIAL_UNUSED_EDGE_CHANGED delta=%0.3f",$realtime-last_data_clock);
        edge_checks=edge_checks+1;
    end
    always @(posedge txc) if(phase_monitor && !dut.reset_pad) begin
        if(last_txc && ($realtime-last_txc<7.999 || $realtime-last_txc>8.001)) $fatal(1,"TXC_PERIOD");
        if(!last_txc) $display("TXC_PHASE rise_delta=%0.3f",$realtime-last_raw);
        if($realtime-last_raw<0.099 || $realtime-last_raw>0.101) $fatal(1,"TXC_RISE_NOT_0NS");
        last_txc=$realtime;
    end
    always @(negedge txc) if(phase_monitor && !dut.reset_pad)
        if($realtime-last_raw<4.099 || $realtime-last_raw>4.101) $fatal(1,"TXC_FALL_NOT_4NS");
    reg [7:0] gold;
    always @(posedge txc) if(monitor && !dut.reset_pad) begin
        gold_index=before_expected;
        if(gold_index>=0) begin
            #0.01; gold=payload(gold_index);
            if(txd!==gold[3:0] || ctl!==((gold_index>>9)&1)) $fatal(1,"PHY_RISING_SYMBOL index=%0d actual=%h wanted=%h",gold_index,txd,gold[3:0]);
        end
    end
    always @(negedge txc) if(monitor && !dut.reset_pad && gold_index>=0) begin
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
    always @(posedge txc or negedge txc) if(monitor && !dut.reset_pad) check_eye();
    reg [7:0] stimulus_byte;
    initial begin
        if($test$plusargs("bad_phase")) force dut.clock_serdes.D=8'h0f;
        if($test$plusargs("duplicate_breach")) force dut.lanes[0].data_serdes.D[1]=1'b1;
        if($test$plusargs("quarter_breach")) force dut.lanes[0].data_serdes.D[2]=1'b1;
        #121; cold_reset=0; wait(locked);
        for(integer epoch=0;epoch<3;epoch=epoch+1) begin
            @(negedge dut.raw); tx_request=0;
            repeat(12) @(negedge dut.raw); last_txc=0; phase_monitor=1; monitor=1;
            for(integer i=0;i<1024;i=i+1) begin
                @(negedge dut.raw); #1; stimulus=i; stimulus_byte=payload(i);
                low_symbols={1'((i>>9)&1),stimulus_byte[3:0]};
                high_symbols={1'(((i>>9)^(i>>8))&1),stimulus_byte[7:4]};
                if($test$plusargs("corrupt_data") && i==300) low_symbols=low_symbols^5'h01;
                if($test$plusargs("corrupt_control") && i==800) high_symbols=high_symbols^5'h10;
            end
            @(negedge dut.raw); #1; stimulus=-1; low_symbols=0; high_symbols=0;
            repeat(3) @(negedge txc); #0.1; monitor=0; phase_monitor=0; gold_index=-1; before_expected=-1;
            #1.17; tx_request=1;
            #1; if(txd!==0 || ctl!==0 || txc!==0) $fatal(1,"ASYNC_RESET");
            repeat(8) @(negedge dut.raw);
            if(epoch<2) begin
                cold_reset=1; last_raw=0; last_serial=0; last_data_clock=0;
                #123.17; cold_reset=0; wait(locked);
            end
            epochs=epochs+1;
        end
        if(checked!=3072 || epochs!=3 || setup_checks<6144 || hold_checks<6144 || edge_checks<3000)
            $fatal(1,"MISSING_COVERAGE bytes=%0d setup=%0d hold=%0d edge=%0d",checked,setup_checks,hold_checks,edge_checks);
        $display("PASS_NATIVE_TX_COMMON_SERIAL_SHORT bytes=3072 encodings=4 reset_epochs=3 cold_relocks=2 setup=%0d hold=%0d edge=%0d",setup_checks,hold_checks,edge_checks);
        $finish;
    end
    initial begin #100000; $fatal(1,"TX_COMMON_SERIAL_TIMEOUT"); end
endmodule

