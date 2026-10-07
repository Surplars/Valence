`timescale 1ns/1ps
// Clock phases have separate reset-release chains; assertion is common.
module native_tx_reset_boundary(
    input wire clock_tx, clock_forward, inhibit,
    output wire reset_raw, reset_forward
);
    (* ASYNC_REG="TRUE" *) reg [2:0] tx_reset_pipe, tx_forward_reset_pipe;
    always @(posedge clock_tx or posedge inhibit)
        if(inhibit) tx_reset_pipe<=3'b111;
        else tx_reset_pipe<={tx_reset_pipe[1:0],1'b0};
    always @(posedge clock_forward or posedge inhibit)
        if(inhibit) tx_forward_reset_pipe<=3'b111;
        else tx_forward_reset_pipe<={tx_forward_reset_pipe[1:0],1'b0};
    assign reset_raw=tx_reset_pipe[2];
    assign reset_forward=tx_forward_reset_pipe[2];
endmodule
