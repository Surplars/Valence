// Source-side sampling only. The existing RAW125 clock remains continuous.
// Map these to negative-edge FFs / C-pin inversion, never a LUT clock inverter.
module ValenceMacRawFallingSample (
    input wire rawClock,
    input wire rawReset,
    input wire [11:0] payload,
    output reg [11:0] sampled
);
    always @(negedge rawClock or posedge rawReset)
        if (rawReset) sampled <= 12'b0;
        else sampled <= payload;
endmodule
