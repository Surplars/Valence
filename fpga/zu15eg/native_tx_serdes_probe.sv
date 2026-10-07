`timescale 1ns/1ps
// PRIVATE feasibility probe; not a production wrapper or board qualification.
// CLK500 and CLKDIV125 come from the same real PLL/global divider tree.
// A constant eight-bit word forwards one 125MHz TXC without a separate
// phase-shifted 125MHz output tree or cascaded I/O delays. The independent
// testbench must prove the actual UNISIM/reset phase before STA uses it.
module native_tx_serdes_probe #(parameter [7:0] CLOCK_PATTERN=8'hf0)(
    input wire ui_pad, cold_reset, tx_reset_request,
    input wire [4:0] symbols_low, symbols_high,
    output wire [3:0] eth_txd,
    output wire eth_tx_ctl, eth_txc, locked);
    wire ui_clock, raw, pad, forward_unused, ref_clock, serial_clock;
    (* DONT_TOUCH="TRUE" *) BUFG input_buffer(.I(ui_pad), .O(ui_clock));
    native_gmac_divided_clock clocks(.ui_clock(ui_clock), .cold_reset(cold_reset),
        .tx_source(raw), .tx_pad_source(pad), .tx_forward_source(forward_unused),
        .delay_source(ref_clock), .locked(locked));
    // Match the last global-buffer stage to the pad-only DIV4 tree. The
    // first experiment's direct CLK500 branch was over 1ns earlier than
    // data's divided pad tree. Preserve the common PLL/first global trunk.
    (* DONT_TOUCH="TRUE" *) BUFG tx_serial_buffer(.I(ref_clock), .O(serial_clock));
    wire inhibit=cold_reset | ~locked | tx_reset_request;
    wire reset_raw, reset_pad;
    native_tx_reset_boundary release_dut(.clock_tx(raw), .clock_forward(pad),
        .inhibit(inhibit), .reset_raw(reset_raw), .reset_forward(reset_pad));
    reg [4:0] registered_low, registered_high;
    always @(posedge raw or posedge reset_raw)
        if(reset_raw) begin registered_low<=0; registered_high<=0; end
        else begin registered_low<=symbols_low; registered_high<=symbols_high; end
    wire clock_symbol;
    OSERDESE3 #(.DATA_WIDTH(8), .INIT(1'b0), .SIM_DEVICE("ULTRASCALE_PLUS")) clock_serdes(
        .CLK(serial_clock), .CLKDIV(pad), .D(CLOCK_PATTERN), .RST(reset_pad),
        .T(1'b0), .T_OUT(), .OQ(clock_symbol));
    OBUF clock_pad(.I(clock_symbol), .O(eth_txc));
    for(genvar n=0;n<5;n=n+1) begin: lanes
        wire symbol;
        ODDRE1 #(.SIM_DEVICE("ULTRASCALE_PLUS")) data_ddr(
            .C(pad), .D1(registered_low[n]), .D2(registered_high[n]),
            .SR(reset_pad), .Q(symbol));
        if(n<4) OBUF data_pad(.I(symbol), .O(eth_txd[n]));
        else OBUF control_pad(.I(symbol), .O(eth_tx_ctl));
    end
endmodule
