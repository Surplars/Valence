`timescale 1ns/1ps
// Independent MAC stimulus on raw125, PHY oracle on the actual delayed pad.
// No oracle delay is derived from the DUT's calibration constants.
module native_tx_calibrated_tb;
    reg ui_clock=0, cold_reset=1, inhibit=1, delay_reset=1;
    always #2 ui_clock=~ui_clock;
    wire source, ref_source, locked, raw, ref_clock, tx_reset, unused_reset;
    native_eth_clock clock_dut(.ui_clock(ui_clock), .cold_reset(cold_reset),
        .tx_source(source), .delay_source(ref_source), .locked(locked));
    BUFG raw_buf(.I(source), .O(raw));
    BUFG ref_buf(.I(ref_source), .O(ref_clock));
    native_tx_reset_boundary release_dut(.clock_tx(raw), .clock_forward(raw),
        .inhibit(inhibit), .reset_raw(tx_reset), .reset_forward(unused_reset));
    integer reset_edges=0;
    always @(posedge raw or posedge inhibit) begin
        if(inhibit) reset_edges=0; else reset_edges=reset_edges+1;
        #0.001;
        if(tx_reset !== (reset_edges<3)) $fatal(1,"Reset release is not three own-clock edges");
    end
    reg [7:0] data=0;
    reg enable=0, error=0;
    wire [3:0] txd;
    wire txctl, txc, ready;
    native_rgmii #(.TX_CALIBRATED_CLOCK(1), .RX_DATA_DELAY_PS(0)) dut(
        .tx_clock(raw), .tx_pad_clock(raw), .tx_forward_clock(raw), .tx_forward_reset(tx_reset), .tx_reset(tx_reset),
        .rx_clock(raw), .rx_reset(1'b1), .delay_clock(ref_clock), .delay_reset(delay_reset), .delay_ready(ready),
        .gmii_tx_data(data), .gmii_tx_enable(enable), .gmii_tx_error(error),
        .rgmii_rx_data(4'b0), .rgmii_rx_control(1'b0), .rgmii_tx_data(txd), .rgmii_tx_control(txctl),
        .rgmii_tx_clock(txc), .gmii_rx_data(), .gmii_rx_valid(), .gmii_rx_error(), .gigabit_link());
    function automatic [7:0] payload(input integer i); payload=8'h53 ^ i[7:0]; endfunction
    integer stimulus=-1, previous=-1, expected=-1, checked=0;
    reg monitor=0;
    real last_raw=0, last_capture=0, last_change=0;
    always @(posedge raw) begin
        last_raw=$realtime;
        if(tx_reset || !monitor) begin previous=-1; expected=-1; end
        else begin expected=previous; previous=stimulus; end
    end
    always @(txd or txctl) begin
        if(monitor && !tx_reset && expected>=0 && last_capture && $realtime-last_capture<1.250)
            $fatal(1,"PHY hold window");
        last_change=$realtime;
    end
    reg [7:0] gold;
    always @(posedge txc) if(monitor && !tx_reset && expected>=0) begin
        if($realtime-last_raw<1.900 || $realtime-last_raw>2.100) $fatal(1,"Calibrated physical pad clock phase");
        if($realtime-last_change<1.250) $fatal(1,"PHY setup window");
        last_capture=$realtime;
        #0.01; gold=payload(expected);
        if(txd!==gold[3:0] || txctl!==((expected>>9)&1)) $fatal(1,"PHY rising symbol index=%0d",expected);
    end
    always @(negedge txc) if(monitor && !tx_reset && expected>=0) begin
        if($realtime-last_change<1.250) $fatal(1,"PHY falling setup window");
        last_capture=$realtime;
        #0.01;
        if(txd!==gold[7:4] || txctl!==(((expected>>9)^(expected>>8))&1)) $fatal(1,"PHY falling symbol index=%0d",expected);
        checked=checked+1;
    end
    initial begin
        if($test$plusargs("bad_phase")) force dut.rgmii_tx_clock=dut.tx_clock_raw;
        #121; cold_reset=0; wait(locked); repeat(80) @(posedge ref_clock);
        @(negedge ref_clock); delay_reset=0; wait(ready);
        for(integer epoch=0;epoch<3;epoch=epoch+1) begin
            stimulus=-1;
            @(negedge raw); inhibit=0;
            repeat(8) @(negedge raw); monitor=1; last_capture=0;
            for(integer i=0;i<1024;i=i+1) begin
                @(negedge raw); #1; stimulus=i;
                data=payload(i); enable=(i>>9)&1; error=(i>>8)&1;
                if($test$plusargs("corrupt_data") && i==300) data=data^8'h01;
                if($test$plusargs("corrupt_control") && i==800) error=~error;
            end
            @(negedge raw); #1; stimulus=-1; enable=0; error=0;
            repeat(2) @(negedge txc); #0.1; monitor=0;
            #1.17; inhibit=1; data=0;
            #5;
            if(txd!==0 || txctl!==0 || txc!==0) $fatal(1,"Async reset pin quiescence");
            repeat(8) @(negedge raw);
        end
        if(checked!=3072) $fatal(1,"Missing captured symbols %0d",checked);
        $display("PASS_NATIVE_TX90_SHORT calibrated_txc bytes=3072 encodings=4 reset_epochs=3 phy_setup_hold_ns=1.25");
        $finish;
    end
    initial begin #100000; $fatal(1,"Calibrated TX timeout"); end
endmodule
