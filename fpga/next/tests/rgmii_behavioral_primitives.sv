`timescale 1ns/1ps
// Behavioral test substitutes, not AMD UNISIM, calibrated delays or STA.
module ODDRE1 #(parameter SIM_DEVICE="ULTRASCALE_PLUS")
    (input wire C,D1,D2,SR,output reg Q=0);
    reg falling=0;
    always @(posedge C or posedge SR)
        if(SR)begin Q<=0;falling<=0;end else begin Q<=#0.1 D1;falling<=D2;end
    always @(negedge C or posedge SR)
        if(SR)Q<=0;else Q<=#0.1 falling;
endmodule
module IDDRE1 #(parameter DDR_CLK_EDGE="SAME_EDGE_PIPELINED",IS_CB_INVERTED=1'b1)
    (input wire C,CB,D,R,output reg Q1=0,Q2=0);
    reg rising=0,falling=0;
    always @(posedge C or posedge R)
        if(R)begin rising<=0;Q1<=0;Q2<=0;end else begin rising<=D;Q1<=rising;Q2<=falling;end
    always @(negedge C or posedge R)if(R)falling<=0;else falling<=D;
endmodule
module IDELAYCTRL #(parameter SIM_DEVICE="ULTRASCALE")
    (input wire REFCLK,RST,output reg RDY=0);
    integer count=0;
    always @(posedge REFCLK or posedge RST)
        if(RST)begin count<=0;RDY<=0;end else if(count==31)RDY<=1;else count<=count+1;
endmodule
module IDELAYE3 #(parameter DELAY_FORMAT="TIME",DELAY_TYPE="FIXED",DELAY_SRC="IDATAIN",
    DELAY_VALUE=1100,REFCLK_FREQUENCY=500.0,SIM_DEVICE="ULTRASCALE_PLUS",CASCADE="NONE")
    (input wire IDATAIN,DATAIN,CLK,CE,INC,LOAD,RST,EN_VTC,CASC_IN,CASC_RETURN,
     input wire [8:0] CNTVALUEIN,output wire DATAOUT,CASC_OUT,output wire [8:0] CNTVALUEOUT);
    assign #(DELAY_VALUE/1000.0) DATAOUT=(CASCADE=="SLAVE_END")?CASC_IN:(DELAY_SRC=="IDATAIN"?IDATAIN:DATAIN);
    assign CASC_OUT=1'b0;assign CNTVALUEOUT=9'b0;
endmodule
