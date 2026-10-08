`timescale 1ns/1ps
// Opt-in tri-speed physical boundary. All TX ODDRs use the SAME continuous
// 125 MHz clock; txc_d1/d2 are generated data patterns, never internal clocks.
// TriSpeedRgmiiTx supplies 125/25/2.5 MHz patterns and low-speed nibble repeats.
// RXC is recovered 125/25/2.5 MHz, independently buffered by the board wrapper.
// RTL8211F policy: RXDLY=1, TXDLY=0. A dedicated cascaded output delay provides
// nominal 2 ns TX skew. Do not enable a second PHY TX delay.
//
// This boundary requires per-rate I/O STA, bank cascade placement and on-board
// validation. Behavioral simulation is not evidence of analog delay accuracy.
module native_rgmii_trispeed #(
    parameter RX_DATA_DELAY_PS = 1100,
    parameter TX_CLOCK_DELAY_PS = 1000
)(
    input wire tx_clock, rx_clock, tx_reset, rx_reset,
    input wire delay_clock, delay_reset,
    input wire [4:0] tx_rise, tx_fall,
    input wire txc_rise, txc_fall,
    input wire [3:0] rgmii_rx_data,
    input wire rgmii_rx_control,
    output wire [4:0] rx_rise, rx_fall,
    output wire [3:0] rgmii_tx_data,
    output wire rgmii_tx_control, rgmii_tx_clock,
    output wire delay_ready
);
    initial begin
        if(RX_DATA_DELAY_PS<0 || RX_DATA_DELAY_PS>1100 ||
           TX_CLOCK_DELAY_PS<0 || TX_CLOCK_DELAY_PS>1100)
            $fatal(1,"RGMII fixed delay outside supported UltraScale+ range");
    end
    wire txc_raw;
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) tx_clock_ddr (
        .C(tx_clock), .D1(txc_rise), .D2(txc_fall), .SR(tx_reset), .Q(txc_raw));
    native_tx_output_delay #(.DELAY_PS(TX_CLOCK_DELAY_PS)) clock_delay (
        .symbol(txc_raw), .delay_reset(delay_reset), .delayed_symbol(rgmii_tx_clock));
    for(genvar n=0;n<5;n=n+1) begin: transmit
        wire symbol;
        ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) data_ddr (
            .C(tx_clock), .D1(tx_rise[n]), .D2(tx_fall[n]), .SR(tx_reset), .Q(symbol));
        if(n<4) assign rgmii_tx_data[n]=symbol;
        else assign rgmii_tx_control=symbol;
    end
    (* IODELAY_GROUP="VALENCE_RGMII" *)
    IDELAYCTRL #(.SIM_DEVICE("ULTRASCALE")) delay_control (
        .REFCLK(delay_clock), .RST(delay_reset), .RDY(delay_ready));
    wire [4:0] pad={rgmii_rx_control,rgmii_rx_data};
    wire [4:0] delayed;
    for(genvar n=0;n<5;n=n+1) begin: receive
        (* IODELAY_GROUP="VALENCE_RGMII" *)
        IDELAYE3 #(.DELAY_FORMAT("TIME"), .DELAY_TYPE("FIXED"), .DELAY_SRC("IDATAIN"),
            .DELAY_VALUE(RX_DATA_DELAY_PS), .REFCLK_FREQUENCY(500.0),
            .SIM_DEVICE("ULTRASCALE_PLUS")) input_delay (
            .IDATAIN(pad[n]), .DATAIN(1'b0), .DATAOUT(delayed[n]), .CLK(1'b0),
            .CE(1'b0), .INC(1'b0), .LOAD(1'b0), .CNTVALUEIN(9'b0), .CNTVALUEOUT(),
            .RST(delay_reset), .EN_VTC(1'b1), .CASC_IN(1'b0), .CASC_RETURN(1'b0), .CASC_OUT());
        IDDRE1 #(.DDR_CLK_EDGE("SAME_EDGE_PIPELINED"), .IS_CB_INVERTED(1'b1)) input_ddr (
            .C(rx_clock), .CB(rx_clock), .D(delayed[n]), .R(rx_reset),
            .Q1(rx_rise[n]), .Q2(rx_fall[n]));
    end
endmodule
