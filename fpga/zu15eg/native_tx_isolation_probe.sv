`timescale 1ns/1ps
// OOC-only normal synthesis proxy. Mirrors the real globally buffered UI250
// and constant GMII_TX_ER=0, but contains no CPU, DDR or MAC engine.
module native_tx_isolation_probe(
    input wire ui_pad, reset,
    input wire [7:0] gmii_data,
    input wire gmii_enable,
    output wire [3:0] tx_data,
    output wire tx_control, tx_clock, locked
);
    wire ui_clock, tx_source, delay_source, raw_clock, pad_clock, delay_clock;
    (* DONT_TOUCH="TRUE" *) BUFG input_buffer(.I(ui_pad), .O(ui_clock));
    native_eth_clock clock_dut(.ui_clock(ui_clock), .cold_reset(reset),
        .tx_source(tx_source), .delay_source(delay_source), .locked(locked));
    (* DONT_TOUCH="TRUE" *) BUFG raw_buffer(.I(tx_source), .O(raw_clock));
    (* DONT_TOUCH="TRUE" *) BUFG pad_buffer(.I(tx_source), .O(pad_clock));
    BUFG delay_buffer(.I(delay_source), .O(delay_clock));
    native_rgmii #(.ISOLATE_TX_PAD_CLOCK(1)) boundary(
        .tx_clock(raw_clock), .tx_pad_clock(pad_clock), .tx_reset(reset),
        .rx_clock(raw_clock), .rx_reset(reset),
        .delay_clock(delay_clock), .delay_reset(reset), .delay_ready(),
        .gmii_tx_data(gmii_data), .gmii_tx_enable(gmii_enable), .gmii_tx_error(1'b0),
        .rgmii_rx_data(4'b0), .rgmii_rx_control(1'b0),
        .rgmii_tx_data(tx_data), .rgmii_tx_control(tx_control), .rgmii_tx_clock(tx_clock),
        .gmii_rx_data(), .gmii_rx_valid(), .gmii_rx_error(), .gigabit_link());
endmodule
