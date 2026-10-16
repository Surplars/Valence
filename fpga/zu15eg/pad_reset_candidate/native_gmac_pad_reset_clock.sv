`timescale 1ns/1ps
// Explicit opt-in clock/reset architecture. No timing/board qualification.
module native_gmac_pad_reset_clock #(parameter ENABLE_PAD_DOMAIN_RESET = 0)(
    input wire ui_clock, cold_reset,
    output wire tx_source, tx_pad_source, tx_forward_source, delay_source, locked);
    initial if (ENABLE_PAD_DOMAIN_RESET != 0 && ENABLE_PAD_DOMAIN_RESET != 1)
        $fatal(1,"ENABLE_PAD_DOMAIN_RESET must be 0 or 1");
    generate if (!ENABLE_PAD_DOMAIN_RESET) begin: disabled
        native_gmac_quarter_clock legacy(.ui_clock(ui_clock), .cold_reset(cold_reset),
            .tx_source(tx_source), .tx_pad_source(tx_pad_source),
            .tx_forward_source(tx_forward_source), .delay_source(delay_source), .locked(locked));
    end else begin: enabled
        wire feedback, ref_source, pad_source, pll_locked;
        PLLE4_ADV #(.CLKIN_PERIOD(4.0), .CLKFBOUT_MULT(4), .DIVCLK_DIVIDE(1),
            .CLKOUT0_DIVIDE(2), .CLKOUT1_DIVIDE(4),
            .CLKOUT0_PHASE(0.0), .CLKOUT1_PHASE(0.0),
            .CLKOUT0_DUTY_CYCLE(0.5), .CLKOUT1_DUTY_CYCLE(0.5),
            .COMPENSATION("AUTO")) pll(
            .CLKIN(ui_clock), .RST(cold_reset), .PWRDWN(1'b0),
            .CLKFBOUT(feedback), .CLKFBIN(feedback),
            .CLKOUT0(ref_source), .CLKOUT1(pad_source), .LOCKED(pll_locked),
            .CLKOUT0B(), .CLKOUT1B(), .CLKOUTPHY(), .CLKOUTPHYEN(1'b0),
            .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'b0), .DI(16'b0), .DO(), .DRDY());
        (* DONT_TOUCH="TRUE" *) BUFG delay_buffer(.I(ref_source), .O(delay_source));
        // PAD buffer and RAW divider are siblings of the SAME PLL250 output.
        (* DONT_TOUCH="TRUE" *) BUFG pad_buffer(.I(pad_source), .O(tx_pad_source));
        wire phase_inhibit=cold_reset | ~pll_locked;
        (* ASYNC_REG="TRUE" *) reg [2:0] phase_reset;
        always @(posedge tx_pad_source or posedge phase_inhibit)
            if(phase_inhibit) phase_reset<=3'b111;
            else phase_reset<={phase_reset[1:0],1'b0};
        assign locked=pll_locked & ~phase_reset[2];
        // Stage1 release has a 4ns nominal cycle. Functional CLR remains timed.
        (* DONT_TOUCH="TRUE" *) BUFGCE_DIV #(.BUFGCE_DIVIDE(2), .SIM_DEVICE("ULTRASCALE_PLUS")) raw_div(
            .I(pad_source), .CE(1'b1), .CLR(phase_reset[1]), .O(tx_source));
        assign tx_forward_source=tx_source;
    end endgenerate
endmodule
