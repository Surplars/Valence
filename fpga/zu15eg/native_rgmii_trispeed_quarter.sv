`timescale 1ns/1ps
// Experimental tri-speed extension of the existing dedicated ODDR250 boundary.
// RAW125 and PAD250 MUST be phase-related outputs of native_gmac_quarter_clock;
// tx_pad_reset MUST use native_tx_word_reset_boundary's common RAW125 release.
// All six pad ODDRs share PAD250; data changes only on positive edges and TXC
// only on negative edges. No fabric-generated/muxed clock or output-delay cascade.
// RX remains direct recovered-clock capture with independent-rate constraints.
// This new logic is NOT physically qualified merely because its1G ancestor was.
module native_rgmii_trispeed_quarter #(
    parameter RX_DATA_DELAY_PS = 1100
)(
    input wire tx_clock, tx_pad_clock, tx_pad_reset, rx_clock, tx_reset, rx_reset,
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
        if(RX_DATA_DELAY_PS<0 || RX_DATA_DELAY_PS>1100)
            $fatal(1,"RGMII fixed input delay outside supported UltraScale+ range");
    end
    // Reuse the established word-reset phase contract: first PAD250 edge after
    // shared RAW125 reset release is raw+4. Low-half edges then occur at raw+0.
    reg phase_high;
    reg [4:0] low_symbol, high_symbol;
    reg low_clock, high_clock, previous_clock;
    always @(posedge tx_pad_clock or posedge tx_pad_reset)
        if(tx_pad_reset) phase_high<=1'b1;
        else phase_high<=~phase_high;
    // Capture a complete stable125MHz pair at raw+6, never mixed byte halves.
    always @(negedge tx_pad_clock or posedge tx_pad_reset)
        if(tx_pad_reset) begin
            low_symbol<=0; high_symbol<=0; low_clock<=0; high_clock<=0;
        end else if(!phase_high) begin
            low_symbol<=tx_rise; high_symbol<=tx_fall;
            low_clock<=txc_rise; high_clock<=txc_fall;
        end
    wire [4:0] symbol=phase_high ? high_symbol : low_symbol;
    wire clock_symbol=phase_high ? high_clock : low_clock;
    always @(posedge tx_pad_clock or posedge tx_pad_reset)
        if(tx_pad_reset) previous_clock<=1'b0;
        else previous_clock<=clock_symbol;
    // D1 repeats the previous physical clock value, so positive PAD250 edges
    // never change TXC. D2 applies this half's clock value2ns after data changes.
    // This is fixed2ns skew at ALL rates, not90degrees of a25/2.5MHz clock.
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) tx_clock_ddr (
        .C(tx_pad_clock), .D1(previous_clock), .D2(clock_symbol), .SR(tx_pad_reset), .Q(rgmii_tx_clock));
    for(genvar n=0;n<5;n=n+1) begin: transmit
        wire output_symbol;
        ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) data_ddr (
            .C(tx_pad_clock), .D1(symbol[n]), .D2(symbol[n]), .SR(tx_pad_reset), .Q(output_symbol));
        if(n<4) assign rgmii_tx_data[n]=output_symbol;
        else assign rgmii_tx_control=output_symbol;
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
