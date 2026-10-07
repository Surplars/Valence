`timescale 1ns/1ps
// Real fixed-pad feasibility only. No CPU, MAC engine, PHY or board qualification.
// All six DDRs share one clock; its inverted forwarded clock captures data
// delayed with ONE dedicated calibrated ODELAY per lane (no adjacent cascade).
module native_tx_single_delay_probe #(parameter DELAY_PS=1000)(
    input wire raw_input, ref_input, reset,
    input wire [4:0] symbols_low, symbols_high,
    output wire [3:0] eth_txd,
    output wire eth_tx_ctl, eth_txc, ready);
    wire raw, ref_clock, clock_symbol;
    BUFG raw_buffer(.I(raw_input), .O(raw));
    BUFG ref_buffer(.I(ref_input), .O(ref_clock));
    (* IODELAY_GROUP="VALENCE_RGMII" *)
    IDELAYCTRL #(.SIM_DEVICE("ULTRASCALE")) delay_control(
        .REFCLK(ref_clock), .RST(reset), .RDY(ready));
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) clock_ddr(
        .C(raw), .D1(1'b0), .D2(1'b1), .SR(reset), .Q(clock_symbol));
    OBUF clock_pad(.I(clock_symbol), .O(eth_txc));
    for(genvar n=0;n<5;n=n+1) begin: lanes
        wire symbol, delayed;
        ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) data_ddr(
            .C(raw), .D1(symbols_low[n]), .D2(symbols_high[n]), .SR(reset), .Q(symbol));
        (* IODELAY_GROUP="VALENCE_RGMII" *)
        ODELAYE3 #(.CASCADE("NONE"), .DELAY_FORMAT("TIME"), .DELAY_TYPE("FIXED"),
            .DELAY_VALUE(DELAY_PS), .REFCLK_FREQUENCY(500.0), .SIM_DEVICE("ULTRASCALE_PLUS")) data_delay(
            .ODATAIN(symbol), .CASC_IN(1'b0), .CASC_OUT(), .CASC_RETURN(1'b0),
            .DATAOUT(delayed), .CLK(1'b0), .CE(1'b0), .INC(1'b0), .LOAD(1'b0),
            .CNTVALUEIN(9'b0), .CNTVALUEOUT(), .RST(reset), .EN_VTC(1'b1));
        if(n<4) OBUF data_pad(.I(delayed), .O(eth_txd[n]));
        else OBUF control_pad(.I(delayed), .O(eth_tx_ctl));
    end
endmodule

// Complementary common-clock boundary: only the forwarded clock passes one
// calibrated ODELAY. Data lanes need no adjacent cascade or output delay.
module native_tx_single_clock_delay_probe #(parameter DELAY_PS=800)(
    input wire raw_input, ref_input, reset,
    input wire [4:0] symbols_low, symbols_high,
    output wire [3:0] eth_txd,
    output wire eth_tx_ctl, eth_txc, ready);
    wire raw, ref_clock, clock_symbol, delayed_clock;
    BUFG raw_buffer(.I(raw_input), .O(raw));
    BUFG ref_buffer(.I(ref_input), .O(ref_clock));
    (* IODELAY_GROUP="VALENCE_RGMII" *)
    IDELAYCTRL #(.SIM_DEVICE("ULTRASCALE")) delay_control(
        .REFCLK(ref_clock), .RST(reset), .RDY(ready));
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) clock_ddr(
        .C(raw), .D1(1'b1), .D2(1'b0), .SR(reset), .Q(clock_symbol));
    (* IODELAY_GROUP="VALENCE_RGMII" *)
    ODELAYE3 #(.CASCADE("NONE"), .DELAY_FORMAT("TIME"), .DELAY_TYPE("FIXED"),
        .DELAY_VALUE(DELAY_PS), .REFCLK_FREQUENCY(500.0), .SIM_DEVICE("ULTRASCALE_PLUS")) clock_delay(
        .ODATAIN(clock_symbol), .CASC_IN(1'b0), .CASC_OUT(), .CASC_RETURN(1'b0),
        .DATAOUT(delayed_clock), .CLK(1'b0), .CE(1'b0), .INC(1'b0), .LOAD(1'b0),
        .CNTVALUEIN(9'b0), .CNTVALUEOUT(), .RST(reset), .EN_VTC(1'b1));
    OBUF clock_pad(.I(delayed_clock), .O(eth_txc));
    for(genvar n=0;n<5;n=n+1) begin: lanes
        wire symbol;
        ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) data_ddr(
            .C(raw), .D1(symbols_low[n]), .D2(symbols_high[n]), .SR(reset), .Q(symbol));
        if(n<4) OBUF data_pad(.I(symbol), .O(eth_txd[n]));
        else OBUF control_pad(.I(symbol), .O(eth_tx_ctl));
    end
endmodule
