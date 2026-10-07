`timescale 1ns / 1ps

// 200 MHz differential board oscillator -> 40 MHz PL-only Valence SoC.
// The boot monitor is initialized in blk_mem_gen_0 by bootrom.coe.
module soc_top (
    input  wire clk_in1_p,
    input  wire clk_in1_n,
    input  wire sys_rst_n,
    input  wire button_n,
    input  wire uart_rxd,
    output wire uart_txd,
    output wire led
);
    wire clk_soc;
    wire mmcm_locked;
    clk_wiz_0 u_clk_wiz (
        .clk_out1  (clk_soc),
        .reset     (~sys_rst_n),
        .locked    (mmcm_locked),
        .clk_in1_p (clk_in1_p),
        .clk_in1_n (clk_in1_n)
    );

    wire reset_request = ~sys_rst_n | ~button_n | ~mmcm_locked;
    (* ASYNC_REG = "TRUE" *) reg [2:0] reset_pipe;
    always @(posedge clk_soc or posedge reset_request) begin
        if (reset_request)
            reset_pipe <= 3'b111;
        else
            reset_pipe <= {reset_pipe[1:0], 1'b0};
    end
    wire soc_reset = reset_pipe[2];
    assign led = ~soc_reset;

    BoardSocTop u_soc (
        .clock     (clk_soc),
        .reset     (soc_reset),
        .io_uartRx (uart_rxd),
        .io_uartTx (uart_txd)
    );
endmodule
