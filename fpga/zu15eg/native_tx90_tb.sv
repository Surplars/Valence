`timescale 1ns/1ps
// Independent PHY captures at the actual centered forwarded pin clock.
// Stimulus stays on the raw source clock, not on DUT TXC edges.
module native_tx90_tb;
    reg ui_clock=0, cold_reset=1, tx_reset_request=1, delay_reset=1;
    always #2 ui_clock=~ui_clock;
    wire source, forward_source, ref_source, locked, raw, forward_clock, ref_clock;
    native_gmac_eth_clock clock_dut(.ui_clock(ui_clock), .cold_reset(cold_reset),
        .tx_source(source), .tx_forward_source(forward_source), .delay_source(ref_source), .locked(locked));
    BUFG raw_buf(.I(source), .O(raw));
    BUFG forward_buf(.I($test$plusargs("bad_phase") ? source : forward_source), .O(forward_clock));
    BUFG ref_buf(.I(ref_source), .O(ref_clock));
    wire tx_reset, tx_forward_reset;
    native_tx_reset_boundary tx_release(.clock_tx(raw), .clock_forward(forward_clock),
        .inhibit(tx_reset_request), .reset_raw(tx_reset), .reset_forward(tx_forward_reset));
    integer raw_edges=0, forward_edges=0;
    always @(posedge raw or posedge tx_reset_request) begin
        if(tx_reset_request) raw_edges=0; else raw_edges=raw_edges+1;
        #0.001;
        if(tx_reset !== (raw_edges<3)) $fatal(1,"Raw reset must release after three own-clock edges");
    end
    always @(posedge forward_clock or posedge tx_reset_request) begin
        if(tx_reset_request) forward_edges=0; else forward_edges=forward_edges+1;
        #0.001;
        if(tx_forward_reset !== (forward_edges<3)) $fatal(1,"Forward reset must release after three own-clock edges");
    end
    reg [7:0] data=0;
    reg enable=0, error=0;
    wire [3:0] txd;
    wire txctl, txc, delay_ready;
    native_rgmii #(.FPGA_TX_CLOCK_SHIFT(1), .RX_DATA_DELAY_PS(0)) dut(
        .tx_clock(raw), .tx_pad_clock(raw), .tx_forward_clock(forward_clock),
        .tx_forward_reset(tx_forward_reset), .tx_reset(tx_reset),
        .rx_clock(raw), .rx_reset(1'b1), .delay_clock(ref_clock), .delay_reset(delay_reset),
        .delay_ready(delay_ready), .gmii_tx_data(data), .gmii_tx_enable(enable), .gmii_tx_error(error),
        .rgmii_rx_data(4'b0), .rgmii_rx_control(1'b0), .rgmii_tx_data(txd),
        .rgmii_tx_control(txctl), .rgmii_tx_clock(txc),
        .gmii_rx_data(), .gmii_rx_valid(), .gmii_rx_error(), .gigabit_link());
    function automatic [7:0] payload(input integer i); payload=8'h53 ^ i[7:0]; endfunction
    integer stimulus=-1, previous=-1, expected=-1, checked=0;
    reg monitor=0;
    real last_raw=0, last_forward=0, last_ref=0;
    always @(posedge raw) begin
        if(locked && last_raw && ($realtime-last_raw<7.999 || $realtime-last_raw>8.001)) $fatal(1,"Raw TX period");
        last_raw=$realtime;
        if(tx_reset || !monitor) begin previous=-1; expected=-1; end
        else begin expected=previous; previous=stimulus; end
    end
    always @(posedge forward_clock) if(locked) begin
        if(last_forward && ($realtime-last_forward<7.999 || $realtime-last_forward>8.001)) $fatal(1,"TXC period");
        if($realtime-last_raw<1.999 || $realtime-last_raw>2.001) $fatal(1,"Physical TXC must be +2ns, not PHY-added twice");
        last_forward=$realtime;
    end
    always @(posedge ref_clock) if(locked) begin
        if(last_ref && ($realtime-last_ref<1.999 || $realtime-last_ref>2.001)) $fatal(1,"Calibration 500MHz period");
        last_ref=$realtime;
    end
    reg [7:0] gold;
    always @(posedge txc) if(monitor && !tx_reset && expected>=0) begin
        #0.01; gold=payload(expected);
        if(txd!==gold[3:0] || txctl!==((expected>>9)&1)) $fatal(1,"PHY rising symbol oracle index=%0d",expected);
    end
    always @(negedge txc) if(monitor && !tx_reset && expected>=0) begin
        #0.01;
        if(txd!==gold[7:4] || txctl!==(((expected>>9)^(expected>>8))&1)) $fatal(1,"PHY falling symbol oracle index=%0d",expected);
        checked=checked+1;
    end
    initial begin
        #121; cold_reset=0; wait(locked); repeat(80) @(posedge ref_clock);
        @(negedge ref_clock); delay_reset=0; wait(delay_ready);
        for(integer epoch=0;epoch<3;epoch=epoch+1) begin
            stimulus=-1;
            @(negedge raw); tx_reset_request=0;
            repeat(8) @(negedge raw); monitor=1;
            for(integer i=0;i<1024;i=i+1) begin
                @(negedge raw); #1; stimulus=i;
                data=payload(i); enable=(i>>9)&1; error=(i>>8)&1;
                if($test$plusargs("corrupt_data") && i==300) data=data^8'h01;
                if($test$plusargs("corrupt_control") && i==800) error=~error;
            end
            @(negedge raw); #1; stimulus=-1; enable=0; error=0;
            repeat(2) @(negedge txc); #0.1; monitor=0;
            #1.17; tx_reset_request=1; data=0;
            #1;
            if(txd!==0 || txctl!==0 || txc!==0) $fatal(1,"Async reset");
            repeat(8) @(negedge raw);
        end
        if(checked!=3072) $fatal(1,"Missing PHY captured symbols %0d",checked);
        $display("PASS_NATIVE_TX90_SHORT bytes=3072 encodings=4 reset_epochs=3 physical_phase_ns=2");
        $finish;
    end
    initial begin #100000; $fatal(1,"TX90 timeout"); end
endmodule
