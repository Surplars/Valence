`timescale 1ns/1ps
// Private six-pad feasibility candidate. All ODDRs share real CLK250.
// Data D1/D2 are one net, so only positive edges change data; the divided
// clock changes only on negative edges, centered 2ns from each symbol.
module native_tx_quarter_ddr_probe(input wire ui_pad, cold_reset, tx_reset_request,
    input wire [4:0] symbols_low, symbols_high,
    output wire [3:0] eth_txd, output wire eth_tx_ctl, eth_txc, locked);
    wire ui_clock, feedback, pll_source, pll_locked, ref_clock;
    wire raw, quarter_clock;
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
    (* DONT_TOUCH="TRUE" *) BUFGCE_DIV #(.BUFGCE_DIVIDE(2), .SIM_DEVICE("ULTRASCALE_PLUS")) quarter_buffer(
        .I(ref_clock), .CE(1'b1), .CLR(phase_reset[1]), .O(quarter_clock));
    wire reset_raw, reset_pad;
    native_tx_reset_boundary release_dut(.clock_tx(raw), .clock_forward(raw),
        .inhibit(cold_reset | ~locked | tx_reset_request),
        .reset_raw(reset_raw), .reset_forward(reset_pad));
    // Preserve a full 8ns cycle from the managed MAC into these registers.
    reg [4:0] registered_low, registered_high;
    always @(posedge raw or posedge reset_raw)
        if(reset_raw) begin registered_low<=0; registered_high<=0; end
        else begin registered_low<=symbols_low; registered_high<=symbols_high; end
    // Release is after a positive word edge. Initial high ensures the next
    // quarter edge (raw+4) ends the idle high half; subsequent low halves
    // align with raw+0. This counter and the pad ODDRs use the SAME CLK250.
    reg phase_high;
    always @(posedge quarter_clock or posedge reset_pad)
        if(reset_pad) phase_high<=1'b1;
        else phase_high<=~phase_high;
    wire capture_word=~phase_high;
    reg [4:0] pad_low, pad_high;
    always @(negedge quarter_clock or posedge reset_pad)
        if(reset_pad) begin pad_low<=0; pad_high<=0; end
        else if(capture_word) begin pad_low<=registered_low; pad_high<=registered_high; end
    wire clock_symbol;
    ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) clock_ddr(
        .C(quarter_clock), .D1(phase_high), .D2(~phase_high), .SR(reset_pad), .Q(clock_symbol));
    OBUF clock_pad(.I(clock_symbol), .O(eth_txc));
    for(genvar n=0;n<5;n=n+1) begin: lanes
        wire selected_symbol=phase_high ? pad_high[n] : pad_low[n];
        wire symbol;
        ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) data_ddr(
            .C(quarter_clock), .D1(selected_symbol), .D2(selected_symbol), .SR(reset_pad), .Q(symbol));
        if(n<4) OBUF data_pad(.I(symbol), .O(eth_txd[n]));
        else OBUF control_pad(.I(symbol), .O(eth_tx_ctl));
    end
endmodule
