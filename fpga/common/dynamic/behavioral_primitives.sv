`ifdef VALENCE_USE_UNISIM
// Compilation must fail if a behavioral stand-in leaks into a vendor run.
ERROR_BEHAVIORAL_PRIMITIVES_FORBIDDEN_IN_UNISIM_VALIDATION
`endif
`timescale 1ns/1ps
`default_nettype none
// TEST ONLY. Not UNISIM, not a physical/MMCM/frequency-legality oracle.
// Exercises production RTL transactions, masks, isolation and edge witnesses.
module BUFG(input wire I, output wire O); assign O=I; endmodule
module BUFGCE #(parameter CE_TYPE="SYNC", SIM_DEVICE="ULTRASCALE_PLUS")
    (input wire I, CE, output wire O);
    reg latched=0;
    always @(I or CE) if (!I) latched=CE;
    assign O=I & latched;
endmodule
module MMCME4_ADV #(
    parameter BANDWIDTH="OPTIMIZED", parameter real CLKIN1_PERIOD=4.0,
    parameter integer DIVCLK_DIVIDE=10, parameter real CLKFBOUT_MULT_F=40.0,
    parameter real CLKOUT0_DIVIDE_F=20.0, CLKOUT0_DUTY_CYCLE=0.5, CLKOUT0_PHASE=0.0,
    parameter CLKOUT0_USE_FINE_PS="FALSE", CLKFBOUT_USE_FINE_PS="FALSE",
    COMPENSATION="AUTO", STARTUP_WAIT="FALSE"
) (
    input wire CLKIN1, CLKIN2, CLKINSEL, CLKFBIN,
    output wire CLKFBOUT, output reg CLKOUT0=0,
    input wire RST, PWRDWN, output reg LOCKED=0,
    input wire DCLK, input wire [6:0] DADDR, input wire [15:0] DI,
    input wire DEN,DWE, output reg [15:0] DO=0, output reg DRDY=0,
    input wire PSCLK,PSEN,PSINCDEC,CDDCREQ
);
    reg [15:0] registers[0:127];
    integer n, lock_cycles=0, latency=2, pending_count=0, transactions=0;
    integer inject_delay=0;
    reg never_ready=0, never_lock=0, stop_clock=0, corrupt_next_write=0;
    reg pending=0, pending_write;
    reg [6:0] pending_address;
    reg [15:0] pending_data;
    initial begin
        for(n=0;n<128;n=n+1)registers[n]=0;
        registers[7'h08]=16'h128a; registers[7'h09]=16'h8000;
        registers[7'h14]=16'h1514; registers[7'h15]=16'h8000;
        registers[7'h16]=16'hc145;
    end
    assign CLKFBOUT=CLKIN1;
    always @(posedge CLKIN1 or posedge RST) begin
        if(RST)begin LOCKED<=0;lock_cycles<=0;end
        else if(never_lock)LOCKED<=0;
        else if(lock_cycles==20)LOCKED<=1;
        else lock_cycles<=lock_cycles+1;
    end
    real half_period;
    integer m,d,o;
    function integer decoded_count(input [5:0] bits6);
        decoded_count = bits6==0 ? 64 : bits6;
    endfunction
    always begin
        // Derive the modeled clock from actual DRP register contents, never
        // from the software target or testbench expectation.
        m=decoded_count(registers[7'h14][11:6])+decoded_count(registers[7'h14][5:0]);
        d=decoded_count(registers[7'h16][11:6])+decoded_count(registers[7'h16][5:0]);
        o=decoded_count(registers[7'h08][11:6])+decoded_count(registers[7'h08][5:0]);
        half_period=CLKIN1_PERIOD*d*o/(2.0*m);
        if($test$plusargs("negative_wrong_rate"))half_period=10.0;
        if(half_period<1.0)half_period=10.0;
        #(half_period);
        if(RST || PWRDWN || stop_clock)CLKOUT0=0;
        else CLKOUT0=~CLKOUT0;
    end
    always @(posedge DCLK) begin
        DRDY<=0;
        if(DEN)begin
            if(pending)$fatal(1,"OVERLAPPING_DRP_TRANSACTION");
            if(!RST)$fatal(1,"DRP_WITHOUT_MMCM_RESET");
            pending<=1;pending_write<=DWE;pending_address<=DADDR;pending_data<=DI;
            pending_count<=latency+inject_delay;inject_delay<=0;transactions<=transactions+1;
        end
        if(pending && !never_ready)begin
            if(pending_count==0)begin
                if(pending_write)begin
                    registers[pending_address]<=pending_data ^ (corrupt_next_write ? 16'h0001 : 16'h0000);
                    corrupt_next_write<=0;
                end
                DO<=registers[pending_address];DRDY<=1;pending<=0;
            end else pending_count<=pending_count-1;
        end
    end
endmodule
`default_nettype wire
