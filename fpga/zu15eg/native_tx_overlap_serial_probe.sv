`timescale 1ns/1ps
// Private full-TX serialization experiment; not the production board.
// Carry the previous high nibble across each serializer word seam. Only
// raw+0/raw+4 positive CLK500 edges can change pins; prove the carry FF,
// after checking the actual synthesized pair nets; not clock/FF/reset paths.
module native_tx_overlap_serial_probe(input wire ui_pad, cold_reset, tx_reset_request,
    input wire [4:0] symbols_low, symbols_high,
    output wire [3:0] eth_txd, output wire eth_tx_ctl, eth_txc, locked);
    wire ui_clock, feedback, pll_source, pll_locked, ref_clock;
    wire raw, serial_clock;
    (* DONT_TOUCH="TRUE" *) BUFG input_buffer(.I(ui_pad), .O(ui_clock));
    PLLE4_ADV #(.CLKIN_PERIOD(4.0), .CLKFBOUT_MULT(4), .DIVCLK_DIVIDE(1),
        .CLKOUT0_DIVIDE(2), .COMPENSATION("AUTO")) pll(
        .CLKIN(ui_clock), .RST(cold_reset), .PWRDWN(1'b0),
        .CLKFBOUT(feedback), .CLKFBIN(feedback), .CLKOUT0(pll_source), .CLKOUT1(),
        .LOCKED(pll_locked), .CLKOUT0B(), .CLKOUT1B(), .CLKOUTPHY(), .CLKOUTPHYEN(1'b0),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY());
    (* DONT_TOUCH="TRUE" *) BUFG reference_buffer(.I(pll_source), .O(ref_clock));
    wire phase_inhibit=cold_reset | ~pll_locked;
    (* ASYNC_REG="TRUE" *) reg [2:0] phase_reset;
    always @(posedge ref_clock or posedge phase_inhibit)
        if(phase_inhibit) phase_reset<=3'b111;
        else phase_reset<={phase_reset[1:0],1'b0};
    assign locked=pll_locked & ~phase_reset[2];
    (* DONT_TOUCH="TRUE" *) BUFGCE_DIV #(.BUFGCE_DIVIDE(4), .SIM_DEVICE("ULTRASCALE_PLUS")) word_buffer(
        .I(ref_clock), .CE(1'b1), .CLR(phase_reset[1]), .O(raw));

    (* DONT_TOUCH="TRUE" *) BUFG clock_buffer(.I(ref_clock), .O(serial_clock));
    wire reset_raw, reset_pad;
    native_tx_reset_boundary release_dut(.clock_tx(raw), .clock_forward(raw),
        .inhibit(cold_reset | ~locked | tx_reset_request),
        .reset_raw(reset_raw), .reset_forward(reset_pad));
    reg [4:0] registered_low, registered_high;
    always @(posedge raw or posedge reset_raw)
        if(reset_raw) begin registered_low<=0; registered_high<=0; end
        else begin registered_low<=symbols_low; registered_high<=symbols_high; end
    // Preserve the full-cycle MAC->input-register timing, then make the
    // serializer word stable half a cycle BEFORE its CLKDIV sampling edge.
    // Only ten local register bits traverse this 4ns half-cycle boundary.
    reg [4:0] pad_low, pad_high, pad_previous_high;
    always @(negedge raw or posedge reset_pad)
        if(reset_pad) begin pad_low<=0; pad_high<=0; pad_previous_high<=0; end
        else begin pad_low<=registered_low; pad_high<=registered_high; pad_previous_high<=pad_high; end
    wire clock_symbol;
    // One real CLK500 net drives all six serializers. DATA8 emits the
    // preceding high nibble twice, low four times, and high twice. The
    // seam repeats exactly the previous high value: no change at raw+6.
    // Current low/high change at raw+8/raw+12; f0 captures at raw+10/+14.
    // The independent UNISIM oracle must verify this before physical STA.
    OSERDESE3 #(.DATA_WIDTH(8), .INIT(1'b0), .SIM_DEVICE("ULTRASCALE_PLUS")) clock_serdes(
        .CLK(serial_clock), .CLKDIV(raw), .D(8'hf0), .RST(reset_pad),
        .T(1'b0), .T_OUT(), .OQ(clock_symbol));
    OBUF clock_pad(.I(clock_symbol), .O(eth_txc));
    for(genvar n=0;n<5;n=n+1) begin: lanes
        wire symbol;
        OSERDESE3 #(.DATA_WIDTH(8), .INIT(1'b0), .SIM_DEVICE("ULTRASCALE_PLUS")) data_serdes(
            .CLK(serial_clock), .CLKDIV(raw),
            .D({{2{pad_high[n]}},{4{pad_low[n]}},{2{pad_previous_high[n]}}}),
            .RST(reset_pad), .T(1'b0), .T_OUT(), .OQ(symbol));
        if(n<4) OBUF data_pad(.I(symbol), .O(eth_txd[n]));
        else OBUF control_pad(.I(symbol), .O(eth_tx_ctl));
    end
endmodule


