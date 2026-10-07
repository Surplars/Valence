`timescale 1ns/1ps
// Dedicated ODDR250 mode shares one 125MHz word release epoch. Assertion
// is asynchronous; the phase/payload/ODDR functional sinks remain STA-timed.
module native_tx_word_reset_boundary(input wire clock_tx, inhibit,
    output wire reset_raw, reset_forward);
    (* ASYNC_REG="TRUE" *) reg [2:0] tx_reset_pipe;
    always @(posedge clock_tx or posedge inhibit)
        if(inhibit) tx_reset_pipe<=3'b111;
        else tx_reset_pipe<={tx_reset_pipe[1:0],1'b0};
    assign reset_raw=tx_reset_pipe[2];
    assign reset_forward=tx_reset_pipe[2];
endmodule
