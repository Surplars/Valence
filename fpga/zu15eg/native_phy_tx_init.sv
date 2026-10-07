`timescale 1ns/1ps
// RTL8211F cold-start configuration on always-on 50MHz. Reuses the actual
// SoC Clause22 engine: divider20 => 1.25MHz MDC, >=400ns read half-cycle.
// No CPU reset dependency on RXC. No software command is assumed successful
// while this controller owns MDIO. Software must wait for qualified linkUp.
module native_phy_tx_init #(
    parameter WAIT_CYCLES = 1000000,
    parameter HANDOFF_CYCLES = 64
)(
    input wire clock, cold_reset, mdio_pad,
    input wire software_mdc, software_oe,
    output wire mdc, mdio_out, mdio_oe,
    output reg bus_released,
    output wire ready,
    output reg [4:0] phy_address,
    output reg [3:0] fault
);
    (* ASYNC_REG="TRUE" *) reg [2:0] reset_pipe=3'b111;
    always @(posedge clock or posedge cold_reset)
        if(cold_reset) reset_pipe<=3'b111;
        else reset_pipe<={reset_pipe[1:0],1'b0};
    wire reset=reset_pipe[2];
    (* ASYNC_REG="TRUE" *) reg mdio_meta, mdio_sync;
    (* ASYNC_REG="TRUE" *) reg software_mdc_meta, software_mdc_sync;
    (* ASYNC_REG="TRUE" *) reg software_oe_meta, software_oe_sync;
    always @(posedge clock) begin
        mdio_meta<=mdio_pad; mdio_sync<=mdio_meta;
        software_mdc_meta<=software_mdc; software_mdc_sync<=software_mdc_meta;
        software_oe_meta<=software_oe; software_oe_sync<=software_oe_meta;
    end
    reg command_valid, command_write;
    reg [4:0] command_register;
    reg [15:0] command_data;
    wire command_ready, response_valid, no_ack, busy;
    wire [15:0] response_data;
    MdioClause22 mdio_engine(.clock(clock), .reset(reset),
        .io_command_ready(command_ready), .io_command_valid(command_valid),
        .io_command_bits_phy(phy_address), .io_command_bits_register(command_register),
        .io_command_bits_write(command_write), .io_command_bits_data(command_data),
        .io_response_valid(response_valid), .io_response_bits_data(response_data),
        .io_response_bits_noAck(no_ack), .io_busy(busy),
        .io_mdc(mdc), .io_mdioIn(mdio_sync), .io_mdioOut(mdio_out), .io_mdioOe(mdio_oe));
    localparam ID1=0, ID2=1, PAGE=2, PAGE_VERIFY=3, TX_READ=4, TX_WRITE=5, TX_VERIFY=6,
        RX_READ=7, RX_WRITE=8, RX_VERIFY=9, RESTORE=10, RESTORE_VERIFY=11;
    localparam WAIT_PHY=0, ISSUE=1, AWAIT_REPLY=2, HANDOFF=3, FINISHED=4, GAP=5;
    reg [2:0] state;
    reg [3:0] operation;
    reg [19:0] settle_count;
    reg [7:0] idle_count;
    reg [4:0] gap_count;
    reg [15:0] tx_value, rx_value;
    reg verified;
    assign ready=verified && bus_released && !cold_reset && !reset;
    initial begin
        if(WAIT_CYCLES<1 || WAIT_CYCLES>1048576 || HANDOFF_CYCLES<4 || HANDOFF_CYCLES>255)
            $fatal(1,"Illegal PHY initialization timing parameters");
    end
    always @* begin
        command_register=5'd2; command_write=0; command_data=0;
        case(operation)
            ID2: command_register=5'd3;
            PAGE: begin command_register=5'd31; command_write=1; command_data=16'h0d08; end
            PAGE_VERIFY: command_register=5'd31;
            TX_READ,TX_VERIFY: command_register=5'd17;
            TX_WRITE: begin command_register=5'd17; command_write=1; command_data=tx_value; end
            RX_READ,RX_VERIFY: command_register=5'd21;
            RX_WRITE: begin command_register=5'd21; command_write=1; command_data=rx_value; end
            RESTORE: begin command_register=5'd31; command_write=1; command_data=0; end
            RESTORE_VERIFY: command_register=5'd31;
            default: begin end
        endcase
        command_valid=(state==ISSUE);
    end
    always @(posedge clock or posedge reset) begin
        if(reset) begin
            state<=WAIT_PHY; operation<=ID1; settle_count<=0; idle_count<=0; gap_count<=0;
            phy_address<=0; tx_value<=0; rx_value<=0; fault<=0;
            verified<=0; bus_released<=0;
        end else begin
            case(state)
                WAIT_PHY: if(settle_count==WAIT_CYCLES-1) state<=ISSUE;
                          else settle_count<=settle_count+1'b1;
                ISSUE: if(command_ready) state<=AWAIT_REPLY;
                AWAIT_REPLY: if(response_valid) begin
                    state<=GAP; gap_count<=0;
                    if(operation==ID1 || operation==ID2) begin
                        if(no_ack || (operation==ID1 && response_data!=16'h001c) ||
                            (operation==ID2 && (response_data & 16'hfff0)!=16'hc910)) begin
                            if(phy_address==31) begin fault<=1; state<=HANDOFF; end
                            else begin phy_address<=phy_address+1'b1; operation<=ID1; end
                        end else operation<=operation+1'b1;
                    end else if(no_ack) begin
                        fault<=2; verified<=0;
                        if(operation==RESTORE_VERIFY) state<=HANDOFF;
                        else operation<=RESTORE;
                    end else case(operation)
                        PAGE: operation<=PAGE_VERIFY;
                        PAGE_VERIFY: if(response_data!=16'h0d08) begin fault<=7; operation<=RESTORE; end
                                     else operation<=TX_READ;
                        TX_READ: begin tx_value<=response_data & 16'hfeff; operation<=TX_WRITE; end
                        TX_WRITE: operation<=TX_VERIFY;
                        TX_VERIFY: if(response_data!=tx_value) begin fault<=3; operation<=RESTORE; end
                                   else operation<=RX_READ;
                        RX_READ: begin rx_value<=response_data | 16'h0008; operation<=RX_WRITE; end
                        RX_WRITE: operation<=RX_VERIFY;
                        RX_VERIFY: begin
                            if(response_data!=rx_value) fault<=4;
                            operation<=RESTORE;
                        end
                        RESTORE: operation<=RESTORE_VERIFY;
                        RESTORE_VERIFY: begin
                            if(response_data!=0) fault<=5;
                            verified<=(fault==0 && response_data==0);
                            state<=HANDOFF;
                        end
                        default: begin fault<=6; state<=HANDOFF; end
                    endcase
                end
                HANDOFF: begin
                    // Observe more than two complete software MDC periods
                    // without edges/OE before a low-clock, high-Z handoff.
                    if(software_mdc_sync || software_oe_sync || mdc || mdio_oe || busy)
                        idle_count<=0;
                    else if(idle_count==HANDOFF_CYCLES-1) begin
                        bus_released<=1; state<=FINISHED;
                    end else idle_count<=idle_count+1'b1;
                end
                FINISHED: begin end
                GAP: if(gap_count==19) state<=ISSUE;
                     else gap_count<=gap_count+1'b1;
                default: begin fault<=6; verified<=0; state<=HANDOFF; end
            endcase
        end
    end
endmodule
