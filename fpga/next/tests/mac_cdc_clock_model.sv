`timescale 1ns/1ps
// Digital pause model only. Retains CE while high and changes it only on the
// inactive phase. It does not claim vendor BUFGCE setup/hold/placement proof.
module BUFGCE #(parameter CE_TYPE="SYNC") (input I, input CE, output O);
    reg enabled=0;
    always @(negedge I) enabled <= CE;
    assign O = I & enabled;
endmodule
