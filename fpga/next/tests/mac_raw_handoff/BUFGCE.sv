// Digital low-phase CE latch model. Models edge suppression, not vendor delays.
module BUFGCE #(parameter CE_TYPE="SYNC")(input I, CE, output O);
 reg gate=0;
 always @(I or CE) if (!I) gate <= CE;
 assign O=I & gate;
endmodule
