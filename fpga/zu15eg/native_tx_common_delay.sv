`timescale 1ns/1ps
// Calibrated, dedicated output-delay cascade. Both blocks use FIXED/TIME;
// their dynamic CLK controls are unused. The bank's REF500 IDELAYCTRL stays on.
module native_tx_output_delay #(parameter DELAY_PS=800)(
    input wire symbol, delay_reset, output wire delayed_symbol);
    wire cascade, returned;
    (* IODELAY_GROUP="VALENCE_RGMII" *)
    ODELAYE3 #(.CASCADE("MASTER"), .DELAY_FORMAT("TIME"), .DELAY_TYPE("FIXED"),
        .DELAY_VALUE(DELAY_PS), .REFCLK_FREQUENCY(500.0), .SIM_DEVICE("ULTRASCALE_PLUS")) master (
        .ODATAIN(symbol), .CASC_IN(1'b0), .CASC_OUT(cascade), .CASC_RETURN(returned),
        .DATAOUT(delayed_symbol), .CLK(1'b0), .CE(1'b0), .INC(1'b0), .LOAD(1'b0),
        .CNTVALUEIN(9'b0), .CNTVALUEOUT(), .RST(delay_reset), .EN_VTC(1'b1));
    (* IODELAY_GROUP="VALENCE_RGMII" *)
    IDELAYE3 #(.CASCADE("SLAVE_END"), .DELAY_SRC("DATAIN"), .DELAY_FORMAT("TIME"),
        .DELAY_TYPE("FIXED"), .DELAY_VALUE(DELAY_PS), .REFCLK_FREQUENCY(500.0),
        .SIM_DEVICE("ULTRASCALE_PLUS")) slave (
        .IDATAIN(1'b0), .DATAIN(1'b0), .CASC_IN(cascade), .CASC_OUT(), .CASC_RETURN(1'b0),
        .DATAOUT(returned), .CLK(1'b0), .CE(1'b0), .INC(1'b0), .LOAD(1'b0),
        .CNTVALUEIN(9'b0), .CNTVALUEOUT(), .RST(delay_reset), .EN_VTC(1'b1));
endmodule

module native_tx_clock_delay_probe(input wire raw_input, ref_input, reset,
    input wire [4:0] symbols_low, symbols_high,
    output wire [3:0] eth_txd, output wire eth_tx_ctl, eth_txc, ready);
    wire raw, ref_clock, txc_raw, txc_delayed;
    BUFG raw_buffer(.I(raw_input), .O(raw));
    BUFG ref_buffer(.I(ref_input), .O(ref_clock));
    (* IODELAY_GROUP="VALENCE_RGMII" *)
    IDELAYCTRL #(.SIM_DEVICE("ULTRASCALE")) delay_control(.REFCLK(ref_clock), .RST(reset), .RDY(ready));
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) clock_ddr (
        .C(raw), .D1(1'b1), .D2(1'b0), .SR(reset), .Q(txc_raw));
    native_tx_output_delay clock_delay(.symbol(txc_raw), .delay_reset(reset), .delayed_symbol(txc_delayed));
    OBUF clock_pad(.I(txc_delayed), .O(eth_txc));
    for(genvar n=0;n<5;n=n+1) begin: lanes
        wire symbol;
        ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) data_ddr (
            .C(raw), .D1(symbols_low[n]), .D2(symbols_high[n]), .SR(reset), .Q(symbol));
        if(n<4) OBUF data_pad(.I(symbol), .O(eth_txd[n]));
        else OBUF ctl_pad(.I(symbol), .O(eth_tx_ctl));
    end
endmodule

// Tiny real-pad feasibility probe only; clocks/CPU/MIG are not a board proof.
module native_tx_common_probe(input wire raw_input, ref_input, reset,
    input wire [4:0] symbols_low, symbols_high,
    output wire [3:0] eth_txd, output wire eth_tx_ctl, eth_txc, ready);
    wire raw, ref_clock, txc_raw;
    BUFG raw_buffer(.I(raw_input), .O(raw));
    BUFG ref_buffer(.I(ref_input), .O(ref_clock));
    (* IODELAY_GROUP="VALENCE_RGMII" *)
    IDELAYCTRL #(.SIM_DEVICE("ULTRASCALE")) delay_control(.REFCLK(ref_clock), .RST(reset), .RDY(ready));
    // Falling raw edge is the PHY rising edge. All six DDRs use the SAME CLK.
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) clock_ddr (
        .C(raw), .D1(1'b0), .D2(1'b1), .SR(reset), .Q(txc_raw));
    OBUF clock_pad(.I(txc_raw), .O(eth_txc));
    for(genvar n=0;n<5;n=n+1) begin: lanes
        wire symbol, delayed;
        ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) data_ddr (
            .C(raw), .D1(symbols_low[n]), .D2(symbols_high[n]), .SR(reset), .Q(symbol));
        native_tx_output_delay delay_dut(.symbol(symbol), .delay_reset(reset), .delayed_symbol(delayed));
        if(n<4) OBUF data_pad(.I(delayed), .O(eth_txd[n]));
        else OBUF ctl_pad(.I(delayed), .O(eth_tx_ctl));
    end
endmodule
